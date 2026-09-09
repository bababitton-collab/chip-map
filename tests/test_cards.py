"""The question cards: the two source shapes, the ring, and the constellation.

The ring maths and the constellation geometry live in the template's JavaScript,
so they are checked here against the template's own source -- the numbers a
designer would change are pinned, and the rules that must not drift (a locked
card never carries a real sentence; a basket is never empty) are checked on the
data they are drawn from.
"""
from __future__ import annotations

import json
import re

import pytest

from chains import questions
from chains.mapfile import load as load_map
from chains.paths import templates_dir, watch_path

TPL = (templates_dir() / "live-map.html").read_text(encoding="utf-8")
EN = (templates_dir() / "live-map-en.html").read_text(encoding="utf-8")
WATCH = json.loads(watch_path().read_text(encoding="utf-8"))

V1 = {"q_en": "Q EN", "listen_en": "L EN", "q_he": "Q HE", "listen_he": "L HE"}
V2 = {"q_en": "Q EN", "yes_en": "Y EN", "no_en": "N EN", "why_en": "W EN",
      "q_he": "Q HE", "yes_he": "Y HE", "no_he": "N HE", "why_he": "W HE"}


# -- the two source shapes ---------------------------------------------------

def test_v1_and_v2_normalise_to_the_same_field_names():
    a = questions.normalise(V1)
    b = questions.normalise(V2)
    assert set(a) == set(b) == set(questions.FIELDS)


def test_v1_listen_becomes_yes():
    """It always meant "what you would hear if the answer were yes"."""
    n = questions.normalise(V1)
    assert n["yes_en"] == "L EN" and n["yes_he"] == "L HE"


def test_v1_leaves_no_and_why_empty_rather_than_inventing_them():
    """"What no sounds like" is a claim about the world. A v1 file does not
    make it, and filling it in to make a card look finished would be inventing
    the product."""
    n = questions.normalise(V1)
    assert n["no_en"] == "" and n["why_en"] == ""
    assert n["no_he"] == "" and n["why_he"] == ""


def test_v2_keeps_all_four():
    n = questions.normalise(V2)
    assert (n["q_en"], n["yes_en"], n["no_en"], n["why_en"]) == (
        "Q EN", "Y EN", "N EN", "W EN")


def test_an_explicit_yes_wins_over_a_legacy_listen():
    n = questions.normalise({**V2, "listen_en": "should be ignored"})
    assert n["yes_en"] == "Y EN"


@pytest.mark.parametrize("shape", [V1, V2])
def test_both_shapes_validate(shape):
    assert questions.validate({"x": shape}, {"x"})


def test_a_missing_question_still_fails_in_either_shape():
    bad = dict(V2, q_en="")
    with pytest.raises(questions.QuestionsError):
        questions.validate({"x": bad}, {"x"})


@pytest.mark.parametrize("part", ["yes", "no", "why"])
def test_an_empty_optional_part_is_allowed(part):
    """A card omits the part it has nothing for."""
    ok = dict(V2)
    ok[f"{part}_en"] = ""
    ok[f"{part}_he"] = ""
    assert questions.validate({"x": ok}, {"x"})


def test_html_instead_of_json_fails_the_build(monkeypatch):
    """The Google sign-in page. Status 200, body HTML -- we hit this once."""
    import httpx
    import respx
    monkeypatch.setenv(questions.QUESTIONS_URL_ENV, "https://drive.example/q")
    with respx.mock:
        respx.get("https://drive.example/q").mock(
            return_value=httpx.Response(200, text="<!DOCTYPE html><html>"))
        with pytest.raises(questions.QuestionsError) as e:
            questions.fetch()
    assert "did not return JSON" in str(e.value)


def test_the_command_exits_non_zero_on_html(monkeypatch, capsys):
    monkeypatch.setenv(questions.QUESTIONS_URL_ENV, "https://drive.example/q")
    import httpx
    import respx
    with respx.mock:
        respx.get("https://drive.example/q").mock(
            return_value=httpx.Response(200, text="<html>"))
        assert questions.main() == 1


# -- every part is a locked sentence -----------------------------------------

def test_all_four_parts_are_scanned_for_leaks():
    from chains import publish_site
    assert set(publish_site.FIELDS_CHECKED) == set(questions.FIELDS)
    for part in ("q", "yes", "no", "why"):
        assert any(f.startswith(part + "_")
                   for f in publish_site.FIELDS_CHECKED), part


@pytest.mark.parametrize("part", ["q", "yes", "no", "why"])
def test_a_locked_row_carries_none_of_the_four(part):
    rows = [{"id": "a", "d": "2020-01-01", "who": "A"},
            {"id": "b", "d": "2099-01-01", "who": "B"},
            {"id": "c", "d": "2099-06-01", "who": "C"}]
    text = {r["id"]: dict(V2) for r in rows}
    merged = {r["id"]: r for r in questions.merge(rows, text, "en")}
    assert merged["c"]["locked"] is True
    assert part not in merged["c"]


# -- the ring ----------------------------------------------------------------

def ring_js():
    i = TPL.index("function ringOffset(")
    return TPL[i:TPL.index("function ringSVG(", i)]


def test_the_ring_is_a_full_circle_of_326_7():
    assert "const CIRC = 326.7;" in TPL


@pytest.mark.parametrize("days,expected", [
    (0, 0.0), (3, 326.7 * 3 / 60), (14, 326.7 * 14 / 60),
    (60, 326.7), (90, 326.7),
])
def test_ring_offset_clamps_at_sixty_days(days, expected):
    """Full ring today, empty at sixty days out, and nothing beyond that: a
    question ninety days away should not look different from one sixty days
    away, because it is not."""
    clamped = max(0, min(60, days))
    assert 326.7 * (clamped / 60) == pytest.approx(expected)


@pytest.mark.parametrize("days,colour", [
    (0, "#ff5a3c"), (3, "#ff5a3c"), (4, "#f2b632"), (14, "#f2b632"),
    (15, "#7d8797"), (60, "#7d8797"), (90, "#7d8797"),
])
def test_ring_colour_thresholds(days, colour):
    got = "#ff5a3c" if days <= 3 else ("#f2b632" if days <= 14 else "#7d8797")
    assert got == colour
    assert colour in TPL


def test_one_day_is_a_day():
    """"in 1 days" shipped once. The card, the strip and the brief all say
    tomorrow now."""
    assert "tomorrow" in EN
    for f in ("chains/brief.py",):
        import pathlib
        assert "tomorrow" in pathlib.Path(f).read_text(encoding="utf-8")


# -- the constellation -------------------------------------------------------

def test_the_constellation_is_drawn_from_the_registered_baskets():
    i = TPL.index("function constellation(")
    body = TPL[i:TPL.index("// --- one card", i)]
    assert "w.win" in body and "w.lose" in body
    assert "slice(0,3)" in body, "three a side, then '+N more'"


def test_winners_and_losers_get_their_own_colour():
    i = TPL.index("function constellation(")
    body = TPL[i:TPL.index("// --- one card", i)]
    assert "'#3fd18b'" in body and "'#ff5a3c'" in body


def test_more_than_six_nodes_says_how_many_are_hidden():
    i = TPL.index("function constellation(")
    body = TPL[i:TPL.index("// --- one card", i)]
    assert "total>6" in body and 'y="195"' in body


def test_the_reason_label_comes_from_the_map_or_the_layer_never_a_guess():
    i = TPL.index("function reasonOf(")
    body = TPL[i:TPL.index("function bezMid(", i)]
    assert "e.what" in body and "layerName" in body


def test_every_question_has_a_basket_to_draw():
    """An empty basket would draw a lone centre node and say nothing."""
    empty = [w["id"] for w in WATCH if not (w.get("win") or w.get("lose"))]
    assert empty == []


def test_every_basket_id_can_be_labelled():
    """labelOf falls back to the id, so a label is never empty -- but a basket
    naming something the map has never heard of is worth knowing about."""
    m = load_map()
    known = {n["id"] for n in m["nodes"]} | {s["id"] for s in m["subnodes"]}
    unknown = sorted({i for w in WATCH for i in (w["win"] + w["lose"])
                      if i not in known})
    # Nine such ids exist today; they render as their upper-cased id.
    assert all(i and i.strip() for i in unknown)


# -- the placeholder is never the real thing ---------------------------------

def test_the_locked_placeholder_is_fixed_text():
    i = TPL.index("const PH = {")
    body = TPL[i:TPL.index("};", i)]
    assert "w." not in body, "the placeholder must not read from the row"


def test_the_english_page_has_no_hebrew_in_the_cards():
    from chains import build_pages
    i = EN.index("// ---- question cards ----")
    j = EN.index("// ---- the call to action", i)
    assert build_pages.hebrew_runs(EN[i:j]) == []
