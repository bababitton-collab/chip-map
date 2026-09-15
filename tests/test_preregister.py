"""Public pre-registration: the contract, its hash, and the dates beside it.

What is pinned here is the property a stranger relies on: the same question
always hashes the same way, any change to what it is scored under changes the
hash, and the day a commitment was made cannot be rewritten by a later build.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re

import pytest

from chains import answers, preregister as P
from chains.paths import commitments_path, watch_path

ROW = {"id": "mu_fq4", "d": "2026-09-30", "confirmed": True, "who": "Micron",
       "tk": "MU", "cps": ["CP5"], "win": ["skhynix", "mu"],
       "lose": ["samsung"], "leaks": [], "lane": "hbm", "lbl": "Micron",
       "kind": "share"}
TEXT = {"yes_en": "Guidance raised above the prior range — “HBM sold out”.",
        "no_en": "Guidance <held> & unchanged.", "q_en": "Q", "why_en": "W"}
DAY = dt.date(2026, 9, 13)


# -- the contract -------------------------------------------------------------

def test_the_contract_has_exactly_the_agreed_fields():
    assert set(P.contract(ROW, TEXT)) == {
        "qid", "win", "lose", "kind", "yes_criteria", "no_criteria",
        "horizons", "primary_horizon", "benchmarks", "sign_convention",
        "observe_only"}
    assert set(P.CONTRACT_FIELDS) == set(P.contract(ROW, TEXT))


def test_the_contract_carries_the_frozen_constants():
    c = P.contract(ROW, TEXT)
    assert c["horizons"] == [5, 10, 20, 40]
    assert c["primary_horizon"] == 20
    assert c["benchmarks"] == {
        "ew": "EW_MAP: equal-weight of the map's priced nodes",
        "sox": "SOXQ.US"}
    assert c["sign_convention"] == (
        "yes -> win basket up / lose basket down; no -> inverted")
    assert c["win"] == ["mu", "skhynix"], "sorted"
    assert c["observe_only"] is False


def test_the_primary_horizon_is_frozen_at_twenty_and_is_a_real_horizon():
    assert answers.PRIMARY_HORIZON == 20
    assert answers.PRIMARY_HORIZON in answers.HORIZONS
    assert answers.PRIMARY_HORIZON in answers.HORIZONS_R2


def test_the_bytes_are_the_canonical_serialisation():
    b = P.canonical(ROW, TEXT)
    assert b == json.dumps(P.contract(ROW, TEXT), sort_keys=True,
                           separators=(",", ":"),
                           ensure_ascii=False).encode("utf-8")
    # Compact separators between structure; string values keep their own
    # punctuation, so the check is on keys and lists, not on every ", ".
    assert b.startswith(b'{"benchmarks":{"ew":"EW_MAP: ')
    assert b'"horizons":[5,10,20,40],"kind":"share",' in b
    assert b'"lose":["samsung"],"no_criteria":' in b
    assert "“HBM sold out”".encode("utf-8") in b, "not ascii-escaped"


def test_a_contract_with_no_yes_rule_is_refused():
    with pytest.raises(P.PreregisterError):
        P.contract(ROW, {"no_en": "x"})


# -- the hash: stable ---------------------------------------------------------

def test_the_same_row_always_yields_the_same_hash():
    assert P.digest(ROW, TEXT) == P.digest(ROW, TEXT)
    shuffled = dict(reversed(list(ROW.items())))
    shuffled["win"] = list(reversed(ROW["win"]))
    assert P.digest(shuffled, TEXT) == P.digest(ROW, TEXT)
    assert P.digest(ROW, {"yes_en": "  " + TEXT["yes_en"] + "\n",
                          "no_en": TEXT["no_en"]}) == P.digest(ROW, TEXT)


@pytest.mark.parametrize("field,value", [
    ("who", "Micron Technology"), ("lbl", "MU"), ("tk", "MU.US"),
    ("d", "2026-10-01"), ("leaks", ["smsg_pre"]), ("lane", "fab"),
    ("confirmed", False)])
def test_prose_and_dates_outside_the_contract_do_not_move_the_hash(field,
                                                                   value):
    assert P.digest(dict(ROW, **{field: value}), TEXT) == P.digest(ROW, TEXT)


def test_commitment_is_the_sha256_of_the_canonical_bytes():
    c = P.commitment(ROW, TEXT)
    b = P.canonical(ROW, TEXT)
    assert c == {"qid": "mu_fq4", "sha256": hashlib.sha256(b).hexdigest(),
                 "contract_bytes_len": len(b)}


# -- the hash: sensitive ------------------------------------------------------

@pytest.mark.parametrize("name,row,text", [
    ("win", dict(ROW, win=["mu", "skhynix", "tsmc"]), TEXT),
    ("lose", dict(ROW, lose=[]), TEXT),
    ("kind", dict(ROW, kind="tide"), TEXT),
    ("yes_criteria", ROW, dict(TEXT, yes_en="Guidance raised.")),
    ("no_criteria", ROW, dict(TEXT, no_en="Guidance cut.")),
    ("observe_only", dict(ROW, observe_only=True), TEXT),
    ("qid", dict(ROW, id="mu_fq1"), TEXT),
])
def test_changing_any_row_field_of_the_contract_changes_the_hash(name, row,
                                                                 text):
    assert P.digest(row, text) != P.digest(ROW, TEXT), name


@pytest.mark.parametrize("attr,value", [
    ("PRIMARY_HORIZON", 10),
    ("CONTRACT_HORIZONS", (5, 10, 20)),
    ("BENCHMARKS", {"ew": "EW_MAP: equal-weight of the map's priced nodes",
                    "sox": "SOXX.US"}),
    ("SIGN_CONVENTION", "yes -> win basket down"),
])
def test_changing_any_frozen_term_changes_the_hash(attr, value, monkeypatch):
    before = P.digest(ROW, TEXT)
    monkeypatch.setattr(P, attr, value)
    assert P.digest(ROW, TEXT) != before, attr


# -- the entries --------------------------------------------------------------

def _rows():
    oracle = dict(ROW, id="orcl_q1", d="2026-09-10", win=["nvda"], lose=[],
                  kind="tide")
    return [oracle, ROW], {"orcl_q1": TEXT, "mu_fq4": TEXT}


def test_a_new_question_is_committed_today_and_validity_follows_the_dates():
    rows, texts = _rows()
    got = {e["qid"]: e for e in P.entries(rows, texts, [], DAY)}
    assert list(got["mu_fq4"]) == list(P.ENTRY_FIELDS)
    assert got["mu_fq4"]["committed_at"] == "2026-09-13"
    assert got["mu_fq4"]["valid_preregistration"] is True
    assert got["mu_fq4"]["primary_horizon"] == 20
    assert got["orcl_q1"]["committed_at"] == "2026-09-13"
    assert got["orcl_q1"]["valid_preregistration"] is False, (
        "answered 2026-09-10, committed after: honest, and not valid")


def test_committed_on_the_answer_date_itself_is_not_valid():
    got = P.entries([dict(ROW, d="2026-09-13")], {"mu_fq4": TEXT}, [], DAY)
    assert got[0]["valid_preregistration"] is False


def test_a_committed_date_is_never_moved_by_a_later_build(tmp_path):
    rows, texts = _rows()
    path = tmp_path / "commitments.json"
    P.dump(P.entries(rows, texts, [], dt.date(2026, 9, 13)), path)
    first = path.read_bytes()
    for later in (dt.date(2026, 9, 20), dt.date(2026, 12, 1)):
        P.dump(P.entries(rows, texts, P.load(path), later), path)
        assert path.read_bytes() == first


def test_a_prior_commitment_keeps_its_date():
    prior = [{"qid": "mu_fq4", "answer_date": "2026-09-30",
              "committed_at": "2026-09-01",
              "sha256": P.digest(ROW, TEXT), "primary_horizon": 20,
              "valid_preregistration": True}]
    got = P.entries([ROW], {"mu_fq4": TEXT}, prior, DAY)
    assert got[0]["committed_at"] == "2026-09-01"


def test_a_changed_contract_is_refused_rather_than_kept_under_the_old_date():
    prior = P.entries([ROW], {"mu_fq4": TEXT}, [], dt.date(2026, 9, 1))
    moved = dict(ROW, lose=[])
    with pytest.raises(P.PreregisterError, match="no longer hashes"):
        P.entries([moved], {"mu_fq4": TEXT}, prior, DAY)


def test_a_changed_contract_can_be_recommitted_only_before_its_answer():
    prior = P.entries([ROW], {"mu_fq4": TEXT}, [], dt.date(2026, 9, 1))
    moved = dict(ROW, lose=[])
    got = P.entries([moved], {"mu_fq4": TEXT}, prior, DAY,
                    recommit={"mu_fq4"}, note="loser removed")
    assert got[0]["committed_at"] == "2026-09-13"
    assert got[0]["sha256"] == P.digest(moved, TEXT)
    with pytest.raises(P.PreregisterError, match="answer date"):
        P.entries([moved], {"mu_fq4": TEXT}, prior, dt.date(2026, 9, 30),
                  recommit={"mu_fq4"}, note="loser removed")


def test_a_recommit_after_the_answer_date_is_refused_and_nothing_moves(
        tmp_path):
    """The day after the answer, with --recommit and a note: refused, and the
    file keeps the hash and the date it had."""
    path = tmp_path / "commitments.json"
    P.dump(P.entries([ROW], {"mu_fq4": TEXT}, [], dt.date(2026, 9, 1)), path)
    first = path.read_bytes()
    moved = dict(ROW, lose=[])
    with pytest.raises(P.PreregisterError, match="cannot re-commit"):
        P.dump(P.entries([moved], {"mu_fq4": TEXT}, P.load(path),
                         dt.date(2026, 10, 1), recommit={"mu_fq4"},
                         note="loser removed"), path)
    assert path.read_bytes() == first


def test_a_recommit_without_a_note_is_refused():
    prior = P.entries([ROW], {"mu_fq4": TEXT}, [], dt.date(2026, 9, 1))
    for note in ("", "   \n "):
        with pytest.raises(P.PreregisterError, match="one line"):
            P.entries([dict(ROW, lose=[])], {"mu_fq4": TEXT}, prior, DAY,
                      recommit={"mu_fq4"}, note=note)


def test_a_recommit_keeps_the_hash_it_replaced():
    first = P.entries([ROW], {"mu_fq4": TEXT}, [], dt.date(2026, 9, 1))
    moved = dict(ROW, lose=[])
    got = P.entries([moved], {"mu_fq4": TEXT}, first, DAY,
                    recommit={"mu_fq4"}, note="loser\nremoved")[0]
    assert tuple(got) == P.ENTRY_FIELDS + P.REVISION_FIELDS
    assert got["revised_at"] == got["committed_at"] == "2026-09-13"
    assert got["revision_note"] == "loser removed", "one line"
    assert got["history"] == [{"sha256": P.digest(ROW, TEXT),
                               "committed_at": "2026-09-01"}]
    assert P.check([moved], {"mu_fq4": TEXT}, [got]) == []
    # A later build keeps all of it; a second re-commit adds to the history.
    assert P.entries([moved], {"mu_fq4": TEXT}, [got],
                     dt.date(2026, 9, 20))[0] == got
    again = P.entries([dict(moved, kind="tide")], {"mu_fq4": TEXT}, [got],
                      dt.date(2026, 9, 20), recommit={"mu_fq4"},
                      note="kind")[0]
    assert [h["committed_at"] for h in again["history"]] == [
        "2026-09-01", "2026-09-13"]
    assert again["history"][-1]["sha256"] == got["sha256"]


def test_check_names_a_malformed_revision():
    first = P.entries([ROW], {"mu_fq4": TEXT}, [], dt.date(2026, 9, 1))
    moved = dict(ROW, lose=[])
    good = P.entries([moved], {"mu_fq4": TEXT}, first, DAY,
                     recommit={"mu_fq4"}, note="loser removed")[0]
    for bad, words in [
            (dict(good, revised_at="2026-09-12"), "revised_at"),
            (dict(good, revision_note="two\nlines"), "revision_note"),
            (dict(good, history=[]), "history"),
            (dict(good, history=[{"sha256": good["sha256"],
                                  "committed_at": "2026-09-01"}]),
             "still in force")]:
        got = P.check([moved], {"mu_fq4": TEXT}, [bad])
        assert got and words in got[0], (words, got)


def test_the_reveal_carries_the_revision():
    first = P.entries([ROW], {"mu_fq4": TEXT}, [], dt.date(2026, 9, 1))
    moved = dict(ROW, lose=[])
    e = P.entries([moved], {"mu_fq4": TEXT}, first, DAY,
                  recommit={"mu_fq4"}, note="loser removed")[0]
    r = P.reveal(moved, TEXT, e)
    assert {k: r[k] for k in P.REVISION_FIELDS} == {
        k: e[k] for k in P.REVISION_FIELDS}
    assert hashlib.sha256(r["contract"].encode("utf-8")).hexdigest() \
        == e["sha256"], "the hash checked is the one in force"
    assert "revised_at" not in P.reveal(ROW, TEXT, first[0])


def test_a_moved_answer_date_keeps_the_commit_date_and_rechecks_validity():
    prior = P.entries([ROW], {"mu_fq4": TEXT}, [], DAY)
    got = P.entries([dict(ROW, d="2026-09-12")], {"mu_fq4": TEXT}, prior,
                    dt.date(2026, 9, 14))
    assert got[0]["committed_at"] == "2026-09-13"
    assert got[0]["answer_date"] == "2026-09-12"
    assert got[0]["valid_preregistration"] is False


def test_a_dropped_question_keeps_its_published_commitment():
    rows, texts = _rows()
    prior = P.entries(rows, texts, [], DAY)
    got = P.entries(rows[:1], texts, prior, dt.date(2026, 9, 20))
    assert [e["qid"] for e in got] == ["orcl_q1", "mu_fq4"]
    assert got[1] == prior[1]


def test_check_names_a_missing_or_changed_commitment():
    rows, texts = _rows()
    good = P.entries(rows, texts, [], DAY)
    assert P.check(rows, texts, good) == []
    assert P.check(rows, texts, good[:1]) == ["mu_fq4: no commitment"]
    changed = P.check([rows[0], dict(ROW, kind="tide")], texts, good)
    assert changed and "contract changed" in changed[0]


def test_the_revealed_contract_hashes_to_the_committed_value():
    entry = P.entries([ROW], {"mu_fq4": TEXT}, [], DAY)[0]
    r = P.reveal(ROW, TEXT, entry)
    assert hashlib.sha256(r["contract"].encode("utf-8")).hexdigest() \
        == entry["sha256"]
    assert {k: r[k] for k in entry if k != "qid"} == {
        k: v for k, v in entry.items() if k != "qid"}


# -- the committed file: the build gate ---------------------------------------

WATCH = json.loads(watch_path().read_text(encoding="utf-8"))
COMMITTED = json.loads(commitments_path().read_text(encoding="utf-8"))
BY = {e["qid"]: e for e in COMMITTED}


def test_every_question_that_is_scored_has_a_commitment():
    missing = [r["id"] for r in WATCH
               if not r.get("observe_only") and r["id"] not in BY]
    assert missing == []


def test_every_question_has_a_commitment_observation_only_included():
    assert [r["id"] for r in WATCH if r["id"] not in BY] == []


def test_each_committed_entry_is_well_formed_and_honest():
    assert len(BY) == len(COMMITTED), "one commitment per question"
    for e in COMMITTED:
        assert tuple(e) in (P.ENTRY_FIELDS,
                            P.ENTRY_FIELDS + P.REVISION_FIELDS), e["qid"]
        if "revised_at" in e:
            assert P._revision_problems(e) == [], e["qid"]
            assert e["revised_at"] < e["answer_date"], (
                f"{e['qid']}: revised on or after its answer date")
        assert re.fullmatch(r"[0-9a-f]{64}", e["sha256"]), e["qid"]
        dt.date.fromisoformat(e["committed_at"])
        dt.date.fromisoformat(e["answer_date"])
        assert e["primary_horizon"] == answers.PRIMARY_HORIZON
        assert e["valid_preregistration"] is (
            e["committed_at"] < e["answer_date"]), e["qid"]


def test_the_committed_answer_dates_match_the_watch_list():
    assert [(r["id"], r["d"]) for r in WATCH if BY[r["id"]]["answer_date"]
            != r["d"]] == []
