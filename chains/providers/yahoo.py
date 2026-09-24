"""Daily bars from Yahoo Finance, on the same interface the EODHD client
exposes, so the price layer cannot tell which one it is holding.

    from chains.providers.yahoo import YahooClient
    with YahooClient() as c:
        rows = c.eod("RHM.XETRA", from_="2026-09-01", to="2026-09-24")

No API token, no signup, no account. This is the data source the ``yfinance``
package wraps, reached directly over the httpx already in requirements.txt.

WHY NOT THE yfinance PACKAGE
----------------------------
Two reasons, and the second is the one that decided it.

``yfinance`` imports pandas unconditionally, and this repository has no pandas
in it on purpose -- the whole price layer is polars, and prices.py says so in
its own docstring. Pulling pandas in for one provider would put two dataframe
libraries in the build for the sake of a JSON call.

And it does not load here at all. On this machine pandas' compiled extensions
are blocked by an Application Control policy:

    ImportError: DLL load failed while importing indexing:
    An Application Control policy has blocked this file.

That is a machine policy and not a broken install -- a forced clean reinstall
fails identically, while numpy, equally compiled, imports fine. So ``yfinance``
cannot be imported, cannot be run, and cannot be tested here. Shipping a price
provider that nobody can execute on the machine that builds the site is the
exact failure this replacement exists to prevent.

The endpoint below is what yfinance calls. Same data, same terms, one less
dependency, and it runs.

THE SYMBOL TABLE IS THE WHOLE RISK
----------------------------------
The store is keyed by the EODHD spelling of a symbol -- that is what is in
every map, every parquet filename and every committed liquidity record -- so
this client keeps taking those and translates on the way out. The two vendors
disagree about suffixes, and Korea is the trap: EODHD calls KRX ``KO`` and
Yahoo calls it ``KS``, which is the exact reverse of the warning in
chains/exchanges.py about Yahoo's habit misleading.

An unknown suffix RAISES. It does not fall through to the US market, and it
does not return empty. prices.currency_for already takes this line -- it
answers "UNKNOWN" rather than guessing "USD" -- and the reason is written into
this repository's history: liquidity.currency_of did guess USD for a suffix it
did not know, and 2269.HK's traded value read 7.8x high for as long as nobody
looked.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

import httpx
from tenacity import (retry, retry_if_exception_type, stop_after_attempt,
                      wait_exponential_jitter)

from chains.providers.ratelimit import RateLimiter

log = logging.getLogger(__name__)

BASE_URL = "https://query2.finance.yahoo.com"
CHART_PATH = "/v8/finance/chart/{symbol}"
DEFAULT_TIMEOUT = 30.0
# Yahoo publishes no documented limit. This is deliberately well under what
# the endpoint tolerates: the build fetches a few hundred symbols once a day
# and has no reason to push.
DEFAULT_RATE_PER_MIN = 120
# Yahoo answers a bare client with 429 more often than not.
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
           "Accept": "application/json"}

# EODHD's suffix -> Yahoo's. Every entry below was confirmed against a live
# response, not remembered; the ones this repository actually uses are marked
# with the count of symbols carrying them across semi, energy and pharma.
SUFFIX = {
    "US": "",          # 117 symbols; Yahoo carries US tickers bare
    "KO": "KS",        # 8   KRX. EODHD says KO, Yahoo says KS -- reversed
    "XETRA": "DE",     # 7
    "SW": "SW",        # 5   SIX
    "TW": "TW",        # 4   Taiwan
    "SHG": "SS",       # 4   Shanghai
    "SHE": "SZ",       # 3   Shenzhen
    "KQ": "KQ",        # 3   KOSDAQ
    "PA": "PA",        # 3   Euronext Paris
    "TWO": "TWO",      # 2   Taipei Exchange
    "AS": "AS",        # 2   Euronext Amsterdam
    "VI": "VI",        # 1   Vienna
    "CO": "CO",        # 1   Copenhagen
    "BR": "BR",        # 1   Euronext Brussels
    # Not used by a live map today, kept because exchanges.py can produce them
    # and because Yahoo carries venues EODHD's plan did not:
    "LSE": "L",        # London
    "HK": "HK",        # Hong Kong
    "TO": "TO",        # Toronto
    "MI": "MI",        # Milan -- absent from the EODHD plan entirely
    "T": "T",          # Tokyo -- absent from the EODHD plan entirely
    "TSE": "T",
}


class YahooError(RuntimeError):
    """Any failure reaching or reading Yahoo."""


class RetryableStatus(YahooError):
    """429 or 5xx -- worth retrying with backoff."""


class NoData(YahooError):
    """The symbol returned no usable series.

    Loud on purpose. An empty price series is not an empty result, it is a
    missing number, and a build that publishes around one looks finished and
    is wrong.
    """


class UnknownSuffix(YahooError):
    """A symbol whose exchange this client cannot translate."""


def to_yahoo(symbol: str) -> str:
    """An EODHD-spelled symbol as Yahoo spells it.

    Raises on a suffix that is not in the table rather than guessing. A guess
    here is a US ticker that happens to collide -- ``BA`` is Boeing in New York
    and BAE Systems in London -- and the series would come back looking
    perfectly healthy.
    """
    base, _, suffix = symbol.rpartition(".")
    if not base:
        # No suffix at all: already a Yahoo-style US ticker.
        return symbol
    key = suffix.upper()
    if key == "FOREX":
        # The liquidity gate asks for rates in the old vendor's spelling,
        # USDTWD.FOREX. Yahoo writes a USD-based pair as the quote currency
        # alone -- TWD=X is dollars into New Taiwan dollars -- and any other
        # pair as the two codes joined. Getting this wrong is not a missing
        # rate, it is a leg measured in the wrong money, which is the bug
        # this repository has already had once.
        pair = base.upper()
        if len(pair) == 6 and pair.startswith("USD"):
            return f"{pair[3:]}=X"
        return f"{pair}=X"
    if key not in SUFFIX:
        raise UnknownSuffix(
            f"{symbol!r}: no Yahoo spelling is known for the exchange suffix "
            f"{suffix!r}. Add it to chains.providers.yahoo.SUFFIX after "
            f"confirming it against a live response -- guessing sends the "
            f"request to the US market, where a colliding ticker answers with "
            f"a healthy series for the wrong company.")
    tail = SUFFIX[key]
    return f"{base}.{tail}" if tail else base


def _epoch(day: str | dt.date, end: bool = False) -> int:
    d = dt.date.fromisoformat(day) if isinstance(day, str) else day
    t = dt.datetime.combine(d, dt.time(23, 59, 59) if end else dt.time())
    return int(t.replace(tzinfo=dt.timezone.utc).timestamp())


class YahooClient:
    """Daily bars, on the EODHD client's interface.

    Only ``eod`` is implemented, because only ``eod`` is called: the splits,
    dividends, bulk and symbol-change endpoints on the EODHD client have no
    caller anywhere in chains/ or tools/ outside that client's own tests.
    Implementing them here would be writing code against no requirement.
    """

    def __init__(self, *, timeout: float = DEFAULT_TIMEOUT,
                 rate_per_min: int = DEFAULT_RATE_PER_MIN,
                 client: httpx.Client | None = None,
                 max_attempts: int = 5):
        self._limiter = RateLimiter(rate_per_min)
        self._max_attempts = max_attempts
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=BASE_URL, timeout=timeout, headers=HEADERS)

    # -- plumbing ---------------------------------------------------------
    def _send(self, symbol: str, params: dict[str, Any]) -> Any:
        self._limiter.acquire()
        path = CHART_PATH.format(symbol=symbol)
        try:
            resp = self._client.get(path, params=params)
        except httpx.TransportError as e:
            raise RetryableStatus(
                f"transport error for {symbol}: {type(e).__name__}") from None
        code = resp.status_code
        if code == 429 or code >= 500:
            raise RetryableStatus(f"HTTP {code} for {symbol}")
        if code == 404:
            raise NoData(f"HTTP 404 for {symbol}: Yahoo does not know it")
        if code >= 400:
            raise YahooError(f"HTTP {code} for {symbol}")
        try:
            return resp.json()
        except ValueError:
            raise YahooError(f"non-JSON response for {symbol}") from None

    def _get(self, symbol: str, params: dict[str, Any]) -> Any:
        @retry(retry=retry_if_exception_type(RetryableStatus),
               wait=wait_exponential_jitter(initial=1.0, max=30.0),
               stop=stop_after_attempt(self._max_attempts), reraise=True)
        def _attempt() -> Any:
            return self._send(symbol, params)
        return _attempt()

    # -- endpoints --------------------------------------------------------
    def eod(self, symbol: str, from_: str | None = None,
            to: str | None = None, exchange: str = "US") -> list[dict]:
        """Daily bars in the EODHD row shape.

        Keys are EODHD's, because prices.frame reads EODHD's: ``date``,
        ``open``, ``high``, ``low``, ``close``, ``adjusted_close``, ``volume``.
        """
        y = to_yahoo(symbol if "." in symbol else f"{symbol}.{exchange}")
        params: dict[str, Any] = {"interval": "1d", "events": "div,split"}
        params["period1"] = _epoch(from_) if from_ else _epoch("1970-01-02")
        params["period2"] = (_epoch(to, end=True) if to
                             else _epoch(dt.date.today(), end=True))
        payload = self._get(y, params)
        return self._rows(symbol, y, payload)

    @staticmethod
    def _rows(symbol: str, y: str, payload: Any) -> list[dict]:
        chart = (payload or {}).get("chart") or {}
        if chart.get("error"):
            raise NoData(f"{symbol} (as {y}): Yahoo returned "
                         f"{chart['error'].get('code')}")
        results = chart.get("result") or []
        if not results:
            raise NoData(f"{symbol} (as {y}): Yahoo returned no result block")
        res = results[0]
        stamps = res.get("timestamp") or []
        quote = ((res.get("indicators") or {}).get("quote") or [{}])[0]
        adj = (((res.get("indicators") or {}).get("adjclose") or [{}])[0]
               .get("adjclose")) or []
        if not stamps:
            # A live symbol with no bars in the window is legitimate -- a
            # holiday week, or a range that ends before the listing. Empty is
            # returned; it is the CALLER that decides whether empty is fatal,
            # exactly as with the EODHD client.
            return []
        out: list[dict] = []
        for i, ts in enumerate(stamps):
            def at(key: str) -> Any:
                seq = quote.get(key) or []
                return seq[i] if i < len(seq) else None
            close = at("close")
            adjusted = adj[i] if i < len(adj) else None
            if close is None and adjusted is None:
                # Yahoo pads gaps with nulls rather than omitting the day.
                continue
            out.append({
                "date": dt.datetime.fromtimestamp(
                    ts, dt.timezone.utc).date().isoformat(),
                "open": at("open"), "high": at("high"), "low": at("low"),
                "close": close,
                "adjusted_close": adjusted if adjusted is not None else close,
                "volume": at("volume"),
            })
        return out

    def currency(self, symbol: str) -> str | None:
        """What Yahoo says the symbol trades in.

        Reported, never trusted: the store's currency comes from
        prices.currency_for, which reads the suffix this repository wrote. This
        exists so a migration can COMPARE the two and shout when they disagree,
        which is the check that would have caught the HK bug.
        """
        y = to_yahoo(symbol)
        payload = self._get(y, {"interval": "1d", "range": "5d"})
        res = ((payload or {}).get("chart") or {}).get("result") or [{}]
        return (res[0].get("meta") or {}).get("currency")

    # -- lifecycle --------------------------------------------------------
    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "YahooClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return "YahooClient()"
