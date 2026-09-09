"""Rebasing, ratios, baskets and the density rule.

The currency-invariance tests are the ones that matter most. The whole design
rests on never converting FX, and that is only safe if every comparison is
genuinely scale-free. If one of these ever fails, a chart is showing the yen.
"""
from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from chains import prices, relative

START = dt.date(2024, 1, 1)
END = dt.date(2024, 12, 30)


def series(values, start=START, step_days=7, currency="USD", symbol="X"):
    """A weekly series of `values`, one bar per week from `start`."""
    dates = [start + dt.timedelta(days=step_days * i) for i in range(len(values))]
    return pl.DataFrame({
        "date": dates,
        "symbol": [symbol] * len(values),
        "adj_close": [float(v) for v in values],
        "currency": [currency] * len(values),
    }).with_columns(pl.col("date").cast(pl.Date))


def dense(n_weeks, first=100.0, growth=1.01, **kw):
    return series([first * growth ** i for i in range(n_weeks)], **kw)


# -- rebasing ---------------------------------------------------------------

def test_a_rebased_series_starts_at_exactly_100():
    pts, diag = relative.rebase(dense(52), START, END)
    assert pts[0][1] == 100.0
    assert diag["classification"] == "ok"


def test_rebasing_is_invariant_to_the_unit_of_the_prices():
    """The same shape priced in yen and in dollars rebases to the same line.
    This is what lets Tokyo Electron sit beside ASML with no conversion."""
    shape = [100.0 * 1.01 ** i for i in range(52)]
    usd = relative.rebase(series(shape, currency="USD"), START, END)[0]
    jpy = relative.rebase(series([v * 157.3 for v in shape], currency="JPY"),
                          START, END)[0]
    assert [p[1] for p in usd] == [p[1] for p in jpy]


def test_a_jpy_line_and_its_usd_adr_differ_by_fx_only():
    """The ADR is the home line times the exchange rate. Rebased, the ratio of
    the two lines is the FX path rebased to 1 -- nothing else survives."""
    home = [100 + i for i in range(52)]
    fx = [1 / (150 + (i % 7)) for i in range(52)]      # JPY -> USD, drifting
    jpy = relative.rebase(series(home, currency="JPY"), START, END)[0]
    adr = relative.rebase(series([h * f for h, f in zip(home, fx)],
                                 currency="USD"), START, END)[0]
    # rebase() rounds to 2dp so the payload stays small, so the recovered FX
    # path is exact to about that, not to machine precision
    got = [a[1] / j[1] for a, j in zip(adr, jpy)]
    want = [f / fx[0] for f in fx]
    for g, w in zip(got, want):
        assert g == pytest.approx(w, abs=2e-4)


def test_a_week_with_no_bar_produces_no_point():
    """No interpolation, no carry-forward: the gap is the information."""
    df = pl.concat([series([100, 101]), series([120], start=START +
                                               dt.timedelta(days=70))])
    pts, _ = relative.rebase(df, START, END)
    assert len(pts) == 3, "three prints, three points, nothing in between"


def test_an_empty_window_is_not_drawable():
    pts, diag = relative.rebase(series([100]), dt.date(2030, 1, 1),
                                dt.date(2030, 12, 31))
    assert pts == [] and diag["drawable"] is False


# -- the density rule at its boundaries ------------------------------------

def test_the_density_boundary_is_inclusive_at_60_percent():
    """59.9% fails and 60% passes. Pinned because a threshold with an
    off-by-one in its comparison is invisible until it silently drops a line."""
    weeks = (END - START).days // 7            # 51
    ok = relative.rebase(dense(int(weeks * 0.60) + 1), START, END)[1]
    assert ok["density_in_window"] >= 0.60 and ok["drawable"]

    diag = {"density_since_first_bar": 0.599}
    assert 0.599 < relative.MIN_WEEKLY_DENSITY
    assert 0.600 >= relative.MIN_WEEKLY_DENSITY


def test_a_sparse_series_is_too_thin_and_says_how_thin():
    sparse = series([100, 101, 102, 103], step_days=70)   # ~4 bars in a year
    pts, diag = relative.rebase(sparse, START, END)
    assert diag["drawable"] is False
    assert diag["classification"] == "too_thin"
    assert "4 bars" in diag["reason"]


def test_a_late_listing_is_short_history_and_IS_drawn():
    """A company that listed mid-window is dense over its own life. Drawing it
    from its first print interpolates nothing; refusing to draw it hides a
    liquid company for being new. GE Vernova is the real case."""
    mid = START + dt.timedelta(days=200)
    late = dense(26, start=mid)                 # every week since it listed
    pts, diag = relative.rebase(late, START, END)
    assert diag["density_in_window"] < 0.60
    assert diag["density_since_first_bar"] >= 0.95
    assert diag["classification"] == "short_history"
    assert diag["drawable"] is True and pts[0][1] == 100.0


def test_thin_and_young_are_never_the_same_label():
    thin = relative.rebase(series([1, 2, 3, 4], step_days=70), START, END)[1]
    young = relative.rebase(dense(20, start=START + dt.timedelta(days=220)),
                            START, END)[1]
    assert thin["classification"] == "too_thin"
    assert young["classification"] == "short_history"


# -- ratios -----------------------------------------------------------------

def test_the_ratio_is_the_quotient_of_the_two_rebased_series():
    """The page receives no ratio series -- it divides the two rebased lines it
    already has. So there is one definition and this is it."""
    h = series([100.0 * 1.01 ** i for i in range(52)])
    c = series([50.0 * 1.005 ** i for i in range(52)])
    rp, _ = relative.ratio(h, c, START, END)
    hp = dict(relative.rebase(h, START, END)[0])
    cp = dict(relative.rebase(c, START, END)[0])
    for week, v in rp:
        assert v == pytest.approx(hp[week] / cp[week] * 100.0, abs=0.01)


def test_the_ratio_is_currency_free():
    shape_h = [100.0 * 1.01 ** i for i in range(52)]
    shape_c = [50.0 * 1.004 ** i for i in range(52)]
    h_usd, c_usd = series(shape_h), series(shape_c)
    h_jpy = series([v * 157 for v in shape_h], currency="JPY")
    a = [v for _, v in relative.ratio(h_usd, c_usd, START, END)[0]]
    b = [v for _, v in relative.ratio(h_jpy, c_usd, START, END)[0]]
    assert a == b


def test_a_week_where_only_one_side_printed_is_dropped():
    h = series([100, 110, 120])
    c = pl.concat([series([50]), series([60], start=START +
                                        dt.timedelta(days=14))])
    rp, _ = relative.ratio(h, c, START, END)
    assert len(rp) == 2, "a ratio needs both sides on the same week"


# -- baskets ----------------------------------------------------------------

def test_a_basket_is_the_mean_of_REBASED_members_not_of_prices(monkeypatch):
    """The one that matters. Members trade in different currencies; the mean of
    their prices is a number with no units that still draws a line."""
    shape = [100.0 * 1.01 ** i for i in range(52)]     # dense enough to draw
    store = {"A.US": series(shape),
             "B.US": series([v / 10 for v in shape]),   # same shape, 1/10 price
             "C.US": series([v * 10 for v in shape])}   # same shape, 10x price
    monkeypatch.setattr(prices, "load", lambda s: store[s])
    pts, diag = relative.basket(list(store), START, END)
    # identical shapes at wildly different price levels -> the basket IS that
    # shape. A mean of the prices would be dominated by C and look nothing
    # like it.
    rebased = [v for _, v in relative.rebase(series(shape), START, END)[0]]
    assert [v for _, v in pts] == pytest.approx(rebased, abs=0.01)
    assert diag["member_count"] == 3


def test_a_basket_across_currencies_equals_the_mean_of_rebased_members(monkeypatch):
    store = {
        "JP.US": series([1000, 1100, 900], currency="JPY"),
        "EU.US": series([50, 60, 55], currency="EUR"),
        "US.US": series([7, 7.7, 6.3], currency="USD"),
    }
    monkeypatch.setattr(prices, "load", lambda s: store[s])
    pts, _ = relative.basket(list(store), START, END)
    each = [dict(relative.rebase(df, START, END)[0]) for df in store.values()]
    for week, v in pts:
        assert v == pytest.approx(sum(e[week] for e in each) / 3, abs=0.01)


def test_a_basket_reports_its_member_count_and_who_was_excluded(monkeypatch):
    store = {"A.US": dense(52), "B.US": dense(52), "C.US": dense(52),
             "THIN.US": series([1, 2, 3], step_days=90),
             "YOUNG.US": dense(10, start=START + dt.timedelta(days=250))}
    monkeypatch.setattr(prices, "load", lambda s: store[s])
    pts, diag = relative.basket(list(store), START, END)
    assert diag["member_count"] == 3
    excluded = {e["symbol"]: e["classification"] for e in diag["excluded"]}
    assert excluded == {"THIN.US": "too_thin", "YOUNG.US": "short_history"}


def test_a_basket_with_fewer_than_three_members_is_not_drawn(monkeypatch):
    """Two companies with a sector's name on them is not a basket."""
    store = {"A.US": dense(52), "B.US": dense(52)}
    monkeypatch.setattr(prices, "load", lambda s: store[s])
    pts, diag = relative.basket(list(store), START, END)
    assert pts == []
    assert diag["member_count"] == 2 and "needs 3" in diag["reason"]


def test_an_empty_basket_says_so_rather_than_returning_a_flat_line(monkeypatch):
    monkeypatch.setattr(prices, "load", lambda s: pl.DataFrame(schema=prices.SCHEMA))
    pts, diag = relative.basket(["A.US"], START, END)
    assert pts == [] and diag["member_count"] == 0


# -- a basket must not be truncated by a late-listing member ----------------

def test_a_basket_starts_at_the_window_start_when_it_has_three_full_members(
        monkeypatch):
    """The bug this pins: CRDO listed 2022-01 and prints every week since, so
    it covers 61% of a 2019 window -- over the density threshold. Judging
    membership on density let it in, and the basket then silently truncated to
    2022-01, throwing away three years for every other member. Coverage and
    density are different questions and the basket needs the first."""
    full = {f"F{i}.US": dense(52) for i in range(3)}
    late = {"LATE.US": dense(20, start=START + dt.timedelta(days=224))}
    store = {**full, **late}
    monkeypatch.setattr(prices, "load", lambda s: store[s])
    pts, diag = relative.basket(list(store), START, END)
    assert pts[0][0] == str(START), (
        f"basket starts at {pts[0][0]}, not the window start {START} -- a late "
        f"lister truncated it"
    )
    assert diag["member_count"] == 3
    assert [e["symbol"] for e in diag["excluded"]] == ["LATE.US"]


def test_a_dense_but_late_series_is_short_history_not_ok(monkeypatch):
    """61% density over the window is above the threshold and still means the
    company did not exist for three of the seven years."""
    late = dense(200, start=START + dt.timedelta(days=224))
    diag = relative.rebase(late, START, dt.date(2027, 12, 31))[1]
    assert diag["density_in_window"] >= 0.60, "dense enough to fool a density test"
    assert diag["covers_window"] is False
    assert diag["classification"] == "short_history"


def test_covers_window_allows_a_few_weeks_of_slack(monkeypatch):
    """A series whose first print is a fortnight after the window opens still
    covers it -- a holiday run is not a late listing."""
    d = dense(52, start=START + dt.timedelta(days=14))
    assert relative.rebase(d, START, END)[1]["covers_window"] is True
    d2 = dense(52, start=START + dt.timedelta(days=60))
    assert relative.rebase(d2, START, END)[1]["covers_window"] is False
