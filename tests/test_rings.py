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
               "s7", "s8", "s9", "both", "p1", "rival")]
    + [node("cash", price_symbol=None),          # nothing to price it with
       node("noticker", ticker=None),            # not a listed company
       node("none_kind", price_symbol_kind="none")],
    "subnodes": [],
    "edges": [
        edge("s1", "a"), edge("s2", "a", share="20% of a's cost"),
        edge("s3", "a"), edge("s4", "a"), edge("s5", "a"), edge("s6", "a"),
        edge("s7", "a"), edge("s8", "a"), edge("s9", "a"),
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

def test_eight_a_side_at_most():
    got = ring()
    assert len(got["win2"]) == rings.MAX_PER_SIDE == 8


def test_the_cap_is_applied_after_the_both_sides_rule():
    """Otherwise a node could survive on one side purely because its copy on
    the other side fell off the end of the list."""
    doc = copy.deepcopy(DOC)
    # "both" now sits past the cap on the win side; it must still leave both.
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


# -- order: multiplicity, then round robin, then share -----------------------
#
# A second map, with two first-ring parents that both have suppliers of their
# own. DOC above has one, which is enough for the exclusions and useless for
# the ordering.

TWO = {
    "nodes": [node(i) for i in
              ("pa", "pb", "shared", "x1", "x2", "x3", "y1", "y2")],
    "subnodes": [],
    "edges": [
        # pa's own, in map order; x1 is the only one with a NUMBER on it.
        edge("x1", "pa", share=40), edge("x2", "pa"), edge("x3", "pa"),
        edge("shared", "pa", what="shared feeds pa"),
        # pb's own; "shared" is its first, and feeds two of the first ring.
        edge("shared", "pb", what="shared feeds pb"),
        edge("y1", "pb"), edge("y2", "pb"),
    ],
}
PARENTS = ["pa", "pb"]


def two(win=None, lose=None):
    return rings.second_ring(TWO, win or PARENTS, lose or [], None)


def test_multiplicity_beats_share():
    """"shared" carries no number and is listed fourth under pa. It supplies
    two of the first ring, and that outranks a disclosed 40% to one of them --
    a name exposed to the answer twice is the point of drawing a second ring at
    all."""
    got = two()
    assert got["win2"][0] == "shared"
    assert got["win2"][1] == "x1", "share still decides among equals"


def test_a_numeric_share_orders_within_one_parent():
    """x1 is listed third in the map and has the only number on it."""
    got = rings.second_ring(TWO, ["pa"], [], None)
    assert got["win2"][0] == "x1"


def test_prose_in_the_share_field_does_not_order_anything():
    """DOC's s2 carries "20% of a's cost" -- a sentence. Reading the 20 out of
    it would be a ranking this code invented and attributed to the map."""
    assert rings.numeric_share("20% of a's cost") is None
    assert rings.numeric_share("19") == 19.0
    assert rings.numeric_share(0.4) == 0.4
    assert rings.numeric_share(None) is None
    assert rings.numeric_share(True) is None, "a flag is not a share"


def test_round_robin_gives_each_parent_its_first_pick():
    """Every parent contributes before any parent contributes twice. Without
    it the node with the most mapped inputs takes the whole ring: NVIDIA has
    seventeen suppliers in the live map and AMD has two."""
    got = two()["win2"]
    # pa's first is x1, pb's first is "shared". pa's SECOND is x2, and it comes
    # after both of them.
    assert got.index("x1") < got.index("x2")
    assert got.index("shared") < got.index("x2")
    assert got.index("y1") < got.index("x3"), "pb's second beats pa's third"


def test_one_parent_with_everything_does_not_take_the_whole_ring():
    doc = copy.deepcopy(TWO)
    doc["edges"] += [edge(f"z{n}", "pa") for n in range(8)]
    doc["nodes"] += [node(f"z{n}") for n in range(8)]
    got = rings.second_ring(doc, PARENTS, [], None)["win2"]
    assert {"y1", "y2"} <= set(got), "pb's suppliers survive pa's crowd"


def test_a_parent_that_runs_out_stops_holding_a_place():
    """pb has three and pa has four. The last slot goes to pa rather than to a
    blank."""
    got = two()["win2"]
    assert set(got) == {"shared", "x1", "x2", "x3", "y1", "y2"}


# -- one node, two lines -----------------------------------------------------

def test_a_two_parent_node_keeps_an_edge_to_each_parent():
    """The drawing needs both: one circle, two thin lines. Dropping the second
    would hide the very thing that ranked the node first."""
    edges = [e for e in two()["ring2_edges"] if e["from"] == "shared"]
    assert [e["to"] for e in edges] == ["pa", "pb"]


def test_each_of_those_edges_keeps_its_own_words():
    edges = [e for e in two()["ring2_edges"] if e["from"] == "shared"]
    assert [e["label"] for e in edges] == ["shared feeds pa", "shared feeds pb"]


def test_a_one_parent_node_still_has_exactly_one_edge():
    edges = [e for e in two()["ring2_edges"] if e["from"] == "x1"]
    assert len(edges) == 1 and edges[0]["to"] == "pa"


def test_there_are_more_edges_than_nodes_when_a_node_is_shared():
    got = two()
    assert len(got["ring2_edges"]) == len(got["win2"]) + 1


def test_every_edge_names_a_node_that_was_kept():
    """An edge to a node the cap dropped would draw a line to nothing."""
    doc = copy.deepcopy(TWO)
    doc["edges"] += [edge(f"z{n}", "pa") for n in range(8)]
    doc["nodes"] += [node(f"z{n}") for n in range(8)]
    got = rings.second_ring(doc, PARENTS, [], None)
    assert {e["from"] for e in got["ring2_edges"]} == set(got["win2"])


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
