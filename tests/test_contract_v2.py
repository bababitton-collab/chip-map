"""Contract v2: the second ring is the basket that is scored.

WHY THERE IS A V2 AT ALL
------------------------
The first ring -- the reporter and its direct rivals -- reprices on the report
day itself. A forecast scored on it is largely a summary of a move that has
already happened by the time the entry is taken. The second ring, the
suppliers and customers standing behind those companies, reacts with a lag,
and that lag is the only part of this that is a forecast.

So a v2 question registers its OWN second-ring basket, by hand, in advance,
and the official score reads that basket. It is NOT the ring chains/rings.py
draws: that one is derived from whatever supply edges the map happens to
record, and a drawing derived after the fact is not a claim anybody made
before the fact.

WHAT THESE TESTS HOLD
---------------------
1. Every v1 hash already published is byte-for-byte unmoved. This is the
   whole credibility of the record and it is checked against the real
   commitments file, not a fixture.
2. A v2 basket cannot be registered unless it can actually be scored.
3. The reader's browser verifies a v2 contract exactly as it verifies a v1.
"""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from chains import liquidity, mapfile, preregister as P, questions
from chains.paths import commitments_path, watch_path

TEXT = {"yes_en": "Share target reaffirmed.", "no_en": "Target softened."}

_TEXTS: dict | None = None


def texts():
    """The published yes/no wording, fetched once.

    It lives behind QUESTIONS_URL, which CI does not have and a flaky link can
    drop. Every test that needs it skips rather than failing: a network
    timeout is not a contract that moved.
    """
    global _TEXTS
    if _TEXTS is None:
        try:
            _TEXTS = questions.fetch()
        except Exception as e:                  # no store in this checkout
            pytest.skip(f"questions store unavailable ({type(e).__name__})")
    return _TEXTS


def v1_row(**over):
    r = {"id": "q", "d": "2026-12-01", "win": ["mu"], "lose": ["samsung"],
         "kind": "share"}
    r.update(over)
    return r


def v2_row(**over):
    r = v1_row()
    r.update({"ring2_win": ["tel"], "ring2_lose": ["advantest"],
              "ring2_rationale": {"win": "Equipment into the winner.",
                                  "lose": "Tester into the loser."}})
    r.update(over)
    return r


DOC = {"nodes": [{"id": i, "ticker": i.upper(), "price_symbol": f"{i.upper()}.US",
                  "price_symbol_kind": "equity"}
                 for i in ("mu", "samsung", "tel", "advantest", "shinetsu")]
       + [{"id": "private", "ticker": "n/a", "price_symbol": None,
           "price_symbol_kind": "none"}],
       "subnodes": [], "edges": []}


# -- 1. v1 is frozen ----------------------------------------------------------
def test_a_row_with_no_second_ring_has_exactly_the_eleven_v1_fields():
    c = P.contract(v1_row(), TEXT)
    assert set(c) == set(P.CONTRACT_FIELDS)
    assert "contract_version" not in c, (
        "a version number on a v1 contract would move every hash ever "
        "published, which is the one thing this file may never do")


def test_adding_and_removing_a_second_ring_returns_the_identical_bytes():
    """The v2 fields are appended, never woven in. Take them away and the
    bytes are the bytes that were hashed before v2 existed."""
    base = P.canonical(v1_row(), TEXT)
    assert P.canonical(v2_row(), TEXT) != base
    stripped = {k: v for k, v in v2_row().items()
                if k not in (P.RING2_WIN, P.RING2_LOSE, P.RING2_RATIONALE)}
    assert P.canonical(stripped, TEXT) == base


V1_GOLD = "1caadaa2e0db4f1eee653bc7ee25db5b87a4c73c2e5e95e89131c8e51739690b"


def test_the_published_v1_hashes_have_not_moved():
    """The real file, not a fixture. Exactly one question on the semi map is
    v2; every other committed contract must still hash to the value beside it.

    This is the test that would catch a v2 change leaking into v1. If it ever
    fails, the published record has been invalidated and no amount of fixing
    the test afterwards puts it back.
    """
    rows = json.loads(watch_path("semi").read_text(encoding="utf-8"))
    store = texts()
    prior = {e["qid"]: e for e in
             json.loads(commitments_path("semi").read_text(encoding="utf-8"))}
    moved, v2 = [], []
    for r in rows:
        qid = r["id"]
        if P.is_v2(r):
            v2.append(qid)
            continue
        old = prior.get(qid, {}).get("sha256")
        if old and old != P.commitment(r, (store or {}).get(qid))["sha256"]:
            moved.append(qid)
    assert moved == [], f"v1 contracts moved: {moved}"
    # mu_fq4 (2026-09-29), then smsg_pre, the first wave (2026-10-02).
    assert sorted(v2) == ["mu_fq4", "smsg_pre"], v2


def test_the_v1_bytes_of_mu_fq4_are_still_reachable_and_still_hash_the_same():
    """mu_fq4's own v1 hash, pinned. It is in the file's history block after
    the re-commit, and a reader checking that history has to be able to get
    the same value out of this code."""
    rows = json.loads(watch_path("semi").read_text(encoding="utf-8"))
    row = next(r for r in rows if r["id"] == "mu_fq4")
    v1 = {k: v for k, v in row.items()
          if k not in (P.RING2_WIN, P.RING2_LOSE, P.RING2_RATIONALE)}
    assert P.digest(v1, texts().get("mu_fq4")) == V1_GOLD


# -- 2. what a v2 contract carries -------------------------------------------
def test_a_v2_contract_is_v1_plus_five_named_fields():
    c = P.contract(v2_row(), TEXT)
    assert set(c) == set(P.CONTRACT_FIELDS_V2)
    assert set(c) - set(P.CONTRACT_FIELDS) == {
        "contract_version", "official_basket", "ring2_win", "ring2_lose",
        "ring2_rationale"}
    assert c["contract_version"] == 2
    assert c["official_basket"] == "ring2"


def test_the_scored_basket_is_the_second_ring_and_the_first_stays_in_the_bytes():
    """The first ring is not deleted by v2. It is still hashed, because it is
    still minted -- as a diagnostic -- and a diagnostic read off a basket that
    was not fixed in advance is worth nothing."""
    c = P.contract(v2_row(), TEXT)
    assert c["win"] == ["mu"] and c["lose"] == ["samsung"]
    assert P.official_basket(c) == (["tel"], ["advantest"])


def test_a_v1_contract_is_scored_on_its_first_ring():
    assert P.official_basket(P.contract(v1_row(), TEXT)) == (["mu"], ["samsung"])


def test_the_second_ring_is_sorted_like_the_first():
    """The hash cannot depend on the order somebody typed the names in."""
    a = P.contract(v2_row(ring2_win=["tel", "shinetsu"]), TEXT)
    b = P.contract(v2_row(ring2_win=["shinetsu", "tel"]), TEXT)
    assert a == b and a["ring2_win"] == ["shinetsu", "tel"]


def test_the_rationale_is_one_line_per_registered_side():
    c = P.contract(v2_row(), TEXT)
    assert set(c["ring2_rationale"]) == {"win", "lose"}
    one = P.contract(v2_row(ring2_lose=[],
                            ring2_rationale={"win": "Only one side."}), TEXT)
    assert set(one["ring2_rationale"]) == {"win"}


def test_whitespace_in_a_rationale_cannot_change_the_hash_silently():
    a = P.contract(v2_row(), TEXT)
    messy = v2_row()
    messy["ring2_rationale"] = {k: f"  {v}\n " for k, v
                                in messy["ring2_rationale"].items()}
    assert P.contract(messy, TEXT) == a


# -- 3. a basket that cannot be scored is not registered ----------------------
def test_an_unpriced_leg_is_refused():
    got = P.ring2_problems(v2_row(ring2_win=["private"]), DOC)
    assert got and "cannot be priced" in got[0]


def test_a_leg_already_in_the_first_ring_is_refused():
    got = P.ring2_problems(v2_row(ring2_win=["mu"]), DOC)
    assert got and "in the first ring" in got[0]
    assert P.ring2_problems(v2_row(ring2_lose=["samsung"]), DOC)


def test_a_leg_on_both_second_ring_sides_is_refused():
    got = P.ring2_problems(v2_row(ring2_win=["tel"], ring2_lose=["tel"]), DOC)
    assert got and "both second-ring sides" in got[0]


def test_one_empty_side_is_allowed_and_two_is_not():
    assert P.ring2_problems(
        v2_row(ring2_lose=[], ring2_rationale={"win": "One side."}), DOC) == []
    # Both empty is not a v2 question at all -- is_v2 is false and the row
    # hashes as v1, which is the honest reading of "registered nothing".
    none = v2_row(ring2_win=[], ring2_lose=[], ring2_rationale={})
    assert not P.is_v2(none)
    assert set(P.contract(none, TEXT)) == set(P.CONTRACT_FIELDS)


def test_a_registered_side_with_no_rationale_is_refused():
    with pytest.raises(P.PreregisterError, match="no rationale"):
        P.contract(v2_row(ring2_rationale={"win": "Only the win side."}), TEXT)


def test_a_rationale_for_a_side_that_was_not_registered_is_refused():
    with pytest.raises(P.PreregisterError, match="rationale with no"):
        P.contract(v2_row(ring2_lose=[]), TEXT)


def test_contract_itself_refuses_a_shape_it_would_otherwise_hash():
    """The map-free rules are enforced where the bytes are built, so an
    invalid basket can never reach a hash even through a caller that skipped
    ring2_problems."""
    with pytest.raises(P.PreregisterError, match="in the first ring"):
        P.contract(v2_row(ring2_win=["mu"]), TEXT)


def test_check_reports_a_bad_basket_rather_than_raising(tmp_path):
    rows = [v2_row(id="q", ring2_win=["private"])]
    got = P.check(rows, {"q": TEXT}, [], doc=DOC, today="2026-01-01")
    assert any("cannot be priced" in p for p in got)


def test_entries_refuses_to_write_a_basket_that_cannot_be_scored():
    with pytest.raises(P.PreregisterError, match="cannot be priced"):
        P.entries([v2_row(id="q", ring2_win=["private"])], {"q": TEXT}, [],
                  today=__import__("datetime").date(2026, 1, 1), doc=DOC)


# -- 4. the gate, the guard, the paywall --------------------------------------
def test_every_scored_leg_has_to_trade():
    """The second ring is the basket that is scored, so it clears the same
    liquidity gate the first ring does. A scored leg that does not trade is
    the exact failure this gate exists to stop."""
    legs = liquidity.legs_of(v2_row())
    assert legs == ["mu", "samsung", "tel", "advantest"]
    assert liquidity.legs_of(v1_row()) == ["mu", "samsung"]
    assert liquidity.legs_of(v2_row(observe_only=True)) == []


def test_a_leg_in_both_rings_is_measured_once():
    r = v2_row()
    r["ring2_win"] = ["tel"]
    r["win"] = ["mu", "tel"]
    assert liquidity.legs_of(r).count("tel") == 1


def test_the_ew_map_guard_asks_the_scored_basket_not_the_first_ring():
    """A v2 question with a two-sided first ring and a one-sided SCORED
    basket is exposed to EW_MAP exactly as a one-sided v1 question is.
    Asking ``lose`` would wave it through."""
    doc = dict(DOC)
    c = P.contract(v2_row(ring2_lose=[],
                          ring2_rationale={"win": "One side."}), TEXT)
    entry = {"qid": "q", "answer_date": "2099-01-01",
             "committed_at": "2026-01-01",
             "ew_map": P.ew_map_fingerprint(doc)}
    assert P.ew_map_problems("q", entry, c, doc, "2026-01-02") == []
    moved = {**doc, "nodes": doc["nodes"] + [
        {"id": "new", "ticker": "NEW", "price_symbol": "NEW.US",
         "price_symbol_kind": "equity"}]}
    got = P.ew_map_problems("q", entry, c, moved, "2026-01-02")
    assert got and "NEW.US" in got[0]
    # And the two-sided scored basket still cancels.
    both = P.contract(v2_row(), TEXT)
    assert P.ew_map_problems("q", entry, both, moved, "2026-01-02") == []


def test_a_locked_row_publishes_neither_ring():
    """The contract bytes stay paid until the answer is in. Shipping the
    scored basket on a locked card would hand over the half of the contract
    the paywall is holding while the hash sits unopened."""
    from chains import live_snapshot
    strip = set(live_snapshot.LOCKED_STRIP)
    assert {"ring2_win", "ring2_lose", "ring2_rationale"} <= strip
    assert {"win", "lose", "win2", "lose2", "mixed"} <= strip

    row = {"id": "q", "locked": True, "win": ["mu"], "lose": ["samsung"],
           "ring2_win": ["tel"], "ring2_lose": ["advantest"],
           "ring2_rationale": {"win": "x"}, "who": "Q", "d": "2026-12-01"}
    for k in live_snapshot.LOCKED_STRIP:
        row.pop(k, None)
    assert sorted(row) == ["d", "id", "locked", "who"]


# -- 5. mu_fq4, the first question committed under v2 -------------------------
def test_mu_fq4_registers_a_scored_second_ring_that_can_be_scored():
    rows = json.loads(watch_path("semi").read_text(encoding="utf-8"))
    row = next(r for r in rows if r["id"] == "mu_fq4")
    doc = mapfile.load(dom="semi")
    assert P.is_v2(row)
    assert P.ring2_problems(row, doc) == []
    c = P.contract(row, texts().get("mu_fq4"))
    assert P.official_basket(c) == (
        ["globalwafers", "shinetsu", "tel"], ["advantest"])
    assert c["win"] == ["mu"] and c["lose"] == ["samsung", "skhynix"]
    priced = {n["id"] for n in doc["nodes"]
              if n.get("ticker") and n.get("price_symbol")
              and n.get("price_symbol_kind") != "none"}
    assert set(sum(P.official_basket(c), [])) <= priced


def test_mu_fq4_is_committed_before_its_answer_date():
    """It is re-committed on 2026-09-29 for an answer on 2026-09-30. A
    contract changed on or after its answer date is not a preregistration and
    the file must go on saying so."""
    e = next(x for x in json.loads(
        commitments_path("semi").read_text(encoding="utf-8"))
        if x["qid"] == "mu_fq4")
    assert e["committed_at"] < e["answer_date"]
    assert e["valid_preregistration"] is True
    assert e["revised_at"] == e["committed_at"]
    assert "second-ring basket" in e["revision_note"]
    assert [h["sha256"] for h in e["history"]] == [V1_GOLD], (
        "the hash v2 replaced stays in the file; a published hash is not "
        "withdrawn by replacing it")


# -- 6. the reader's own browser ----------------------------------------------
def cards_source():
    from chains.paths import templates_dir
    return (templates_dir() / "track-cards.js").read_text(encoding="utf-8")


@pytest.mark.parametrize("row", [v1_row(), v2_row()],
                         ids=["v1", "v2"])
def test_the_browser_recomputes_either_version_of_the_hash(row, tmp_path):
    """Same control, same bytes, both versions. The v2 fields are inside the
    hashed contract, so a browser that verifies v1 verifies v2 -- this proves
    it rather than assuming it, over the real renderer."""
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    contract = P.canonical(row, TEXT).decode("utf-8")
    sha = P.digest(row, TEXT)
    payload = {"as_of": "2026-10-01", "summary": {}, "forecasts": [{
        "qid": "q", "who": "Q", "state": "reported", "status": "yes",
        "d": "2026-12-01", "report_date": "2026-12-01", "members": [],
        "prereg": {"sha256": sha, "committed_at": "2026-09-29",
                   "answer_date": "2026-12-01", "valid_preregistration": True,
                   "primary_horizon": 20, "contract": contract}}]}
    js = tmp_path / "verify2.js"
    js.write_text(
        "globalThis.window = {};\n" + cards_source() + "\n"
        "const root = {};\n"
        f"window.renderTrack(root, {json.dumps(payload)});\n"
        "const html = root.innerHTML;\n"
        "const un = s => s.replace(/&quot;/g,'\"').replace(/&lt;/g,'<')"
        ".replace(/&gt;/g,'>').replace(/&amp;/g,'&');\n"
        "const m = html.match(/data-sha=\"([^\"]*)\"[\\s\\S]*?"
        "data-contract=\"([^\"]*)\"/);\n"
        "(async () => {\n"
        "  const r = await window.verifyPrereg(un(m[2]), m[1], true, 'c', 'a');\n"
        "  process.stdout.write(JSON.stringify(\n"
        "    {state: r.state, hex: r.hex, contract: un(m[2])}));\n"
        "})();\n", encoding="utf-8")
    got = json.loads(subprocess.run(["node", str(js)], capture_output=True,
                                    check=True).stdout.decode("utf-8"))
    assert got["contract"] == contract, "revealed bytes == hashed bytes"
    assert got["hex"] == sha, "the browser and the build agree"
    assert got["state"] == "verified"


def test_the_v2_contract_the_browser_sees_names_the_scored_basket():
    """A reader opening the bytes must be able to see WHICH basket was scored
    and why, without being told. Both are in the contract, so both are in the
    bytes the page reveals."""
    text = P.canonical(v2_row(), TEXT).decode("utf-8")
    assert '"contract_version":2' in text
    assert '"official_basket":"ring2"' in text
    assert '"ring2_win":["tel"]' in text
    assert "Tester into the loser." in text
