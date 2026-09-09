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
    assert answers.read(tmp_path / "nope.json", ids=IDS) == ({}, [], [])


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


# -- forecasts: the pre-registration is the whole point ----------------------
# A forecast is only a forecast if its baskets were fixed before the event.
# They are, in data/watch.json, in git, with a commit date. So an incoming row
# is checked against that copy and its own baskets are never used to score
# anything. A forward test whose hypothesis can be edited afterwards is a
# backtest wearing a disguise.

BASKETS = {"mu_fq4": (["mu"], ["skhynix", "samsung"]),
           "nvda_q3": (["tsmc", "skhynix", "mu"], [])}
FIDS = set(BASKETS)


def forecast_row(**over):
    r = {"id": "f1", "qid": "mu_fq4", "marked_at": "2026-09-30T21:05:00Z",
         "status": "yes", "direction": 1, "win": ["mu"],
         "lose": ["skhynix", "samsung"], "benchmark": "EW_MAP",
         "horizons": [5, 10, 20]}
    r.update(over)
    return r


def collect_f(rows):
    return answers.collect_forecasts(rows, FIDS, BASKETS)


def test_a_well_formed_forecast_survives():
    good, log = collect_f([forecast_row()])
    assert len(good) == 1 and log == []
    assert good[0]["direction"] == 1 and good[0]["qid"] == "mu_fq4"


def test_baskets_that_drifted_from_the_registered_ones_are_refused():
    """The check the forward test rests on. A row that quietly added a name to
    the winning side would be scoring a hypothesis nobody committed."""
    good, log = collect_f([forecast_row(win=["mu", "nvda"])])
    assert good == []
    assert "do not match the ones registered" in log[0]
    assert "not a forecast" in log[0]


def test_the_registered_baskets_are_what_gets_scored():
    """Not the received copy. They were just proved equal; using the git copy
    means the thing scored is the thing in git even if that check is loosened."""
    good, _ = collect_f([forecast_row()])
    assert good[0]["win"] == BASKETS["mu_fq4"][0]
    assert good[0]["lose"] == BASKETS["mu_fq4"][1]


@pytest.mark.parametrize("status", ["mixed", "none"])
def test_an_ambiguous_answer_supports_no_forecast(status):
    """"Partial" and "not disclosed" are real answers and neither points
    anywhere. A direction taken from one would be invented."""
    good, log = collect_f([forecast_row(status=status)])
    assert good == [] and "supports no direction" in log[0]


def test_an_unknown_direction_is_refused():
    good, log = collect_f([forecast_row(direction="sideways")])
    assert good == [] and "direction" in log[0]


@pytest.mark.parametrize("given,want", [(1, 1), (-1, -1),
                                        ("long", 1), ("short", -1)])
def test_a_direction_is_normalised_to_plus_or_minus_one(given, want):
    good, _ = collect_f([forecast_row(direction=given)])
    assert good[0]["direction"] == want


def test_a_qid_that_is_not_a_question_is_refused():
    good, log = collect_f([forecast_row(qid="nope_q9")])
    assert good == [] and "not a question" in log[0]


def test_another_benchmark_is_refused():
    """Nothing here scores against anything but EW_MAP, so a row naming
    something else is a row this build cannot honour."""
    good, log = collect_f([forecast_row(benchmark="SPX")])
    assert good == [] and "EW_MAP" in log[0]


def test_different_horizons_are_refused():
    good, log = collect_f([forecast_row(horizons=[1, 3])])
    assert good == [] and "horizons" in log[0]


def test_a_bad_marked_at_is_refused():
    good, log = collect_f([forecast_row(marked_at="30/09/2026")])
    assert good == [] and "marked_at" in log[0]


def test_a_duplicate_forecast_id_is_refused():
    good, log = collect_f([forecast_row(), forecast_row()])
    assert len(good) == 1 and "duplicate" in log[0]


def test_one_bad_forecast_does_not_take_the_good_one_with_it():
    good, log = collect_f([forecast_row(),
                           forecast_row(id="f2", qid="nvda_q3",
                                        win=["tsmc"], lose=[])])
    assert [g["id"] for g in good] == ["f1"] and len(log) == 1


def test_forecasts_are_returned_oldest_first():
    good, _ = collect_f([
        forecast_row(id="b", marked_at="2026-10-15T00:00:00Z"),
        forecast_row(id="a", marked_at="2026-09-30T00:00:00Z"),
    ])
    assert [g["id"] for g in good] == ["a", "b"]


def test_a_forecasts_value_that_is_not_a_list_is_refused():
    good, log = collect_f({"nope": 1})
    assert good == [] and "must be a list" in log[0]


# -- the payload's two shapes -----------------------------------------------

def test_the_new_shape_carries_both_halves(tmp_path):
    p = write(tmp_path, {"answers": {"mu_fq4": {"status": "yes"}},
                         "forecasts": []})
    a, f, problems = answers.read(p, ids=IDS)
    assert set(a) == {"mu_fq4"} and f == [] and problems == []


def test_the_old_bare_shape_is_still_read(tmp_path):
    """A hand-written file looks like this, and there is no reason to make
    that an error."""
    p = write(tmp_path, {"mu_fq4": {"status": "yes"}})
    a, f, problems = answers.read(p, ids=IDS)
    assert set(a) == {"mu_fq4"} and f == [] and problems == []


def test_forecasts_alone_is_a_valid_payload(tmp_path):
    p = write(tmp_path, {"forecasts": []})
    a, f, problems = answers.read(p, ids=IDS)
    assert a == {} and f == [] and problems == []
