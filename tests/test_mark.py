"""The marking job, with nothing reaching the network.

Every test here is about one of two promises: a person's mark is never
overwritten by a machine, and a forecast is registered once from the watch row
and never again. Everything else in this file exists to make those two
testable without an API key.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from pathlib import Path

from chains import mark
from chains.paths import watch_path


TODAY = dt.date(2026, 9, 11)


def row(qid, d, **over):
    r = {"id": qid, "d": d, "who": qid.upper(), "tk": qid[:4].upper(),
         "win": ["nvda"], "lose": ["amd"]}
    r.update(over)
    return r


def marks(answers=None, forecasts=None):
    return {"answers": answers or {}, "forecasts": list(forecasts or [])}


# -- the window ---------------------------------------------------------------
def test_a_row_dated_today_is_due():
    rows = [row("a", "2026-09-11")]
    assert [r["id"] for r in mark.due(rows, marks(), TODAY)] == ["a"]


def test_a_row_five_sessions_back_is_still_due():
    """Fri 4 Sep to Fri 11 Sep is five sessions: 7, 8, 9, 10, 11."""
    rows = [row("a", "2026-09-04")]
    assert [r["id"] for r in mark.due(rows, marks(), TODAY)] == ["a"]
    assert mark.expired(rows, marks(), TODAY) == []


def test_a_row_six_sessions_back_is_not_due_but_expires():
    rows = [row("a", "2026-09-03")]
    assert mark.due(rows, marks(), TODAY) == []
    assert [r["id"] for r in mark.expired(rows, marks(), TODAY)] == ["a"]


def test_sessions_are_weekdays_after_the_date_through_today():
    assert mark.sessions_after(dt.date(2026, 9, 30), dt.date(2026, 9, 30)) == 0
    assert mark.sessions_after(dt.date(2026, 9, 30), dt.date(2026, 10, 1)) == 1
    assert mark.sessions_after(dt.date(2026, 9, 30), dt.date(2026, 10, 4)) == 2
    assert mark.sessions_after(dt.date(2026, 9, 30), dt.date(2026, 10, 7)) == 5


# Micron reports Wed 30 Sep after the US close. Its "open" is asked again on
# every run through Wed 7 Oct -- the fifth session -- and closed on 8 Oct.
@pytest.mark.parametrize("today,is_due,is_expired", [
    ("2026-09-29", False, False),        # before the date: nothing
    ("2026-09-30", True, False),         # the 03:00 and the 23:30 run
    ("2026-10-01", True, False),         # the morning after the call
    ("2026-10-03", True, False),         # a weekend changes nothing
    ("2026-10-05", True, False),
    ("2026-10-07", True, False),         # fifth session
    ("2026-10-08", False, True),         # sixth: closed as none
])
def test_an_open_answer_is_rechecked_until_the_window_ends(
        today, is_due, is_expired):
    rows = [row("mu_fq4", "2026-09-30")]
    m = marks({"mu_fq4": {"status": "open", "basis": "unclear", "auto": True}})
    t = dt.date.fromisoformat(today)
    assert bool(mark.due(rows, m, t)) is is_due
    assert bool(mark.expired(rows, m, t)) is is_expired


def test_a_settled_or_manual_mark_never_expires():
    rows = [row("a", "2026-09-01"), row("b", "2026-09-01"),
            row("c", "2026-09-01")]
    m = marks({"a": {"status": "yes", "basis": "yes", "auto": True},
               "b": {"status": "mixed", "basis": "unclear", "auto": True},
               "c": {"status": "open", "basis": "unclear"}})
    assert mark.expired(rows, m, TODAY) == []


def test_a_row_dated_tomorrow_is_not():
    rows = [row("a", "2026-09-12")]
    assert mark.due(rows, marks(), TODAY) == []


def test_a_row_with_no_date_is_skipped():
    assert mark.due([row("a", None)], marks(), TODAY) == []


def test_only_narrows_to_one_id():
    rows = [row("a", "2026-09-11"), row("b", "2026-09-11")]
    got = mark.due(rows, marks(), TODAY, only="b")
    assert [r["id"] for r in got] == ["b"]


# -- a person's mark is not a machine's to revisit ----------------------------
def test_a_manual_mark_is_never_due():
    """No auto flag means a person wrote it. It is left exactly as it is."""
    rows = [row("a", "2026-09-11")]
    m = marks({"a": {"status": "yes", "basis": "yes"}})
    assert mark.due(rows, m, TODAY) == []


def test_a_manual_open_mark_is_also_left_alone():
    rows = [row("a", "2026-09-11")]
    m = marks({"a": {"status": "open", "basis": "unclear"}})
    assert mark.due(rows, m, TODAY) == []


def test_an_auto_open_mark_is_retried():
    rows = [row("a", "2026-09-11")]
    m = marks({"a": {"status": "open", "basis": "unclear", "auto": True}})
    assert [r["id"] for r in mark.due(rows, m, TODAY)] == ["a"]


def test_an_auto_settled_mark_is_not_retried():
    rows = [row("a", "2026-09-11")]
    m = marks({"a": {"status": "yes", "basis": "yes", "auto": True}})
    assert mark.due(rows, m, TODAY) == []


# -- validation ---------------------------------------------------------------
GOOD = ('{"status":"yes","basis":"yes",'
        '"evidence":"Reuters 2026-09-11: shipments raised.",'
        '"note":"auto: confirmed by the call"}')


def test_a_good_payload_parses():
    got = mark.parse(GOOD, "2026-09-11")
    assert got["status"] == "yes" and got["basis"] == "yes"


def test_prose_around_the_json_is_tolerated():
    assert mark.parse("Here it is:\n" + GOOD + "\nthanks", "2026-09-11")


@pytest.mark.parametrize("bad", [
    "",
    "not json at all",
    '{"status":"maybe","basis":"yes","evidence":"x 2026-09-11","note":"auto: x"}',
    '{"status":"yes","basis":"sideways","evidence":"x 2026-09-11","note":"auto: x"}',
    # a note that does not say a machine wrote it
    '{"status":"yes","basis":"yes","evidence":"x 2026-09-11","note":"confirmed"}',
    # evidence with no date is not evidence
    '{"status":"yes","basis":"yes","evidence":"Reuters said so","note":"auto: x"}',
    '{"status":"yes","basis":"yes","evidence":"","note":"auto: x"}',
])
def test_a_bad_payload_is_rejected(bad):
    assert mark.parse(bad, "2026-09-11") is None


def test_an_over_long_evidence_is_rejected():
    ev = "2026-09-11 " + "x" * mark.MAX_EVIDENCE
    bad = json.dumps({"status": "yes", "basis": "yes", "evidence": ev,
                      "note": "auto: x"})
    assert mark.parse(bad, "2026-09-11") is None


def test_an_over_long_note_is_rejected():
    bad = json.dumps({"status": "yes", "basis": "yes",
                      "evidence": "Reuters 2026-09-11: x",
                      "note": "auto: " + "x" * mark.MAX_NOTE})
    assert mark.parse(bad, "2026-09-11") is None


def test_open_needs_no_evidence():
    """Nothing found is a legitimate answer, and it has nothing to cite."""
    ok = '{"status":"open","basis":"unclear","evidence":"","note":"auto: none"}'
    assert mark.parse(ok, "2026-09-11")["status"] == "open"


# -- the forecast is assembled in code ----------------------------------------
def test_a_forecast_takes_its_baskets_from_the_watch_row():
    r = row("a", "2026-09-11", win=["mu", "skhynix"], lose=["samsung"])
    f = mark.forecast_for(r, "yes", "2026-09-11T03:00:00Z", "2026-09-11")
    assert f["win"] == ["mu", "skhynix"] and f["lose"] == ["samsung"]
    assert f["direction"] == 1
    assert f["benchmark"] == mark.BENCHMARK
    assert f["horizons"] == mark.HORIZONS
    assert f["id"] == "a-2026-09-11" and f["qid"] == "a"


def test_a_no_points_the_other_way():
    f = mark.forecast_for(row("a", "2026-09-11"), "no",
                          "2026-09-11T03:00:00Z", "2026-09-11")
    assert f["direction"] == -1


# -- the run ------------------------------------------------------------------
class Fake:
    """Stands in for the model. No key, no socket, no search."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = 0

    def __call__(self, row, q, news, key, model, tools=True):
        self.calls += 1
        return self.replies[min(self.calls - 1, len(self.replies) - 1)]


@pytest.fixture
def wired(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIP_MAP_DATA", str(tmp_path))
    monkeypatch.setenv(mark.KEY_ENV, "not-a-real-key")
    monkeypatch.setenv(mark.MODEL_ENV, "claude-test")
    monkeypatch.delenv("EODHD_API_TOKEN", raising=False)
    d = tmp_path / "semi"
    d.mkdir(parents=True)
    (d / "watch.json").write_text(json.dumps(
        [row("a", "2026-09-11", win=["mu"], lose=["samsung"])]),
        encoding="utf-8")
    (d / "marks.json").write_text(json.dumps(mark.load_marks.__defaults__ and
                                             {"answers": {}, "forecasts": []}),
                                  encoding="utf-8")
    monkeypatch.setattr(mark, "headlines", lambda *a, **k: [])
    monkeypatch.setattr(mark, "pick_model", lambda key: "claude-test")
    monkeypatch.setattr("chains.questions.fetch", lambda url=None, dom=None: {
        "a": {"q_en": "Did the company raise its guidance for the year?",
              "yes_en": "Guidance for the full year is raised outright.",
              "no_en": "Guidance for the full year is held or cut.",
              "why_en": "It is the only number the market reads."}})
    return d


def read_marks(d):
    return json.loads((d / "marks.json").read_text(encoding="utf-8"))


def test_a_yes_writes_a_mark_and_registers_one_forecast(wired, monkeypatch):
    monkeypatch.setattr(mark, "ask", Fake(GOOD))
    assert mark.run(None, TODAY, False, None, say=lambda *_: None) == 0
    got = read_marks(wired)
    assert got["answers"]["a"]["status"] == "yes"
    assert got["answers"]["a"]["auto"] is True
    assert got["answers"]["a"]["updated"].endswith("Z")
    assert len(got["forecasts"]) == 1
    assert got["forecasts"][0]["win"] == ["mu"]


def test_a_second_run_does_not_register_a_second_forecast(wired, monkeypatch):
    monkeypatch.setattr(mark, "ask", Fake(GOOD))
    mark.run(None, TODAY, False, None, say=lambda *_: None)
    # force it to be due again, as an auto-open row would be
    doc = read_marks(wired)
    doc["answers"]["a"]["status"] = "open"
    (wired / "marks.json").write_text(json.dumps(doc), encoding="utf-8")
    mark.run(None, TODAY, False, None, say=lambda *_: None)
    assert len(read_marks(wired)["forecasts"]) == 1


def test_an_existing_forecast_is_never_rewritten(wired, monkeypatch):
    doc = {"answers": {}, "forecasts": [
        {"id": "a-2026-09-09", "qid": "a", "marked_at": "2026-09-09T03:00:00Z",
         "status": "no", "direction": -1, "win": ["old"], "lose": ["older"],
         "benchmark": "EW_MAP", "horizons": [5, 10, 20]}]}
    (wired / "marks.json").write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(mark, "ask", Fake(GOOD))
    mark.run(None, TODAY, False, None, say=lambda *_: None)
    fs = read_marks(wired)["forecasts"]
    assert len(fs) == 1
    assert fs[0] == doc["forecasts"][0]      # byte for byte the same entry


@pytest.mark.parametrize("status", ["mixed", "none", "open"])
def test_an_unsettled_status_registers_nothing(wired, monkeypatch, status):
    reply = json.dumps({"status": status, "basis": "unclear",
                        "evidence": "Reuters 2026-09-11: unclear.",
                        "note": "auto: " + status})
    monkeypatch.setattr(mark, "ask", Fake(reply))
    mark.run(None, TODAY, False, None, say=lambda *_: None)
    assert read_marks(wired)["forecasts"] == []


def test_invalid_output_is_retried_once_then_left_open(wired, monkeypatch):
    fake = Fake("rubbish", "still rubbish")
    monkeypatch.setattr(mark, "ask", fake)
    mark.run(None, TODAY, False, None, say=lambda *_: None)
    assert fake.calls == 2                   # one retry, not a loop
    rec = read_marks(wired)["answers"]["a"]
    assert rec["status"] == "open"
    assert rec["note"] == "auto: model output invalid on 2026-09-11"


def test_a_retry_that_succeeds_is_used(wired, monkeypatch):
    monkeypatch.setattr(mark, "ask", Fake("rubbish", GOOD))
    mark.run(None, TODAY, False, None, say=lambda *_: None)
    assert read_marks(wired)["answers"]["a"]["status"] == "yes"


def test_dry_run_writes_nothing(wired, monkeypatch):
    monkeypatch.setattr(mark, "ask", Fake(GOOD))
    mark.run(None, TODAY, True, None, say=lambda *_: None)
    assert read_marks(wired) == {"answers": {}, "forecasts": []}


def test_a_missing_key_stops_the_run(wired, monkeypatch):
    monkeypatch.delenv(mark.KEY_ENV, raising=False)
    monkeypatch.setattr(mark, "ask", Fake(GOOD))
    with pytest.raises(mark.MarkError) as e:
        mark.run(None, TODAY, True, None, say=lambda *_: None)
    assert mark.KEY_ENV in str(e.value)


# -- after the window ------------------------------------------------------------
def test_an_expired_row_is_closed_as_none_without_asking(wired, monkeypatch):
    from chains import answers
    doc = {"answers": {"a": {"status": "open", "basis": "unclear", "auto": True,
                             "note": "auto: no source found on 2026-09-11"}},
           "forecasts": []}
    (wired / "marks.json").write_text(json.dumps(doc), encoding="utf-8")
    fake = Fake(GOOD)
    monkeypatch.setattr(mark, "ask", fake)
    monkeypatch.setattr("chains.questions.fetch",
                        lambda url=None, dom=None: pytest.fail("fetched"))
    monkeypatch.delenv(mark.KEY_ENV, raising=False)   # closing needs no key
    mon = dt.date(2026, 9, 21)                         # sixth session after
    assert mark.run(None, mon, False, None, say=lambda *_: None) == 0
    assert fake.calls == 0
    got = read_marks(wired)
    rec = got["answers"]["a"]
    assert rec["status"] == "none"
    assert rec["note"] == "auto: no clean answer within 5 sessions"
    assert rec["auto"] is True and rec["updated"].endswith("Z")
    assert got["forecasts"] == []
    assert answers.check_row("a", rec, {"a"}) is None


def test_an_expired_row_on_a_dry_run_writes_nothing(wired, monkeypatch):
    monkeypatch.setattr(mark, "ask", Fake(GOOD))
    said: list[str] = []
    mark.run(None, dt.date(2026, 9, 21), True, None, say=said.append)
    assert "closed as none" in "\n".join(said)
    assert read_marks(wired) == {"answers": {}, "forecasts": []}


def test_an_open_answer_is_asked_again_the_next_session(wired, monkeypatch):
    doc = {"answers": {"a": {"status": "open", "basis": "unclear", "auto": True,
                             "note": "auto: no source found on 2026-09-11"}},
           "forecasts": []}
    (wired / "marks.json").write_text(json.dumps(doc), encoding="utf-8")
    fake = Fake(GOOD)
    monkeypatch.setattr(mark, "ask", fake)
    mark.run(None, dt.date(2026, 9, 14), False, None, say=lambda *_: None)
    assert fake.calls == 1
    assert read_marks(wired)["answers"]["a"]["status"] == "yes"


def test_the_workflow_runs_in_the_morning_and_after_the_close():
    """The morning run moved 03:00 -> 05:00. It shared 03:00 with the daily
    Cowork marker, which writes the same data/<domain>/marks.json, and two
    whole-document writers in the same minute is a race no git rebase can
    adjudicate. 05:00 is still half an hour ahead of the 05:30 build, so the
    build of the same morning still sees the marks."""
    from pathlib import Path
    yml = (Path(__file__).resolve().parents[1] / ".github" / "workflows"
           / "mark.yml").read_text(encoding="utf-8")
    assert 'cron: "0 5 * * 2-6"' in yml
    assert 'cron: "30 23 * * 1-5"' in yml


# -- a forced question: the whole path, on a dry run only -----------------------
def test_force_asks_a_question_outside_the_window_and_writes_nothing(
        wired, monkeypatch):
    fake = Fake(GOOD)
    monkeypatch.setattr(mark, "ask", fake)
    far = TODAY - dt.timedelta(days=30)
    said: list[str] = []
    assert mark.run(None, far, True, None, say=said.append, force="a") == 0
    assert fake.calls == 1
    out = "\n".join(said)
    assert "force: a" in out and "questions: 1 fetched" in out
    assert '"status": "yes"' in out and "commit: לא נדרש (dry-run)" in out
    assert read_marks(wired) == {"answers": {}, "forecasts": []}


def test_force_ignores_a_manual_mark_but_still_writes_nothing(wired, monkeypatch):
    doc = {"answers": {"a": {"status": "no", "note": "by hand"}}, "forecasts": []}
    (wired / "marks.json").write_text(json.dumps(doc), encoding="utf-8")
    fake = Fake(GOOD)
    monkeypatch.setattr(mark, "ask", fake)
    mark.run(None, TODAY, True, None, say=lambda *_: None, force="a")
    assert fake.calls == 1
    assert read_marks(wired) == doc


def test_force_without_dry_run_is_refused_before_anything_runs(
        wired, monkeypatch):
    fake = Fake(GOOD)
    monkeypatch.setattr(mark, "ask", fake)
    monkeypatch.setattr("chains.questions.fetch",
                        lambda url=None, dom=None: pytest.fail("fetched"))
    with pytest.raises(mark.MarkError) as e:
        mark.run(None, TODAY, False, None, say=lambda *_: None, force="a")
    assert "dry run" in str(e.value)
    assert fake.calls == 0
    assert read_marks(wired) == {"answers": {}, "forecasts": []}


def test_the_command_line_refuses_force_without_dry_run():
    with pytest.raises(SystemExit) as e:
        mark.main(["--force", "a"])
    assert e.value.code == 2


def test_force_names_an_unknown_question(wired):
    with pytest.raises(mark.MarkError) as e:
        mark.run(None, TODAY, True, None, say=lambda *_: None, force="nope")
    assert "nope" in str(e.value)


def test_the_trail_shows_sources_read_but_no_question_text(wired, monkeypatch):
    def reads(row, q, news, key, model, tools=True):
        mark.LAST_CALL.update(searches=2, sources=["https://a.example/mu"])
        return GOOD
    monkeypatch.setattr(mark, "ask", reads)
    said: list[str] = []
    mark.run(None, TODAY, True, None, say=said.append, force="a")
    out = "\n".join(said)
    assert "2 web search(es), 1 source(s) read, valid decision" in out
    assert "https://a.example/mu" in out
    assert "Did the company raise its guidance for the year?" not in out


def test_the_workflow_keeps_force_a_dry_run_that_commits_nothing():
    from pathlib import Path
    yml = (Path(__file__).resolve().parents[1] / ".github" / "workflows"
           / "mark.yml").read_text(encoding="utf-8")
    assert "force_qid:" in yml
    assert "FORCE_QID: ${{ inputs.force_qid }}" in yml
    assert "${{ inputs.force_qid }}\"" not in yml   # never pasted into the shell
    assert "force_qid runs only as a dry run" in yml
    assert "if: ${{ inputs.dry_run != true && !inputs.force_qid }}" in yml


# -- the question text goes nowhere -------------------------------------------
def test_no_question_text_in_the_file_or_the_summary(wired, monkeypatch):
    monkeypatch.setattr(mark, "ask", Fake(GOOD))
    said: list[str] = []
    mark.run(None, TODAY, False, None, say=said.append)
    blob = (wired / "marks.json").read_text(encoding="utf-8") + "\n".join(said)
    for sentence in ("Did the company raise its guidance for the year?",
                     "Guidance for the full year is raised outright.",
                     "Guidance for the full year is held or cut.",
                     "It is the only number the market reads."):
        assert sentence not in blob


def test_the_guard_catches_a_sentence_that_did_leak():
    qs = {"a": {"q_en": "Did the company raise its guidance for the year?"}}
    leaked = '{"note": "Did the company raise its guidance for the year?"}'
    assert mark.check_no_question_text(leaked, qs) == ["a.q_en"]


def test_the_guard_ignores_a_short_field():
    """A two-word field would match half the English language."""
    qs = {"a": {"q_en": "Up?"}}
    assert mark.check_no_question_text("Up? yes", qs) == []


def test_the_run_refuses_to_write_a_leak(wired, monkeypatch):
    leak = json.dumps({
        "status": "yes", "basis": "yes",
        "evidence": "Reuters 2026-09-11: x",
        "note": "auto: Guidance for the full year is raised outright."})
    monkeypatch.setattr(mark, "ask", Fake(leak))
    with pytest.raises(mark.MarkError) as e:
        mark.run(None, TODAY, False, None, say=lambda *_: None)
    assert "reached marks.json" in str(e.value)
    assert read_marks(wired) == {"answers": {}, "forecasts": []}


# -- the publish gate covers the file this job commits ------------------------
def test_the_locked_text_gate_reads_marks_json(tmp_path, monkeypatch):
    """A leak into marks.json is a leak into a public repository, for good.

    marks.json is never served, so it was outside the scan that protects every
    file that is. It is committed to a public repo by the mark workflow, which
    is worse: a served file can be rebuilt, and a commit cannot be unmade.
    """
    from chains import publish_site

    monkeypatch.setenv("CHIP_MAP_DATA", str(tmp_path))
    (tmp_path / "semi").mkdir(parents=True)
    site = tmp_path / "site"
    site.mkdir()
    (site / "live_en.json").write_text(json.dumps(
        {"watch": [{"id": "locked1", "locked": True},
                   {"id": "open1"}]}), encoding="utf-8")
    secret = "Does the company raise its full-year guidance on this call?"
    monkeypatch.setattr("chains.questions.fetch", lambda url=None, dom=None: {
        "locked1": {"q_en": secret, "yes_en": "", "no_en": "", "why_en": "",
                    "q_he": "", "yes_he": "", "no_he": "", "why_he": ""},
        "open1": {"q_en": "An open question nobody pays for.", "yes_en": "",
                  "no_en": "", "why_en": "", "q_he": "", "yes_he": "",
                  "no_he": "", "why_he": ""}})

    from chains.paths import marks_path
    marks_path().write_text(json.dumps(
        {"answers": {}, "forecasts": []}), encoding="utf-8")
    assert publish_site.locked_text_in_site(site) == []

    marks_path().write_text(json.dumps(
        {"answers": {"locked1": {"note": "auto: " + secret}},
         "forecasts": []}, ensure_ascii=False), encoding="utf-8")
    hits = publish_site.locked_text_in_site(site)
    assert hits, "a locked sentence in marks.json was not caught"
    assert "marks.json" in hits[0] and "locked1" in hits[0]


# -- every map gets marked, each in its own process ---------------------------
# The job ran `python -m chains.mark` once, with no domain and nothing in the
# environment, so every path helper fell back to the default map. Only the
# first industry was ever marked; a second map's answered question would pass
# its date and nothing would record it -- silently, because the job reported
# success after marking the first one. The workflow now walks
# domains.discover() with a subprocess per map. These tests hold the two
# properties that walk depends on.

TWO = {
    "alpha": [row("shared", "2026-10-15", win=["x"], lose=[]),
              row("alpha_only", "2026-10-15", win=["x"], lose=[])],
    "beta": [row("shared", "2026-10-15", win=["y"], lose=[])],
}

# The same id in two maps, with different text. This is real: semi and energy
# both own gev_q3 today.
CORPUS = {
    "alpha": {"shared": {"q_en": "Did ALPHA raise its full-year guidance?",
                         "yes_en": "y", "no_en": "n", "why_en": "w"},
              "alpha_only": {"q_en": "Did ALPHA sign the contract?",
                             "yes_en": "y", "no_en": "n", "why_en": "w"}},
    "beta": {"shared": {"q_en": "Did BETA hold its reactor schedule?",
                        "yes_en": "y", "no_en": "n", "why_en": "w"}},
}


@pytest.fixture
def two_maps(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIP_MAP_DATA", str(tmp_path))
    monkeypatch.setenv(mark.KEY_ENV, "not-a-real-key")
    monkeypatch.setenv(mark.MODEL_ENV, "claude-test")
    # Set, not deleted. mark.main() assigns CHIP_MAP_DOMAIN itself, and a
    # delenv of a variable that was already absent records nothing to undo
    # -- so the value the code sets outlives the test, and every later test
    # in the process reads a map that does not exist. Handing monkeypatch a
    # value first makes it own the variable and restore it whatever the code
    # does. A deliberately wrong one, so --domain is proved to win.
    monkeypatch.setenv("CHIP_MAP_DOMAIN", "not-a-real-map")
    for dom, rows in TWO.items():
        d = tmp_path / dom
        d.mkdir(parents=True)
        (d / "watch.json").write_text(json.dumps(rows), encoding="utf-8")
        (d / "watch_en.json").write_text(json.dumps(rows), encoding="utf-8")
        (d / "map.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mark, "headlines", lambda *a, **k: [])
    monkeypatch.setattr(mark, "pick_model", lambda key: "claude-test")
    asked = []

    def fetch(url=None, dom=None):
        asked.append(dom)
        if dom not in CORPUS:
            raise AssertionError(
                f"the fetch was handed {dom!r}: a map must ask for its own "
                f"section of the corpus, never the default one's")
        return CORPUS[dom]

    monkeypatch.setattr("chains.questions.fetch", fetch)
    return tmp_path, asked


def test_the_walk_writes_one_marks_file_per_map(two_maps, monkeypatch):
    """What the workflow loop does, in process: one call per domain, each
    with its own --domain. Each map must land in its own file."""
    root, _asked = two_maps
    monkeypatch.setattr(mark, "ask", Fake(GOOD))
    for dom in ("alpha", "beta"):
        assert mark.main(["--domain", dom, "--today", "2026-10-15"]) == 0
    for dom in ("alpha", "beta"):
        got = json.loads((root / dom / "marks.json").read_text(
            encoding="utf-8"))
        assert got["answers"], f"{dom} wrote no answer"
        assert "shared" in got["answers"], dom
    # and neither wrote into the other's file
    a = json.loads((root / "alpha" / "marks.json").read_text(encoding="utf-8"))
    b = json.loads((root / "beta" / "marks.json").read_text(encoding="utf-8"))
    assert "alpha_only" in a["answers"]
    assert "alpha_only" not in b["answers"], \
        "one map's question reached another map's marks file"


def test_each_map_is_handed_its_own_question_text(two_maps, monkeypatch):
    """The fetch must be asked for THIS map's section. Keyed on the id alone
    the two maps' `shared` question is one question with two meanings, and
    the wrong section does not fail loudly -- it answers with the other
    industry's sentence for the same id."""
    root, asked = two_maps
    monkeypatch.setattr(mark, "ask", Fake(GOOD))
    for dom in ("alpha", "beta"):
        mark.main(["--domain", dom, "--today", "2026-10-15"])
    assert asked == ["alpha", "beta"], \
        f"the fetch was handed {asked}, not each map's own name"


def test_the_second_map_never_sees_the_first_maps_corpus(two_maps,
                                                         monkeypatch):
    """Asked for beta, the corpus handed over must be beta's -- the fixture
    raises if the fetch is called with anything else, including None."""
    root, asked = two_maps
    seen = {}

    def spy(rw, q, news, key, model, tools=True):
        seen[rw["id"]] = q
        return GOOD

    monkeypatch.setattr(mark, "ask", spy)
    mark.main(["--domain", "beta", "--today", "2026-10-15"])
    assert asked == ["beta"]
    text = json.dumps(seen, ensure_ascii=False)
    assert "BETA" in text
    assert "ALPHA" not in text, "the first map's sentence reached the second"


def test_a_dry_run_on_the_second_map_finds_its_own_due_question(
        tmp_path, monkeypatch):
    """The real case, with no API call: energy's first question is abb_q3 on
    2026-10-15, and nothing but energy has it."""
    monkeypatch.setenv(mark.KEY_ENV, "not-a-real-key")
    monkeypatch.setenv(mark.MODEL_ENV, "claude-test")
    monkeypatch.setenv("CHIP_MAP_DOMAIN", "not-a-real-map")
    monkeypatch.setattr(mark, "headlines", lambda *a, **k: [])
    monkeypatch.setattr(mark, "pick_model", lambda key: "claude-test")
    asked = {}

    def fetch(url=None, dom=None):
        asked["dom"] = dom
        rows = json.loads(
            (watch_path(dom)).read_text(encoding="utf-8"))
        return {r["id"]: {"q_en": "q", "yes_en": "y", "no_en": "n",
                          "why_en": "w"} for r in rows}

    monkeypatch.setattr("chains.questions.fetch", fetch)
    said = []
    rc = mark.run("energy", dt.date(2026, 10, 15), True, None, say=said.append)
    assert rc == 0
    assert asked["dom"] == "energy"
    blob = "\n".join(said)
    assert "abb_q3" in blob, blob
    assert "1/1 due" in blob or "questions:" in blob


def test_the_forced_id_narrows_the_walk_to_the_maps_that_own_it():
    """--force names one question, and mark.py raises on a map that does not
    have it. Walking every map would turn a forced dry run red on all but
    one, so the list is narrowed first."""
    from chains import mark_domains
    assert mark_domains.owners("abb_q3") == ["energy"]
    assert mark_domains.owners("no_such_question_anywhere") == []
    # a question two maps both name belongs to both walks
    assert set(mark_domains.owners("gev_q3")) == {"semi", "energy"}


def test_an_id_no_map_owns_is_an_error_not_an_empty_walk():
    """A walk that visited nothing and reported success would be the quietest
    possible way to lose a typo."""
    from chains import mark_domains
    assert mark_domains.main(["no_such_question_anywhere"]) == 1
    assert mark_domains.main([]) == 0


def test_the_forced_id_is_an_argument_not_an_environment_variable():
    """chains/paths.py's docstring is the one place a reader should have to
    look to learn what this build reads from the environment, and a one-shot
    debugging input does not belong on that list."""
    import ast
    from pathlib import Path as _P
    tree = ast.parse((_P(__file__).resolve().parents[1] / "chains"
                      / "mark_domains.py").read_text(encoding="utf-8"))
    reads = [n for n in ast.walk(tree)
             if isinstance(n, ast.Attribute) and n.attr in ("environ",
                                                            "getenv")]
    assert reads == [], "the forced id must not become an environment knob"


def test_the_workflow_walks_every_domain_in_its_own_process():
    """Pinned on the workflow: the single bare call must not come back."""
    yml = (Path(__file__).resolve().parents[1] / ".github" / "workflows"
           / "mark.yml").read_text(encoding="utf-8")
    assert 'python -m chains.mark_domains' in yml
    assert 'CHIP_MAP_DOMAIN="$dom" python -m chains.mark --domain "$dom"' in yml
    assert "exit $rc" in yml, "a failed map must make the run red"
    assert "\n          python -m chains.mark $args" not in yml


# -- the three rules the silent week exposed ---------------------------------
# For a week every scheduled mark logged "קריאה נכשלה (HTTPStatusError)",
# "0 EODHD headline(s)" and "0 web search(es)", then wrote
# `auto: model output invalid`. Three separate faults behind one message:
# the status code was thrown away, the note blamed the model for a call that
# never returned, and the unsourced mark would have overwritten whatever was
# already there.

class Boom:
    """A model call that fails the way the runner's did."""

    def __init__(self, status=400, detail="tool not enabled"):
        self.status = status
        self.detail = detail
        self.calls = 0
        self.tools_seen = []

    def __call__(self, row, q, news, key, model, tools=True):
        self.calls += 1
        self.tools_seen.append(tools)
        raise mark.AskFailed(f"HTTP {self.status}", status=self.status,
                             detail=self.detail)


# -- rule 1: the status code reaches the log ---------------------------------

def test_a_failed_call_reports_its_status_not_just_its_class(wired,
                                                             monkeypatch):
    boom = Boom(status=403)
    monkeypatch.setattr(mark, "ask", boom)
    said: list[str] = []
    mark.run(None, TODAY, True, None, say=said.append)
    out = "\n".join(said)
    assert "HTTP 403" in out, out
    assert "HTTPStatusError" not in out, \
        "the class name alone is every 4xx and every 5xx at once"


def test_the_failure_detail_never_carries_the_key(wired, monkeypatch):
    monkeypatch.setattr(mark, "ask", Boom(status=401, detail="x" * 500))
    said: list[str] = []
    mark.run(None, TODAY, True, None, say=said.append)
    out = "\n".join(said)
    assert "not-a-real-key" not in out
    # printed, but trimmed: a response body can be a page of HTML
    longest = max((len(l) for l in out.splitlines()), default=0)
    assert longest <= 220, longest


def test_the_news_lookup_says_why_it_found_nothing(monkeypatch):
    """"0 headlines" was true and useless for a week."""
    monkeypatch.setattr(mark, "LAST_NEWS", dict(mark.LAST_NEWS))
    assert mark.headlines("MU", dt.date(2026, 9, 30), None) == []
    assert mark.LAST_NEWS["error"] == "no token"
    assert mark.headlines("", dt.date(2026, 9, 30), "tok") == []
    assert mark.LAST_NEWS["error"] == "no ticker"


# -- rule 2: a call that never returned is not invalid model output ----------

def test_a_failed_call_is_recorded_as_no_source_not_invalid_output(
        wired, monkeypatch):
    monkeypatch.setattr(mark, "ask", Boom(status=429))
    mark.run(None, TODAY, False, None, say=lambda *_: None)
    got = read_marks(wired)["answers"]["a"]
    assert got["status"] == "open"
    assert "no source found" in got["note"]
    assert "HTTP 429" in got["note"]
    assert "model output invalid" not in got["note"], \
        "the model answered nothing; it did not answer badly"


def test_a_reply_that_came_back_unusable_is_still_invalid_output(wired,
                                                                 monkeypatch):
    """The distinction has to cut both ways, or it is not a distinction."""
    monkeypatch.setattr(mark, "ask", Fake("not json at all"))
    mark.run(None, TODAY, False, None, say=lambda *_: None)
    assert "model output invalid" in read_marks(wired)["answers"]["a"]["note"]


def test_the_search_tool_is_dropped_once_before_giving_up(wired, monkeypatch):
    """A server tool the account cannot use fails identically every time.
    Retrying the same shape twice more spends time to reach the same
    nothing, so the last attempt asks without it."""
    boom = Boom(status=400)
    monkeypatch.setattr(mark, "ask", boom)
    mark.run(None, TODAY, True, None, say=lambda *_: None)
    assert boom.tools_seen == [True, True, False]


def test_a_call_that_works_never_reaches_the_fallback(wired, monkeypatch):
    good = Fake(GOOD)
    monkeypatch.setattr(mark, "ask", good)
    mark.run(None, TODAY, True, None, say=lambda *_: None)
    assert good.calls == 1, "the fallback is for a failure, not a habit"


# -- rule 3: an unsourced automatic mark never replaces a sourced one --------

# Open, and pointing at something: the morning run read a source and could
# not settle the question on it. This is the only shape a later run can
# overwrite, because a settled mark is never asked again — and it is exactly
# the shape worth protecting. The first draft of these tests used a settled
# mark, which is not due at all, so they passed without the rule they were
# written to prove.
SOURCED = {"status": "open", "basis": "yes", "auto": True,
           "evidence": "2026-09-11 the company reported, wording ambiguous",
           "note": "auto: open", "updated": "2026-09-11T00:00:00Z"}


def test_an_unsourced_auto_mark_does_not_replace_a_sourced_one(wired,
                                                               monkeypatch):
    (wired / "marks.json").write_text(json.dumps(
        {"answers": {"a": dict(SOURCED)}, "forecasts": []}), encoding="utf-8")
    monkeypatch.setattr(mark, "ask", Boom(status=500))
    mark.run(None, TODAY, False, None, say=lambda *_: None)
    got = read_marks(wired)["answers"]["a"]
    assert got["evidence"] == SOURCED["evidence"], \
        "a dead endpoint erased a finding somebody had already checked"
    assert got["basis"] == SOURCED["basis"]
    assert "no source found" not in str(got.get("note"))


def test_the_run_says_out_loud_that_it_kept_the_old_mark(wired, monkeypatch):
    (wired / "marks.json").write_text(json.dumps(
        {"answers": {"a": dict(SOURCED)}, "forecasts": []}), encoding="utf-8")
    monkeypatch.setattr(mark, "ask", Boom(status=500))
    said: list[str] = []
    mark.run(None, TODAY, False, None, say=said.append)
    assert "kept the existing mark" in "\n".join(said)


def test_a_sourced_mark_does_replace_an_unsourced_one(wired, monkeypatch):
    """The rule is about evidence, not about age: a run that finds something
    must be able to improve on a run that found nothing."""
    (wired / "marks.json").write_text(json.dumps(
        {"answers": {"a": {"status": "open", "basis": "unclear",
                           "evidence": "", "auto": True,
                           "note": "auto: no source found (HTTP 400) on x"}},
         "forecasts": []}), encoding="utf-8")
    monkeypatch.setattr(mark, "ask", Fake(GOOD))
    mark.run(None, TODAY, False, None, say=lambda *_: None)
    assert read_marks(wired)["answers"]["a"]["status"] == "yes"


@pytest.mark.parametrize("m,expected", [
    ({"evidence": "2026-09-11 said so", "basis": "unclear"}, True),
    ({"evidence": "", "basis": "filing"}, True),
    ({"evidence": "", "basis": "unclear"}, False),
    ({"evidence": "   ", "basis": ""}, False),
    (None, False),
])
def test_what_counts_as_sourced(m, expected):
    assert mark.sourced(m) is expected


# -- --no-model: report the due question, decide nothing ---------------------
# The daily Cowork task is the marker of record now. This job still runs --
# it closes expired rows, which asks nobody -- but a question whose date is
# due is reported and left alone. Nothing is decided for it and nothing is
# written for it, so the two markers cannot disagree about the same qid.

class NeverCalled:
    def __call__(self, *a, **k):
        raise AssertionError("the model was called with --no-model set")


def test_no_model_leaves_a_due_question_alone(wired, monkeypatch):
    monkeypatch.setattr(mark, "ask", NeverCalled())
    monkeypatch.setattr("chains.questions.fetch", NeverCalled())
    before = (wired / "marks.json").read_text(encoding="utf-8")
    said: list[str] = []
    rc = mark.run(None, TODAY, False, None, say=said.append, no_model=True)
    assert rc == 0
    assert (wired / "marks.json").read_text(encoding="utf-8") == before, \
        "a --no-model run wrote to marks.json"
    assert "  a: due — left to the Cowork marker" in said
    assert "commit: לא נדרש" in said


def test_no_model_does_not_even_fetch_the_question_text(wired, monkeypatch):
    """No text, no key, no model. Fetching a corpus it will not use would
    still be a network call and a secret read for nothing."""
    monkeypatch.setattr(mark, "ask", NeverCalled())
    monkeypatch.setattr("chains.questions.fetch", NeverCalled())
    monkeypatch.delenv(mark.KEY_ENV, raising=False)
    assert mark.run(None, TODAY, False, None, say=lambda *_: None,
                    no_model=True) == 0


def test_no_model_with_nothing_due_is_unchanged(wired, monkeypatch):
    monkeypatch.setattr(mark, "ask", NeverCalled())
    before = (wired / "marks.json").read_text(encoding="utf-8")
    said: list[str] = []
    # a date before the row's own date: nothing due, nothing expired
    rc = mark.run(None, dt.date(2026, 9, 1), False, None, say=said.append,
                  no_model=True)
    assert rc == 0
    assert (wired / "marks.json").read_text(encoding="utf-8") == before
    assert "אין שאלות לסימון היום." in said


def test_without_the_flag_the_model_is_still_asked(wired, monkeypatch):
    """The default path is untouched."""
    good = Fake(GOOD)
    monkeypatch.setattr(mark, "ask", good)
    mark.run(None, TODAY, False, None, say=lambda *_: None)
    assert good.calls == 1
    assert read_marks(wired)["answers"]["a"]["status"] == "yes"


def test_the_flag_reaches_run_from_the_command_line(wired, monkeypatch):
    monkeypatch.setattr(mark, "ask", NeverCalled())
    monkeypatch.setattr("chains.questions.fetch", NeverCalled())
    assert mark.main(["--today", TODAY.isoformat(), "--no-model"]) == 0


# -- the write merges onto what is on disk, atomically ----------------------
# mark.py loads marks.json at the top of the run and used to write the whole
# document from that copy at the end. In between it fetched a corpus and made
# network calls -- seconds to minutes -- and another writer touches the same
# file. The older copy then silently won on every key, including the ones it
# never looked at, and no git rebase can catch that: the content was decided
# before the commit step ran.

def _marks(path, answers, forecasts=()):
    path.write_text(json.dumps({"answers": answers,
                                "forecasts": list(forecasts)}),
                    encoding="utf-8")


def test_two_writers_with_different_questions_both_survive(tmp_path):
    p = tmp_path / "marks.json"
    _marks(p, {"other": {"status": "yes", "basis": "yes",
                         "evidence": "2026-09-11 filing", "note": "auto: yes"}})
    kept = mark.merge_and_write(
        p, {"mine": {"status": "no", "basis": "no",
                     "evidence": "2026-09-12 filing", "note": "auto: no"}}, [])
    got = json.loads(p.read_text(encoding="utf-8"))["answers"]
    assert kept == []
    assert set(got) == {"other", "mine"}, "one writer erased the other"
    assert got["other"]["evidence"] == "2026-09-11 filing"


def test_a_sourced_mark_on_disk_beats_an_unsourced_one_from_this_run(tmp_path):
    p = tmp_path / "marks.json"
    disk = {"status": "open", "basis": "yes", "auto": True,
            "evidence": "2026-09-11 reported, wording ambiguous",
            "note": "auto: open"}
    _marks(p, {"a": dict(disk)})
    kept = mark.merge_and_write(
        p, {"a": {"status": "open", "basis": "unclear", "evidence": "",
                  "note": "auto: no source found (model call HTTP 400)"}}, [])
    got = json.loads(p.read_text(encoding="utf-8"))["answers"]["a"]
    assert kept == ["a"]
    assert got == disk, "a run that read nothing erased a run that read"


def test_an_unsourced_mark_on_disk_is_replaced_by_a_sourced_one(tmp_path):
    p = tmp_path / "marks.json"
    _marks(p, {"a": {"status": "open", "basis": "unclear", "evidence": "",
                     "note": "auto: no source found"}})
    kept = mark.merge_and_write(
        p, {"a": {"status": "yes", "basis": "yes",
                  "evidence": "2026-09-12 the company said so",
                  "note": "auto: yes"}}, [])
    assert kept == []
    assert json.loads(p.read_text(encoding="utf-8"))["answers"]["a"]["status"] \
        == "yes"


def test_a_forecast_already_on_disk_is_not_added_twice(tmp_path):
    p = tmp_path / "marks.json"
    _marks(p, {}, [{"qid": "a", "id": "a-1"}])
    mark.merge_and_write(p, {}, [{"qid": "a", "id": "a-2"},
                                 {"qid": "b", "id": "b-1"}])
    got = json.loads(p.read_text(encoding="utf-8"))["forecasts"]
    assert [f["id"] for f in got] == ["a-1", "b-1"]


def test_the_write_leaves_no_temporary_file_behind(tmp_path):
    p = tmp_path / "marks.json"
    _marks(p, {})
    mark.merge_and_write(p, {"a": {"status": "open", "basis": "unclear",
                                   "evidence": "", "note": "auto: x"}}, [])
    assert [f.name for f in tmp_path.iterdir()] == ["marks.json"]


def test_an_unreadable_file_is_refused_not_overwritten(tmp_path):
    p = tmp_path / "marks.json"
    p.write_text("{ this is not json", encoding="utf-8")
    with pytest.raises(mark.MarkError):
        mark.merge_and_write(p, {"a": {"status": "open"}}, [])
    assert p.read_text(encoding="utf-8") == "{ this is not json", \
        "a corrupt file became a lost one"


def test_the_workflow_asks_no_model_unless_a_dispatch_opts_in():
    yml = (Path(__file__).resolve().parents[1] / ".github" / "workflows"
           / "mark.yml").read_text(encoding="utf-8")
    assert 'cron: "0 5 * * 2-6"' in yml, "the 03:00 collision must be gone"
    assert 'cron: "0 3 * * 2-6"' not in yml
    assert "use_model" in yml
    assert 'args="$args --no-model"' in yml
