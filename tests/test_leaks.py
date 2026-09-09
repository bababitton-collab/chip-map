"""The forecast board's invariants, checked against the curated watch list.

These used to read a Python table. The table was the source of the JSON, and
holding both meant the engine carried one domain's vocabulary -- lane names
like "hbm" and "lithography" -- in its own source. The JSON is the source now,
and the invariants are checked where they actually have to hold.

A leak edge is a claim about CHRONOLOGY, not causation: this question is
answered first, so by the time that one is asked its answer is already public.
An edge pointing backwards through time would be drawn as an arrow on the board
and read as something much stronger than it is. A question with no lane would
be drawn at whatever row the fallback picks, which looks deliberate and is not.
"""
from __future__ import annotations

import json

import pytest

from chains.mapfile import load as load_map
from chains.paths import watch_en_path, watch_path

WATCH = json.loads(watch_path().read_text(encoding="utf-8"))
WATCH_EN = json.loads(watch_en_path().read_text(encoding="utf-8"))
BY = {r["id"]: r for r in WATCH}
IDS = set(BY)
LANES = set((load_map().get("labels") or {}).get("lanes") or {})


# -- every edge points at a question that exists ----------------------------

@pytest.mark.parametrize("row", WATCH, ids=lambda r: r["id"])
def test_every_leak_names_a_question_in_the_list(row):
    assert [l for l in row["leaks"] if l not in IDS] == []


def test_no_question_leaks_into_itself():
    assert [r["id"] for r in WATCH if r["id"] in r["leaks"]] == []


def test_the_board_has_edges_at_all():
    assert sum(len(r["leaks"]) for r in WATCH) > 0


# -- the edges point backwards in time, never forwards ----------------------

@pytest.mark.parametrize("row", WATCH, ids=lambda r: r["id"])
def test_every_leak_is_dated_earlier_than_its_question(row):
    late = [(l, BY[l]["d"]) for l in row["leaks"] if BY[l]["d"] >= row["d"]]
    assert late == [], (
        f"{row['id']} ({row['d']}) is fed by a question that is not earlier; "
        f"the board would draw an arrow running backwards through time")


# -- lanes ------------------------------------------------------------------

def test_every_question_has_a_lane():
    assert [r["id"] for r in WATCH if not r.get("lane")] == []


def test_every_lane_is_one_the_map_has_a_label_for():
    """A lane the map cannot name is a row of the board with a blank heading."""
    assert LANES, "the map declares no lanes"
    assert sorted({r["lane"] for r in WATCH} - LANES) == []


def test_the_board_has_at_least_one_edge_in_every_populated_lane():
    """A lane with questions but no edges is a column of unconnected dots --
    usually a half-updated list."""
    lanes = {r["lane"] for r in WATCH}
    linked = {r["lane"] for r in WATCH if r["leaks"]}
    assert sorted(lanes - linked) == []


# -- what every row carries -------------------------------------------------

@pytest.mark.parametrize("field", ["leaks", "lane", "lbl"])
def test_every_row_carries_the_board_fields(field):
    assert [r["id"] for r in WATCH if field not in r] == []


def test_the_label_is_short_enough_for_a_circle():
    assert [r["id"] for r in WATCH if len(r["lbl"]) > 18] == []


# -- the two languages stay in step -----------------------------------------

def test_the_two_watch_lists_carry_the_same_questions_in_the_same_order():
    assert [r["id"] for r in WATCH] == [r["id"] for r in WATCH_EN]


def test_the_two_watch_lists_agree_on_dates_and_edges():
    """Only the prose may differ. A date that differed between languages would
    put the same question on two different days of the same board."""
    en = {r["id"]: r for r in WATCH_EN}
    bad = [r["id"] for r in WATCH
           if (r["d"], r["confirmed"], r["leaks"], r["lane"])
           != (en[r["id"]]["d"], en[r["id"]]["confirmed"],
               en[r["id"]]["leaks"], en[r["id"]]["lane"])]
    assert bad == []
