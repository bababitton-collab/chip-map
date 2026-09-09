"""Fundamentals straight from EDGAR. No key, no local store.

    from chains import edgar
    edgar.rows_for("NVDA")        # one company's periods

WHY THIS EXISTS AT ALL
----------------------
The version of this build that ran on a laptop did not fetch EDGAR. It read a
DuckDB store that a different project maintained, at an absolute path outside
its own tree -- 700 MB that no CI runner will ever have. That single read is
what made the build unmovable. This module replaces it with the public API the
store was itself built from, so the repository depends on nothing but itself
and two public endpoints.

The shape it returns is deliberately the shape the store returned, because the
maths downstream -- deduplication, year-on-year, operating margin -- was
written against real data and its reasoning is still correct. See
chains/fundamentals.py.

NO KEY, BUT A NAME AND AN ADDRESS
---------------------------------
SEC asks for a User-Agent that identifies who is calling and how to reach them,
and it does not merely throttle traffic that does not say -- it refuses it. The
address below is real for that reason. The polite thing and the working thing
are the same thing here.

A PERIOD IS CLASSIFIED BY ITS LENGTH, NOT BY ITS LABEL
-------------------------------------------------------
companyfacts tags each fact with a fiscal year and period, and those tags are
not reliable: the same fact is restated under different tags in later filings,
which is exactly the duplication the store showed 67,732 of. What is reliable
is ``start`` and ``end``. A fact spanning about a year is annual, one spanning
about a quarter is quarterly, and anything else -- a six-month interim, a
53-week stub -- is neither and is dropped rather than filed under a guess.

WHAT IS NOT DERIVED
-------------------
R&D is not read, for the same reason it was not read before: it needs an XBRL
tag chosen here, and a tag guessed at in this module produces numbers nobody
can trace. Revenue is read from a short list of tags in priority order, and the
list is explicit rather than a search for anything revenue-shaped.
"""
from __future__ import annotations

import datetime as dt
import json
import time
from typing import Iterable

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

# SEC's fair-access policy: identify yourself, and stay under 10 requests a
# second.
#
# The format is "name email" and nothing else. A User-Agent containing a URL is
# rejected by SEC's WAF with a 403 and an HTML error page -- confirmed against
# the live endpoint, not guessed: the same request with the repo's GitHub URL
# in the header returns 403, and with "chip-map someone@example.com" returns
# 200. So the repo name goes in bare, without a link.
#
# A real address, not a placeholder: with a placeholder every request returns
# 403 and the fundamentals step fails the build. That failure is deliberate --
# a silent fallback would publish a map with every filing panel blank and no
# record of why -- and PLACEHOLDER_HINT below still explains it if the address
# is ever removed.
REPO = "chip-map"
CONTACT = "bababitton@gmail.com"
USER_AGENT = f"{REPO} {CONTACT}"
HEADERS = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}

PLACEHOLDER_HINT = (
    "EDGAR refused the request (403). chains/edgar.py CONTACT is still "
    f"{CONTACT!r}; SEC requires a real address in the User-Agent and rejects "
    "anything else. Put an email there and re-run.")

REQUEST_TIMEOUT = 30.0
SLEEP_BETWEEN = 0.15          # ~7 req/s, inside SEC's limit with room to spare

# One tag per company per measure -- but the one with the FRESHEST coverage,
# not the first in this list.
#
# The obvious rule is priority order, and it is wrong. NVIDIA reports
# RevenueFromContractWithCustomerExcludingAssessedTax for 2017-2022 and nothing
# after, having moved to Revenues, which it carries from 2008 to 2026. Taking
# the first tag present gives NVIDIA a revenue series that stops in 2022 -- a
# chart that is silently four years stale, on the single most-looked-at company
# on the map. Found by reading the real document, not by guessing.
#
# So the list says which tags are acceptable, and coverage decides between
# them. Still exactly one tag per company: a series that switches definition
# partway through has a year-on-year across the seam comparing two different
# things.
REVENUE_TAGS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
)
OPERATING_INCOME_TAGS = ("OperatingIncomeLoss",)
CAPEX_TAGS = (
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
)

# A fact's period is read from its length. Annual is a year give or take a
# 52/53-week calendar; a quarter is thirteen weeks give or take.
ANNUAL_MIN_DAYS, ANNUAL_MAX_DAYS = 300, 400
QUARTER_MIN_DAYS, QUARTER_MAX_DAYS = 60, 120

PERIOD_ANNUAL = "annual"
PERIOD_QUARTER = "quarter"


class EdgarError(RuntimeError):
    """EDGAR is unreachable or answered with something unusable."""


def _client():
    import httpx
    return httpx.Client(headers=HEADERS, timeout=REQUEST_TIMEOUT,
                        follow_redirects=True)


def ticker_to_cik(client=None) -> dict[str, int]:
    """SEC's own ticker list. Upper-cased, because the map's tickers are."""
    own = client is None
    client = client or _client()
    try:
        r = client.get(TICKERS_URL)
        if r.status_code == 403 and CONTACT.startswith("CONTACT-"):
            raise EdgarError(PLACEHOLDER_HINT)
        if r.status_code != 200:
            raise EdgarError(f"company_tickers.json: HTTP {r.status_code}")
        payload = r.json()
    finally:
        if own:
            client.close()
    out: dict[str, int] = {}
    for rec in payload.values():
        t = str(rec.get("ticker", "")).upper()
        if t and t not in out:
            out[t] = int(rec["cik_str"])
    return out


def _facts(cik: int, client) -> dict:
    r = client.get(FACTS_URL.format(cik=cik))
    if r.status_code == 404:
        return {}
    if r.status_code == 403 and CONTACT.startswith("CONTACT-"):
        raise EdgarError(PLACEHOLDER_HINT)
    if r.status_code != 200:
        raise EdgarError(f"companyfacts CIK{cik:010d}: HTTP {r.status_code}")
    return r.json()


def _period_of(start: str, end: str) -> str | None:
    """annual, quarter, or None for a span that is neither."""
    try:
        a = dt.date.fromisoformat(start)
        b = dt.date.fromisoformat(end)
    except (TypeError, ValueError):
        return None
    n = (b - a).days
    if ANNUAL_MIN_DAYS <= n <= ANNUAL_MAX_DAYS:
        return PERIOD_ANNUAL
    if QUARTER_MIN_DAYS <= n <= QUARTER_MAX_DAYS:
        return PERIOD_QUARTER
    return None


def _rows_of(gaap: dict, tag: str) -> list[dict]:
    return ((gaap.get(tag) or {}).get("units") or {}).get("USD") or []


def best_tag(gaap: dict, tags: Iterable[str]) -> str | None:
    """The acceptable tag this filer carries furthest forward.

    Ranked by the newest period it covers, then by how many periods it covers.
    A tag a company abandoned years ago loses to the one it still files under,
    which is the whole point -- see the note on REVENUE_TAGS.
    """
    best, best_key = None, None
    for tag in tags:
        rows = _rows_of(gaap, tag)
        ends = [r["end"] for r in rows
                if r.get("start") and r.get("end")
                and _period_of(r["start"], r["end"])]
        if not ends:
            continue
        key = (max(ends), len(ends))
        if best_key is None or key > best_key:
            best, best_key = tag, key
    return best


def _collect(facts: dict, tags: Iterable[str], into: dict, field: str) -> None:
    """Fold one measure's USD facts into the period table, keyed by span."""
    gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    tag = best_tag(gaap, tags)
    if tag:
        rows = _rows_of(gaap, tag)
        for r in rows:
            start, end = r.get("start"), r.get("end")
            if not start or not end:
                continue                       # an instant, not a duration
            period = _period_of(start, end)
            if period is None:
                continue
            key = (period, end)
            rec = into.setdefault(key, {
                "period_end": dt.date.fromisoformat(end),
                "fiscal_year": r.get("fy"), "fiscal_period": r.get("fp"),
                "revenue": None, "operating_income": None,
                "capital_expenditure": None, "pub": "",
            })
            filed = str(r.get("filed") or "")
            # Later filings restate earlier ones. Keeping the most recently
            # filed value is the same rule the store applied, for the same
            # reason: the newest statement of a fact is the company's own
            # current answer.
            if filed >= rec["pub"]:
                rec["pub"] = filed
                rec["fiscal_year"] = r.get("fy")
                rec["fiscal_period"] = r.get("fp")
            if rec[field] is None or filed >= rec["pub"]:
                rec[field] = r.get("val")


def rows_from_facts(facts: dict) -> dict[str, list[dict]]:
    """{annual: [...], quarter: [...]} in the shape fundamentals.py expects."""
    table: dict[tuple[str, str], dict] = {}
    _collect(facts, REVENUE_TAGS, table, "revenue")
    _collect(facts, OPERATING_INCOME_TAGS, table, "operating_income")
    _collect(facts, CAPEX_TAGS, table, "capital_expenditure")
    out: dict[str, list[dict]] = {PERIOD_ANNUAL: [], PERIOD_QUARTER: []}
    for (period, _end), rec in table.items():
        if rec["revenue"] is None:
            continue          # the store's WHERE clause: no revenue, no row
        out[period].append(rec)
    for k in out:
        out[k].sort(key=lambda r: (r["period_end"], r["pub"]))
    return out


def rows_for(ticker: str, cik_map: dict[str, int] | None = None,
             client=None) -> dict[str, list[dict]]:
    """One company's periods, or empty when it does not file with the SEC."""
    own = client is None
    client = client or _client()
    try:
        cik_map = ticker_to_cik(client) if cik_map is None else cik_map
        cik = cik_map.get(ticker.upper())
        if cik is None:
            return {PERIOD_ANNUAL: [], PERIOD_QUARTER: []}
        return rows_from_facts(_facts(cik, client))
    finally:
        if own:
            client.close()


class Source:
    """A callable ticker -> rows, with one HTTP session and one CIK map.

    Constructed once per build. Sixty-odd companyfacts documents at a few MB
    each is the bulk of the fundamentals step, so the connection is reused and
    the calls are paced rather than issued as fast as they can be.
    """

    def __init__(self, client=None, sleep: float = SLEEP_BETWEEN):
        self._own = client is None
        self._client = client or _client()
        self._sleep = sleep
        self._cik: dict[str, int] | None = None

    def cik_map(self) -> dict[str, int]:
        if self._cik is None:
            self._cik = ticker_to_cik(self._client)
        return self._cik

    def __call__(self, ticker: str) -> dict[str, list[dict]]:
        rows = rows_for(ticker, self.cik_map(), self._client)
        if self._sleep:
            time.sleep(self._sleep)
        return rows

    def close(self) -> None:
        if self._own:
            self._client.close()

    def __enter__(self) -> "Source":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def main() -> int:
    import sys
    ticker = (sys.argv[1] if len(sys.argv) > 1 else "NVDA").upper()
    with Source() as src:
        rows = src(ticker)
    for period in (PERIOD_ANNUAL, PERIOD_QUARTER):
        print(f"{ticker} {period}: {len(rows[period])} periods")
        for r in rows[period][-4:]:
            rev = r["revenue"]
            print(f"  {r['period_end']}  rev {rev:>16,.0f}  "
                  f"filed {r['pub']}")
    if CONTACT.startswith("CONTACT-"):
        print(f"\nnote: chains/edgar.py CONTACT is still the placeholder "
              f"({CONTACT}). SEC asks for a real address.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
