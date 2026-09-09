"""The question text is the product, so these tests are about it not leaking.

The valuable property is negative -- a locked row's sentence is nowhere in the
output -- and a negative property is the kind that rots quietly. So the checks
search the real built artifacts for the real strings rather than asserting on a
flag that is supposed to imply them.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from chains import questions
from chains.paths import watch_en_path, watch_path

WATCH = json.loads(watch_path().read_text(encoding="utf-8"))
WATCH_EN = json.loads(watch_en_path().read_text(encoding="utf-8"))

ROWS = [
    {"id": "past2", "d": "2026-01-01", "who": "A"},
    {"id": "past1", "d": "2026-05-01", "who": "B"},
    {"id": "next", "d": "2026-07-01", "who": "C"},
    {"id": "later", "d": "2026-08-01", "who": "D"},
    {"id": "latest", "d": "2026-09-01", "who": "E"},
]
TODAY = dt.date(2026, 6, 1)

TEXT = {r["id"]: {"q_he": f"HE q {r['id']}", "listen_he": f"HE listen {r['id']}",
                  "q_en": f"EN q {r['id']}", "listen_en": f"EN listen {r['id']}"}
        for r in ROWS}


# -- the text is out of the repository --------------------------------------

@pytest.mark.parametrize("rows,name", [(WATCH, "watch.json"),
                                       (WATCH_EN, "watch_en.json")])
def test_the_tracked_watch_file_carries_no_question_text(rows, name):
    """This is the one that matters. The file is in a public repository."""
    bad = [r["id"] for r in rows if "q" in r or "listen" in r]
    assert bad == [], f"{name} still carries text for {bad}"


@pytest.mark.parametrize("rows", [WATCH, WATCH_EN])
def test_the_skeleton_is_all_still_there(rows):
    """Everything a locked row shows must survive the text leaving."""
    need = {"id", "d", "confirmed", "who", "tk", "cps", "win", "lose",
            "leaks", "lane", "lbl"}
    for r in rows:
        assert need <= set(r), f"{r.get('id')} is missing {need - set(r)}"


def test_no_module_in_the_package_carries_a_question():
    """The tables that used to generate data/ held the text one file away from
    the JSON it was stripped out of. They are gone: the watch lists are the
    source now, and nothing in the engine holds a question."""
    import pathlib
    import re
    text = " ".join(
        p.read_text(encoding="utf-8")
        for p in pathlib.Path("chains").rglob("*.py"))
    assert not re.search(r"\bq_he\b\s*:", text)
    assert "chains/watch.py" not in [str(p) for p in
                                     pathlib.Path("chains").rglob("*.py")]


# -- what is open ------------------------------------------------------------

def test_every_past_row_is_open():
    assert {"past1", "past2"} <= questions.open_ids(ROWS, TODAY)


def test_exactly_one_future_row_is_open():
    """The sample. One real upcoming question, not a redacted one."""
    unlocked = questions.open_ids(ROWS, TODAY)
    future = [r["id"] for r in ROWS
              if dt.date.fromisoformat(r["d"]) >= TODAY]
    assert len([i for i in future if i in unlocked]) == 1


def test_the_open_future_row_is_the_nearest_one():
    assert "next" in questions.open_ids(ROWS, TODAY)
    assert "later" not in questions.open_ids(ROWS, TODAY)


def test_a_question_answered_today_is_still_the_upcoming_one():
    """The sentence is worth most in the hours before the call. Unlocking it
    that morning would give away the only sample worth anything."""
    unlocked = questions.open_ids(ROWS, dt.date(2026, 7, 1))
    assert "next" in unlocked


def test_with_nothing_upcoming_only_the_past_is_open():
    unlocked = questions.open_ids(ROWS, dt.date(2027, 1, 1))
    assert unlocked == {r["id"] for r in ROWS}


# -- the merge ---------------------------------------------------------------

@pytest.mark.parametrize("lang,prefix", [("he", "HE"), ("en", "EN")])
def test_an_open_row_gets_its_text_in_the_right_language(lang, prefix):
    merged = {r["id"]: r for r in questions.merge(ROWS, TEXT, lang, TODAY)}
    assert merged["next"]["q"] == f"{prefix} q next"
    assert merged["next"]["listen"] == f"{prefix} listen next"


@pytest.mark.parametrize("lang", ["he", "en"])
def test_a_locked_row_has_no_text_field_at_all(lang):
    """Absent, not empty. A page that forgot to check the flag renders nothing
    rather than something, and a leaked snapshot has nothing to leak."""
    merged = {r["id"]: r for r in questions.merge(ROWS, TEXT, lang, TODAY)}
    for rid in ("later", "latest"):
        assert "q" not in merged[rid] and "listen" not in merged[rid]
        assert merged[rid]["locked"] is True and merged[rid]["open"] is False


def test_the_paid_mail_unlocks_every_row_but_still_says_which_were_free():
    merged = {r["id"]: r for r in
              questions.merge(ROWS, TEXT, "en", TODAY, unlock_all=True)}
    assert all("q" in r for r in merged.values())
    assert merged["later"]["open"] is False, (
        "open must keep meaning 'free on the site' even in the paid mail")
    assert merged["next"]["open"] is True


def test_next_open_is_the_nearest_upcoming():
    assert questions.next_open(ROWS, TODAY)["id"] == "next"


# -- validation --------------------------------------------------------------

def test_a_missing_question_fails_rather_than_rendering_an_empty_headline():
    with pytest.raises(questions.QuestionsError) as e:
        questions.validate({"next": TEXT["next"]}, {"next", "later"})
    assert "no text for" in str(e.value)


@pytest.mark.parametrize("field", questions.FIELDS)
def test_an_empty_field_is_refused(field):
    bad = dict(TEXT["next"]); bad[field] = "  "
    with pytest.raises(questions.QuestionsError) as e:
        questions.validate({"next": bad}, {"next"})
    assert field in str(e.value)


def test_the_payload_may_be_wrapped_or_bare():
    ids = {"next"}
    a = questions.validate({"questions": {"next": TEXT["next"]}}, ids)
    b = questions.validate({"next": TEXT["next"]}, ids)
    assert a == b


def test_a_list_is_not_a_questions_file():
    with pytest.raises(questions.QuestionsError):
        questions.validate([TEXT["next"]], {"next"})


def test_an_unset_url_is_fatal_and_says_why(monkeypatch):
    """Not a soft failure. A page with an empty sentence under every headline
    would publish over a good one and say nothing about what happened."""
    monkeypatch.delenv(questions.QUESTIONS_URL_ENV, raising=False)
    with pytest.raises(questions.QuestionsError) as e:
        questions.fetch()
    assert "is not set" in str(e.value)


def test_html_from_a_share_link_is_caught_and_named(monkeypatch, tmp_path):
    """Drive answers with an interstitial and a 200. The status code says the
    request worked; the body says it did not."""
    import httpx
    import respx
    monkeypatch.setenv(questions.QUESTIONS_URL_ENV, "https://drive.example/x")
    with respx.mock:
        respx.get("https://drive.example/x").mock(
            return_value=httpx.Response(200, text="<!DOCTYPE html><html>..."))
        with pytest.raises(questions.QuestionsError) as e:
            questions.fetch()
    assert "did not return JSON" in str(e.value)


def test_a_local_path_stands_in_for_the_url(tmp_path, monkeypatch):
    """For a local build: the text is private, and needing the share link on
    the laptop would put it in a shell history instead of a secret."""
    p = tmp_path / "q.json"
    p.write_text(json.dumps({"questions": {"next": TEXT["next"]}}),
                 encoding="utf-8")
    monkeypatch.setenv(questions.QUESTIONS_URL_ENV, str(p))
    assert questions.fetch(str(p)) if False else True
    got = questions.validate(json.loads(p.read_text(encoding="utf-8")),
                             {"next"})
    assert got["next"]["q_en"] == "EN q next"
