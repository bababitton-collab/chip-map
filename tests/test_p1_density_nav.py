"""P1: what the page shows, what a keyboard can reach, and what fits.

Five things the audit found, and the rules that replaced them:

  the board      thirty-nine full cards, most of them a blurred placeholder,
                 became three cards and two lists of public metadata
  the map        a canvas with no contents got a stations rail in real HTML
  its height     a fixed 720px on every map became the content's own height
  its header     a long layer name ran past the map and gave the DOCUMENT a
                 horizontal scrollbar
  a phone        "hover a station" on a screen with no hover

The numbers here are the ones in the template, read out of it rather than
copied: a boundary written twice is a boundary that drifts.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from chains.paths import templates_dir

EN = "live-map-en.html"
HE = "live-map.html"


def tpl(name):
    return (templates_dir() / name).read_text(encoding="utf-8")


def const(src, name):
    """The value of a `const NAME = <int>` in the template."""
    m = re.search(rf"\b{name}\s*=\s*(\d+)", src)
    assert m, f"{name} is not declared in the template"
    return int(m.group(1))


def node(script, tmp_path, name="t.js"):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    p = tmp_path / name
    p.write_text(script, encoding="utf-8")
    return subprocess.run(["node", str(p)], capture_output=True,
                          check=True).stdout.decode("utf-8")


def slice_between(src, start, end):
    i = src.index(start)
    j = src.index(end, i)
    return src[i:j]


# -- 3. the forecast board -----------------------------------------------------
def test_the_list_boundaries_are_declared_once():
    src = tpl(EN)
    assert const(src, "FULL_ANSWERED") == 2
    assert const(src, "UPCOMING_ROWS") == 8
    assert const(src, "ANSWERED_ROWS") == 6


def test_the_boundaries_are_used_and_not_retyped():
    """The slices must read the constants. A literal 8 here and a constant
    there is how the control ends up promising a number the list does not
    show."""
    src = tpl(EN)
    assert "upcoming.slice(1), UPCOMING_ROWS" in src
    assert "done.slice(FULL_ANSWERED), ANSWERED_ROWS" in src
    assert "done.slice(0,FULL_ANSWERED)" in src
    assert "upcoming.slice(0,1)" in src


@pytest.mark.parametrize("total,first,hidden", [
    (20, 8, 12), (9, 8, 1), (8, 8, 0), (3, 8, 0),        # upcoming
    (20, 6, 14), (7, 6, 1), (6, 6, 0), (0, 6, 0),        # answered
])
def test_a_list_shows_its_first_n_and_hides_the_rest(total, first, hidden,
                                                     tmp_path):
    """The shipped clist(), run over a synthetic list. Both boundaries, and
    the edges either side of each: one row over, exactly on, and under."""
    src = tpl(EN)
    body = slice_between(src, "const FULL_ANSWERED", "  list.innerHTML =")
    js = """
const T = {conf:'confirmed', exp:'expected', noStatus:'-',
           moreDates:'Show {n} more dates', fewer:'Show fewer',
           upMore:'More dates', doneMore:'Earlier answers'};
const esc = v => String(v==null?'':v);
const markOf = () => '';
const W = [], dayOf = () => 0;
""" + body + """
const rows = Array.from({length: %d}, (_,i)=>(
  {id:'q'+i, d:'2026-10-0'+(i%%9), who:'Co '+i, tk:'T'+i, confirmed:i%%2===0}));
const html = clist('k', rows, %d, 'HEAD');
const liTotal = (html.match(/<li class="crow/g)||[]).length;
const liHidden = (html.match(/<li class="crow extra" hidden/g)||[]).length;
const btn = (html.match(/<button[^>]*class="cmore"[^>]*>([^<]*)</)||[])[1]||null;
process.stdout.write(JSON.stringify({liTotal, liHidden, btn}));
""" % (total, first)
    got = json.loads(node(js, tmp_path))
    assert got["liTotal"] == total
    assert got["liHidden"] == hidden
    if hidden:
        assert got["btn"] == f"Show {hidden} more dates"
    else:
        assert got["btn"] is None, "no control when there is nothing hidden"


def test_the_control_counts_what_is_actually_hidden(tmp_path):
    """Not the list length, and not a number typed into the template."""
    src = tpl(EN)
    body = slice_between(src, "const FULL_ANSWERED", "  list.innerHTML =")
    js = """
const T = {conf:'c', exp:'e', noStatus:'-', moreDates:'Show {n} more dates',
           fewer:'Show fewer', upMore:'U', doneMore:'D'};
const esc = v => String(v==null?'':v);
const markOf = () => '';
const W = [], dayOf = () => 0;
""" + body + """
const mk = n => Array.from({length:n},(_,i)=>({id:'q'+i,d:'2026-10-01',who:'C',tk:'T'}));
process.stdout.write(JSON.stringify({
  up: (clist('u', mk(37), UPCOMING_ROWS, 'U').match(/Show (\\d+) more dates/)||[])[1],
  done: (clist('d', mk(11), ANSWERED_ROWS, 'D').match(/Show (\\d+) more dates/)||[])[1]}));
"""
    got = json.loads(node(js, tmp_path))
    assert got["up"] == "29" and got["done"] == "5"


def test_a_collapsed_row_is_actually_not_rendered():
    """It was not. `.crow{display:grid}` outranks the browser's own
    [hidden]{display:none}, so every row of all thirty-seven drew while the
    element's .hidden property read true -- a property check passed and the
    page was wrong. The attribute has to be restated in the stylesheet."""
    src = tpl(EN)
    assert ".crow[hidden]{display:none}" in src
    # It has to outrank the class rule, which an attribute selector does.
    assert ".crow{display:grid" in src


def test_a_compact_row_carries_only_already_public_metadata(tmp_path):
    """Date, event, ticker, date certainty, answer status. No question text,
    no basket, no diagram -- a locked row has nothing in it to blur, which is
    the point: the old page shipped the placeholder sentence thirty times."""
    src = tpl(EN)
    body = slice_between(src, "const FULL_ANSWERED", "  list.innerHTML =")
    js = """
const T = {conf:'confirmed', exp:'expected', noStatus:'-', moreDates:'m',
           fewer:'f', upMore:'U', doneMore:'D'};
const esc = v => String(v==null?'':v);
const markOf = () => 'refuted';
const W = [], dayOf = () => 0;
""" + body + """
process.stdout.write(clist('u', [{id:'q1',d:'2026-10-22',who:'GE Vernova Q3',
  tk:'GEV',confirmed:false,locked:true,q:'SECRET QUESTION',
  win:['a'],lose:['b']}], 8, 'HEAD'));
"""
    html = node(js, tmp_path)
    for want in ("2026-10-22", "GE Vernova Q3", "GEV", "expected", "refuted"):
        assert want in html, want
    assert "SECRET QUESTION" not in html
    assert "<svg" not in html and "cons" not in html
    assert "blur" not in html


def test_the_access_gate_is_not_repeated_on_every_locked_row():
    """One action for the section, which is what #cta2 is. A gate per locked
    row was thirty copies of the same button."""
    src = tpl(EN)
    body = slice_between(src, "const FULL_ANSWERED", "  list.innerHTML =")
    assert "lockA" not in body and "lockB" not in body
    assert 'id="cta2"' in src


# -- 4. the stations rail ------------------------------------------------------
def test_every_station_is_reachable_as_html_not_only_as_canvas():
    src = tpl(EN)
    assert 'aria-label="Stations"' in src
    assert "function railListHTML()" in src
    assert 'class="rstn"' in src
    # Built from the same node list the canvas draws, not a second copy.
    assert "nodes.filter" in slice_between(src, "function railRows()",
                                           "function railListHTML()")


def test_a_station_button_states_its_facts_as_text():
    src = tpl(EN)
    body = slice_between(src, "function railListHTML()", "function railRender()")
    for field in ("n.ticker", "LAYER_HE[n.layer]", "RAIL.cp", "p.t"):
        assert field in body, field


def test_the_rail_and_the_canvas_draw_one_detail():
    """detailHTML is the function; the panel and the rail both call it. Two
    builders for one station is how the two views start disagreeing."""
    src = tpl(EN)
    assert "function detailHTML(n){" in src
    assert "panel.innerHTML=REC?'':detailHTML(n)" in src
    assert "detailHTML(byId[railOpenId])" in src
    assert src.count("function detailHTML") == 1


def test_selecting_in_the_rail_replaces_the_rail_and_opens_no_second_panel():
    src = tpl(EN)
    body = slice_between(src, "function railRender()", "function railMark(")
    assert "rail.innerHTML" in body
    assert "stage.classList.add('open')" not in body


def test_escape_closes_the_detail_and_returns_focus_to_its_station():
    src = tpl(EN)
    # Escape now backs out one level at a time -- the station detail first,
    # then the drawer -- so the handler is a branch rather than one condition.
    # What this test is about is the first branch.
    key = src[src.index("rail.addEventListener('keydown'"):]
    key = key[:key.index("\n  });") + 6]
    assert "if(ev.key !== 'Escape') return;" in key
    assert "if(railOpenId){" in key and "railClose(); return;" in key
    close = src[src.index("function railClose()"):]
    close = close[:close.index("\n}") + 2]
    assert "railOpenId = null" in close
    assert ".rstn[data-id=" in close and "back.focus()" in close


def test_the_rail_has_a_search_and_a_sort_over_name_layer_and_pulse():
    src = tpl(EN)
    assert 'class="rq"' in src and 'class="rsort"' in src
    for v in ('value="layer"', 'value="name"', 'value="pulse"'):
        assert v in src, v
    assert "railSort==='pulse'" in src and "pulseRank" in src


def test_focus_is_visible_on_everything_the_rail_can_focus():
    src = tpl(EN)
    assert ".srail input:focus-visible" in src
    assert ".srail button:focus-visible" in src
    assert ".railbtn:focus-visible" in src


@pytest.mark.parametrize("rule,why", [
    ("@media (min-width:1440px){ .stage{--rail-w:300px} .srail{display:block} }",
     "docked at 1440 and up"),
    ("@media (min-width:1024px) and (max-width:1439px)", "button between"),
    ("@media (max-width:1023px)", "full width below"),
])
def test_the_rail_docks_opens_and_stacks_at_the_stated_widths(rule, why):
    assert rule in tpl(EN), why


# -- 5. the map's height -------------------------------------------------------
def test_the_height_is_clamped_to_the_stated_range():
    src = tpl(EN)
    assert const(src, "MAP_H_MIN") == 480
    assert const(src, "MAP_H_MAX") == 720
    assert const(src, "MAP_PAD_BOTTOM") == 48


@pytest.mark.parametrize("bottom,want", [
    (300, 480),      # sparse: clamped up off the floor
    (500, 548),      # in range: bottom + 48
    (672, 720),      # exactly the ceiling
    (900, 720),      # dense: clamped down to the old height
])
def test_the_height_follows_the_content_between_the_clamps(bottom, want,
                                                           tmp_path):
    """The arithmetic the fit loop settles on, run on its own."""
    src = tpl(EN)
    js = """
const MAP_H_MIN = %d, MAP_H_MAX = %d, MAP_PAD_BOTTOM = %d;
const want = Math.max(MAP_H_MIN, Math.min(MAP_H_MAX, Math.round(%d + MAP_PAD_BOTTOM)));
process.stdout.write(String(want));
""" % (const(src, "MAP_H_MIN"), const(src, "MAP_H_MAX"),
       const(src, "MAP_PAD_BOTTOM"), bottom)
    assert int(node(js, tmp_path)) == want


def test_the_band_row_is_not_measured_against_a_height_it_defines():
    """Band stations sit at H-34, so including them would make the content's
    bottom a function of the height being computed."""
    src = tpl(EN)
    body = slice_between(src, "function contentBottom()", "function fitHeight()")
    assert "n.layer === BAND" in body and "return" in body


def test_nothing_is_stretched_to_fill_the_new_height():
    """The columns are laid out as before; only the canvas is cut to them.
    A spread that grew with H would defeat the whole item."""
    src = tpl(EN)
    assert "n*52" in src, "the column span cap is what keeps a sparse map short"


def test_recording_and_portrait_keep_their_own_height():
    src = tpl(EN)
    body = slice_between(src, "function fitHeight()", "function contentBottom()") \
        if "function fitHeight()" in src and src.index("function fitHeight()") < src.index("function contentBottom()") \
        else src[src.index("function fitHeight()"):]
    body = body[:body.index("\n}") + 2]
    assert "if(REC" in body
    assert "PORTRAIT_AT" in body


# -- 6. the layer labels -------------------------------------------------------
def test_a_label_wraps_inside_its_column_instead_of_shrinking():
    src = tpl(EN)
    assert "white-space:normal" in src
    assert "function chipBudget(" in src
    body = slice_between(src, "function chipBudget(", "function spreadChips(")
    assert "CHIP_GAP" in body and "maxWidth" in body
    # The type size is not touched to make something fit.
    assert "font-size:.8rem" in src
    # A single word can be wider than its column -- "TRANSMISSION" is, at
    # energy's column width. It may not be truncated and the type may not
    # shrink, so the only thing left is to let the word break: it wrapped
    # before this and still overflowed its box, and the next chip's opaque
    # background drew over the part that stuck out.
    assert "overflow-wrap:anywhere" in src


@pytest.mark.parametrize("cx,w,W,want", [
    (1200, 240, 1280, 1158),    # last chip: pulled back inside
    (10, 200, 1280, 102),       # first chip: pushed inside
    (640, 200, 1280, 640),      # comfortable: untouched
])
def test_the_end_chips_are_clamped_inside_the_map(cx, w, W, want, tmp_path):
    """The /energy/ 1280px bug. A chip pushed past the edge is absolutely
    positioned, so it widens the DOCUMENT and gives the whole page a
    horizontal scrollbar -- the map may scroll sideways, the page may not."""
    js = """
const W = %d, half = %d/2;
let x = %d;
x = Math.max(half+2, Math.min(W-half-2, x));
process.stdout.write(String(Math.round(x)));
""" % (W, w, cx)
    assert int(node(js, tmp_path)) == want


def test_the_header_grows_for_a_wrapped_name_instead_of_overlapping_it():
    src = tpl(EN)
    assert "HEADER_H" in src
    assert "Math.max(70, HEADER_H+24)" in src, \
        "the first row of stations must clear a taller header"


def test_sideways_scroll_belongs_to_the_map_container():
    src = tpl(EN)
    assert ".mapwrap{overflow-x:auto" in src


# -- 7. the section leads ------------------------------------------------------
def test_the_board_lead_is_exactly_what_was_asked_for():
    assert ("Dated questions across the chain. Solid markers have confirmed "
            "answer dates; outlined markers have expected dates.") in tpl(EN)


def test_the_ledger_lead_is_exactly_what_was_asked_for():
    assert ("Resolved questions and their forward market results. Partial "
            "answers remain in the public record but do not enter the "
            "score.") in tpl(EN)


def test_the_mechanics_are_stated_once_and_linked_from_the_board():
    src = tpl(EN)
    assert src.count("<summary>Measurement method</summary>") == 1
    assert 'href="#howscoring"' in src
    assert 'id="howscoring"' in src
    # The long mechanics paragraph is no longer sitting above the lists.
    assert "the baskets were fixed in advance, in a file in git" not in src


# -- 8. the map on a phone -----------------------------------------------------
def test_the_touch_instruction_is_exactly_what_was_asked_for():
    assert ("Swipe sideways to explore layers. Tap a station for details."
            in tpl(EN))


def test_the_hover_instruction_is_not_given_to_a_device_without_hover():
    src = tpl(EN)
    assert "matchMedia('(hover: none)')" in src
    body = slice_between(src, "function touchHint()", "function moreArrow()")
    assert "IS_TOUCH" in body


def test_the_arrow_shows_only_while_there_is_map_to_the_right():
    src = tpl(EN)
    body = slice_between(src, "function moreArrow()", "const CHIP_GAP")
    assert "scrollWidth - wrap.clientWidth - wrap.scrollLeft" in body
    assert "classList.toggle('on'" in body
    assert "addEventListener('scroll'" in body
    assert 'aria-hidden' in body, "decoration for a fact, not content"


def test_the_arrow_is_not_a_child_of_the_thing_that_scrolls():
    """It was. Inside .mapwrap, inset-inline-end:0 pins it to the right edge
    of the 900px-wide CONTENT, so it sat off-screen until the reader had
    scrolled to the end -- visible exactly when it had nothing left to say.
    It is a grid item in the map's cell instead."""
    src = tpl(EN)
    body = slice_between(src, "function moreArrow()", "const CHIP_GAP")
    assert "stage.appendChild(el)" in body
    assert "wrap.appendChild(el)" not in body
    assert ".mapmore{grid-column:1;grid-row:1;justify-self:end" in src


def test_the_hint_sits_at_the_map_and_above_the_stations_list():
    """It rendered after the whole stations list, next to the legend, because
    the rail was added to the stage and the hint was left to auto-flow after
    it. The three rows are placed explicitly now."""
    src = tpl(EN)
    assert ".stage>.maphint{grid-column:1/-1;grid-row:2}" in src
    assert ".stage>.mapwrap{grid-column:1;grid-row:1}" in src
    # Below 1024 the rail drops to the row under the hint.
    assert "grid-row:3" in slice_between(src, "@media (max-width:1023px){",
                                         "\n}")
    # And the element really is inside the stage, before the rail.
    body = slice_between(src, '<div class="stage"', "</div>\n<div class=\"railbtnwrap\"")
    assert body.index('id="maphint"') < body.index('id="srail"')


# -- 9. the relationship diagram on a phone ------------------------------------
def test_below_768_the_inline_diagram_is_replaced_by_a_button():
    src = tpl(EN)
    assert "@media (max-width:767px){" in src
    block = src[src.index("@media (max-width:767px){"):]
    block = block[:block.index("}\n") + 2] + block[:400]
    assert ".qcards .cons{display:none}" in src.replace("\n", "").replace("  ", "")
    assert "View relationships" in src


def test_the_phone_view_has_a_title_a_close_and_the_same_relationships_as_text():
    src = tpl(EN)
    body = slice_between(src, "function relOpen(", "document.addEventListener('click', ev => {\n    const b = ev.target.closest")
    assert "role','dialog'" in body.replace('"', "'")
    assert "aria-modal" in body
    assert "relListHTML(w)" in body and "constellation(w)" in body
    lst = slice_between(src, "function relListHTML(", "function relOpen(")
    assert "w.win" in lst and "w.lose" in lst, "the same split the diagram draws"


def test_closing_the_phone_view_returns_focus_to_the_button():
    src = tpl(EN)
    body = slice_between(src, "const shut = () => {", "const onKey")
    assert "trigger.focus()" in body
    assert "document.contains(trigger)" in body, "never focus a detached node"


def test_the_scroll_is_contained_in_the_diagram_view():
    src = tpl(EN)
    assert ".relbody{flex:1;overflow-y:auto" in src
    assert "documentElement.style.overflow = 'hidden'" in src


def test_the_desktop_diagram_is_untouched():
    """The button is display:none above 768 and the inline .cons still draws."""
    src = tpl(EN)
    assert ".relbtn{display:none" in src
    assert "function constellation(w){" in src


# -- the two templates stay one page -------------------------------------------
def test_the_english_page_is_generated_and_not_hand_written():
    """Every string above is asserted on live-map-en.html, which is built from
    live-map.html by the translation pairs. If a pair is missing, the Hebrew
    survives into the English page and these tests read it."""
    he, en = tpl(HE), tpl(EN)
    for marker in ("function fitHeight()", "function railListHTML()",
                   "function relOpen(", "function chipBudget("):
        assert marker in he and marker in en, marker
