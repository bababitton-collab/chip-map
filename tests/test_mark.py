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

from chains import mark


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


def test_a_row_three_days_back_is_still_due():
    """Three days covers a Friday call reached on Monday."""
    rows = [row("a", "2026-09-08")]
    assert [r["id"] for r in mark.due(rows, marks(), TODAY)] == ["a"]


def test_a_row_four_days_back_is_not():
    rows = [row("a", "2026-09-07")]
    assert mark.due(rows, marks(), TODAY) == []


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

    def __call__(self, row, q, news, key, model):
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
    monkeypatch.setattr("chains.questions.fetch", lambda url=None: {
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
    monkeypatch.setattr("chains.questions.fetch", lambda url=None: {
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
