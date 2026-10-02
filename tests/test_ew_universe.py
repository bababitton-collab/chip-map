"""EW_MAP frozen per commitment: the map can grow without moving a benchmark.

Every committed question is scored against the universe of priced nodes the
map held when its hash was recorded (chains/ew_universe.py). These tests hold
the three things that freeze promises, on the real files where it matters.
"""
from __future__ import annotations

import copy
import json

import pytest

from chains import domains, ew_universe as U, forecast, mapfile, preregister as P
from chains.paths import commitments_path, map_path, watch_path

TEXT = {"yes_en": "yes looks like", "no_en": "no looks like"}


def dummy(doc: dict) -> dict:
    """The map with one extra priced node."""
    m = copy.deepcopy(doc)
    m["nodes"].append({"id": "zz_dummy", "ticker": "ZZDUM", "price_symbol": "ZZDUM.US",
                       "price_symbol_kind": "primary"})
    return m


def committed(dom: str) -> list[dict]:
    return json.loads(commitments_path(dom).read_text(encoding="utf-8"))


# -- every committed question is frozen, and the 15 fingerprints reproduce ----
@pytest.mark.parametrize("dom", domains.discover())
def test_every_commitment_has_a_frozen_universe_matching_its_fingerprint(dom):
    assert U.problems(dom, committed(dom)) == []


def test_all_fifteen_stored_fingerprints_were_verified_from_git():
    """The fifteen fingerprints the freeze found were each reproduced from git.
    A commitment made since is recorded at --write ("commit"), from the live
    map it was made against: smsg_pre, 2026-10-02."""
    idx = {d: U.load_index(d) for d in domains.discover()}
    stored = {(d, e["qid"]) for d in idx for e in committed(d) if e.get("ew_map")}
    since = {("semi", "smsg_pre")}
    assert len(stored - since) == 15 and since <= stored
    for d, q in stored:
        assert idx[d][q]["verified"] is True, (d, q)
        assert idx[d][q]["source"] == ("commit" if (d, q) in since else "git")


# -- 1. a new priced node leaves --check green --------------------------------
@pytest.mark.parametrize("dom", ["semi", "medicine"])
def test_adding_a_dummy_priced_node_leaves_check_green(dom, monkeypatch):
    monkeypatch.setenv("CHIP_MAP_DOMAIN", dom)
    from chains import questions
    try:
        texts = questions.fetch(dom=dom)
    except Exception as e:                       # no question store here
        pytest.skip(f"questions store unavailable ({type(e).__name__})")
    rows = json.loads(watch_path(dom).read_text(encoding="utf-8"))
    grown = dummy(mapfile.load(map_path(dom)))
    got = P.check(rows, texts, committed(dom), doc=grown, today="2026-10-01")
    assert got == [], got


def test_without_the_freeze_the_same_node_would_have_tripped():
    """The control: medicine's 14 one-sided entries carry a fingerprint, and
    the live-map guard trips on exactly this change."""
    e = next(e for e in committed("medicine") if e.get("ew_map"))
    row = next(r for r in json.loads(watch_path("medicine").read_text(encoding="utf-8"))
               if r["id"] == e["qid"])
    c = P.contract(row, TEXT)
    if P.official_basket(c)[1]:
        pytest.skip("this entry is two-sided; the benchmark cancels")
    grown = dummy(mapfile.load(map_path("medicine")))
    assert P.ew_map_problems(e["qid"], e, c, grown, "2026-10-01")


# -- 2. a new commitment picks up the new node --------------------------------
def test_a_new_commitment_is_made_against_the_current_map(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIP_MAP_DATA", str(tmp_path))
    grown = dummy({"nodes": [{"id": "a", "price_symbol": "A.US",
                              "price_symbol_kind": "primary"}]})
    row = {"id": "newq", "d": "2027-01-01", "win": ["a"], "lose": [], "kind": "tide"}
    e = P.entries([row], {"newq": TEXT}, [], doc=grown)[0]
    assert "ZZDUM.US" in e["ew_map"]["symbols"]
    U.write("newq", e["ew_map"]["symbols"], "commit", None, True, dom="x")
    assert "ZZDUM.US" in U.symbols_for("newq", ["LIVE.US"], dom="x")
    assert U.problems("x", [e]) == []


# -- 3. a fingerprint mismatch is an error ------------------------------------
def test_a_frozen_universe_that_is_not_the_committed_one_is_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIP_MAP_DATA", str(tmp_path))
    U.write("q", ["A.US", "B.US"], "git", "abc", True, dom="x")
    entry = {"qid": "q", "ew_map": U.fingerprint(["A.US", "C.US"])}
    got = U.problems("x", [entry])
    assert len(got) == 1 and "is not the one committed" in got[0]


def test_a_tampered_universe_file_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIP_MAP_DATA", str(tmp_path))
    fp = U.write("q", ["A.US", "B.US"], "git", "abc", True, dom="x")
    f = tmp_path / "x" / "ew_universes" / f"{fp}.json"
    rec = json.loads(f.read_text())
    rec["symbols"].append("EXTRA.US")
    f.write_text(json.dumps(rec))
    with pytest.raises(U.UniverseError):
        U.load_universe(fp, dom="x")
    assert "unreadable" in U.problems("x", [{"qid": "q"}])[0]


def test_a_question_with_no_frozen_universe_is_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIP_MAP_DATA", str(tmp_path))
    assert "no frozen EW_MAP universe" in U.problems("x", [{"qid": "q"}])[0]


def test_the_rebuild_refuses_a_fingerprint_it_cannot_reproduce(monkeypatch):
    """The real git history, with one stored fingerprint altered in memory."""
    real = U._git

    def fake(*args):
        out = real(*args)
        if args[0] == "show" and args[1].endswith("medicine/commitments.json"):
            es = json.loads(out)
            for e in es:
                if e.get("ew_map"):
                    e["ew_map"]["sha256"] = "0" * 64
                    break
            out = json.dumps(es)
        return out
    monkeypatch.setattr(U, "_git", fake)
    with pytest.raises(U.UniverseError, match="Not frozen"):
        U.rebuild("medicine")


# -- scoring reads the frozen list --------------------------------------------
def test_the_ledger_scores_each_question_on_its_frozen_universe(monkeypatch):
    seen = {}

    def spy(f, book, cal, node_symbols, *a, **k):
        seen[f["qid"]] = list(node_symbols)
        return None
    monkeypatch.setattr(forecast, "score_one", spy)
    monkeypatch.setattr(forecast, "Book", lambda syms: None)
    monkeypatch.setattr(U, "load_index", lambda dom=None: {"frozen_q": {"fingerprint": "f"}})
    monkeypatch.setattr(U, "load_universe", lambda fp, dom=None: ["OLD.US"])
    doc = {"nodes": [{"id": "n", "price_symbol": "NEW.US", "price_symbol_kind": "primary"}]}
    fs = [{"qid": q, "win": [], "lose": [], "id": q} for q in ("frozen_q", "live_q")]
    forecast.build(fs, doc, [], cal=[])
    assert seen == {"frozen_q": ["OLD.US"], "live_q": ["NEW.US"]}
