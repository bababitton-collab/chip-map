"""The answers file is written somewhere else, so it is checked here.

It crosses from the private artifact's database to this laptop as a file, and a
file is the one link in the chain with nothing on the other end to validate it.
A wrong status does not crash anything -- it colours a row on a public board
and prints a wrong word in a brief.

The policy is per-row: a bad row is dropped and named, and the run goes on with
the rows that survived. The exporter runs on Friday in the cloud and the reader
runs on Saturday on a laptop; losing the whole Saturday chain -- snapshot,
pages, brief -- to one malformed status string would be the worse failure. Being
quiet about it would be worse still, so every drop is printed and the by-hand
command exits non-zero.
"""
from __future__ import annotations

import json

import pytest

from chains import answers

IDS = {"mu_fq4", "nvda_q3", "asml_q3"}


def write(tmp_path, obj):
    p = tmp_path / "answers.json"
    p.write_text(json.dumps(obj) if not isinstance(obj, str) else obj,
                 encoding="utf-8")
    return p


def load(tmp_path, obj):
    """Load, capturing what was reported instead of printing it."""
    log: list[str] = []
    good = answers.load(write(tmp_path, obj), ids=IDS, on_problem=log.append)
    return good, log


# -- absent is not an error -------------------------------------------------

def test_a_missing_file_is_an_empty_dict_not_a_failure(tmp_path):
    """The normal state before the first export. "No answer is known" and
    "the file is not there" are the same statement."""
    assert answers.load(tmp_path / "nope.json", ids=IDS) == {}


def test_a_missing_file_reports_no_problem(tmp_path):
    assert answers.read(tmp_path / "nope.json", ids=IDS) == ({}, [])


def test_an_empty_file_is_an_empty_dict(tmp_path):
    assert load(tmp_path, {})[0] == {}


# -- what a good row looks like ---------------------------------------------

def test_a_valid_row_survives_intact(tmp_path):
    good, log = load(tmp_path, {"mu_fq4": {
        "status": "yes", "note": "40% by 2027",
        "updated": "2026-10-01T09:12:00.000Z"}})
    assert good["mu_fq4"]["status"] == "yes"
    assert good["mu_fq4"]["note"] == "40% by 2027"
    assert log == []


@pytest.mark.parametrize("status", sorted(answers.STATUSES))
def test_every_status_the_page_can_produce_is_accepted(status, tmp_path):
    good, _ = load(tmp_path, {"mu_fq4": {"status": status}})
    assert good["mu_fq4"]["status"] == status


def test_open_is_a_real_answer_not_a_missing_one():
    """Somebody looked and the question is still open. That is different from
    nobody having looked, and the file is allowed to say so."""
    assert "open" in answers.STATUSES


def test_a_row_with_no_note_gets_an_empty_string_not_none(tmp_path):
    assert load(tmp_path, {"mu_fq4": {"status": "no"}})[0]["mu_fq4"]["note"] == ""


def test_a_date_only_timestamp_is_accepted(tmp_path):
    good, _ = load(tmp_path, {"mu_fq4": {"status": "no",
                                         "updated": "2026-10-01"}})
    assert good


# -- a bad row is dropped and named, and the run goes on --------------------

def test_a_bad_row_is_dropped_and_the_good_one_is_kept(tmp_path):
    """The case the policy exists for: one usable answer, one unusable, and a
    run that still produces a snapshot."""
    good, log = load(tmp_path, {
        "mu_fq4": {"status": "yes", "note": "40% by 2027"},
        "nvda_q3": {"status": "probably"},
    })
    assert set(good) == {"mu_fq4"}
    assert good["mu_fq4"]["status"] == "yes"
    assert len(log) == 1 and "nvda_q3" in log[0] and "probably" in log[0]


@pytest.mark.parametrize("bad,needle", [
    ({"status": "probably"}, "probably"),
    ({"note": "no status at all"}, "status"),
    ({"status": "yes", "updated": "01/10/2026"}, "ISO"),
    ({"status": "yes", "confidence": 0.8}, "confidence"),
    ({"status": "yes", "note": "x" * 400}, "over 300"),
    ("not an object", "expected an object"),
])
def test_each_kind_of_bad_row_is_dropped_with_its_reason(bad, needle, tmp_path):
    good, log = load(tmp_path, {"mu_fq4": bad})
    assert good == {}
    assert len(log) == 1 and needle in log[0]


def test_an_unknown_id_is_dropped_and_named(tmp_path):
    """An answer for a question nobody can see is either a typo or a watch
    list that has moved on. Both are worth saying out loud; neither is worth
    losing the run over."""
    good, log = load(tmp_path, {"nope_q9": {"status": "yes"},
                                "mu_fq4": {"status": "no"}})
    assert set(good) == {"mu_fq4"}
    assert "nope_q9" in log[0] and "no such question" in log[0]


def test_a_list_is_not_an_answers_file_and_yields_nothing(tmp_path):
    good, log = load(tmp_path, [{"id": "mu_fq4"}])
    assert good == {} and len(log) == 1
    assert "keyed by question id" in log[0]


def test_unparseable_json_does_not_raise(tmp_path):
    """The Friday job wrote something broken. Saturday still runs."""
    good, log = load(tmp_path, "{not json at all,")
    assert good == {} and len(log) == 1 and "not valid JSON" in log[0]


def test_nothing_is_invented_for_a_question_with_no_row(tmp_path):
    """No default status, no answer inferred from a leak. A question with no
    row simply has no entry, and the page renders it open."""
    assert set(load(tmp_path, {"mu_fq4": {"status": "yes"}})[0]) == {"mu_fq4"}


# -- loud by hand, quiet in the pipeline ------------------------------------

def test_the_by_hand_command_fails_on_a_bad_row(tmp_path, monkeypatch, capsys):
    """A broken exporter must fail the command a person runs to check it, even
    though it must not fail the scheduled build that only consumes it."""
    monkeypatch.setenv("CHIP_MAP_OUT", str(tmp_path))
    monkeypatch.delenv("ANSWERS_URL", raising=False)
    (tmp_path / "answers.json").write_text(
        json.dumps({"mu_fq4": {"status": "probably"}}), encoding="utf-8")
    assert answers.main() == 1
    assert "DROPPED" in capsys.readouterr().err


def test_the_by_hand_command_is_happy_with_an_absent_file(tmp_path,
                                                          monkeypatch):
    monkeypatch.setenv("CHIP_MAP_OUT", str(tmp_path))
    monkeypatch.delenv("ANSWERS_URL", raising=False)
    assert answers.main() == 0


# -- the real ids -----------------------------------------------------------

def test_known_ids_comes_from_the_tracked_watch_list():
    ids = answers.known_ids()
    assert len(ids) >= 39 and "nvda_q3" in ids


def test_the_default_path_is_the_derived_output_directory():
    """It is generated data, so it lives with the generated data -- not in
    data/, which is reviewed input, and not outside the checkout, which is
    what this repository exists to stop."""
    from chains import paths
    assert answers.answers_path().parent == paths.out_dir()


# -- auto: a mark a machine made --------------------------------------------

def test_auto_defaults_to_false(tmp_path):
    """Every row written before the field existed was written by a person."""
    good, _ = load(tmp_path, {"mu_fq4": {"status": "yes"}})
    assert good["mu_fq4"]["auto"] is False


def test_an_auto_row_carries_the_flag_through(tmp_path):
    good, log = load(tmp_path, {"mu_fq4": {
        "status": "yes", "note": "auto: guidance raised",
        "updated": "2026-09-11T17:30:00Z", "auto": True}})
    assert good["mu_fq4"]["auto"] is True
    assert log == []


def test_a_non_boolean_auto_is_dropped_and_named(tmp_path):
    """"true" is a string and every non-empty string is truthy. A row that
    reads as machine-written when it was not is exactly the confusion the flag
    exists to prevent."""
    good, log = load(tmp_path, {"mu_fq4": {"status": "yes", "auto": "true"}})
    assert good == {} and "auto must be true or false" in log[0]


def test_auto_is_an_accepted_field_not_an_unexpected_one():
    assert "auto" in answers.FIELDS
