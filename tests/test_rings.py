"""The second ring: what it includes, and everything it refuses to include.

The ring is drawn on a public page and scored in a ledger, so a wrong member is
not a cosmetic error -- it is a claim the map never made, printed with the map's
authority behind it. Every exclusion below exists because the alternative was a
sentence that would have been false.

The map here is synthetic and tiny. A test against data/semi/map.json would
pass for as long as that file happens to have the shape the rule wants, and
would stop testing the rule the moment somebody added an edge.
"""
from __future__ import annotations

import copy
import json

import pytest

from chains import rings


def node(i, **over):
    n = {"id": i, "name": i.upper(), "ticker": i.upper(),
         "price_symbol": i.upper() + ".US", "price_symbol_kind": "primary",
         "layer": "L1"}
    n.update(over)
    return n


def edge(f, t, **over):
    e = {"from": f, "to": t, "type": "supplies", "what": f"{f} supplies {t}"}
    e.update(over)
    return e


# reporter -> the company the question is about; a/b -> the registered win
# basket; c -> the registered lose basket.
DOC = {
    "nodes": [node(i) for i in
              ("reporter", "a", "b", "c", "s1", "s2", "s3", "s4", "s5", "s6",
               "s7", "both", "p1", "rival")]
    + [node("cash", price_symbol=None),          # nothing to price it with
       node("noticker", ticker=None),            # not a listed company
       node("none_kind", price_symbol_kind="none")],
    "subnodes": [],
    "edges": [
        edge("s1", "a"), edge("s2", "a", share="20% of a's cost"),
        edge("s3", "a"), edge("s4", "a"), edge("s5", "a"), edge("s6", "a"),
        edge("s7", "a"),
        edge("reporter", "a"),      # the subject of the question
        edge("b", "a"),             # already in the first ring
        edge("both", "a"), edge("both", "c"),   # no sign
        edge("cash", "a"), edge("noticker", "a"), edge("none_kind", "a"),
        edge("rival", "a", type="competes"),    # not a supply edge
        edge("p1", "c"),
        edge("a", "b"),             # outgoing from a: the wrong direction
    ],
}

WIN, LOSE = ["a", "b"], ["c"]


def ring(doc=None, win=None, lose=None, reporter="reporter"):
    return rings.second_ring(doc or DOC,
                             WIN if win is None else win,
                             LOSE if lose is None else lose, reporter)


# -- direction ---------------------------------------------------------------

def test_the_ring_is_what_the_first_ring_depends_on():
    """A map edge is supplier -> customer. The second ring is the suppliers of
    the first, not its other customers: if the first ring sells more, its
    inputs sell more. Its fellow buyers do not."""
    got = ring()
    assert "s1" in got["win2"]
    assert "b" not in got["win2"], "b is a customer of a, not a supplier"


def test_an_edge_is_stored_the_way_the_map_states_it():
    """No direction is invented here: the record still reads supplier -> the
    node it supplies, which is what map.json says."""
    e = [e for e in ring()["ring2_edges"] if e["from"] == "s1"][0]
    assert (e["from"], e["to"]) == ("s1", "a")


# -- the exclusions ----------------------------------------------------------

def test_the_reporting_company_is_not_its_own_second_ring():
    assert "reporter" not in ring()["win2"]


def test_a_first_ring_node_is_not_also_a_second_ring_node():
    """b supplies a, and b is in the win basket. It is already drawn."""
    assert "b" not in ring()["win2"] and "b" not in ring()["lose2"]


def test_a_node_reached_from_both_sides_is_dropped_from_both():
    """It supplies a winner and a loser, so it has no sign. A node drawn with
    no sign is a guess with a colour on it."""
    got = ring()
    assert "both" not in got["win2"]
    assert "both" not in got["lose2"]
    assert all(e["from"] != "both" for e in got["ring2_edges"])


@pytest.mark.parametrize("who", ["cash", "noticker", "none_kind"])
def test_a_node_the_ledger_could_not_score_is_not_a_basket_leg(who):
    """A leg with no price line is dropped silently at scoring time. Drawing it
    on the card would promise a test that never runs."""
    assert who not in ring()["win2"]


def test_only_supply_edges_count():
    """The map also carries competes/substitutes/customer_of. A competitor of a
    winner is not a second-order winner -- it is the opposite claim."""
    assert "rival" not in ring()["win2"]


def test_the_lose_side_gets_its_own_ring():
    assert ring()["lose2"] == ["p1"]


# -- the cap -----------------------------------------------------------------

def test_six_a_side_at_most():
    got = ring()
    assert len(got["win2"]) == rings.MAX_PER_SIDE == 6


def test_the_cap_is_applied_after_the_both_sides_rule():
    """Otherwise a node could survive on one side purely because its copy on
    the other side fell off the end of the list."""
    doc = copy.deepcopy(DOC)
    # Push "both" past the cap on the win side; it must still leave both sides.
    doc["edges"] = [e for e in doc["edges"] if e["from"] != "both"] + [
        edge("both", "a"), edge("both", "c")]
    got = rings.second_ring(doc, WIN, LOSE, "reporter")
    assert "both" not in got["win2"] and "both" not in got["lose2"]


# -- nothing to draw ---------------------------------------------------------

def test_a_node_with_no_incoming_edge_has_no_second_ring():
    """The upstream end of the map: ASML's own suppliers are private subnodes,
    so most equipment questions get no ring at all. Empty is the right answer
    and it is not an error."""
    got = rings.second_ring(DOC, ["s1"], [], None)
    assert got == {"win2": [], "lose2": [], "ring2_edges": []}


def test_an_empty_basket_gives_an_empty_ring():
    assert rings.second_ring(DOC, [], [], None)["win2"] == []


# -- the labels --------------------------------------------------------------

def test_a_label_is_the_edge_s_own_words_and_nothing_else():
    got = ring()
    for e in got["ring2_edges"]:
        src = [x for x in DOC["edges"]
               if x["from"] == e["from"] and x["to"] == e["to"]][0]
        assert src["what"].startswith(e["label"].rstrip("…"))


def test_a_label_is_the_first_clause_only():
    doc = copy.deepcopy(DOC)
    doc["edges"] = [edge("s1", "a", what="the thing; the evidence for it")]
    got = rings.second_ring(doc, ["a"], [], None)
    assert got["ring2_edges"][0]["label"] == "the thing"


def test_a_long_label_is_cut_not_dropped():
    doc = copy.deepcopy(DOC)
    doc["edges"] = [edge("s1", "a", what="x" * 200)]
    lab = rings.second_ring(doc, ["a"], [], None)["ring2_edges"][0]["label"]
    assert len(lab) == rings.MAX_LABEL and lab.endswith("…")


def test_an_edge_with_no_words_gets_an_empty_label_not_an_invented_one():
    doc = copy.deepcopy(DOC)
    doc["edges"] = [edge("s1", "a", what=None)]
    assert rings.second_ring(doc, ["a"], [], None)["ring2_edges"][0]["label"] == ""


# -- order -------------------------------------------------------------------

def test_a_disclosed_share_ranks_an_edge_first():
    """``share`` is a sentence out of a 10-K, not a number, so it cannot sort
    an edge -- but an edge somebody disclosed and sourced outranks one nobody
    put a number on."""
    assert ring()["win2"][0] == "s2"


def test_the_rest_keep_the_map_s_own_order():
    assert ring()["win2"][1:] == ["s1", "s3", "s4", "s5", "s6"]


# -- purity ------------------------------------------------------------------

def test_the_same_map_and_baskets_always_give_the_same_ring():
    """What makes an r2 forecast a forward test: the basket is a function of
    two committed files, so it cannot be edited after the event without a
    commit that says so."""
    assert ring() == ring()


def test_the_map_is_not_modified():
    before = json.dumps(DOC, sort_keys=True)
    ring()
    assert json.dumps(DOC, sort_keys=True) == before


def test_for_rows_attaches_the_ring_to_every_row():
    rows = [{"id": "q1", "tk": "REPORTER", "win": WIN, "lose": LOSE},
            {"id": "q2", "tk": "A", "win": ["s1"], "lose": []}]
    rings.for_rows(rows, DOC)
    assert rows[0]["win2"] and rows[0]["lose2"] == ["p1"]
    assert rows[1]["win2"] == [] and rows[1]["ring2_edges"] == []


def test_for_rows_finds_the_reporter_through_its_ticker():
    """The watch list names the company by ticker; the map keys on an id."""
    rows = [{"id": "q1", "tk": "REPORTER", "win": WIN, "lose": LOSE}]
    rings.for_rows(rows, DOC)
    assert "reporter" not in rows[0]["win2"]
