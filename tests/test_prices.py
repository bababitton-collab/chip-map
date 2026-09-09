"""What the price store must never do to a series.

The failure this guards against is silent: a filled or interpolated value looks
exactly like a real one downstream, and every chart drawn from it is a little
bit invented.
"""
from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from chains import prices


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(prices, "prices_dir", lambda: tmp_path)


def bars(pairs, key="adjusted_close"):
    return [{"date": d, key: v} for d, v in pairs]


# -- no value is ever invented --------------------------------------------

def test_a_series_has_exactly_the_dates_the_vendor_supplied():
    """Three prints with a two-week hole stay three prints. Nothing fills the
    hole, and nothing carries the last value across it."""
    prices.store("X.US", bars([("2024-01-02", 10.0),
                               ("2024-01-03", 11.0),
                               ("2024-01-19", 12.0)]))
    got = prices.load("X.US")
    assert got["date"].to_list() == [dt.date(2024, 1, 2), dt.date(2024, 1, 3),
                                     dt.date(2024, 1, 19)]
    assert got.height == 3


def test_a_gap_is_not_forward_filled():
    prices.store("X.US", bars([("2024-01-02", 10.0), ("2024-03-01", 20.0)]))
    got = prices.load("X.US")
    assert got.height == 2, "a two-month hole must stay a hole"
    assert dt.date(2024, 2, 1) not in got["date"].to_list()


def test_a_row_with_no_price_is_dropped_not_zeroed():
    """Missing is never favourable, and it is certainly never zero: a zero
    price would rebase every later value to a division by nothing."""
    prices.store("X.US", bars([("2024-01-02", 10.0), ("2024-01-03", None),
                               ("2024-01-04", 12.0)]))
    got = prices.load("X.US")
    assert got.height == 2
    assert 0.0 not in got["adj_close"].to_list()


def test_a_repeated_date_keeps_one_row():
    prices.store("X.US", bars([("2024-01-02", 10.0), ("2024-01-02", 10.5)]))
    assert prices.load("X.US").height == 1


# -- currency ---------------------------------------------------------------

def test_every_row_carries_a_currency():
    prices.store("6857.KO", bars([("2024-01-02", 10.0), ("2024-01-03", 11.0)]))
    got = prices.load("6857.KO")
    assert got["currency"].to_list() == ["KRW", "KRW"]
    assert got["currency"].null_count() == 0


@pytest.mark.parametrize("symbol, want", [
    ("AMAT.US", "USD"), ("2330.TW", "TWD"), ("005930.KO", "KRW"),
    ("300316.SHE", "CNY"), ("TPE.XETRA", "EUR"), ("ASML.AS", "EUR"),
    ("MTLN.LSE", "GBP"),
])
def test_the_currency_comes_from_the_exchange(symbol, want):
    assert prices.currency_for(symbol) == want


def test_an_unknown_venue_is_UNKNOWN_and_not_quietly_usd():
    """A wrong currency label is a quiet error; a missing one is a loud one."""
    assert prices.currency_for("FOO.ZZZ") == "UNKNOWN"
    assert prices.currency_for("FOO") == "UNKNOWN"


# -- adjusted, and continuous across a split -------------------------------

def test_the_adjusted_close_is_what_is_stored():
    """Not the raw close. The vendor sends both and the difference is exactly
    the corporate actions."""
    rows = [{"date": "2024-01-02", "close": 400.0, "adjusted_close": 100.0}]
    prices.store("X.US", rows)
    assert prices.load("X.US")["adj_close"][0] == 100.0


def test_a_split_in_the_window_produces_no_step():
    """A 4:1 split leaves the raw close a quarter of what it was overnight. The
    adjusted series is continuous through it, which is the whole reason the
    adjusted column is the one stored."""
    raw = [400.0, 404.0, 101.0, 102.0]          # split between bar 2 and 3
    adj = [100.0, 101.0, 101.0, 102.0]          # continuous
    rows = [{"date": d, "close": c, "adjusted_close": a}
            for d, c, a in zip(["2024-01-02", "2024-01-03",
                                "2024-01-04", "2024-01-05"], raw, adj)]
    prices.store("X.US", rows)
    series = prices.load("X.US")["adj_close"].to_list()
    steps = [abs(b / a - 1.0) for a, b in zip(series, series[1:])]
    assert max(steps) < 0.05, f"a split leaked into the adjusted series: {steps}"


def test_the_close_is_used_only_when_there_is_no_adjusted_close():
    prices.store("X.US", [{"date": "2024-01-02", "close": 7.0}])
    assert prices.load("X.US")["adj_close"][0] == 7.0


# -- shape ------------------------------------------------------------------

def test_an_empty_response_stores_nothing_and_reads_back_empty():
    assert prices.store("X.US", []) == 0
    assert prices.load("X.US").is_empty()


def test_the_stored_series_is_sorted_by_date():
    prices.store("X.US", bars([("2024-03-01", 3.0), ("2024-01-02", 1.0),
                               ("2024-02-01", 2.0)]))
    d = prices.load("X.US")["date"].to_list()
    assert d == sorted(d)


def test_an_int_price_does_not_break_the_build():
    """The vendor mixes int and float in one response."""
    prices.store("X.US", [{"date": "2024-01-02", "adjusted_close": 37},
                          {"date": "2024-01-03", "adjusted_close": 37.08}])
    assert prices.load("X.US")["adj_close"].dtype == pl.Float64


# -- the two paths to the same parquet --------------------------------------
# Added when the build became stateless: with no cache every series is
# downloaded whole, with a cache only the tail is fetched and merged. Two code
# paths writing the same file is exactly where a schema quietly diverges.

def _bars(start_day: int, n: int, base: float = 100.0) -> list[dict]:
    """A deterministic series. The price is a function of the DAY, not of the
    offset, so a full download and a tail fetch of the same window agree --
    which is the whole point of the two tests below."""
    return [{"date": f"2026-01-{start_day + i:02d}",
             "adjusted_close": base + (start_day - 1 + i)} for i in range(n)]


def test_both_paths_write_the_same_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIP_MAP_PRICES", str(tmp_path))
    prices.store("FULL.US", _bars(1, 10))
    prices.store("INCR.US", _bars(1, 5))
    prices.append("INCR.US", _bars(6, 5))
    full, incr = prices.load("FULL.US"), prices.load("INCR.US")
    assert full.schema == incr.schema
    assert list(full.columns) == list(prices.SCHEMA) == list(incr.columns)


def test_both_paths_produce_the_same_rows(tmp_path, monkeypatch):
    """Not just the same columns. The same series."""
    monkeypatch.setenv("CHIP_MAP_PRICES", str(tmp_path))
    prices.store("FULL.US", _bars(1, 10))
    prices.store("INCR.US", _bars(1, 5))
    prices.append("INCR.US", _bars(6, 5))
    a = prices.load("FULL.US").drop("symbol")
    b = prices.load("INCR.US").drop("symbol")
    assert a.to_dicts() == b.to_dicts()


def test_an_append_overlapping_the_cache_does_not_duplicate_a_date(
        tmp_path, monkeypatch):
    monkeypatch.setenv("CHIP_MAP_PRICES", str(tmp_path))
    prices.store("A.US", _bars(1, 10))
    prices.append("A.US", _bars(6, 10))          # five days of overlap
    df = prices.load("A.US")
    assert df.height == df["date"].n_unique()


def test_the_appended_value_wins_on_an_overlapping_date(tmp_path, monkeypatch):
    """The vendor's latest word about a date is the one to keep."""
    monkeypatch.setenv("CHIP_MAP_PRICES", str(tmp_path))
    prices.store("A.US", [{"date": "2026-01-05", "adjusted_close": 100.0}])
    prices.append("A.US", [{"date": "2026-01-05", "adjusted_close": 100.0005}])
    assert prices.load("A.US")["adj_close"][0] == 100.0005


def test_a_restatement_is_detected_rather_than_appended_across(
        tmp_path, monkeypatch):
    """adjusted_close is retroactive: a split rewrites every bar before it.
    Appending across that would join two scales at an invisible seam and draw
    a step no corporate action explains."""
    monkeypatch.setenv("CHIP_MAP_PRICES", str(tmp_path))
    prices.store("A.US", _bars(1, 10))
    kept, restated = prices.append("A.US", [
        {"date": "2026-01-08", "adjusted_close": 53.5},   # a 2:1 split
        {"date": "2026-01-11", "adjusted_close": 55.0}])
    assert restated is True
    assert kept == 10, "the stored series is left alone for the caller to redo"


def test_a_rounding_wobble_is_not_a_restatement(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIP_MAP_PRICES", str(tmp_path))
    prices.store("A.US", _bars(1, 10))
    _, restated = prices.append("A.US", [
        {"date": "2026-01-08", "adjusted_close": 107.00001}])
    assert restated is False


def test_appending_to_an_empty_cache_is_just_a_write(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIP_MAP_PRICES", str(tmp_path))
    kept, restated = prices.append("NEW.US", _bars(1, 4))
    assert kept == 4 and restated is False


def test_last_date_is_none_with_no_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIP_MAP_PRICES", str(tmp_path))
    assert prices.last_date("NOPE.US") is None


def test_last_date_is_the_newest_bar(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIP_MAP_PRICES", str(tmp_path))
    prices.store("A.US", _bars(1, 5))
    assert prices.last_date("A.US").isoformat() == "2026-01-05"


# -- the rejection rule ------------------------------------------------------

def test_a_bar_with_no_usable_close_is_rejected_not_stored_as_null(
        tmp_path, monkeypatch):
    """A null in the series is a hole the chart has to guess about. A bar the
    vendor could not price is not a bar."""
    monkeypatch.setenv("CHIP_MAP_PRICES", str(tmp_path))
    prices.store("A.US", [{"date": "2026-01-01", "adjusted_close": 10.0},
                          {"date": "2026-01-02", "adjusted_close": None},
                          {"date": "2026-01-03", "adjusted_close": "n/a"}])
    df = prices.load("A.US")
    assert df.height == 1 and df["adj_close"].null_count() == 0


def test_a_repeated_date_collapses_to_the_last_one_sent(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIP_MAP_PRICES", str(tmp_path))
    prices.store("A.US", [{"date": "2026-01-01", "adjusted_close": 10.0},
                          {"date": "2026-01-01", "adjusted_close": 11.0}])
    df = prices.load("A.US")
    assert df.height == 1 and df["adj_close"][0] == 11.0


def test_the_currency_is_carried_never_converted(tmp_path, monkeypatch):
    """Converting would import FX into a chart about chokepoints: a Tokyo
    Electron line in dollars moves when the yen moves."""
    monkeypatch.setenv("CHIP_MAP_PRICES", str(tmp_path))
    prices.store("8035.TSE", _bars(1, 3))
    assert prices.load("8035.TSE")["currency"].unique().to_list() != ["USD"]
