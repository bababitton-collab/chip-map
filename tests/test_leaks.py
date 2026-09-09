"""The forecast board's two invariants, checked against the real watch list.

A leak edge is a claim about CHRONOLOGY, not causation: this question is
answered first, so by the time that one is asked its answer is already public.
An edge pointing backwards through time would be drawn as an arrow on the board
and read as something much stronger than it is. And a question with no lane
would be drawn at whatever row the fallback picks, which looks deliberate and
is not.

Both tables are hand-written and the watch list moves underneath them, so this
runs against the generated JSON rather than against the tables: an id that was
retired, or a date that a company announced and moved, shows up here.
"""
from __future__ import annotations

import json

import pytest

from chains import leaks
from chains.paths import watch_en_path, watch_path

WATCH = json.loads(watch_path().read_text(encoding="utf-8"))
WATCH_EN = json.loads(watch_en_path().read_text(encoding="utf-8"))
BY = {r["id"]: r for r in WATCH}
IDS = set(BY)


# -- the tables refer to questions that exist -------------------------------

def test_every_id_named_in_LEAKS_exists_in_the_watch_list():
    """Both ends of every edge. A dangling id is a silently dropped edge."""
    named = set(leaks.LEAKS) | {t for v in leaks.LEAKS.values() for t in v}
    assert sorted(named - IDS) == []


def test_every_id_named_in_LANE_exists_in_the_watch_list():
    named = {i for v in leaks.LANE.values() for i in v}
    assert sorted(named - IDS) == []


def test_every_question_has_a_lane():
    """Not "gets the fallback" -- has one, explicitly, in the table."""
    assert sorted(IDS - set(leaks.LANE_OF)) == []


def test_no_question_is_in_two_lanes():
    seen: dict[str, str] = {}
    dupes = []
    for lane, ids in leaks.LANE.items():
        for i in ids:
            if i in seen:
                dupes.append((i, seen[i], lane))
            seen[i] = lane
    assert dupes == []


# -- the edges point backwards in time, never forwards ----------------------

@pytest.mark.parametrize("row", WATCH, ids=lambda r: r["id"])
def test_every_leak_is_dated_earlier_than_its_question(row):
    late = [(l, BY[l]["d"]) for l in row["leaks"] if BY[l]["d"] >= row["d"]]
    assert late == [], (
        f"{row['id']} ({row['d']}) is fed by a question that is not earlier; "
        f"the board would draw an arrow running backwards through time")


def test_no_question_leaks_into_itself():
    self_links = [i for i, v in leaks.LEAKS.items() if i in v]
    assert self_links == []


def test_a_leak_that_stopped_being_earlier_is_dropped_not_reversed():
    """The table is static; the dates are not. When a company announces and a
    row moves past one of its own leakers, the edge disappears rather than
    quietly pointing the wrong way."""
    rows = [{"id": "early", "d": "2026-01-01", "who": "E"},
            {"id": "late", "d": "2026-02-01", "who": "L"}]
    table = dict(leaks.LEAKS)
    try:
        leaks.LEAKS.clear()
        leaks.LEAKS["late"] = ["early"]
        assert leaks.apply(rows, {})[1]["leaks"] == ["early"]
        rows[0]["d"] = "2026-03-01"      # the leaker slips past its question
        assert leaks.apply(rows, {})[1]["leaks"] == []
    finally:
        leaks.LEAKS.clear()
        leaks.LEAKS.update(table)


def test_an_edge_to_a_retired_question_is_dropped():
    rows = [{"id": "late", "d": "2026-02-01", "who": "L"}]
    table = dict(leaks.LEAKS)
    try:
        leaks.LEAKS.clear()
        leaks.LEAKS["late"] = ["gone"]
        assert leaks.apply(rows, {})[0]["leaks"] == []
    finally:
        leaks.LEAKS.clear()
        leaks.LEAKS.update(table)


# -- what apply() wrote into the file ---------------------------------------

@pytest.mark.parametrize("field", ["leaks", "lane", "lbl"])
def test_every_row_carries_the_board_fields(field):
    assert [r["id"] for r in WATCH if field not in r] == []


def test_the_label_is_short_enough_for_a_circle():
    assert [r["id"] for r in WATCH if len(r["lbl"]) > 18] == []


def test_the_board_has_at_least_one_edge_in_every_populated_lane():
    """A lane with questions but no edges is a column of unconnected dots --
    worth knowing about, because it usually means a table was half-updated."""
    lanes = {r["lane"] for r in WATCH}
    linked = {r["lane"] for r in WATCH if r["leaks"]}
    assert sorted(lanes - linked) == []


# -- the two languages stay in step -----------------------------------------

def test_the_two_watch_lists_carry_the_same_questions_in_the_same_order():
    assert [r["id"] for r in WATCH] == [r["id"] for r in WATCH_EN]


def test_the_two_watch_lists_agree_on_dates_and_edges():
    """Only the prose may differ. A date that differs between languages would
    put the same question on two different days of the same board."""
    en = {r["id"]: r for r in WATCH_EN}
    bad = [r["id"] for r in WATCH
           if (r["d"], r["confirmed"], r["leaks"], r["lane"])
           != (en[r["id"]]["d"], en[r["id"]]["confirmed"],
               en[r["id"]]["leaks"], en[r["id"]]["lane"])]
    assert bad == []
