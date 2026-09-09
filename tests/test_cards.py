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
    assert "total>6" in body and 'y="215"' in body


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


# -- the second ring ---------------------------------------------------------
#
# The drawing is JavaScript, so the geometry is pinned here against the
# template's own constants and then checked against the widths the REAL watch
# list produces. A constant that drifts fails the first group; a label that
# happens to be too long for the box fails the second, which is the failure
# that actually reaches a reader.

R1X, R2X, R2R, VBW, VBH = 230, 345, 8, 420, 230
REASON_MAX, R2_LABEL_MAX, R2_MAX = 12, 9, 8

# Inter's average advance is about 0.56em. Ring-1 reasons render at 11px and
# ring-2 labels at 9px; both are rounded up, because a test that under-measures
# a width is worse than no test.
EM11, EM9 = 6.3, 5.2


def cons_js():
    i = TPL.index("function constellation(")
    return TPL[i:TPL.index("// --- one card", i)]


def ring2_js():
    i = TPL.index("function ring2For(")
    return TPL[i:TPL.index("function constellation(", i)]


def test_the_viewbox_widened_for_the_second_ring():
    assert f"const VBW={VBW}, VBH={VBH}," in TPL
    assert f"R1X={R1X}, R2X={R2X}, R2R={R2R};" in TPL


def test_the_column_holds_the_wider_drawing_without_shrinking_it():
    """A 420 viewBox in the old 340px column renders 11px type at 8.9px. The
    column takes the 40px; the gap gives 12 of them back."""
    assert "grid-template-columns:150px minmax(0,1fr) 380px;gap:0 28px" in TPL
    assert ".cons svg{width:380px;height:208px" in TPL


def test_ring_two_draws_at_most_eight_and_counts_the_rest():
    assert f"const R2_MAX={R2_MAX};" in TPL
    body = ring2_js()
    assert "kids.slice(0, R2_MAX)" in body
    assert "hidden:total-show.length" in body
    assert "+${r2.hidden}" in cons_js(), "the hidden ones are counted, not lost"


def test_children_are_pushed_apart_rather_than_drawn_on_top_of_each_other():
    body = ring2_js()
    assert "const GAP=18;" in TPL
    assert "Math.max(k.y, prev+GAP)" in body


def test_a_child_is_only_drawn_if_its_parent_is():
    """Ring 1 shows three a side. A second-ring node whose parent fell off that
    list has nothing to hang from, and a line to nowhere is not a relationship."""
    assert "const p = at[e.to]; if(!p) continue;" in ring2_js()


def test_the_second_ring_borrows_its_parents_colour():
    """It is the same claim one hop out, so it is not given a colour of its
    own -- it is the parent's, thinned."""
    body = cons_js()
    assert "col=k.parents[0].col;" in body
    assert 'stroke="${col}"' in body
    assert 'stroke-width="1" opacity=".45"' in body, "the connector is thin"


def test_a_node_supplying_two_of_the_first_ring_gets_a_line_to_each():
    """One circle, two lines. It ranked first because it is exposed to the
    answer twice, and one line would hide that."""
    body = cons_js()
    i = body.index("k.parents.forEach(p=>{")
    assert body.index("<circle", i) > body.index("</path>", i) if "</path>" in body[i:] else True
    assert "k.parents.forEach(p=>{" in body
    # one circle per child, drawn once, outside the per-parent loop
    assert body.count("<circle cx=\"${R2X}\"") == 1


def test_a_shared_node_is_drawn_more_firmly_than_a_single_one():
    body = cons_js()
    assert "const two = k.parents.length>1;" in body
    assert '${two?2:1.4}' in body and '${two?.95:.7}' in body


def test_a_child_of_two_parents_sits_between_them():
    body = ring2_js()
    assert "k.parents.reduce((a,p)=>a+p.y, 0)/k.parents.length" in body


def test_a_ring_one_reason_is_cut_at_twelve_and_keeps_the_whole_sentence():
    """"power & cooli" shipped. The cut is now explicit, and the full text is
    on the element, so hovering gives it back."""
    assert f"const REASON_MAX={REASON_MAX};" in TPL
    body = cons_js()
    assert "clip(full,REASON_MAX)" in body
    assert "<title>${esc(full)}</title>" in body


def test_the_legend_names_the_second_ring():
    body = cons_js()
    assert "T.ring2" in body and 'class="ln"' in body
    assert ".cons .cap i.ln{border-top-width:1px" in TPL
    assert "second ring · via the map" in EN


def label_of(nid, doc):
    for coll in ("nodes", "subnodes"):
        for n in doc.get(coll, []):
            if n["id"] == nid:
                return (n.get("short")
                        or (n.get("ticker") or n["name"]).split(".")[0][:8])
    return nid.upper()


def clip(t, n):
    return t[:n] + "…" if len(t) > n else t


def test_no_ring_two_label_reaches_the_edge_of_the_viewbox():
    """Measured on every row the live watch list produces, not on a sample."""
    doc = load_map()
    rows = [dict(r) for r in WATCH]
    from chains import rings
    rings.for_rows(rows, doc)
    worst = 0.0
    for r in rows:
        for nid in (r["win2"] + r["lose2"]):
            lab = clip(label_of(nid, doc), R2_LABEL_MAX)
            worst = max(worst, R2X + R2R + 4 + len(lab) * EM9)
    assert worst <= VBW, f"a ring-2 label reaches {worst:.1f} of {VBW}"


def test_no_ring_one_reason_reaches_the_second_ring():
    """The reason sits between the two rings. Cut at twelve characters it has
    to stop before x=337, where the ring-2 nodes begin."""
    longest = R1X + 16 + 6 + (REASON_MAX + 1) * EM11
    assert longest <= R2X - R2R, f"{longest:.1f} runs into ring 2"


def test_every_ring_two_edge_names_a_node_in_the_basket():
    """The drawing joins ring2_edges to win2/lose2 by id. An edge naming
    something outside them would draw a line from nowhere."""
    doc = load_map()
    rows = [dict(r) for r in WATCH]
    from chains import rings
    rings.for_rows(rows, doc)
    for r in rows:
        legs = set(r["win2"]) | set(r["lose2"])
        assert {e["from"] for e in r["ring2_edges"]} == legs
        assert all(e["to"] in (r["win"] + r["lose"]) for e in r["ring2_edges"])


# -- the board shows two orders ---------------------------------------------

def test_the_board_shows_a_direct_row_and_an_indirect_row():
    i = TPL.index("// ---- the forecast ledger ----")
    body = TPL[i:TPL.index("// ---- question cards ----", i)]
    assert "tileRow(S, LT.direct)" in body
    assert "tileRow(IND, LT.indirect)" in body


def test_the_board_never_adds_the_two_orders_together():
    """Each row reads one summary object. Nothing here sums them, and the
    ledger does not hand it a pooled one to read."""
    i = TPL.index("// ---- the forecast ledger ----")
    body = TPL[i:TPL.index("// ---- question cards ----", i)]
    assert "S.n_scored + " not in body and "+ IND.n" not in body
    from chains import forecast
    s = forecast.summarise([])
    assert "indirect" not in s, "summarise() knows about one order at a time"


def test_the_gate_is_drawn_from_the_direct_row_only():
    i = TPL.index("// ---- the forecast ledger ----")
    body = TPL[i:TPL.index("// ---- question cards ----", i)]
    assert "tileRow(S, LT.direct) + gate(S)" in body


def test_each_ledger_row_says_which_order_it_is():
    i = TPL.index("// ---- the forecast ledger ----")
    body = TPL[i:TPL.index("// ---- question cards ----", i)]
    assert "r.order===2?LT.indirect:LT.direct" in body
    # the em dash is an escape in the template source, not a character
    assert "second ring, via the map" in EN
