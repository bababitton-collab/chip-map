"""The daily bar: what is stored, what is drawable, and what is refused.

The close layer kept one number a day. A candle needs four, and they come from
the same vendor response, so they are kept in the same parquet beside it. What
is tested here is that keeping them cannot corrupt what was already there: an
old cache without the columns still loads and still appends, a bar missing one
of the four is never drawn, and a window with nothing drawable comes back empty
rather than as a shape.
"""
from __future__ import annotations

import datetime as dt
import json

import polars as pl
import pytest

from chains import candles, prices

D = dt.date


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIP_MAP_PRICES", str(tmp_path))
    return tmp_path


def bar(day: str, o=10.0, h=11.0, lo=9.0, c=10.5, adj=None, vol=1000):
    return {"date": day, "open": o, "high": h, "low": lo, "close": c,
            "adjusted_close": c if adj is None else adj, "volume": vol}


# -- what is stored ---------------------------------------------------------
def test_the_four_raw_prices_are_kept_beside_the_adjusted_close():
    prices.store("AAA.US", [bar("2026-09-14", 10, 12, 9.5, 11, adj=5.5)])
    row = prices.load("AAA.US").row(0, named=True)
    assert (row["open"], row["high"], row["low"], row["close"]) == (10, 12, 9.5, 11)
    assert row["adj_close"] == 5.5, "the adjusted close is still its own column"
    assert row["volume"] == 1000


def test_a_bar_with_no_raw_prices_is_still_stored_for_its_close():
    """The close layer's own history has no OHLC. Dropping those bars would
    throw away the series every score reads."""
    prices.store("AAA.US", [{"date": "2026-09-14", "adjusted_close": 5.5}])
    df = prices.load("AAA.US")
    assert df.height == 1 and df["adj_close"][0] == 5.5
    assert df["open"][0] is None
    assert prices.bars("AAA.US") == [], "nothing drawable, and it says so"


def test_a_bar_missing_one_of_the_four_is_not_drawable():
    prices.store("AAA.US", [bar("2026-09-14"), bar("2026-09-15", h=None)])
    got = prices.bars("AAA.US")
    assert [b["date"] for b in got] == [D(2026, 9, 14)]


def test_bars_are_windowed_and_sorted_oldest_first():
    prices.store("AAA.US", [bar("2026-09-16"), bar("2026-09-14"),
                            bar("2026-09-15")])
    got = prices.bars("AAA.US", D(2026, 9, 15), D(2026, 9, 16))
    assert [b["date"] for b in got] == [D(2026, 9, 15), D(2026, 9, 16)]
    assert prices.has_ohlc("AAA.US", D(2026, 9, 15))
    assert not prices.has_ohlc("AAA.US", D(2026, 9, 17))


# -- an older cache ---------------------------------------------------------
def _legacy(tmp_path, symbol="AAA.US"):
    """A parquet as the close-only build wrote it: no OHLC columns at all."""
    old = {"date": pl.Date, "symbol": pl.Utf8, "adj_close": pl.Float64,
           "currency": pl.Utf8}
    pl.DataFrame({"date": [D(2026, 9, 10), D(2026, 9, 11)],
                  "symbol": [symbol] * 2, "adj_close": [100.0, 101.0],
                  "currency": ["USD"] * 2}, schema=old
                 ).write_parquet(prices.path_for(symbol))


def test_a_cache_written_before_the_columns_existed_still_loads(tmp_path):
    _legacy(tmp_path)
    df = prices.load("AAA.US")
    assert list(df.columns) == list(prices.SCHEMA)
    assert df.height == 2 and df["adj_close"].to_list() == [100.0, 101.0]
    assert df["close"].to_list() == [None, None]
    assert prices.bars("AAA.US") == []


def test_a_tail_fetch_fills_candles_into_an_older_cache(tmp_path):
    _legacy(tmp_path)
    kept, restated = prices.append(
        "AAA.US", [bar("2026-09-11", adj=101.0), bar("2026-09-12", adj=102.0)])
    assert not restated and kept == 3
    got = prices.bars("AAA.US")
    assert [b["date"] for b in got] == [D(2026, 9, 11), D(2026, 9, 12)]
    assert prices.load("AAA.US")["adj_close"].to_list() == [100.0, 101.0, 102.0]


def test_the_close_layer_still_round_trips_through_the_wider_schema():
    rows = [{"date": "2026-09-14", "adjusted_close": 7.0},
            {"date": "2026-09-15", "adjusted_close": 8.0}]
    prices.store("AAA.US", rows)
    assert prices.load("AAA.US")["adj_close"].to_list() == [7.0, 8.0]


# -- the plan the fetcher makes ---------------------------------------------
def _script():
    import importlib.util
    from chains.paths import REPO_ROOT
    spec = importlib.util.spec_from_file_location(
        "build_daily", REPO_ROOT / "chains" / "scripts" / "build_daily.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DOC = {"nodes": [{"id": "up", "price_symbol": "UP.US"},
                 {"id": "down", "price_symbol": "DOWN.US"},
                 {"id": "mute", "price_symbol": None}],
       "subnodes": []}
WATCH = [{"id": "q1", "win": ["up"], "lose": ["down"]},
         {"id": "q2", "win": ["up"], "lose": []},
         {"id": "q3", "win": ["down"], "lose": []}]
COMMITS = [{"qid": "q1", "committed_at": "2026-09-13"},
           {"qid": "q2", "committed_at": "2026-09-01"}]


def test_a_leg_is_fetched_from_the_earliest_signature_that_names_it():
    want = _script().legs_by_symbol(DOC, WATCH, COMMITS)
    assert want["UP.US"]["since"] == D(2026, 9, 1), "q2 signed first"
    assert want["DOWN.US"]["since"] == D(2026, 9, 13)
    assert sorted(q for q, _ in want["UP.US"]["legs"]) == ["q1", "q2"]


def test_a_question_with_no_signature_is_not_a_window():
    """q3 names DOWN.US but has no commitment entry, so it adds nothing."""
    want = _script().legs_by_symbol(DOC, WATCH, COMMITS)
    assert [q for q, _ in want["DOWN.US"]["legs"]] == ["q1"]


def test_a_symbol_the_map_does_not_price_is_skipped():
    want = _script().legs_by_symbol(
        DOC, [{"id": "q1", "win": ["mute"], "lose": []}], COMMITS)
    assert want == {}


def test_the_plan_asks_for_nothing_when_the_window_is_already_candled():
    prices.store("UP.US", [bar("2026-09-14"), bar("2026-09-15")])
    (row,) = _script().plan({"UP.US": {"since": D(2026, 9, 14), "legs": []}})
    assert row["todo"] == "cached" and row["from"] is None


def test_the_plan_asks_for_a_tail_when_the_candles_stop_short(tmp_path):
    prices.store("UP.US", [bar("2026-09-14")])
    prices.append("UP.US", [{"date": "2026-09-15", "adjusted_close": 9.0}])
    (row,) = _script().plan({"UP.US": {"since": D(2026, 9, 14), "legs": []}})
    assert row["todo"] == "tail" and row["from"] < D(2026, 9, 14)


def test_the_plan_asks_for_the_whole_window_when_there_are_no_candles(tmp_path):
    _legacy(tmp_path, "UP.US")
    (row,) = _script().plan({"UP.US": {"since": D(2026, 9, 1), "legs": []}})
    assert row["todo"] == "window" and row["from"] == D(2026, 9, 1)


# -- the drawing ------------------------------------------------------------
def test_nothing_drawable_draws_nothing():
    assert candles.svg([]) == ""
    assert candles.svg([{"date": "2026-09-14", "open": 1, "high": None,
                         "low": 1, "close": 1}]) == ""


def test_one_candle_per_session_and_no_gap_filling():
    got = candles.svg([bar("2026-09-14"), bar("2026-09-16")])
    assert got.count("<rect") == 3, "background plus two candles"
    assert "2026-09-14" in got and "2026-09-16" in got
    assert "2026-09-15" not in got, "a session that never printed is not drawn"


def test_a_falling_session_is_drawn_in_the_falling_colour():
    up = candles.svg([bar("2026-09-14", o=10, c=11)])
    down = candles.svg([bar("2026-09-14", o=11, c=10)])
    assert candles.UP in up and candles.DOWN not in up
    assert candles.DOWN in down and candles.UP not in down


def test_the_chart_says_what_it_is_for_a_reader_who_cannot_see_it():
    got = candles.svg([bar("2026-09-14"), bar("2026-09-15")], title="NVDA.US")
    assert 'role="img"' in got
    assert "NVDA.US" in got and "2 sessions from 2026-09-14 to 2026-09-15" in got
