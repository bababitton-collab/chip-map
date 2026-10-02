"""The arithmetic under the H1 test, on numbers small enough to check by hand."""
from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "h1", Path(__file__).resolve().parents[1] / "scripts" / "h1_backtest.py")
H = importlib.util.module_from_spec(spec)
spec.loader.exec_module(H)


def line(closes, start=dt.date(2026, 1, 5), suffix="US"):
    ln = H.Line.__new__(H.Line)
    ln.dates = [start + dt.timedelta(days=i) for i in range(len(closes))]
    ln.closes = list(closes)
    ln.ts = [H.close_utc(suffix, d) for d in ln.dates]
    return ln


def test_session0_is_the_first_close_after_the_report():
    ln = line([100, 101, 102, 103])
    after_close = H.close_utc("US", ln.dates[1]) + 60          # filed after day 1's close
    assert ln.session0(after_close) == 2
    before_close = H.close_utc("US", ln.dates[1]) - 60         # filed during day 1
    assert ln.session0(before_close) == 1


def test_a_window_is_measured_from_the_close_before_its_first_session():
    ln = line([100, 110, 121, 133.1, 146.41])
    ts = H.close_utc("US", ln.dates[0]) + 60                   # session 0 = index 1
    assert abs(ln.ret(ts, 0, 1) - (121 / 100 - 1)) < 1e-12     # sessions 0-1
    assert abs(ln.ret(ts, 2, 3) - (146.41 / 121 - 1)) < 1e-12  # sessions 2-3
    assert ln.ret(ts, 2, 9) is None                            # past the data: missing, not zero


def test_edgar_acceptance_is_read_as_utc():
    ts, flagged = H.accepted_utc({"accepted": "2024-02-21T21:22:09.000Z", "filed": "2024-02-21"})
    assert dt.datetime.fromtimestamp(ts, dt.timezone.utc).hour == 21 and not flagged
    ts, flagged = H.accepted_utc({"accepted": None, "filed": "2024-02-21"})
    assert flagged                                             # assumed after the US close


def test_the_benchmark_excludes_the_reporter_and_the_basket_and_skips_missing():
    rets = {"r": 0.5, "b1": 0.2, "x": 0.1, "y": None, "z": 0.3}
    assert abs(H.excl_mean(rets, {"r", "b1"}) - 0.2) < 1e-12


def test_week_clustering_takes_the_mean_per_week_first():
    rows = [{"week": (2024, 1), "d": 0.01}, {"week": (2024, 1), "d": 0.03},
            {"week": (2024, 2), "d": 0.02}, {"week": (2024, 3), "d": 0.04}]
    c = H.clustered(rows, "d")
    assert c["weeks"] == 3 and abs(c["mean"] - (0.02 + 0.02 + 0.04) / 3) < 1e-12


def test_tokyo_closes_at_1530_from_2024_11_05():
    early = dt.datetime.fromtimestamp(H.close_utc("T", dt.date(2024, 11, 1)), H.ZoneInfo("Asia/Tokyo"))
    late = dt.datetime.fromtimestamp(H.close_utc("T", dt.date(2024, 11, 6)), H.ZoneInfo("Asia/Tokyo"))
    assert (early.hour, early.minute, late.hour, late.minute) == (15, 0, 15, 30)
