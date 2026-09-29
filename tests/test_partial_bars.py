"""A bar is not a close until its session has closed.

Yahoo's ``interval=1d`` returns the day in progress as the final row, and its
"close" is the last trade so far -- the same number as
``meta.regularMarketPrice``. Published as end-of-day it is a live quote
wearing a settled price's name.

Deploy 36518572381 built at 03:46 UTC on 2026-09-29 and stored twenty such
bars: every Asia-Pacific listing on the site (KRX, TSE, TWSE, TPEx, SSE, SZSE,
NSE, ASX), each mid-session, and none of the US or European ones, which had
not opened. The front door then said "prices through 2026-09-29", because
``last_price_date`` is the max over all symbols and one unfinished bar carries
the whole map forward.

WHERE THIS IS ENFORCED, AND WHAT THAT DOES NOT COVER
----------------------------------------------------
One gate, in the provider, because that is the single place a bar enters the
system: chains/providers/yahoo.py drops the final row unless the payload
demonstrates the session ended.

Scoring cannot make this check for itself. chains/forecast.py reads closes
from the price store and the store records no completeness flag, so by the
time a price reaches a forecast the question "was this session open when we
fetched it" is no longer answerable from the data. What is asserted below is
the chain of custody -- scoring reads the store, the store is written from
provider rows, the provider drops open sessions -- and that a stored partial
bar is overwritten rather than kept. Making scoring itself refuse would mean
recording completeness per bar, which is a schema change and a bigger one than
this.
"""
from __future__ import annotations

import datetime as dt
import inspect

import polars as pl
import pytest

from chains import forecast, prices
from chains.providers import yahoo
from chains.providers.yahoo import YahooClient, _session_open

UTC = dt.timezone.utc

# The real moment the bad build fetched, and Seoul's session that day.
FETCH = dt.datetime(2026, 9, 29, 3, 46, 25, tzinfo=UTC).timestamp()
KRX_OPEN = dt.datetime(2026, 9, 29, 0, 0, tzinfo=UTC).timestamp()
KRX_SHUT = dt.datetime(2026, 9, 29, 6, 0, tzinfo=UTC).timestamp()
# New York had not opened yet that morning; its last close was the 28th.
NYSE_OPEN = dt.datetime(2026, 9, 29, 13, 30, tzinfo=UTC).timestamp()
NYSE_SHUT = dt.datetime(2026, 9, 29, 20, 0, tzinfo=UTC).timestamp()


def payload(dates, closes, *, regular=None, gmtoffset=None,
            market_price=None):
    """A chart payload in the shape the endpoint really returns."""
    meta = {}
    if regular:
        meta["currentTradingPeriod"] = {"regular": {"start": regular[0],
                                                    "end": regular[1]}}
    if gmtoffset is not None:
        meta["gmtoffset"] = gmtoffset
    if market_price is not None:
        meta["regularMarketPrice"] = market_price
    stamps = [int(d.timestamp()) for d in dates]
    return {"chart": {"result": [{
        "meta": meta,
        "timestamp": stamps,
        "indicators": {
            "quote": [{"close": list(closes),
                       "open": list(closes), "high": list(closes),
                       "low": list(closes), "volume": [1] * len(closes)}],
            "adjclose": [{"adjclose": list(closes)}],
        }}]}}


def rows(p, now=FETCH):
    return YahooClient._rows("005930.KO", "005930.KS", p, now=now)


# -- a. the final bar goes only when its session has ended ---------------------
def test_a_bar_from_a_session_still_trading_is_dropped():
    p = payload([dt.datetime(2026, 9, 28, 0, 0, tzinfo=UTC),
                 dt.datetime(2026, 9, 29, 0, 0, tzinfo=UTC)],
                [270000.0, 272500.0], regular=(KRX_OPEN, KRX_SHUT))
    assert [r["date"] for r in rows(p)] == ["2026-09-28"]


def test_the_same_bar_is_kept_once_the_session_has_closed():
    p = payload([dt.datetime(2026, 9, 28, 0, 0, tzinfo=UTC),
                 dt.datetime(2026, 9, 29, 0, 0, tzinfo=UTC)],
                [270000.0, 272500.0], regular=(KRX_OPEN, KRX_SHUT))
    after = dt.datetime(2026, 9, 29, 7, 0, tzinfo=UTC).timestamp()
    assert [r["date"] for r in rows(p, now=after)] == ["2026-09-28", "2026-09-29"]


def test_the_boundary_is_the_session_end_itself():
    p = payload([dt.datetime(2026, 9, 29, 0, 0, tzinfo=UTC)], [272500.0],
                regular=(KRX_OPEN, KRX_SHUT))
    assert rows(p, now=KRX_SHUT - 1) == []
    assert [r["date"] for r in rows(p, now=KRX_SHUT)] == ["2026-09-29"]


def test_a_market_that_has_not_opened_keeps_its_last_close():
    """New York at 03:46 UTC: the 29th has not begun, so the 28th is the last
    bar and it is complete. Nothing is dropped."""
    p = payload([dt.datetime(2026, 9, 25, 13, 30, tzinfo=UTC),
                 dt.datetime(2026, 9, 28, 13, 30, tzinfo=UTC)],
                [100.0, 101.0], regular=(NYSE_OPEN, NYSE_SHUT))
    assert [r["date"] for r in rows(p)] == ["2026-09-25", "2026-09-28"]


def test_only_the_final_bar_is_ever_questioned():
    """History is history. A rule that walked the whole series would start
    deleting closes that settled years ago."""
    days = [dt.datetime(2026, 9, d, 0, 0, tzinfo=UTC) for d in (23, 24, 25, 28, 29)]
    p = payload(days, [1.0, 2.0, 3.0, 4.0, 5.0], regular=(KRX_OPEN, KRX_SHUT))
    got = [r["date"] for r in rows(p)]
    assert got == ["2026-09-23", "2026-09-24", "2026-09-25", "2026-09-28"]


def test_an_empty_series_is_still_empty():
    p = payload([], [], regular=(KRX_OPEN, KRX_SHUT))
    assert rows(p) == []


def test_no_internal_field_leaks_into_a_stored_row():
    p = payload([dt.datetime(2026, 9, 28, 0, 0, tzinfo=UTC)], [270000.0],
                regular=(KRX_OPEN, KRX_SHUT))
    got = rows(p)
    assert got and set(got[0]) == {"date", "open", "high", "low", "close",
                                   "adjusted_close", "volume"}


# -- b. the fingerprint that was actually observed -----------------------------
def test_the_live_quote_wearing_a_closes_name_is_dropped():
    """The bar that shipped: 005930 on 2026-09-29, close 272500.0, identical
    to meta.regularMarketPrice, with Seoul open until 06:00 UTC."""
    p = payload([dt.datetime(2026, 9, 28, 0, 0, tzinfo=UTC),
                 dt.datetime(2026, 9, 29, 0, 0, tzinfo=UTC)],
                [270000.0, 272500.0], regular=(KRX_OPEN, KRX_SHUT),
                market_price=272500.0)
    got = rows(p)
    assert [r["date"] for r in got] == ["2026-09-28"]
    assert all(r["close"] != 272500.0 for r in got)


# -- the fallbacks, when the payload says less ---------------------------------
def test_without_a_trading_period_the_exchange_date_decides():
    """No currentTradingPeriod, but gmtoffset. A bar dated locally today
    cannot be shown to have closed, so it is not kept."""
    seoul = 9 * 3600
    p = payload([dt.datetime(2026, 9, 29, 0, 0, tzinfo=UTC)], [272500.0],
                gmtoffset=seoul)
    assert rows(p) == []
    # The day before is behind the exchange's today, so it stays.
    p2 = payload([dt.datetime(2026, 9, 28, 0, 0, tzinfo=UTC)], [270000.0],
                 gmtoffset=seoul)
    assert [r["date"] for r in rows(p2)] == ["2026-09-28"]


def test_with_no_meta_at_all_a_bar_dated_today_is_not_kept():
    p = payload([dt.datetime(2026, 9, 29, 0, 0, tzinfo=UTC)], [272500.0])
    assert rows(p) == []
    p2 = payload([dt.datetime(2026, 9, 28, 0, 0, tzinfo=UTC)], [270000.0])
    assert [r["date"] for r in rows(p2)] == ["2026-09-28"]


def test_silence_is_never_read_as_a_close():
    """The rule in one line: a bar is dropped unless the payload demonstrates
    the session ended."""
    src = inspect.getsource(_session_open)
    assert "currentTradingPeriod" in src and "gmtoffset" in src
    for meta in ({}, {"gmtoffset": 0}, {"currentTradingPeriod": {}}):
        assert _session_open({"meta": meta},
                             dt.datetime(2026, 9, 29, 0, 0, tzinfo=UTC).timestamp(),
                             FETCH) is True


# -- c. one map, several venues ------------------------------------------------
def test_the_price_date_never_runs_ahead_of_the_newest_complete_bar():
    """A mixed map at 03:46 UTC: Seoul mid-session, New York not yet open.
    last_price_date is the max over the symbols, so the open session must not
    be among them or it carries the whole map a day forward."""
    seoul = payload([dt.datetime(2026, 9, 28, 0, 0, tzinfo=UTC),
                     dt.datetime(2026, 9, 29, 0, 0, tzinfo=UTC)],
                    [270000.0, 272500.0], regular=(KRX_OPEN, KRX_SHUT))
    york = payload([dt.datetime(2026, 9, 25, 13, 30, tzinfo=UTC),
                    dt.datetime(2026, 9, 28, 13, 30, tzinfo=UTC)],
                   [100.0, 101.0], regular=(NYSE_OPEN, NYSE_SHUT))
    last = {"005930.KO": rows(seoul)[-1]["date"],
            "AAPL.US": rows(york)[-1]["date"]}
    assert last == {"005930.KO": "2026-09-28", "AAPL.US": "2026-09-28"}
    assert max(last.values()) == "2026-09-28"


def test_the_price_date_is_a_max_over_symbols_and_that_is_why_this_matters():
    """Read out of the code, so the reason this bug reached the front door
    stays written down beside the fix."""
    src = inspect.getsource(__import__("chains.live_snapshot",
                                       fromlist=["x"]))
    assert 'max((p["last"] for p in cache.values() if p)' in src


# -- the store keeps no partial bar --------------------------------------------
def _stored_partial(tmp_path, monkeypatch, settled):
    """A store holding the partial bar, then a tail fetch carrying the close
    it settled at. Returns what append decided and what is on disk after."""
    monkeypatch.setenv("CHIP_MAP_PRICES", str(tmp_path))
    sym = "005930.KO"
    prices.store(sym, [
        {"date": "2026-09-28", "adjusted_close": 270000.0},
        {"date": "2026-09-29", "adjusted_close": 272500.0},   # the partial one
    ])
    assert prices.load(sym)["adj_close"].to_list()[-1] == 272500.0
    kept, restated = prices.append(sym, [
        {"date": "2026-09-28", "adjusted_close": 270000.0},
        {"date": "2026-09-29", "adjusted_close": settled},
    ])
    return sym, restated, prices.load(sym)


def test_a_partial_bar_that_settled_somewhere_else_forces_a_refetch(tmp_path,
                                                                    monkeypatch):
    """The common case, and the one the twenty in the cache will take. The
    quote at 03:46 and the close at 06:00 differ by more than ADJ_TOLERANCE,
    so the overlap is read as a restatement and the WHOLE series is refetched
    -- which is the heavier of the two ways this cleans itself, and the surer.
    """
    sym, restated, got = _stored_partial(tmp_path, monkeypatch, 268000.0)
    assert restated is True
    # append leaves the file alone and hands the decision up; refresh() then
    # calls store() with the full series, which replaces it outright.
    prices.store(sym, [{"date": "2026-09-28", "adjusted_close": 270000.0},
                       {"date": "2026-09-29", "adjusted_close": 268000.0}])
    after = prices.load(sym)
    assert after.height == 2
    assert after["adj_close"].to_list()[-1] == 268000.0


def test_a_partial_bar_that_barely_moved_is_merged_over(tmp_path, monkeypatch):
    """And the light case: inside the tolerance, the tail merges with
    keep="last" and the settled close simply replaces the quote."""
    sym, restated, got = _stored_partial(tmp_path, monkeypatch, 272510.0)
    assert restated is False
    assert got.height == 2, "the day is replaced, not duplicated"
    assert got["adj_close"].to_list()[-1] == 272510.0


def test_the_tail_fetch_always_reaches_back_over_the_last_stored_bar():
    """Which is what lets the overwrite above ever happen."""
    assert prices.OVERLAP_DAYS >= 1
    src = inspect.getsource(prices)
    assert "timedelta(days=OVERLAP_DAYS)" in src


# -- d. the real store ---------------------------------------------------------
def test_no_stored_series_carries_a_bar_from_the_future():
    """What can be checked without a network: a bar dated after today is
    wrong however it got there. Whether yesterday's Tokyo bar was complete
    cannot be re-derived offline -- the store records no completeness flag,
    which is the note in this module's docstring."""
    from chains.paths import prices_dir
    store = prices_dir()
    if not store.is_dir():
        pytest.skip("no price store on this machine")
    today = dt.datetime.now(UTC).date()
    bad = []
    for p in sorted(store.glob("*.parquet")):
        try:
            df = pl.read_parquet(p)
        except Exception:
            continue
        if df.is_empty() or "date" not in df.columns:
            continue
        last = df["date"].max()
        last = last if isinstance(last, dt.date) else dt.date.fromisoformat(str(last))
        if last > today:
            bad.append(f"{p.stem}: {last}")
    assert bad == [], bad


# -- e. the chain of custody ---------------------------------------------------
def test_scoring_reads_prices_only_from_the_store():
    """So the provider's gate is the only door. A scoring path that called a
    client directly would be a second one, and this rule would not cover it."""
    src = inspect.getsource(forecast)
    assert "prices.load(" in src
    for direct in ("YahooClient", "httpx", "requests.get", "urlopen"):
        assert direct not in src, f"forecast.py reaches for {direct}"


def test_the_store_is_written_only_from_provider_rows():
    src = inspect.getsource(prices)
    for direct in ("YahooClient(", "httpx.get", "requests.get"):
        assert direct not in src, f"prices.py fetches directly via {direct}"


def test_the_gate_is_in_the_one_place_a_bar_enters():
    src = inspect.getsource(yahoo)
    assert "_session_open(res, out[-1]" in src
    # And it is applied on the endpoint the store actually calls.
    assert "return self._rows(symbol, y, payload)" in src
