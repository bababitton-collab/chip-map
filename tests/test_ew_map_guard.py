"""The guard on the benchmark moving under a question already committed.

EW_MAP is the equal-weight of the map's priced nodes, and the contract names
it as a string -- "equal-weight of the map's priced nodes" -- which stays
true whatever the map contains. So a node added to a map moves the benchmark
under every question already committed against it, silently, and the
published record still verifies.

It only matters for a question with no lose basket. With both sides present
the benchmark cancels algebraically and the excess is win minus lose.
"""
from __future__ import annotations

import json

import pytest

from chains import domains, preregister as P
from chains.paths import map_path

TODAY = "2026-09-25"
AHEAD = "2026-12-31"
PAST = "2026-01-31"


def doc(*symbols: str) -> dict:
    return {"nodes": [{"id": s.split(".")[0].lower(), "price_symbol": s,
                       "price_symbol_kind": "primary"} for s in symbols]}


def row(qid="q", lose=None, d=AHEAD) -> dict:
    return {"id": qid, "d": d, "win": ["a"], "lose": lose or [],
            "kind": "share" if lose else "tide"}


TEXT = {"q_en": "Q?", "yes_en": "yes looks like", "no_en": "no looks like"}


def entry_for(m: dict, d=AHEAD, lose=None) -> dict:
    """One committed entry carrying the fingerprint of ``m``."""
    got = P.entries([row(lose=lose, d=d)], {"q": TEXT}, [], doc=m)
    return got[0]


# -- the fingerprint itself ----------------------------------------------------
def test_the_fingerprint_reads_the_same_nodes_the_ledger_does():
    """Nodes only, priced only, and 'none' excluded -- the forecast test."""
    m = {"nodes": [
        {"id": "a", "price_symbol": "A.US", "price_symbol_kind": "primary"},
        {"id": "b", "price_symbol": "B.US", "price_symbol_kind": "none"},
        {"id": "c", "price_symbol": None},
        {"id": "d", "price_symbol": "D.US", "price_symbol_kind": "adr"}],
        "subnodes": [{"id": "e", "price_symbol": "E.US",
                      "price_symbol_kind": "primary"}]}
    assert P.priced_symbols(m) == ["A.US", "D.US"], (
        "an unpriced node, a 'none' node and a subnode are all out")


def test_the_fingerprint_does_not_depend_on_map_order():
    assert (P.ew_map_fingerprint(doc("B.US", "A.US"))["sha256"]
            == P.ew_map_fingerprint(doc("A.US", "B.US"))["sha256"])


def test_the_fingerprint_carries_the_members_not_just_the_hash():
    """A build log that says "the map changed" is not actionable."""
    fp = P.ew_map_fingerprint(doc("A.US", "B.US"))
    assert fp["n"] == 2 and fp["symbols"] == ["A.US", "B.US"]


# -- what trips it -------------------------------------------------------------
def test_adding_a_priced_node_trips_an_open_tide_entry():
    m = doc("A.US", "B.US")
    e = entry_for(m)
    problems = P.ew_map_problems("q", e, P.contract(row(), TEXT),
                                 doc("A.US", "B.US", "C.US"), TODAY)
    assert problems, "the benchmark moved and nothing said so"
    assert "added C.US" in problems[0]
    assert "no lose basket" in problems[0]


def test_removing_a_priced_node_trips_it_too():
    e = entry_for(doc("A.US", "B.US"))
    problems = P.ew_map_problems("q", e, P.contract(row(), TEXT),
                                 doc("A.US"), TODAY)
    assert "removed B.US" in problems[0]


def test_the_message_names_both_sides_of_the_change():
    e = entry_for(doc("A.US", "B.US"))
    problems = P.ew_map_problems("q", e, P.contract(row(), TEXT),
                                 doc("A.US", "C.US"), TODAY)
    assert "added C.US" in problems[0] and "removed B.US" in problems[0]


def test_an_unchanged_map_is_silent():
    m = doc("A.US", "B.US")
    assert P.ew_map_problems("q", entry_for(m), P.contract(row(), TEXT),
                             m, TODAY) == []


# -- what does NOT trip it -----------------------------------------------------
def test_a_share_question_is_immune_because_the_benchmark_cancels():
    """(win - EW_MAP) - (lose - EW_MAP) is win - lose. The map cannot reach it."""
    e = entry_for(doc("A.US", "B.US"), lose=["b"])
    assert P.ew_map_problems("q", e, P.contract(row(lose=["b"]), TEXT),
                             doc("A.US", "B.US", "C.US"), TODAY) == []


def test_a_question_whose_answer_date_has_passed_is_not_reopened():
    """It was already scored on whatever the map was. Not this gate's job."""
    e = entry_for(doc("A.US", "B.US"), d=PAST)
    e["answer_date"] = PAST
    assert P.ew_map_problems("q", e, P.contract(row(d=PAST), TEXT),
                             doc("A.US", "B.US", "C.US"), TODAY) == []


def test_an_entry_written_before_the_guard_is_skipped():
    """The 78 commitments that predate this carry no fingerprint."""
    e = entry_for(doc("A.US", "B.US"))
    del e["ew_map"]
    assert P.ew_map_problems("q", e, P.contract(row(), TEXT),
                             doc("Z.US"), TODAY) == []


# -- the entry envelope --------------------------------------------------------
def test_the_new_group_is_a_legal_entry_shape():
    e = entry_for(doc("A.US"))
    assert tuple(e) in P.ENTRY_SHAPES
    assert "ew_map" in e


def test_every_existing_shape_is_still_legal():
    """A file written before either optional group must still validate."""
    base = P.ENTRY_FIELDS
    for shape in (base, base + P.REVISION_FIELDS, base + P.LIQUIDITY_FIELDS,
                  base + P.REVISION_FIELDS + P.LIQUIDITY_FIELDS):
        assert shape in P.ENTRY_SHAPES


def test_the_fingerprint_is_not_in_the_contract():
    """The whole reason it sits on the entry. If it reached contract() every
    hash already published would break on the next --check."""
    c = P.contract(row(), TEXT)
    assert "ew_map" not in c and "ew_map" not in json.dumps(c)
    assert set(c) == set(P.CONTRACT_FIELDS)


# -- the live files ------------------------------------------------------------
def test_no_committed_hash_moved_when_the_guard_landed(monkeypatch):
    """Recompute every published contract and compare. 78 of them.

    monkeypatch, not os.environ: setting CHIP_MAP_DOMAIN by hand and leaving
    it set makes every test after this one read another domain's data. That
    is not hypothetical -- it is how this file first ran, and it broke
    fifty-five unrelated tests.
    """
    from chains import questions

    n = 0
    for dom in domains.discover():
        monkeypatch.setenv("CHIP_MAP_DOMAIN", dom)
        rows = {r["id"]: r for r in json.loads(
            (map_path(dom=dom).parent / "watch_en.json").read_text("utf-8"))}
        com = json.loads((map_path(dom=dom).parent
                          / "commitments.json").read_text("utf-8"))
        try:
            texts = questions.fetch(dom=dom)
        except Exception:                       # no store in this checkout
            pytest.skip("questions store unavailable")
        for e in com:
            r = rows.get(e["qid"])
            if r is None:
                continue
            assert P.digest(r, texts[e["qid"]]) == e["sha256"], (
                f"{dom}:{e['qid']} hash moved")
            n += 1
    assert n >= 78, f"expected at least 78 published contracts, checked {n}"
