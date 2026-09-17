"""The track record of a closed question: the window, the legs, the benchmarks.

Every expected number here is worked out on paper from round prices, not read
back from the code that produced it. The window is deliberately short -- three
sessions -- because that is what a question signed last week actually has, and
a page that only works with a year of history would be no use for months.
"""
from __future__ import annotations

import datetime as dt

import pytest

from chains import forecast, prices, record

CAL = [dt.date(2026, 9, 9), dt.date(2026, 9, 10), dt.date(2026, 9, 11),
       dt.date(2026, 9, 14), dt.date(2026, 9, 15), dt.date(2026, 9, 16)]
TODAY = CAL[-1]

# UP rises 10% a session from 100; DOWN falls 10% from 100; FLAT never moves.
# ADR is the same shape as FLAT, priced through a New York line.
SERIES = {
    "UP.US": [100.0, 110.0, 121.0, 133.1, 146.41, 161.051],
    "DOWN.US": [100.0, 90.0, 81.0, 72.9, 65.61, 59.049],
    "FLAT.US": [100.0] * 6,
    "SHECY.US": [50.0] * 6,
    "SOXQ.US": [200.0, 200.0, 200.0, 200.0, 200.0, 220.0],
}

DOC = {
    "nodes": [
        {"id": "up", "ticker": "UP", "price_symbol": "UP.US",
         "price_symbol_kind": "primary"},
        {"id": "down", "ticker": "DOWN", "price_symbol": "DOWN.US",
         "price_symbol_kind": "primary"},
        {"id": "flat", "ticker": "FLAT", "price_symbol": "FLAT.US",
         "price_symbol_kind": "primary"},
        {"id": "shinetsu", "ticker": "4063.T", "price_symbol": "SHECY.US",
         "price_symbol_kind": "adr"},
        {"id": "private", "ticker": "PRIV"},
    ],
    "subnodes": [],
}
NODE_SYMS = ["UP.US", "DOWN.US", "FLAT.US", "SHECY.US"]


@pytest.fixture
def book(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIP_MAP_PRICES", str(tmp_path))
    for sym, vals in SERIES.items():
        prices.store(sym, [{"date": d.isoformat(), "adjusted_close": v,
                            "open": v, "high": v * 1.01, "low": v * 0.99,
                            "close": v, "volume": 1000}
                           for d, v in zip(CAL, vals)])
    return forecast.Book(list(SERIES))


KINDS = record.kinds_for(DOC)


def card(**over) -> dict:
    r = {"qid": "q1", "who": "Acme Q3", "tk": "ACME", "d": "2026-09-10",
         "status": "mixed", "win": ["up"], "lose": ["down"],
         "commitment": {"committed_at": "2026-09-10", "sha256": "a" * 64,
                        "answer_date": "2026-09-10"},
         "official": {"counts": False, "state": "unscored", "reason": "x"},
         "horizons": {}, "primary_horizon": 20}
    r.update(over)
    return r


# -- the window --------------------------------------------------------------
def test_the_window_starts_at_the_session_the_contract_was_signed_on():
    w = record.window_from(dt.date(2026, 9, 10), CAL, TODAY)
    assert w[0] == dt.date(2026, 9, 10) and w[-1] == TODAY and len(w) == 5


def test_a_signature_on_a_closed_day_baselines_on_the_session_before_it():
    """2026-09-13 is a Sunday. The claim was signed against Friday's close."""
    w = record.window_from(dt.date(2026, 9, 13), CAL, TODAY)
    assert w[0] == dt.date(2026, 9, 11)


def test_a_signature_after_every_session_has_no_window():
    assert record.window_from(dt.date(2026, 9, 20), CAL, TODAY) == []
    assert record.window_from(None, CAL, TODAY) == []


# -- the legs ----------------------------------------------------------------
def test_the_daily_move_is_the_last_session_and_the_other_is_cumulative(book):
    w = record.window_from(dt.date(2026, 9, 10), CAL, TODAY)
    rows = record.leg_rows({"win": ["up"], "lose": []}, DOC, book, KINDS, w,
                           None, CAL)
    (up,) = rows
    assert up["commit_close"] == 110.0 and up["last"] == 161.051
    # Percentages, converted once in record.py as the rest of the payload is.
    assert up["day_pct"] == pytest.approx(10.0)          # 146.41 -> 161.051
    assert up["since_commit"] == pytest.approx(46.41)    # 110 -> 161.051
    assert up["since_entry"] is None, "no entry, so no number pretending to be one"


def test_an_entry_adds_its_own_date_and_price_without_moving_the_rest(book):
    w = record.window_from(dt.date(2026, 9, 10), CAL, TODAY)
    (up,) = record.leg_rows({"win": ["up"], "lose": []}, DOC, book, KINDS, w,
                            dt.date(2026, 9, 14), CAL)
    assert up["entry_date"] == "2026-09-14" and up["entry_close"] == 133.1
    assert up["since_entry"] == pytest.approx(21.0)      # 133.1 -> 161.051
    assert up["since_commit"] == pytest.approx(46.41)    # unchanged


def test_both_sides_of_the_basket_are_rows_in_the_order_they_were_signed(book):
    w = record.window_from(dt.date(2026, 9, 10), CAL, TODAY)
    rows = record.leg_rows({"win": ["up", "flat"], "lose": ["down"]}, DOC,
                           book, KINDS, w, None, CAL)
    assert [(r["tk"], r["group"]) for r in rows] == [
        ("UP", "win"), ("FLAT", "win"), ("DOWN", "lose")]
    assert rows[2]["since_commit"] == pytest.approx(-34.39)


def test_a_leg_with_no_series_keeps_its_row_and_says_so(book):
    w = record.window_from(dt.date(2026, 9, 10), CAL, TODAY)
    rows = record.leg_rows({"win": ["up", "private"], "lose": []}, DOC, book,
                           KINDS, w, None, CAL)
    assert len(rows) == 2, "a dropped leg would make the basket look smaller"
    priv = rows[1]
    assert priv["no_series"] == "no clean series"
    assert priv["last"] is None and priv["since_commit"] is None


def test_a_leg_priced_through_an_adr_says_which_line_was_used(book):
    w = record.window_from(dt.date(2026, 9, 10), CAL, TODAY)
    (adr,) = record.leg_rows({"win": ["shinetsu"], "lose": []}, DOC, book,
                             KINDS, w, None, CAL)
    assert adr["priced_via"] == "adr" and adr["symbol"] == "SHECY.US"
    assert adr["tk"] == "4063.T", "the home ticker, with the traded line beside it"
    assert adr["currency"] == "USD"


# -- the benchmarks ----------------------------------------------------------
def test_the_basket_is_measured_against_the_map_and_sox_over_one_window(book):
    w = record.window_from(dt.date(2026, 9, 14), CAL, TODAY)   # 3 sessions
    b = record.benchmarks({"win": ["up"], "lose": ["down"]}, book, NODE_SYMS,
                          KINDS, w)
    assert (b["from"], b["to"], b["sessions"]) == ("2026-09-14", "2026-09-16", 2)
    assert b["win"] == pytest.approx(21.0)      # 133.1 -> 161.051
    assert b["lose"] == pytest.approx(-19.0)    # 72.9 -> 59.049
    assert b["sox"] == pytest.approx(10.0)      # 200 -> 220
    # EW_MAP is the daily-rebalanced mean of the four priced stations.
    assert b["ew"] == pytest.approx(0.0, abs=2.0)
    assert b["win_ew"] == pytest.approx(b["win"] - b["ew"])
    assert b["win_sox"] == pytest.approx(b["win"] - b["sox"])


def test_a_basket_with_no_priced_leg_reports_nothing_rather_than_zero(book):
    w = record.window_from(dt.date(2026, 9, 14), CAL, TODAY)
    b = record.benchmarks({"win": ["private"], "lose": []}, book, NODE_SYMS,
                          KINDS, w)
    assert b["win"] is None and b["win_ew"] is None
    assert b["ew"] is not None, "the benchmark still printed"


# -- the drawing and the table ----------------------------------------------
def test_a_legs_contribution_is_its_share_of_its_own_side(book):
    """Two priced legs on the win side, so each put in half of its own move.
    A leg with no series does not dilute the ones that have one."""
    w = record.window_from(dt.date(2026, 9, 14), CAL, TODAY)
    up, flat, priv = record.leg_rows(
        {"win": ["up", "flat", "private"], "lose": []}, DOC, book, KINDS, w,
        None, CAL)
    assert up["weight"] == 0.5 and flat["weight"] == 0.5
    assert up["contribution"] == pytest.approx(10.5)     # half of +21.0%
    assert flat["contribution"] == pytest.approx(0.0)
    assert priv["weight"] is None and priv["contribution"] is None


def test_there_is_one_candle_per_company_that_has_a_series(book):
    """One chart per company, in the order the basket was signed. They belong
    to the question's own page, which has room to draw them large."""
    w = record.window_from(dt.date(2026, 9, 14), CAL, TODAY)
    rows = record.leg_rows({"win": ["private", "up", "flat"], "lose": ["down"]},
                           DOC, book, KINDS, w, None, CAL)
    cs = record.candles_for(rows, w)
    assert [c["id"] for c in cs] == ["up", "flat", "down"]
    assert all(c["svg"].startswith("<svg") and c["sessions"] == 3 for c in cs)
    assert [c["group"] for c in cs] == ["win", "win", "lose"]


def test_with_nothing_drawable_there_are_no_candles(book):
    w = record.window_from(dt.date(2026, 9, 14), CAL, TODAY)
    rows = record.leg_rows({"win": ["private"], "lose": []}, DOC, book, KINDS,
                           w, None, CAL)
    assert record.candles_for(rows, w) == []


def test_a_resolved_card_gets_a_record_and_an_unresolved_one_does_not(book):
    data = {"forecasts": [card(), card(qid="q2", status="open",
                                       commitment={"committed_at": "2026-09-10"})]}
    record.attach(data, DOC, book, NODE_SYMS, CAL, TODAY)
    assert "record" in data["forecasts"][0]
    assert "record" not in data["forecasts"][1]
    assert [r["qid"] for r in data["record_table"]] == ["q1"]


def test_the_table_row_carries_what_the_page_sorts_by(book):
    data = {"forecasts": [card()]}
    record.attach(data, DOC, book, NODE_SYMS, CAL, TODAY)
    (row,) = data["record_table"]
    assert row["qid"] == "q1" and row["verdict"] == "mixed"
    assert row["committed_at"] == "2026-09-10" and row["sha"] == "a" * 12
    assert row["scored"] is False and row["official_excess"] is None
    assert row["excess_ew"] == pytest.approx(row["basket"] - row["ew"])
    assert row["no_series"] == 0


# -- the lines the question's own page draws ---------------------------------
def test_the_benchmark_series_has_one_point_per_session_in_the_window(book):
    """A crosshair reads a date off this series. A value that did not line up
    with its own day would be a wrong number under a right label."""
    w = record.window_from(dt.date(2026, 9, 14), CAL, TODAY)
    b = record.benchmarks({"win": ["up"], "lose": ["down"]}, book, NODE_SYMS,
                          KINDS, w)
    s = b["series"]
    assert s["dates"] == ["2026-09-14", "2026-09-15", "2026-09-16"]
    for key in ("win", "lose", "ew", "sox"):
        assert len(s[key]) == len(s["dates"]), key
    assert s["win"][0] == pytest.approx(0.0), "the window opens at its baseline"
    # The last point of the line and the number on the tile are one measure.
    assert s["win"][-1] == pytest.approx(b["win"])
    assert s["sox"][-1] == pytest.approx(b["sox"])


def test_a_side_with_no_priced_leg_gets_no_line_at_all(book):
    w = record.window_from(dt.date(2026, 9, 14), CAL, TODAY)
    s = record.benchmarks({"win": ["private"], "lose": []}, book, NODE_SYMS,
                          KINDS, w)["series"]
    assert "win" not in s, "an absent basket drawn flat at zero would be a lie"
    assert len(s["ew"]) == 3, "the benchmark still has its line"


def test_each_candle_carries_the_bars_the_browser_draws(book):
    """The page draws these in the browser; the SVG stays beside them for a
    reader running no script. Both are the same bars."""
    w = record.window_from(dt.date(2026, 9, 14), CAL, TODAY)
    rows = record.leg_rows({"win": ["up"], "lose": []}, DOC, book, KINDS, w,
                           None, CAL)
    (c,) = record.candles_for(rows, w)
    assert [b["time"] for b in c["bars"]] == \
        ["2026-09-14", "2026-09-15", "2026-09-16"]
    first = c["bars"][0]
    assert set(first) == {"time", "open", "high", "low", "close"}
    assert first["close"] == pytest.approx(133.1)
    assert first["high"] == pytest.approx(133.1 * 1.01)
    assert c["svg"].startswith("<svg")


def test_a_card_that_was_never_signed_gets_no_record(book):
    data = {"forecasts": [card(commitment={})]}
    record.attach(data, DOC, book, NODE_SYMS, CAL, TODAY)
    assert "record" not in data["forecasts"][0] and data["record_table"] == []
