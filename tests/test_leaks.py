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
import re

import pytest

from chains.mapfile import load as load_map
from chains.paths import watch_en_path, watch_path

WATCH = json.loads(watch_path().read_text(encoding="utf-8"))
WATCH_EN = json.loads(watch_en_path().read_text(encoding="utf-8"))
BY = {r["id"]: r for r in WATCH}
IDS = set(BY)
LANES = set((load_map().get("labels") or {}).get("lanes") or {})

MAP = load_map()
NODES = MAP.get("nodes") or []
EDGES = MAP.get("edges") or []
# A node with a ticker has a price, and only a priced node can carry a basket
# leg -- an unpriced one has nothing to measure the move against.
PRICED = {n["id"] for n in NODES if n.get("ticker")}
# .KS/.T/.TW/.TWO/.DE: the map's tickers carry the exchange, the watch list's
# do not, so 8035.T and 8035 are the same company written two ways.
EXCHANGE = re.compile(r"\.(KS|T|TW|TWO|DE)$", re.I)


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


# -- a question has to reach somebody other than the company reporting -------

def _bare(ticker: str) -> str:
    return EXCHANGE.sub("", str(ticker or "")).strip().upper()


BY_TICKER = {}
for _n in NODES:
    if _n.get("ticker"):
        BY_TICKER.setdefault(_bare(_n["ticker"]), _n["id"])


def reporting_node(row) -> str | None:
    """The station the question is about, or None if it is not on the map.

    A policy date (MOFCOM), an industry body (SEMI, SPIE) and a company that
    the map does not draw have no station, so a rule about their edges cannot
    be asked of them.
    """
    return BY_TICKER.get(_bare(row.get("tk")))


def priced_neighbours(node_id: str) -> set:
    """Every priced station one edge away, in either direction.

    Direction does not matter here. The question is whether the reporting
    company is connected to anything the map can price, not which way the
    goods travel.
    """
    out = set()
    for e in EDGES:
        if e.get("from") == node_id and e.get("to") in PRICED:
            out.add(e["to"])
        if e.get("to") == node_id and e.get("from") in PRICED:
            out.add(e["from"])
    out.discard(node_id)
    return out


def test_a_connected_station_propagates_to_somebody_other_than_itself():
    """The basket is the propagation claim, so it has to leave the reporter.

    A row whose win and lose name only the company that is reporting says
    nothing the price of that company does not already say -- it is a bet on
    the stock, not a claim about the chain. The map is what makes it a claim
    about the chain, so the rule applies exactly where the map has something
    to say: a station with at least one priced neighbour.
    """
    bad = []
    for r in WATCH:
        nid = reporting_node(r)
        if nid is None or not priced_neighbours(nid):
            continue
        legs = [x for x in (list(r.get("win") or []) + list(r.get("lose") or []))
                if x != nid]
        if not legs:
            bad.append("%s (%s -> %s, %d priced neighbours) win=%s lose=%s"
                       % (r["id"], r.get("tk"), nid,
                          len(priced_neighbours(nid)),
                          r.get("win"), r.get("lose")))
    assert bad == [], ("a connected station with a self-only basket:" + chr(10)
                       + chr(10).join(bad))


def test_a_share_question_names_a_loser():
    """tide lifts the lane; share moves it from one player to another.

    So a share question with an empty lose list is not a share question -- it
    has been tagged as competitive and then written as if the whole lane won,
    which scores the same basket twice under two different claims.
    """
    bad = ["%s (%s) win=%s" % (r["id"], r.get("who"), r.get("win"))
           for r in WATCH
           if r.get("kind") == "share" and not (r.get("lose") or [])]
    assert bad == [], ("a share question with nobody on the losing side:"
                       + chr(10) + chr(10).join(bad))


def test_every_row_is_tagged_tide_or_share():
    """The tag decides which rule above applies, so an untagged row is a row
    that quietly escapes both."""
    bad = [(r["id"], r.get("kind")) for r in WATCH
           if r.get("kind") not in ("tide", "share")]
    assert bad == [], f"rows with no usable kind: {bad}"


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
