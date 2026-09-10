"""The forward test: five states, one card each, and no invented blanks.

The unit is the dated question, not the forecast. Every one of them gets a card
the day it enters the watch list, and the card moves through states without
moving on the page. What is tested here is the state machine, the numbers that
appear before there is anything to measure, and the ones that must not.

The prices below are round on purpose: every expected number is worked out on
paper from the levels, not read back out of the code that produced it.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from chains import forecast, prices, track

# Sixty weekday sessions, so a card can be forty past its entry.
CAL = []
_d = dt.date(2026, 1, 5)
while len(CAL) < 60:
    if _d.weekday() < 5:
        CAL.append(_d)
    _d += dt.timedelta(days=1)
TODAY = CAL[-1]

# UP +1 a session on 100, DOWN -1, FLAT still, S1 +0.5, S2 -0.5.
# STALE stops printing after the twentieth session, on purpose.
LEVELS = (("up", 1.0, 60), ("down", -1.0, 60), ("flat", 0.0, 60),
          ("s1", 0.5, 60), ("s2", -0.5, 60), ("stale", 2.0, 20))

DOC = {
    "nodes": [{"id": i, "name": i.title(), "short": i.upper(),
               "ticker": i.upper(), "price_symbol": i.upper() + ".US",
               "price_symbol_kind": "primary"} for i, _s, _n in LEVELS],
    "subnodes": [],
    "edges": [{"from": "s1", "to": "up", "type": "supplies", "what": "parts"},
              {"from": "s2", "to": "down", "type": "supplies", "what": "parts"}],
}


@pytest.fixture
def book(monkeypatch, tmp_path):
    monkeypatch.setenv("CHIP_MAP_PRICES", str(tmp_path))
    for i, step, n in LEVELS:
        prices.store(i.upper() + ".US",
                     [{"date": c.isoformat(), "adjusted_close": 100.0 + step * k}
                      for k, c in enumerate(CAL[:n])])
    return forecast.Book([n["price_symbol"] for n in DOC["nodes"]])


def q(qid, d, win, lose, **over):
    r = {"id": qid, "who": qid.upper(), "tk": qid[:4].upper(), "d": d,
         "confirmed": True, "win": win, "lose": lose}
    r.update(over)
    return r


def fc(fid, qid, win, lose, marked, direction=1, order=1):
    from chains.answers import ORDERS
    r = {"id": fid, "qid": qid, "marked_at": marked,
         "status": "yes" if direction > 0 else "no", "direction": direction,
         "win": win, "lose": lose, "benchmark": "EW_MAP",
         "horizons": list(ORDERS[order])}
    if order != 1:
        r["order"] = order
    return r


def built(book, watch, forecasts=(), marks=None, ledger=None):
    fs = list(forecasts)
    led = ledger if ledger is not None else forecast.build(fs, DOC, [], CAL)
    return track.build(fs, led, list(watch), DOC, marks or {}, book, CAL, TODAY)


def one(book, watch, forecasts=(), marks=None):
    return built(book, watch, forecasts, marks)["forecasts"][0]


# -- the five states ---------------------------------------------------------

def test_a_dated_question_with_no_mark_is_upcoming(book):
    r = one(book, [q("a", (TODAY + dt.timedelta(days=9)).isoformat(),
                     ["up"], ["down"])])
    assert r["state"] == "upcoming"


def test_a_mark_with_no_session_since_it_is_awaiting_entry(book):
    late = (TODAY + dt.timedelta(days=1)).isoformat()
    r = one(book, [q("a", TODAY.isoformat(), ["up"], ["down"])],
            [fc("f", "a", ["up"], ["down"], late)],
            {"a": {"status": "yes"}})
    assert r["state"] == "marked" and r["entry_date"] is None


def test_a_forecast_inside_forty_sessions_is_tracking(book):
    r = one(book, [q("a", "2026-01-06", ["up"], ["down"])],
            [fc("f", "a", ["up"], ["down"], CAL[-8].isoformat())],
            {"a": {"status": "yes"}})
    assert r["state"] == "tracking" and r["day_index"] == 6


def test_a_forecast_past_forty_sessions_is_closed(book):
    r = one(book, [q("a", "2026-01-06", ["up"], ["down"])],
            [fc("f", "a", ["up"], ["down"], CAL[0].isoformat())],
            {"a": {"status": "yes"}})
    assert r["state"] == "closed"
    assert r["day_index"] >= track.CLOSED_AFTER


@pytest.mark.parametrize("status", sorted(track.UNDIRECTED))
def test_an_answer_that_points_nowhere_gets_no_forecast(status, book):
    """"mixed", "none" and "open" are real answers and none of them is a
    direction. The card stays, says which one it was, and is never scored."""
    r = one(book, [q("a", (TODAY - dt.timedelta(days=3)).isoformat(),
                     ["up"], ["down"])], [], {"a": {"status": status}})
    assert r["state"] == "none"
    assert r["status"] == status
    assert r["today"] == {} and r["horizons"] == {}
    assert r["series"] is None


def test_a_date_that_passed_with_no_mark_at_all_is_not_upcoming(book):
    r = one(book, [q("a", (TODAY - dt.timedelta(days=3)).isoformat(),
                     ["up"], ["down"])])
    assert r["state"] == "none"


def test_every_dated_question_gets_a_card(book):
    watch = [q("a", "2026-06-01", ["up"], []),
             q("b", "2026-06-02", ["down"], []),
             q("c", "2026-06-03", ["flat"], [])]
    out = built(book, watch)
    assert len(out["forecasts"]) == 3
    assert out["summary"]["n_cards"] == 3


def test_a_question_with_no_date_is_not_a_card(book):
    """The page is a calendar of claims. A row with no date has no place on it
    and no countdown to draw."""
    watch = [q("a", "2026-06-01", ["up"], []), q("b", None, ["down"], [])]
    assert len(built(book, watch)["forecasts"]) == 1


# -- the order they appear in ------------------------------------------------

def test_the_bands_are_tracking_marked_upcoming_none_closed(book):
    late = (TODAY + dt.timedelta(days=1)).isoformat()
    watch = [q("track1", "2026-01-06", ["up"], ["down"]),
             q("mark1", TODAY.isoformat(), ["up"], ["down"]),
             q("up1", (TODAY + dt.timedelta(days=9)).isoformat(), ["up"], []),
             q("none1", (TODAY - dt.timedelta(days=2)).isoformat(), ["up"], []),
             q("closed1", "2026-01-06", ["down"], [])]
    fs = [fc("f1", "track1", ["up"], ["down"], CAL[-8].isoformat()),
          fc("f2", "mark1", ["up"], ["down"], late),
          fc("f3", "closed1", ["down"], [], CAL[0].isoformat())]
    marks = {"track1": {"status": "yes"}, "mark1": {"status": "yes"},
             "closed1": {"status": "yes"}, "none1": {"status": "mixed"}}
    got = [r["state"] for r in built(book, watch, fs, marks)["forecasts"]]
    assert got == ["tracking", "marked", "upcoming", "none", "closed"]


def test_upcoming_cards_are_ordered_by_date(book):
    watch = [q("c", "2026-07-03", ["up"], []), q("a", "2026-07-01", ["up"], []),
             q("b", "2026-07-02", ["up"], [])]
    got = [r["qid"] for r in built(book, watch)["forecasts"]]
    assert got == ["a", "b", "c"]


def test_tracking_cards_are_newest_entry_first(book):
    watch = [q("old", "2026-01-06", ["up"], []),
             q("new", "2026-01-07", ["down"], [])]
    fs = [fc("f1", "old", ["up"], [], CAL[-20].isoformat()),
          fc("f2", "new", ["down"], [], CAL[-6].isoformat())]
    marks = {"old": {"status": "yes"}, "new": {"status": "yes"}}
    got = [r["qid"] for r in built(book, watch, fs, marks)["forecasts"]]
    assert got == ["new", "old"]


# -- the member table --------------------------------------------------------

def test_the_same_columns_exist_in_every_state(book):
    """A blank is a blank, and the shape of the row does not change with it."""
    fields = {"id", "tk", "label", "group", "expected_dir", "report_close",
              "entry_close", "last", "day_pct", "since_pct", "stale"}
    for r in built(book,
                   [q("u", (TODAY + dt.timedelta(days=9)).isoformat(),
                      ["up"], ["down"]),
                    q("t", "2026-01-06", ["up"], ["down"])],
                   [fc("f", "t", ["up"], ["down"], CAL[-8].isoformat())],
                   {"t": {"status": "yes"}})["forecasts"]:
        for m in r["members"]:
            assert set(m) == fields


def test_an_upcoming_card_has_no_entry_and_no_since(book):
    """Nothing has been entered, so those cells are absent -- not zero. A zero
    is a measurement and there has not been one."""
    r = one(book, [q("a", (TODAY + dt.timedelta(days=9)).isoformat(),
                     ["up"], ["down"])])
    for m in r["members"]:
        assert m["entry_close"] is None
        assert m["since_pct"] is None
        assert m["report_close"] is None, "the date has not come"
        assert m["last"] is not None, "but a last close always exists"


def test_a_blank_never_becomes_a_zero(book):
    r = one(book, [q("a", (TODAY + dt.timedelta(days=9)).isoformat(),
                     ["up"], ["down"])])
    blanks = [m["entry_close"] for m in r["members"]] + \
             [m["since_pct"] for m in r["members"]]
    assert all(b is None for b in blanks)
    assert 0 not in blanks and 0.0 not in blanks


def test_the_members_are_the_registered_baskets_before_any_mark(book):
    """The claim is public before the answer exists. That is the whole point of
    the upcoming card."""
    r = one(book, [q("a", (TODAY + dt.timedelta(days=9)).isoformat(),
                     ["up", "flat"], ["down"])])
    assert [m["id"] for m in r["members"] if m["group"] == "win"] == \
        ["up", "flat"]
    assert [m["id"] for m in r["members"] if m["group"] == "lose"] == ["down"]


def test_the_second_ring_is_its_own_group(book):
    r = one(book, [q("a", (TODAY + dt.timedelta(days=9)).isoformat(),
                     ["up"], ["down"])])
    assert {m["group"] for m in r["members"]} == {"win", "lose", "win2", "lose2"}
    assert [m["id"] for m in r["members"] if m["group"] == "win2"] == ["s1"]


def test_a_carried_forward_member_says_so(book):
    """STALE stops printing after the twentieth session. Carrying it forward is
    what a basket does; a flat line that is really an absent one is a lie by
    omission, so the row is marked."""
    r = one(book, [q("a", (TODAY + dt.timedelta(days=9)).isoformat(),
                     ["stale"], [])])
    m = [x for x in r["members"] if x["id"] == "stale"][0]
    assert m["stale"] > track.STALE_AFTER
    assert m["last"] == 138.0, "the last real close, carried"


# -- report-day close --------------------------------------------------------

def test_the_report_day_close_is_the_close_on_the_day(book):
    """UP is 100 + the session index. CAL[30] is the thirty-first session."""
    d = CAL[30].isoformat()
    r = one(book, [q("a", d, ["up"], [])], [], {"a": {"status": "mixed"}})
    got = {m["id"]: m["report_close"] for m in r["members"]}
    assert got["up"] == 130.0
    assert got["s1"] == 115.0, "the second ring is priced on the same day"


def test_a_report_day_that_is_not_a_session_takes_the_one_before(book):
    """A Saturday announcement is measured at Friday's close, because there is
    no Saturday close to measure it at."""
    friday = next(c for c in CAL if c.weekday() == 4 and c > CAL[25])
    saturday = friday + dt.timedelta(days=1)
    assert saturday.weekday() == 5
    on_friday = 100.0 + CAL.index(friday)
    r = one(book, [q("a", saturday.isoformat(), ["up"], [])], [],
            {"a": {"status": "mixed"}})
    got = {m["id"]: m["report_close"] for m in r["members"]}
    assert got["up"] == on_friday


def test_a_report_day_in_the_future_has_no_close(book):
    """It would be today's price wearing a future date."""
    r = one(book, [q("a", (TODAY + dt.timedelta(days=9)).isoformat(),
                     ["up"], [])])
    assert r["members"][0]["report_close"] is None


def test_the_report_day_close_does_not_move_with_the_entry(book):
    """Marked later, entered later, and still the same number: it is a fact
    about the day the news landed, not about the position."""
    d = CAL[30].isoformat()
    before = one(book, [q("a", d, ["up"], [])], [], {"a": {"status": "mixed"}})
    after = one(book, [q("a", d, ["up"], [])],
                [fc("f", "a", ["up"], [], CAL[40].isoformat())],
                {"a": {"status": "yes"}})
    assert before["members"][0]["report_close"] == \
        after["members"][0]["report_close"] == 130.0


# -- the sign ----------------------------------------------------------------

def test_a_yes_subtracts_in_the_order_it_was_written():
    assert track.spread(1, 5.0, 2.0) == 3.0


def test_a_no_flips_the_baskets_before_subtracting():
    assert track.spread(-1, 5.0, 2.0) == -3.0
    assert track.spread(-1, 2.0, 5.0) == 3.0


def test_with_no_lose_side_a_no_negates():
    assert track.spread(1, 4.0, None) == 4.0
    assert track.spread(-1, 4.0, None) == -4.0


def test_a_missing_side_is_not_a_zero():
    assert track.spread(1, None, 2.0) is None
    assert track.spread(1, None, None) is None


@pytest.mark.parametrize("group,direction,want", [
    ("win", 1, 1), ("lose", 1, -1), ("win2", 1, 1), ("lose2", 1, -1),
    ("win", -1, -1), ("lose", -1, 1), ("win2", -1, -1), ("lose2", -1, 1),
])
def test_the_expected_direction_of_a_row_follows_the_mark(group, direction,
                                                          want):
    """A "no" mark says the win basket falls, so the arrow on a win row points
    down. The column header follows: "expected if no"."""
    assert track.expected_dir(group, direction) == want


def test_the_sign_is_applied_exactly_once(book):
    watch = [q("a", "2026-01-06", ["up"], ["down"])]
    yes = one(book, watch, [fc("y", "a", ["up"], ["down"],
                               CAL[-8].isoformat())], {"a": {"status": "yes"}})
    no = one(book, watch, [fc("n", "a", ["up"], ["down"], CAL[-8].isoformat(),
                              direction=-1)], {"a": {"status": "no"}})
    assert yes["today"]["win_lose"] == pytest.approx(
        -no["today"]["win_lose"], abs=1e-6)
    assert yes["today"]["win_lose"] > 0 and no["today"]["win_lose"] < 0


# -- what the chart is drawn from --------------------------------------------

def test_every_series_starts_at_zero_on_the_entry_close(book):
    r = one(book, [q("a", "2026-01-06", ["up"], ["down"])],
            [fc("f", "a", ["up"], ["down"], CAL[-8].isoformat())],
            {"a": {"status": "yes"}})
    for k in ("win", "lose", "ew"):
        assert r["series"][k][0] == 0.0


def test_the_series_is_a_percentage_from_the_closes(book):
    """Marked on CAL[-8], so entry is CAL[-7] at 100+53=153, and five sessions
    later UP is at 158."""
    r = one(book, [q("a", "2026-01-06", ["up"], ["down"])],
            [fc("f", "a", ["up"], ["down"], CAL[-8].isoformat())],
            {"a": {"status": "yes"}})
    assert r["entry_date"] == CAL[-7].isoformat()
    assert r["series"]["win"][5] == pytest.approx((158 / 153 - 1) * 100,
                                                  abs=1e-4)


def test_today_and_the_horizons_are_in_the_same_unit(book):
    r = one(book, [q("a", "2026-01-06", ["up"], ["down"])],
            [fc("f", "a", ["up"], ["down"], CAL[-8].isoformat())],
            {"a": {"status": "yes"}})
    assert abs(r["today"]["win_lose"]) > 1, "a percentage, not a fraction"
    assert abs(r["horizons"]["5"]["spread"]) > 1


def test_the_horizons_come_from_the_ledger_unchanged(book):
    f = fc("f", "a", ["up"], ["down"], CAL[-8].isoformat())
    led = forecast.build([f], DOC, [], CAL)
    r = built(book, [q("a", "2026-01-06", ["up"], ["down"])], [f],
              {"a": {"status": "yes"}}, ledger=led)["forecasts"][0]
    assert r["horizons"]["5"]["spread"] == pytest.approx(
        led["rows"][0]["horizons"]["5"]["excess"] * 100, rel=1e-9)
    assert r["horizons"]["5"]["hit"] is led["rows"][0]["horizons"]["5"]["hit"]


# -- the two orders ----------------------------------------------------------

def test_the_twin_folds_into_the_same_card(book):
    marked = CAL[-8].isoformat()
    fs = [fc("f", "a", ["up"], ["down"], marked),
          fc("a-" + marked + "-r2", "a", ["s1"], ["s2"], marked, order=2)]
    out = built(book, [q("a", "2026-01-06", ["up"], ["down"])], fs,
                {"a": {"status": "yes"}})
    assert len(out["forecasts"]) == 1, "one card, not two"
    assert out["forecasts"][0]["series"]["win2"][0] == 0.0


def test_the_orders_are_never_pooled(book):
    marked = CAL[-8].isoformat()
    fs = [fc("f1", "a", ["up"], ["down"], marked),
          fc("f2", "b", ["up"], ["down"], marked),
          fc("a-" + marked + "-r2", "a", ["s1"], ["s2"], marked, order=2)]
    out = built(book, [q("a", "2026-01-06", ["up"], ["down"]),
                       q("b", "2026-01-07", ["up"], ["down"])], fs,
                {"a": {"status": "yes"}, "b": {"status": "yes"}})
    assert out["summary"]["direct_hit_5"]["n"] == 2
    assert out["summary"]["ring2_hit_5"]["n"] == 1


# -- the tiles ---------------------------------------------------------------

def test_the_summary_carries_the_n_behind_every_number(book):
    out = built(book, [q("a", "2026-06-01", ["up"], [])])
    for k in ("direct_hit_5", "direct_spread_5", "direct_spread_20",
              "ring2_hit_5", "ring2_spread_5"):
        assert set(out["summary"][k]) == {"n", "value"}
        assert out["summary"][k] == {"n": 0, "value": None}


def test_the_sixth_tile_counts_what_is_pre_registered(book):
    watch = [q("a", "2026-06-01", ["up"], []),
             q("b", "2026-06-02", ["down"], []),
             q("c", "2026-05-30", ["flat"], [])]
    s = built(book, watch)["summary"]
    assert s["n_upcoming"] == 3
    assert s["next_up"] == {"d": "2026-05-30", "who": "C"}


def test_a_page_with_nothing_scored_still_counts_its_cards(book):
    """Never an empty state: the claims exist before the answers do."""
    s = built(book, [q("a", "2026-06-01", ["up"], [])])["summary"]
    assert s["n_cards"] == 1 and s["n_scored"] == 0


# -- the slim copy that rides in live.json ------------------------------------

def test_live_json_carries_a_slimmed_copy(book):
    """The full record set is 42 KB of members and series for thirty-nine
    questions, and live.json has a hard ceiling it was already close to."""
    full = built(book, [q("a", "2026-06-01", ["up"], ["down"])])
    thin = track.slim(full)
    assert thin["summary"] == full["summary"]
    r = thin["forecasts"][0]
    assert "members" not in r and "series" not in r and "ring2_edges" not in r
    assert r["state"] == "upcoming" and r["who"] == "A"


def test_the_slim_copy_is_much_smaller(book):
    full = built(book, [q("a", "2026-06-01", ["up"], ["down"])])
    assert len(json.dumps(track.slim(full))) < len(json.dumps(full)) / 2


# -- the paywall and the copy -------------------------------------------------

def test_a_locked_question_contributes_no_text(book):
    r = one(book, [q("a", "2026-06-01", ["up"], [])])
    assert "q" not in r


def test_an_open_question_text_rides_along(book):
    r = one(book, [q("a", "2026-06-01", ["up"], [], q="Is it shipping?")])
    assert r["q"] == "Is it shipping?"


def test_the_publisher_scans_the_track_page_for_locked_text():
    from chains import publish_site
    assert "track/index.html" in publish_site.PAYWALLED
    assert "track/track.enc.json" in publish_site.PAYWALLED


def test_the_track_page_is_published_under_its_own_path():
    from chains import publish_site
    assert ("track.html", "index.html") in publish_site.TRACK_FILES
    assert ("track.enc.json", "track.enc.json") in publish_site.TRACK_FILES


TEMPLATE = None


def template() -> str:
    global TEMPLATE
    if TEMPLATE is None:
        from chains.paths import templates_dir
        TEMPLATE = (templates_dir() / "track.html").read_text(encoding="utf-8")
    return TEMPLATE


def test_the_page_never_tells_anybody_to_do_anything():
    """It measures a spread between baskets. "buy" and "sell" are instructions
    and this page issues none -- "entry" and "measured from" are the words."""
    import re
    body = template()
    # The page's own copy: the question text is quoted from the watch list and
    # is Michael's sentence, not this page's.
    body = re.sub(r"\$\{[^}]*\}", "", body)
    for word in ("buy", "buys", "buying", "bought",
                 "sell", "sells", "selling", "sold"):
        assert not re.search(r"\b" + word + r"\b", body, re.I), word
    assert "entry" in body.lower()


def test_the_footer_says_the_orders_are_reported_apart():
    """The footer is built by concatenation in the page, so the sentence is
    checked on what a reader actually gets."""
    from chains import forecast as _f
    body = template()
    assert "Direct and second-ring results are reported separately" in body
    assert "averaged together" in body
    assert "never pooled" not in body, "the old wording"


def test_the_footer_keeps_the_disclaimer():
    assert "Not a recommendation and not investment advice." in template()


def test_the_page_has_no_hebrew():
    from chains import build_pages
    assert build_pages.hebrew_runs(template()) == []


def test_a_template_with_no_placeholder_fails_loudly():
    with pytest.raises(SystemExit) as e:
        track.render({"summary": {}, "forecasts": []}, template="<html></html>")
    assert "empty shell" in str(e.value)


def test_the_rendered_page_says_nothing_undefined(book):
    data = built(book, [q("a", "2026-06-01", ["up"], ["down"])])
    assert "undefined" not in json.dumps(data)
    assert "__TRACK__" not in track.render(data)


def test_the_page_never_shows_a_bare_dash_in_a_tile():
    """With nothing finished the honest reading is a zero out of a zero, and a
    caption that says which zero it is."""
    body = template()
    assert "'0 / 0'" in body
    assert "no finished forecasts yet" in body


# -- what the edge carries ----------------------------------------------------

def test_the_reason_is_the_edge_between_the_company_and_the_station(book):
    """The same rule the map's cards use: the first clause of the edge's own
    words, in either direction."""
    doc = dict(DOC, edges=[{"from": "up", "to": "acme", "type": "supplies",
                            "what": "wafers and packaging; per the 10-K"}])
    assert track.reason_for(doc, "acme", "up") == "wafers and packaging"
    assert track.reason_for(doc, "up", "acme") == "wafers and packaging"


def test_a_station_with_no_edge_gets_no_reason_at_all(book):
    """The layer name used to stand in there, which put the same three words
    beside every station on a card and read like three findings when it was one
    label. A blank says what is true: the map records no link."""
    doc = {"nodes": [{"id": "up", "layer": "L4"}], "subnodes": [], "edges": [],
           "labels": {"layers": {"L4": {"he": "x", "en": "chip designers"}}}}
    assert track.reason_for(doc, "acme", "up") == ""


def test_a_reason_is_never_hebrew():
    """The page is English-only, and the only text that can reach it is an
    edge's own words from the map, which are English."""
    from chains import build_pages
    doc = {"nodes": [{"id": "up"}], "subnodes": [],
           "edges": [{"from": "up", "to": "acme", "type": "supplies",
                      "what": "wafers"}]}
    assert build_pages.hebrew_runs(track.reason_for(doc, "acme", "up")) == []


def test_a_station_the_map_has_never_heard_of_gets_no_reason():
    """Nine basket ids are not map nodes. An invented sentence would be worse
    than a blank line beside the circle."""
    assert track.reason_for({"nodes": [], "subnodes": []}, "acme", "who") == ""


def test_the_reason_is_the_whole_clause_not_the_drawn_one(book):
    """The page clips it to twelve characters and keeps this in a <title>.
    Truncating here as well is what made the map's own hover give back the cut
    text for a while."""
    long = "GPUs (Oracle as buyer): OCI Supercluster up to 131,072 Blackwell"
    doc = dict(DOC, edges=[{"from": "up", "to": "acme", "type": "supplies",
                            "what": long}])
    assert track.reason_for(doc, "acme", "up") == long
    assert len(track.reason_for(doc, "acme", "up")) > 12


def test_a_reason_longer_than_the_cap_is_cut_not_dropped(book):
    doc = dict(DOC, edges=[{"from": "up", "to": "acme", "type": "supplies",
                            "what": "x" * 400}])
    got = track.reason_for(doc, "acme", "up")
    assert len(got) == track.MAX_REASON


def test_the_record_carries_a_reason_for_every_drawn_ring_one_station(book):
    """Three a side is what the constellation draws, so three a side is what
    rides in the payload."""
    r = one(book, [q("a", "2026-06-01", ["up", "flat", "s1", "s2"], ["down"])])
    assert [e["id"] for e in r["ring1_edges"]] == ["up", "flat", "s1", "down"]
    assert all(set(e) == {"id", "label"} for e in r["ring1_edges"])


def test_the_reasons_do_not_ride_in_the_slim_copy(book):
    """live.json has a hard ceiling and no use for them."""
    thin = track.slim(built(book, [q("a", "2026-06-01", ["up"], ["down"])]))
    assert "ring1_edges" not in thin["forecasts"][0]


# -- the drawing keeps the cut and the whole ---------------------------------

def cards_source() -> str:
    from chains.paths import templates_dir
    return (templates_dir() / "track-cards.js").read_text(encoding="utf-8")


def test_the_page_clips_the_reason_at_twelve_and_titles_the_whole():
    body = cards_source()
    assert "const REASON_MAX=12;" in body
    assert "esc(clip(full,REASON_MAX))" in body
    assert "<title>${esc(full)}</title>" in body


def test_the_second_ring_keeps_its_own_words_on_hover():
    body = cards_source()
    assert "by[e.from].labels.push(e.label||'');" in body
    assert "(k.labels||[]).filter(Boolean).join(' · ')" in body


# -- the sealed payload ------------------------------------------------------

def key() -> bytes:
    import os
    return os.urandom(32)


def test_a_payload_survives_a_round_trip(book):
    data = built(book, [q("a", "2026-06-01", ["up"], ["down"])])
    k = key()
    assert track.decrypt(track.encrypt(data, k), k) == data


def test_the_sealed_file_is_the_shape_the_page_expects(book):
    """The page reads it with WebCrypto and no library, so the field names and
    the base64 are the contract."""
    import base64
    blob = track.encrypt(built(book, [q("a", "2026-06-01", ["up"], [])]), key())
    assert blob["v"] == 1 and blob["alg"] == "A256GCM"
    assert len(base64.b64decode(blob["nonce"])) == track.NONCE_BYTES
    assert len(base64.b64decode(blob["tag"])) == 16
    assert base64.b64decode(blob["ct"])


def test_as_of_rides_outside_the_ciphertext(book):
    """The page has to say how fresh the locked data is without holding the
    key."""
    data = built(book, [q("a", "2026-06-01", ["up"], [])])
    assert track.encrypt(data, key())["as_of"] == data["as_of"]


def test_the_wrong_key_is_a_clean_error_not_a_partial_read(book):
    data = built(book, [q("a", "2026-06-01", ["up"], [])])
    blob = track.encrypt(data, key())
    with pytest.raises(track.TrackKeyError) as e:
        track.decrypt(blob, key())
    assert "does not open" in str(e.value)


def test_a_changed_file_fails_to_open_rather_than_opening_wrong(book):
    """GCM authenticates. A byte flipped in transit is not a partial read."""
    import base64
    k = key()
    blob = track.encrypt(built(book, [q("a", "2026-06-01", ["up"], [])]), k)
    ct = bytearray(base64.b64decode(blob["ct"]))
    ct[0] ^= 0x01
    blob["ct"] = base64.b64encode(bytes(ct)).decode()
    with pytest.raises(track.TrackKeyError):
        track.decrypt(blob, k)


def test_an_unknown_algorithm_is_refused(book):
    k = key()
    blob = track.encrypt(built(book, [q("a", "2026-06-01", ["up"], [])]), k)
    blob["alg"] = "rot13"
    with pytest.raises(track.TrackKeyError) as e:
        track.decrypt(blob, k)
    assert "unknown algorithm" in str(e.value)


def test_a_missing_key_stops_the_build(monkeypatch):
    """The one bug in this arrangement nobody would notice: the site would look
    exactly right and be unlocked."""
    monkeypatch.delenv(track.KEY_ENV, raising=False)
    with pytest.raises(track.TrackKeyError) as e:
        track.load_key()
    assert "will not fall back to plaintext" in str(e.value)


@pytest.mark.parametrize("bad,why", [
    ("not base64!!", "base64"),
    ("c2hvcnQ=", "AES-256 needs"),
])
def test_a_malformed_key_says_which_way_it_is_wrong(bad, why, monkeypatch):
    monkeypatch.setenv(track.KEY_ENV, bad)
    with pytest.raises(track.TrackKeyError) as e:
        track.load_key()
    assert why in str(e.value)


def test_a_good_key_loads(monkeypatch):
    import base64
    import os
    raw = os.urandom(32)
    monkeypatch.setenv(track.KEY_ENV, base64.b64encode(raw).decode())
    assert track.load_key() == raw


# -- the free half -----------------------------------------------------------

def test_the_public_payload_describes_nothing_in_flight(book):
    """Anything still running is counted, never described: its members and its
    prices are not in the object at all."""
    watch = [q("t", "2026-01-06", ["up"], ["down"]),
             q("u", (TODAY + dt.timedelta(days=9)).isoformat(), ["up"], [])]
    fs = [fc("f", "t", ["up"], ["down"], CAL[-8].isoformat())]
    pub = track.public(built(book, watch, fs, {"t": {"status": "yes"}}))
    blob = json.dumps(pub)
    assert pub["n_active"] == 1 and pub["closed"] == []
    for word in ("members", "series", "entry_close", "since_pct", "win2",
                 "ring2_edges", "UP", "DOWN"):
        assert word not in blob, word


def test_a_finished_forecast_goes_out_whole(book):
    """The record is the evidence, and evidence nobody can see is not
    evidence."""
    watch = [q("c", "2026-01-06", ["up"], ["down"])]
    fs = [fc("f", "c", ["up"], ["down"], CAL[0].isoformat())]
    pub = track.public(built(book, watch, fs, {"c": {"status": "yes"}}))
    assert len(pub["closed"]) == 1
    row = pub["closed"][0]
    assert row["who"] == "C" and row["status"] == "yes"
    assert row["horizons"]["5"]["spread"] is not None
    assert "members" not in row


def test_the_second_ring_is_a_count_not_a_cast_list(book):
    marked = CAL[0].isoformat()
    watch = [q("c", "2026-01-06", ["up"], ["down"])]
    fs = [fc("f", "c", ["up"], ["down"], marked),
          fc("c-" + marked + "-r2", "c", ["s1"], ["s2"], marked, order=2)]
    pub = track.public(built(book, watch, fs, {"c": {"status": "yes"}}))
    row = pub["closed"][0]
    assert isinstance(row["ring2_scored"], int)
    blob = json.dumps(pub)
    assert "s1" not in blob and "S1" not in blob


def test_the_public_payload_names_the_next_date_and_who(book):
    """A date is not a finding; it is a public fact with a countdown on it."""
    pub = track.public(built(book, [
        q("a", "2026-06-02", ["up"], []), q("b", "2026-06-01", ["down"], [])]))
    assert pub["next_up"] == {"d": "2026-06-01", "who": "B", "confirmed": True}
    assert pub["n_upcoming"] == 2


def test_the_public_payload_is_small(book):
    """It is the free half of a paid product; it should not be most of it."""
    full = built(book, [q("a", "2026-06-01", ["up"], ["down"])])
    assert len(json.dumps(track.public(full))) < len(json.dumps(full)) / 10


# -- what the publisher ships ------------------------------------------------

def test_only_the_sealed_file_is_published():
    from chains import publish_site
    names = [dst for _src, dst in publish_site.TRACK_FILES]
    assert "track.enc.json" in names
    assert "track.json" not in names
    assert publish_site.TRACK_PLAINTEXT == "track.json"


def test_the_sealed_file_goes_through_the_leak_scan():
    from chains import publish_site
    assert "track/track.enc.json" in publish_site.PAYWALLED
    assert "track/track.json" not in publish_site.PAYWALLED


def test_the_page_asks_for_a_key_and_keeps_it_in_the_browser():
    body = template()
    assert "crypto.subtle.decrypt" in body and "AES-GCM" in body
    assert "track.enc.json" in body
    assert "localStorage.setItem" in body
    assert "That key does not open this month" in body


def test_the_key_input_is_a_password_field():
    """It is a shared secret; it should not sit in a screenshot or a screen
    share in plain sight."""
    assert 'id="key" type="password"' in template()


def test_the_locked_panel_holds_no_real_content():
    body = template()
    i = body.index('id="locked"')
    j = body.index("// ---- the key", i)
    panel = body[i:j]
    assert "gb" in panel and "gring" in panel, "generic bars and a ring"
    assert "members" not in panel


def test_the_shared_renderer_is_one_file():
    """The unlocked public view and the private map's section draw the same
    cards; two copies would drift."""
    from chains.paths import templates_dir
    js = (templates_dir() / "track-cards.js").read_text(encoding="utf-8")
    assert "window.renderTrack" in js
    assert track.CARDS_PLACEHOLDER in template()
    assert track.CARDS_PLACEHOLDER in (
        templates_dir() / "live-map.html").read_text(encoding="utf-8")


def test_the_renderer_does_not_fetch_or_decrypt_anything():
    """It draws what it is handed. Deciding what a reader may see is not its
    job and it has no way to do it."""
    from chains.paths import templates_dir
    js = (templates_dir() / "track-cards.js").read_text(encoding="utf-8")
    for word in ("fetch(", "crypto.subtle", "localStorage", "track.enc"):
        assert word not in js, word


# -- the sealed payload carries every question -------------------------------
#
# The tier rule -- nearest question only -- is a rule about PLAINTEXT. This
# file is encrypted before it is published and the plaintext never leaves the
# runner, so the paywall here is the key. A subscriber who cannot see the
# question a forecast was made from cannot check the forecast, which is the
# whole thing they are paying for.

def test_a_record_carries_whatever_text_it_was_handed(book):
    """The tier is decided upstream by what merge() attached. record() copies;
    it does not decide again -- one place deciding is the point of
    chains/access.py."""
    w = q("a", "2026-06-01", ["up"], [], q="Is it shipping?",
          yes="Units up", no="Units flat", why="It sets the floor.")
    r = one(book, [w])
    assert (r["q"], r["yes"], r["no"], r["why"]) == (
        "Is it shipping?", "Units up", "Units flat", "It sets the floor.")


def test_a_record_omits_a_part_it_was_not_handed(book):
    """A v1 questions file has no "no" sentence. The field is absent, not
    empty: inventing one would be inventing the product."""
    r = one(book, [q("a", "2026-06-01", ["up"], [], q="Is it shipping?",
                     yes="Units up")])
    assert r["q"] and r["yes"]
    assert "no" not in r and "why" not in r


def test_a_record_with_no_text_has_none_of_the_four(book):
    r = one(book, [q("a", "2026-06-01", ["up"], [])])
    for part in ("q", "yes", "no", "why"):
        assert part not in r


def test_the_public_half_never_carries_the_three_extra_parts(book):
    """Only the question itself, and only on a finished forecast, whose answer
    is already public. yes/no/why stay behind the key."""
    watch = [q("c", "2026-01-06", ["up"], ["down"], q="Q?", yes="Y", no="N",
               why="W")]
    fs = [fc("f", "c", ["up"], ["down"], CAL[0].isoformat())]
    pub = track.public(built(book, watch, fs, {"c": {"status": "yes"}}))
    row = pub["closed"][0]
    assert row["q"] == "Q?"
    for part in ("yes", "no", "why"):
        assert part not in row
    blob = json.dumps(pub)
    assert '"Y"' not in blob and '"N"' not in blob and '"W"' not in blob


def test_the_slim_copy_carries_no_text_at_all(book):
    """live.json is published as plaintext. Nothing of the four goes in it."""
    watch = [q("a", "2026-06-01", ["up"], [], q="Q?", yes="Y", no="N", why="W")]
    thin = track.slim(built(book, watch))
    for part in ("q", "yes", "no", "why"):
        assert part not in thin["forecasts"][0]
    assert "Q?" not in json.dumps(thin)


def test_the_text_is_unreadable_once_sealed(book):
    """The obvious property, asserted anyway: it is the one that makes putting
    every question in this file safe."""
    watch = [q("a", "2026-06-01", ["up"], [],
               q="A sentence nobody has paid for yet.")]
    data = built(book, watch)
    k = key()
    blob = json.dumps(track.encrypt(data, k))
    assert "A sentence nobody has paid for yet." not in blob
    assert track.decrypt(json.loads(blob), k)["forecasts"][0]["q"] == \
        "A sentence nobody has paid for yet."


def test_only_paid_outputs_unlock_every_row():
    """The flag is explicit and every caller is a paid output: the two letters,
    which pass ``not free``, and the sealed payload, which passes True outright
    because that file is encrypted before it is published.

    Nothing that writes a plaintext published file sets it, and this is the
    check that says so -- grep, as a test, because the property is "no fourth
    caller appeared" and nothing else can assert that.
    """
    import pathlib
    hits = {p.name for p in sorted(pathlib.Path("chains").glob("*.py"))
            if "unlock_all=" in p.read_text(encoding="utf-8")}
    assert hits == {"brief.py", "brief_he.py", "track.py"}, hits
    # and the one that unlocks unconditionally is the encrypted one
    src = pathlib.Path("chains/track.py").read_text(encoding="utf-8")
    assert "unlock_all=True" in src
    for name in ("brief.py", "brief_he.py"):
        assert "unlock_all=not free" in pathlib.Path(
            "chains", name).read_text(encoding="utf-8")


# -- the renderer draws it ---------------------------------------------------

def test_the_renderer_draws_the_question_block():
    body = cards_source()
    assert "function question(r){" in body
    assert "Yes looks like" in body and "No looks like" in body
    assert "Why it matters." in body


def test_the_renderer_omits_a_part_that_is_not_there():
    body = cards_source()
    assert "if(!r.q && !r.yes && !r.no && !r.why) return '';" in body
    assert "r.no?" in body and "r.why?" in body


def test_the_block_goes_to_one_column_with_only_one_side():
    """A v1 file has no "no" sentence, and a half-width column beside an empty
    one wraps three words to a line for no reason."""
    assert "const both = !!(r.yes && r.no);" in cards_source()
    assert ".fc .yn.one{grid-template-columns:1fr}" in template()


def test_both_pages_style_the_block():
    """The renderer is shared, so the classes have to exist on both."""
    from chains.paths import templates_dir
    priv = (templates_dir() / "live-map.html").read_text(encoding="utf-8")
    for css in (template(), priv):
        assert ".yn" in css and ".why" in css
