"""The forward test: the shape between the checkpoints.

The ledger says whether a claim was met at 5, 10, 20 and 40 sessions. This says
what happened on the days in between, and it must not be able to disagree with
the ledger about the days that are also checkpoints -- so the horizons are the
ledger's own objects, converted to this page's units and otherwise untouched.

The prices below are round on purpose: every expected number is worked out on
paper from the levels, not read back out of the code that produced it.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from chains import forecast, prices, track

# Twelve consecutive weekday sessions.
CAL = []
_d = dt.date(2026, 3, 2)
while len(CAL) < 12:
    if _d.weekday() < 5:
        CAL.append(_d)
    _d += dt.timedelta(days=1)

DOC = {
    "nodes": [
        {"id": "up", "name": "Up Co", "short": "UP", "ticker": "UP",
         "price_symbol": "UP.US", "price_symbol_kind": "primary"},
        {"id": "down", "name": "Down Co", "short": "DOWN", "ticker": "DN",
         "price_symbol": "DOWN.US", "price_symbol_kind": "primary"},
        {"id": "flat", "name": "Flat Co", "short": "FLAT", "ticker": "FL",
         "price_symbol": "FLAT.US", "price_symbol_kind": "primary"},
        {"id": "s1", "name": "Ring Two", "short": "S1", "ticker": "S1",
         "price_symbol": "S1.US", "price_symbol_kind": "primary"},
        {"id": "s2", "name": "Ring Two B", "short": "S2", "ticker": "S2",
         "price_symbol": "S2.US", "price_symbol_kind": "primary"},
        {"id": "stale", "name": "Stale Co", "short": "STALE", "ticker": "ST",
         "price_symbol": "STALE.US", "price_symbol_kind": "primary"},
    ],
    "subnodes": [],
}
WATCH = [{"id": "mu_fq4", "who": "Micron FQ4", "tk": "MU", "d": "2026-03-10"},
         {"id": "nvda_q3", "who": "NVIDIA Q3", "tk": "NVDA", "d": "2026-03-12"}]


@pytest.fixture
def book(monkeypatch, tmp_path):
    """UP +1 a session on 100, DOWN -1, FLAT still, S1 +0.5, S2 -0.5.

    STALE stops printing after the fourth session, on purpose.
    """
    monkeypatch.setenv("CHIP_MAP_PRICES", str(tmp_path))
    for sym, step, n in (("UP.US", 1.0, 12), ("DOWN.US", -1.0, 12),
                         ("FLAT.US", 0.0, 12), ("S1.US", 0.5, 12),
                         ("S2.US", -0.5, 12), ("STALE.US", 2.0, 4)):
        prices.store(sym, [{"date": c.isoformat(),
                            "adjusted_close": 100.0 + step * i}
                           for i, c in enumerate(CAL[:n])])
    return forecast.Book(["UP.US", "DOWN.US", "FLAT.US", "S1.US", "S2.US",
                          "STALE.US"])


def fc(fid, qid, win, lose, order=1, direction=1, marked="2026-03-02"):
    from chains.answers import ORDERS
    r = {"id": fid, "qid": qid, "marked_at": marked, "status":
         "yes" if direction > 0 else "no", "direction": direction,
         "win": win, "lose": lose, "benchmark": "EW_MAP",
         "horizons": list(ORDERS[order])}
    if order != 1:
        r["order"] = order
    return r


def built(book, forecasts, watch=WATCH, marks=None, ledger=None):
    led = ledger if ledger is not None else forecast.build(
        forecasts, DOC, [], CAL)
    return track.build(forecasts, led, watch, DOC, marks or {}, book, CAL)


# -- the sign, in one place --------------------------------------------------

def test_a_yes_forecast_subtracts_in_the_order_it_was_written():
    assert track.spread(1, 5.0, 2.0) == 3.0


def test_a_no_forecast_flips_the_baskets_before_subtracting():
    """A "no" mark says the win basket FALLS. The page must show that claim
    being met as a positive number, or a correct forecast reads as a wrong
    one."""
    assert track.spread(-1, 5.0, 2.0) == -3.0
    assert track.spread(-1, 2.0, 5.0) == 3.0


def test_with_no_lose_side_a_no_forecast_negates():
    assert track.spread(1, 4.0, None) == 4.0
    assert track.spread(-1, 4.0, None) == -4.0


def test_a_missing_side_is_not_a_zero():
    assert track.spread(1, None, 2.0) is None
    assert track.spread(1, None, None) is None


def test_the_sign_is_applied_exactly_once(book):
    """Twice would silently undo itself. UP rises and DOWN falls, so a "no"
    forecast over the same baskets is the negative of the "yes" one -- not the
    same number, and not zero."""
    yes = built(book, [fc("y", "mu_fq4", ["up"], ["down"])])["forecasts"][0]
    no = built(book, [fc("n", "mu_fq4", ["up"], ["down"],
                         direction=-1)])["forecasts"][0]
    assert yes["today"]["win_lose"] == pytest.approx(
        -no["today"]["win_lose"], abs=1e-6)
    assert yes["today"]["win_lose"] > 0 and no["today"]["win_lose"] < 0


# -- indexing ----------------------------------------------------------------

def test_every_series_starts_at_zero_on_the_entry_close(book):
    r = built(book, [fc("f", "mu_fq4", ["up"], ["down"])])["forecasts"][0]
    for k in ("win", "lose", "ew"):
        assert r["series"][k][0] == 0.0


def test_the_series_is_a_percentage_worked_out_from_the_closes(book):
    """Entry is CAL[1] at 101. Five sessions later UP is at 106."""
    r = built(book, [fc("f", "mu_fq4", ["up"], ["down"])])["forecasts"][0]
    assert r["entry_date"] == CAL[1].isoformat()
    assert r["series"]["win"][5] == pytest.approx((106 / 101 - 1) * 100, abs=1e-4)
    assert r["series"]["lose"][5] == pytest.approx((94 / 99 - 1) * 100, abs=1e-4)


def test_one_point_per_session_from_entry_to_the_last_close(book):
    r = built(book, [fc("f", "mu_fq4", ["up"], ["down"])])["forecasts"][0]
    assert len(r["series"]["dates"]) == len(CAL) - 1
    assert r["series"]["dates"][0] == CAL[1].isoformat()
    assert r["series"]["dates"][-1] == CAL[-1].isoformat()
    assert r["day_index"] == len(CAL) - 2


def test_a_basket_is_the_equal_weight_mean_of_its_members(book):
    r = built(book, [fc("f", "mu_fq4", ["up", "flat"], [])])["forecasts"][0]
    got = r["series"]["win"][5]
    want = ((106 / 101 - 1) + 0.0) / 2 * 100
    # stored to four decimal places of a percentage
    assert got == pytest.approx(want, abs=1e-4)


def test_today_and_the_horizons_are_in_the_same_unit(book):
    """Both percentages. A page that mixes fractions and percentages is a page
    where a number is eventually read in the wrong one."""
    r = built(book, [fc("f", "mu_fq4", ["up"], ["down"])])["forecasts"][0]
    assert abs(r["today"]["win_lose"]) > 1, "a percentage, not a fraction"
    assert abs(r["horizons"]["5"]["spread"]) > 1


def test_the_horizons_come_from_the_ledger_unchanged(book):
    f = fc("f", "mu_fq4", ["up"], ["down"])
    led = forecast.build([f], DOC, [], CAL)
    r = built(book, [f], ledger=led)["forecasts"][0]
    assert r["horizons"]["5"]["spread"] == pytest.approx(
        led["rows"][0]["horizons"]["5"]["excess"] * 100, rel=1e-9)
    assert r["horizons"]["5"]["hit"] is led["rows"][0]["horizons"]["5"]["hit"]


# -- members and staleness ---------------------------------------------------

def test_a_member_carries_its_last_close_and_says_so(book):
    """STALE stops printing after the fourth session. The line is carried
    forward -- that is what a basket does -- and the row is marked, because a
    flat line that is really an absent one is a lie by omission."""
    r = built(book, [fc("f", "mu_fq4", ["up", "stale"], [])])["forecasts"][0]
    st = [m for m in r["members"] if m["id"] == "stale"][0]
    assert st["stale"] > track.STALE_AFTER
    assert st["last"] == 106.0, "the last real close, carried"


def test_a_fresh_member_is_not_marked_stale(book):
    r = built(book, [fc("f", "mu_fq4", ["up"], ["down"])])["forecasts"][0]
    assert all(m["stale"] == 0 for m in r["members"])


def test_a_member_carries_its_group(book):
    twin = fc("mu_fq4-2026-03-02-r2", "mu_fq4", ["s1"], ["s2"], order=2)
    r = built(book, [fc("f", "mu_fq4", ["up"], ["down"]), twin])["forecasts"][0]
    assert {m["group"] for m in r["members"]} == {"win", "lose", "win2", "lose2"}


def test_since_entry_is_measured_from_the_entry_close(book):
    r = built(book, [fc("f", "mu_fq4", ["up"], ["down"])])["forecasts"][0]
    up = [m for m in r["members"] if m["id"] == "up"][0]
    assert up["entry"] == 101.0
    assert up["since"] == pytest.approx((111 / 101 - 1) * 100, abs=1e-4)


# -- the two orders ----------------------------------------------------------

def test_the_twin_folds_into_the_same_record(book):
    twin = fc("mu_fq4-2026-03-02-r2", "mu_fq4", ["s1"], ["s2"], order=2)
    out = built(book, [fc("f", "mu_fq4", ["up"], ["down"]), twin])
    assert len(out["forecasts"]) == 1, "one card, not two"
    assert out["forecasts"][0]["has_r2"] is True
    assert out["forecasts"][0]["series"]["win2"][0] == 0.0


def test_a_forecast_without_a_twin_says_so(book):
    r = built(book, [fc("f", "mu_fq4", ["up"], ["down"])])["forecasts"][0]
    assert r["has_r2"] is False
    assert r["series"]["win2"] is None
    assert r["today"]["win2_lose2"] is None


def test_the_orders_are_never_pooled(book):
    """Two direct forecasts and one twin. The direct N is 2 and the ring's is
    1 -- a hit rate over both would describe neither."""
    twin = fc("mu_fq4-2026-03-02-r2", "mu_fq4", ["s1"], ["s2"], order=2)
    out = built(book, [fc("a", "mu_fq4", ["up"], ["down"]),
                       fc("b", "nvda_q3", ["up"], ["down"]), twin])
    assert out["summary"]["direct_hit_5"]["n"] == 2
    assert out["summary"]["ring2_hit_5"]["n"] == 1


def test_the_summary_carries_the_n_behind_every_number(book):
    out = built(book, [fc("f", "mu_fq4", ["up"], ["down"])])
    for k in ("direct_hit_5", "direct_spread_5", "direct_spread_20",
              "ring2_hit_5", "ring2_spread_5"):
        assert set(out["summary"][k]) == {"n", "value"}


def test_a_number_with_no_forecasts_behind_it_is_none_not_zero(book):
    out = built(book, [fc("f", "mu_fq4", ["up"], ["down"])])
    # 20 sessions have not passed in a twelve-session calendar.
    assert out["summary"]["direct_spread_20"] == {"n": 0, "value": None}


# -- not entered yet ---------------------------------------------------------

def test_a_forecast_with_no_session_since_the_mark_is_listed(book):
    """Registered but not entered. Dropping it would hide a claim; scoring it
    would invent one."""
    late = (CAL[-1] + dt.timedelta(days=1)).isoformat()
    r = built(book, [fc("f", "mu_fq4", ["up"], ["down"],
                        marked=late)])["forecasts"][0]
    assert r["entry_date"] is None
    assert r["series"] is None and r["members"] == []
    assert r["today"] == {} and r["horizons"] == {}
    assert r["who"] == "Micron FQ4", "it is still a named, dated claim"


def test_it_counts_as_open_not_as_scored(book):
    late = (CAL[-1] + dt.timedelta(days=1)).isoformat()
    out = built(book, [fc("f", "mu_fq4", ["up"], ["down"], marked=late)])
    assert out["summary"]["n_forecasts"] == 1
    assert out["summary"]["n_open"] == 1 and out["summary"]["n_scored"] == 0


# -- nothing marked ----------------------------------------------------------

def test_a_zero_forecast_build_is_valid_and_empty():
    out = track.build([])
    assert out["forecasts"] == []
    assert out["summary"]["n_forecasts"] == 0
    assert out["summary"]["direct_hit_5"] == {"n": 0, "value": None}


def test_the_page_renders_with_nothing_marked():
    html = track.render(track.build([]))
    assert "__TRACK__" not in html
    assert "The first forecast registers when" in html


def test_a_template_with_no_placeholder_fails_loudly():
    """It would render an empty shell that reads as "no forecasts yet"."""
    with pytest.raises(SystemExit) as e:
        track.render({"summary": {}, "forecasts": []}, template="<html></html>")
    assert "empty shell" in str(e.value)


# -- the checkpoint counter --------------------------------------------------

def test_the_next_checkpoint_is_the_first_one_still_ahead(book):
    r = built(book, [fc("f", "mu_fq4", ["up"], ["down"])])["forecasts"][0]
    assert r["day_index"] == 10
    assert r["next_checkpoint"] == 20 and r["sessions_to"] == 10


def test_the_checkpoints_are_the_ledger_s(book):
    assert track.CHECKPOINTS == (5, 10, 20, 40)


# -- the paywall -------------------------------------------------------------

def test_a_locked_question_contributes_no_text(book):
    """The watch row of a locked question carries no q at all, so the record
    has no field to leak -- absent, not empty: an empty string is still a
    field somebody can learn the shape of."""
    r = built(book, [fc("f", "mu_fq4", ["up"], ["down"])])["forecasts"][0]
    assert "q" not in r


def test_an_open_question_s_text_rides_along(book):
    watch = [dict(WATCH[0], q="How much is Micron shipping?")]
    r = built(book, [fc("f", "mu_fq4", ["up"], ["down"])],
              watch=watch)["forecasts"][0]
    assert r["q"] == "How much is Micron shipping?"


def test_the_publisher_scans_the_track_page_for_locked_text():
    from chains import publish_site
    assert "track/index.html" in publish_site.PAYWALLED
    assert "track/track.json" in publish_site.PAYWALLED


def test_the_track_page_is_published_under_its_own_path():
    from chains import publish_site
    assert ("track.html", "index.html") in publish_site.TRACK_FILES
    assert ("track.json", "track.json") in publish_site.TRACK_FILES


# -- the rendered page -------------------------------------------------------

def rendered(book):
    twin = fc("mu_fq4-2026-03-02-r2", "mu_fq4", ["s1"], ["s2"], order=2)
    late = (CAL[-1] + dt.timedelta(days=1)).isoformat()
    data = built(book, [fc("f", "mu_fq4", ["up"], ["down"]), twin,
                        fc("g", "nvda_q3", ["up"], [], marked=late)])
    return data, track.render(data)


def test_the_page_says_nothing_undefined(book):
    _data, html = rendered(book)
    body = html[html.index("const TRACK"):]
    assert "undefined" not in json.dumps(_data)


def test_the_page_carries_no_hebrew(book):
    from chains import build_pages
    _data, html = rendered(book)
    assert build_pages.hebrew_runs(html) == []


def test_the_page_inlines_its_own_data(book):
    data, html = rendered(book)
    assert json.dumps(data["forecasts"][0]["id"]) in html
    assert "__TRACK__" not in html


def test_the_page_names_both_orders_apart(book):
    _data, html = rendered(book)
    assert "ring 2 up − down" in html and "up − down today" in html
    assert "second ring hit 5d" in html
