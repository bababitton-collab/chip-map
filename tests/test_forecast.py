"""The ledger's arithmetic, against prices chosen so the answer is known by hand.

Every number in these fixtures is round on purpose. A test that asserts a hit
rate computed by the same code that produced it proves only that the code is
deterministic; these assert against returns worked out on paper, so a change in
the maths shows up as a wrong number rather than a differently-wrong one.
"""
from __future__ import annotations

import datetime as dt

import pytest

from chains import forecast, prices

# Ten consecutive weekday sessions. No holidays in the window, on purpose:
# the calendar is tested separately.
CAL = [dt.date(2026, 3, 2) + dt.timedelta(days=n)
       for n in (0, 1, 2, 3, 4, 7, 8, 9, 10, 11, 14, 15, 16, 17, 18,
                 21, 22, 23, 24, 25, 28, 29, 30, 31)]
CAL = [d for d in CAL if d.weekday() < 5]

DOC = {
    "nodes": [
        {"id": "up", "price_symbol": "UP.US", "price_symbol_kind": "primary"},
        {"id": "down", "price_symbol": "DOWN.US",
         "price_symbol_kind": "primary"},
        {"id": "flat", "price_symbol": "FLAT.US",
         "price_symbol_kind": "primary"},
    ],
    "subnodes": [
        {"id": "noprice", "price_symbol": "NOPRICE.US"},
    ],
}
NODE_SYMS = ["UP.US", "DOWN.US", "FLAT.US"]


def write(monkeypatch, tmp_path, symbol: str, values: dict[dt.date, float]):
    monkeypatch.setenv("CHIP_MAP_PRICES", str(tmp_path))
    prices.store(symbol, [{"date": d.isoformat(), "adjusted_close": v}
                          for d, v in sorted(values.items())])


@pytest.fixture
def book(monkeypatch, tmp_path):
    """UP rises 1% a session, DOWN falls 1%, FLAT does nothing.

    Compounding is avoided by construction: the levels are written out, so the
    expected returns below are read off the numbers rather than derived.
    """
    monkeypatch.setenv("CHIP_MAP_PRICES", str(tmp_path))
    up, down, flat = {}, {}, {}
    for i, d in enumerate(CAL):
        up[d] = 100.0 + i          # +1 a session on a 100 base
        down[d] = 100.0 - i
        flat[d] = 100.0
    write(monkeypatch, tmp_path, "UP.US", up)
    write(monkeypatch, tmp_path, "DOWN.US", down)
    write(monkeypatch, tmp_path, "FLAT.US", flat)
    return forecast.Book(NODE_SYMS)


def fc(fid, qid, marked_at, direction, win, lose, status="yes"):
    return {"id": fid, "qid": qid, "marked_at": marked_at, "status": status,
            "direction": direction, "win": win, "lose": lose,
            "benchmark": "EW_MAP", "horizons": [5, 10, 20]}


# -- the calendar ------------------------------------------------------------

def test_entry_is_the_first_session_strictly_after_the_mark():
    """Strictly: a mark written while a session is printing is entered at the
    NEXT close, not the one it was watching."""
    assert forecast.entry_session("2026-03-02", CAL) == dt.date(2026, 3, 3)


def test_a_mark_on_a_weekend_enters_on_mondays_close():
    """Saturday 2026-03-07 and Sunday the 8th both enter on Monday the 9th."""
    assert forecast.entry_session("2026-03-07", CAL) == dt.date(2026, 3, 9)
    assert forecast.entry_session("2026-03-08", CAL) == dt.date(2026, 3, 9)


def test_a_mark_with_no_session_after_it_yet_has_no_entry():
    assert forecast.entry_session("2026-04-30", CAL) is None


def test_a_timestamp_is_read_as_its_date():
    assert forecast.entry_session("2026-03-02T18:30:00Z", CAL) == dt.date(
        2026, 3, 3)


def test_the_derived_calendar_has_no_weekends(monkeypatch, tmp_path):
    monkeypatch.setenv("CHIP_MAP_PRICES", str(tmp_path))
    days = CAL + [dt.date(2026, 3, 7)]        # a Saturday only one name prints
    for sym in NODE_SYMS:
        vals = {d: 100.0 for d in CAL}
        prices.store(sym, [{"date": d.isoformat(), "adjusted_close": v}
                           for d, v in sorted(vals.items())])
    prices.store("ODD.US", [{"date": dt.date(2026, 3, 7).isoformat(),
                             "adjusted_close": 1.0}])
    cal = forecast.sessions(NODE_SYMS + ["ODD.US"])
    assert dt.date(2026, 3, 7) not in cal, "one symbol is not a session"
    assert all(d.weekday() < 5 for d in cal)


# -- the measures ------------------------------------------------------------

def test_a_symbol_return_is_measured_from_the_entry_close(book):
    entry = CAL[0]
    r = forecast.symbol_returns(book, "UP.US", entry, CAL[:6])
    assert r[0] == pytest.approx(0.0)
    assert r[5] == pytest.approx(5 / 100)


def test_a_basket_is_the_equal_weight_of_its_members(book):
    entry = CAL[0]
    r = forecast.basket_returns(book, ["UP.US", "FLAT.US"], entry, CAL[:6])
    # +5% and 0% -> +2.5%
    assert r[5] == pytest.approx(0.025)


def test_ew_map_uses_the_symbols_that_printed_that_day(monkeypatch, tmp_path):
    """One name missing on one day drops out of that day's mean and rejoins
    the next. It does not take the index with it, and it does not freeze it."""
    monkeypatch.setenv("CHIP_MAP_PRICES", str(tmp_path))
    a = {d: 100.0 * (1.10 ** i) for i, d in enumerate(CAL[:4])}   # +10%/session
    b = {d: 100.0 for d in CAL[:4]}                                # flat
    del b[CAL[2]]                                                  # b misses day 2
    for sym, vals in (("UP.US", a), ("FLAT.US", b)):
        prices.store(sym, [{"date": d.isoformat(), "adjusted_close": v}
                           for d, v in sorted(vals.items())])
    bk = forecast.Book(["UP.US", "FLAT.US"])
    out = forecast.ew_map(bk, ["UP.US", "FLAT.US"], CAL[0], CAL[:4])
    # day1: mean(+10%, 0%) = +5%. day2: FLAT is stale -- its last close on or
    # before day2 is day1's, so it still contributes 0%; mean is +5% again.
    assert out[1] == pytest.approx(0.05)
    assert out[2] == pytest.approx(1.05 * 1.05 - 1)


def test_the_excess_formula_nets_the_benchmark_out():
    win = [0.10] * 3
    lose = [0.02] * 3
    bench = [0.04] * 3
    out = forecast.excess(win, lose, bench)
    assert out[0] == pytest.approx(0.08)          # (.10-.04)-(.02-.04)


def test_with_no_lose_side_the_excess_is_against_the_benchmark_alone():
    out = forecast.excess([0.10], [], [0.04])
    assert out[0] == pytest.approx(0.06)


# -- two forecasts, one hit and one miss -------------------------------------

def scored(book, monkeypatch, tmp_path, forecasts, log=None):
    monkeypatch.setenv("CHIP_MAP_PRICES", str(tmp_path))
    return forecast.build(forecasts, DOC, log=log if log is not None else [],
                          cal=CAL)


def test_a_hit_and_a_miss_are_scored_as_such(book, monkeypatch, tmp_path):
    """UP beats DOWN, and both forecasts point at the same fact.

    hit:  direction +1, win=[up] lose=[down]  -> excess strongly positive
    miss: direction -1, same baskets          -> same excess, wrong direction
    """
    led = scored(book, monkeypatch, tmp_path, [
        fc("f-hit", "mu_fq4", "2026-03-02", 1, ["up"], ["down"]),
        fc("f-miss", "nvda_q3", "2026-03-02", -1, ["up"], ["down"]),
    ])
    rows = {r["id"]: r for r in led["rows"]}
    h5 = rows["f-hit"]["horizons"]["5"]
    m5 = rows["f-miss"]["horizons"]["5"]

    # entry is CAL[1]; five sessions later is CAL[6].
    # UP: 106/101-1 = +4.9505%   DOWN: 94/99-1 = -5.0505%
    assert h5["win"] == pytest.approx(106 / 101 - 1, rel=1e-6)
    assert h5["lose"] == pytest.approx(94 / 99 - 1, rel=1e-6)
    assert h5["excess"] == pytest.approx((106 / 101 - 1) - (94 / 99 - 1),
                                         rel=1e-6)
    assert h5["hit"] is True
    assert m5["excess"] == pytest.approx(h5["excess"], rel=1e-9)
    assert m5["hit"] is False, "same excess, opposite direction"


def test_the_summary_counts_both(book, monkeypatch, tmp_path):
    led = scored(book, monkeypatch, tmp_path, [
        fc("f-hit", "mu_fq4", "2026-03-02", 1, ["up"], ["down"]),
        fc("f-miss", "nvda_q3", "2026-03-02", -1, ["up"], ["down"]),
    ])
    s = led["summary"]["horizons"]["5"]
    assert s["n"] == 2 and s["hits"] == 1 and s["hit_rate"] == 0.5
    assert s["mean_excess"] == pytest.approx(
        led["rows"][0]["horizons"]["5"]["excess"], rel=1e-6)


def test_the_capital_rule_travels_with_every_summary(book, monkeypatch,
                                                     tmp_path):
    """The number is never readable without the caveat attached to it."""
    led = scored(book, monkeypatch, tmp_path,
                 [fc("f", "mu_fq4", "2026-03-02", 1, ["up"], ["down"])])
    assert led["summary"]["capital_rule"] == "no capital decision below N=30"
    assert led["summary"]["min_n"] == 30


def test_an_empty_ledger_is_valid(monkeypatch, tmp_path):
    monkeypatch.setenv("CHIP_MAP_PRICES", str(tmp_path))
    led = forecast.build([], DOC)
    assert led["rows"] == []
    assert led["summary"]["horizons"]["5"]["n"] == 0
    assert led["summary"]["capital_rule"]


# -- missing prices ----------------------------------------------------------

def test_a_symbol_without_a_price_line_is_skipped_and_logged(book, monkeypatch,
                                                             tmp_path):
    log: list[str] = []
    led = scored(book, monkeypatch, tmp_path,
                 [fc("f", "mu_fq4", "2026-03-02", 1, ["up", "noprice"],
                     ["down"])], log=log)
    syms = [s["id"] for s in led["rows"][0]["symbols"]]
    assert "noprice" in [s for s in ("noprice",)] and "noprice" not in syms
    assert any("noprice" in line and "no price line" in line for line in log)
    # and the surviving leg still scores
    assert led["rows"][0]["horizons"]["5"]["win"] == pytest.approx(
        106 / 101 - 1, rel=1e-6)


def test_a_leg_absent_from_the_map_is_skipped_and_logged(book, monkeypatch,
                                                         tmp_path):
    """Nine ids in the watch baskets name companies the map has no node for.
    They have no symbol at all, which is a different miss from having a symbol
    with no data, and it is logged as such."""
    log: list[str] = []
    scored(book, monkeypatch, tmp_path,
           [fc("f", "mu_fq4", "2026-03-02", 1, ["up", "ghost"], ["down"])],
           log=log)
    assert any("ghost" in line and "no price symbol" in line for line in log)


def test_a_forecast_whose_win_basket_is_entirely_unpriced_is_not_scored(
        book, monkeypatch, tmp_path):
    """Seven of the registered questions are in this state today. A row with
    nothing on the long side is not a weak forecast, it is not a forecast."""
    log: list[str] = []
    led = scored(book, monkeypatch, tmp_path,
                 [fc("f", "mu_fq4", "2026-03-02", 1, ["ghost"], ["down"])],
                 log=log)
    assert led["rows"] == []
    assert any("not scored" in line for line in log)


# -- horizons lock only when they arrive -------------------------------------

def test_a_horizon_is_none_until_its_session_has_closed(book, monkeypatch,
                                                        tmp_path):
    """Twelve sessions exist, entry is the second, so eleven have closed
    since: 5 and 10 lock, 20 has not arrived and stays null. A horizon that
    reported a number before its date would be reading a shorter window under
    a longer label."""
    monkeypatch.setenv("CHIP_MAP_PRICES", str(tmp_path))
    led = forecast.build(
        [fc("f", "mu_fq4", "2026-03-02", 1, ["up"], ["down"])],
        DOC, log=[], cal=CAL[:12])
    hz = led["rows"][0]["horizons"]
    assert hz["5"] is not None and hz["10"] is not None
    assert hz["20"] is None, "not enough sessions have closed"
    assert led["summary"]["horizons"]["20"]["n"] == 0
    assert led["summary"]["horizons"]["20"]["n_pending"] == 1


def test_a_mark_with_no_session_yet_is_pending_entry(book, monkeypatch,
                                                     tmp_path):
    led = scored(book, monkeypatch, tmp_path,
                 [fc("f", "mu_fq4", "2026-04-30", 1, ["up"], ["down"])])
    r = led["rows"][0]
    assert r["pending_entry"] is True and r["entry_session"] is None
    assert led["summary"]["n_pending"] == 1


# -- what travels to the page ------------------------------------------------

def test_the_per_symbol_series_is_capped(book, monkeypatch, tmp_path):
    led = scored(book, monkeypatch, tmp_path,
                 [fc("f", "mu_fq4", "2026-03-02", 1, ["up"], ["down"])])
    for s in led["rows"][0]["symbols"]:
        assert len(s["series"]) <= forecast.MAX_SERIES
    assert len(led["rows"][0]["series"]) <= forecast.MAX_SERIES


def test_dropping_the_symbol_series_keeps_the_basket_one(book, monkeypatch,
                                                         tmp_path):
    """The first thing given up under the size ceiling. The basket line is the
    claim; the per-symbol lines are the detail behind it."""
    led = scored(book, monkeypatch, tmp_path,
                 [fc("f", "mu_fq4", "2026-03-02", 1, ["up"], ["down"])])
    forecast.drop_symbol_series(led)
    assert all("series" not in s for s in led["rows"][0]["symbols"])
    assert led["rows"][0]["series"], "the basket series must survive"
