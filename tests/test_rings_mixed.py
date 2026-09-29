"""A supplier that serves both sides of a question has no direction.

The exact-node rule was already here: a node reached from the win basket and
from the lose basket leaves both. It can only fire on an edge the map records,
and the map's coverage is uneven. On mu_fq4 -- "will Micron confirm it is on
track for its 2027 HBM share target" -- Micron had ONE recorded supplier and
SK hynix and Samsung had four each, so the card drew ASML, Advantest, Applied
Materials, Hanmi and Siltronic as unambiguously "down if Micron says yes".
Every one of them sells into the memory layer. Micron is in the memory layer.

The layer rule closes that: a candidate that supplies ANY node in the same
layer as a first-ring node on the other side has no sign either. Nothing here
invents a relationship -- the layer is the map's own field.

Also here: the hard rule that a second ring already MARKED is frozen. See
tests/test_ledger_orders.py for the other half of it.
"""
from __future__ import annotations

import json

import pytest

from chains import domains, mapfile, rings
from chains.paths import map_path, out_dir, watch_path


@pytest.fixture(scope="module")
def semi():
    return json.loads(map_path("semi").read_text(encoding="utf-8"))


def registered(qid, dom="semi"):
    for r in json.loads(watch_path(dom).read_text(encoding="utf-8")):
        if r["id"] == qid:
            return r
    raise AssertionError(f"{dom}/{qid} is not in the watch list")


def ring(doc, qid, dom="semi"):
    r = registered(qid, dom)
    by_tk = {str(n.get("ticker", "")).upper(): n["id"]
             for n in doc.get("nodes", []) if n.get("ticker")}
    return rings.second_ring(doc, r.get("win") or [], r.get("lose") or [],
                             by_tk.get(str(r.get("tk") or "").upper()))


# -- the card that started this ------------------------------------------------
MU_DROPPED = ["asml", "advantest", "amat", "hanmi", "siltronic"]


def test_mu_fq4_draws_none_of_the_five_that_serve_the_memory_layer(semi):
    got = ring(semi, "mu_fq4")
    drawn = set(got["win2"]) | set(got["lose2"])
    still = sorted(set(MU_DROPPED) & drawn)
    assert still == [], f"{still} are drawn with a sign they do not have"
    # Lam Research was already cut by the exact-node rule: the map records it
    # supplying Micron AND both of the others.
    assert got["mixed"] == 6, got
    assert got["win2"] == [] and got["lose2"] == []


def test_each_of_the_five_really_does_serve_micron_s_layer(semi):
    """The rule's premise, checked against the map rather than asserted.

    None of them has a recorded edge to Micron -- that is the gap the rule
    exists for -- but every one sells into the layer Micron is in.
    """
    layers = rings.layer_of(semi)
    mu_layer = layers["mu"]
    for c in MU_DROPPED:
        serves = rings.serves_layers(semi, c, layers)
        assert mu_layer in serves, (c, sorted(serves), mu_layer)
        direct = [e for e in semi["edges"]
                  if e.get("type") == "supplies" and e.get("from") == c
                  and e.get("to") == "mu"]
        assert direct == [], (
            f"{c} now has a recorded edge to Micron; the exact-node rule "
            f"covers it and this test is about the case where it does not")


def test_amkr_q3_is_the_worst_case_and_draws_nothing(semi):
    """Amkor has no recorded supplier at all and ASE plus TSMC have fourteen,
    so every candidate came from one side. The old rule found no overlap and
    drew all of them as losers."""
    got = ring(semi, "amkr_q3")
    assert got["win2"] == [] and got["lose2"] == []
    assert got["mixed"] == 14, got


def test_intc_q3_keeps_the_ring_the_map_really_does_support(semi):
    """The rule has to be able to say yes. Intel's win basket spans three
    layers and the eight lose-side suppliers sell only into TSMC's, so they
    keep their sign."""
    got = ring(semi, "intc_q3")
    assert got["win2"] == ["ajinomoto"]
    assert len(got["lose2"]) == 8
    assert set(got["win2"]) & set(got["lose2"]) == set()
    assert got["mixed"] == 4


# -- the rule itself, in isolation ----------------------------------------------
def _doc(nodes, edges):
    return {"nodes": [{"id": i, "layer": l, "ticker": i.upper(),
                       "price_symbol": f"{i.upper()}.US",
                       "price_symbol_kind": "equity"}
                      for i, l in nodes],
            "edges": [{"from": a, "to": b, "type": "supplies"}
                      for a, b in edges]}


def test_a_supplier_of_the_other_sides_layer_has_no_sign():
    doc = _doc([("w", "L1"), ("l", "L1"), ("s", "L2")], [("s", "l")])
    got = rings.second_ring(doc, ["w"], ["l"])
    assert got["win2"] == [] and got["lose2"] == []
    assert got["mixed"] == 1


def test_a_supplier_of_a_different_layer_keeps_its_sign():
    doc = _doc([("w", "L1"), ("l", "L2"), ("s", "L3")], [("s", "l")])
    got = rings.second_ring(doc, ["w"], ["l"])
    assert got["lose2"] == ["s"] and got["mixed"] == 0


def test_the_reporters_layer_counts_as_the_win_side():
    """The reporter is the subject of the question, not a consequence of it,
    so it is not a candidate -- but its layer is the question's own side, and
    a supplier serving that layer serves the reporter.

    This is mu_fq4 in miniature: Micron is the reporter and shares the memory
    layer with both losers, so a memory-equipment supplier has no direction
    even with no recorded edge to Micron at all.
    """
    same = _doc([("rep", "L1"), ("l", "L1"), ("s", "L2")], [("s", "l")])
    got = rings.second_ring(same, [], ["l"], reporter="rep")
    assert got["lose2"] == [] and got["mixed"] == 1

    # A reporter in a different layer leaves the sign alone.
    apart = _doc([("rep", "L3"), ("l", "L1"), ("s", "L2")], [("s", "l")])
    assert rings.second_ring(apart, [], ["l"], reporter="rep")["lose2"] == ["s"]


def test_a_node_with_no_layer_is_judged_only_by_the_exact_rule():
    """The map's own field, and nothing derived from its absence."""
    doc = _doc([("w", "L1"), ("l", "L1"), ("s", "L2")], [("s", "l")])
    for n in doc["nodes"]:
        if n["id"] == "w":
            n.pop("layer")
    got = rings.second_ring(doc, ["w"], ["l"])
    assert got["lose2"] == ["s"], "no layer, no layer rule"


def test_the_count_is_every_candidate_dropped_by_either_rule():
    doc = _doc([("w", "L1"), ("l", "L1"), ("both", "L2"), ("layer", "L2")],
               [("both", "w"), ("both", "l"), ("layer", "l")])
    got = rings.second_ring(doc, ["w"], ["l"])
    assert got["mixed"] == 2 and got["win2"] == [] and got["lose2"] == []


# -- the build-time warning -----------------------------------------------------
def test_a_one_sided_map_is_a_warning_and_never_a_failure(semi):
    rows = [dict(registered(q)) for q in ("amkr_q3", "mu_fq4", "intc_q3")]
    for r in rows:
        r["id"] = r["id"]
    got = rings.warnings_for(rows, semi)
    assert len(got) == 1 and got[0].startswith("amkr_q3:"), got
    assert "no recorded supplier" in got[0] and "14" in got[0]


def test_the_warning_needs_a_real_imbalance_not_just_a_thin_map():
    doc = _doc([("w", "L1"), ("l", "L2"), ("a", "L3"), ("b", "L3")],
               [("a", "l"), ("b", "l")])
    rows = [{"id": "q", "win": ["w"], "lose": ["l"]}]
    assert rings.warnings_for(rows, doc) == [], "two is under the threshold"
    doc["edges"].append({"from": "a", "to": "l", "type": "supplies"})
    assert len(rings.warnings_for(rows, doc)) == 1


def test_every_published_map_is_checked_not_only_semi():
    """The warning is computed per map, so a second industry with a thin side
    reports it too rather than silently drawing one."""
    seen = []
    for dom in domains.discover():
        p = out_dir(dom) / "live_en.json"
        if not p.exists():
            continue
        doc = mapfile.load(dom=dom)
        watch = json.loads(watch_path(dom).read_text(encoding="utf-8"))
        seen.append((dom, rings.warnings_for(watch, doc)))
    assert seen, "no map is built; run python -m chains.live_snapshot"
    flat = [w for _d, ws in seen for w in ws]
    assert all(": the " in w for w in flat), flat
