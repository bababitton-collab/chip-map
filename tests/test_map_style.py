"""The map's surface: the inner shadow, the column bands, the header row.

These are drawings, so most of what matters is checked in a browser -- the
Playwright run measures the real bounding boxes and the real frame cost. What
is checked here is what a browser cannot tell you afterwards: that the pieces
are still wired to each other, and that the colour rule the header rests on is
arithmetically true rather than true by inspection on one screen.
"""
from __future__ import annotations

import re

import pytest

from chains import build_pages as bp
from chains.paths import templates_dir

TPL = (templates_dir() / "live-map.html").read_text(encoding="utf-8")
EN = (templates_dir() / "live-map-en.html").read_text(encoding="utf-8")

BG = "#0b0e14"          # the ground, everywhere: there are no bands
CHIP = "#141922"        # the chip's own background
NAME = "#f3e2b4"        # the layer name, gold and glowing
NUM = "#9ba6b4"         # the L-number
MOCK_NUM = "#9aa4b2"    # what the mock asked for


# -- contrast, computed rather than eyeballed --------------------------------

def luminance(hex_colour: str) -> float:
    """WCAG relative luminance."""
    h = hex_colour.lstrip("#")
    out = 0.0
    for w, i in ((0.2126, 0), (0.7152, 1), (0.0722, 2)):
        c = int(h[i * 2:i * 2 + 2], 16) / 255
        out += w * (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return out


def contrast(fg: str, bg: str) -> float:
    a, b = luminance(fg), luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def test_the_layer_name_clears_ten_to_one_on_the_chip():
    assert contrast(NAME, CHIP) >= 10


def test_the_l_number_clears_seven_to_one_on_the_chip():
    assert contrast(NUM, CHIP) >= 7


def test_the_mock_s_own_number_colour_missed_seven_by_a_hair():
    """#9aa4b2 computes to 6.99:1 on #141922 and the rule beside it asks for 7.
    The colour is one step lighter than the mock -- indistinguishable to look
    at, and the difference between a test that passes and one that nearly
    does."""
    assert contrast(MOCK_NUM, CHIP) < 7
    assert contrast(NUM, CHIP) >= 7
    # The comment above the rule names the mock colour, so the check is on the
    # declaration rather than on the span.
    assert f'.lchip .n{{color:{NUM};' in TPL
    assert f'color:{MOCK_NUM}' not in TPL


# -- no bands ----------------------------------------------------------------

def test_nothing_paints_a_ground():
    """Michael's call: the map is one colour the whole way across. The column
    geometry survives only to place the chips."""
    i = TPL.index("function draw(now){")
    body = TPL[i:i + 1500]
    assert "ctx.fillRect(b.x0,0,b.x1-b.x0,H)" not in body
    assert "b.tone" not in TPL
    assert "#0e121a" not in TPL


def test_the_column_geometry_is_kept_only_to_place_the_chips():
    assert "bands = cols.map(L=>({L:L, x0:xOf[L]-colW/2, x1:xOf[L]+colW/2, "            "cx:xOf[L]}));" in TPL
    assert "left:${b.cx.toFixed(1)}px" in TPL
    assert "transform:translateX(-50%)" in TPL, "centred over its column"


# -- the chip ----------------------------------------------------------------

def chip_css() -> str:
    i = TPL.index(".lchip{")
    return TPL[i:TPL.index("@media (max-width:900px){", i)]


def test_the_chip_is_the_approved_one():
    css = chip_css()
    assert "background:#141922" in css
    assert "border:1px solid #3a3320" in css and "border-radius:5px" in css
    assert "padding:5px 11px" in css
    assert 'font-family:"IBM Plex Mono",monospace' in css
    assert "font-size:.72rem" in css and "letter-spacing:.14em" in css
    assert "text-transform:uppercase" in css


def test_the_chip_carries_the_four_shadows():
    css = chip_css()
    for layer in ("0 1px 0 rgba(255,255,255,.04) inset",
                  "0 0 0 1px rgba(242,182,50,.08)",
                  "0 6px 16px rgba(0,0,0,.45)",
                  "0 0 18px rgba(242,182,50,.10)"):
        assert layer in css, layer


def test_the_name_glows_gold():
    css = chip_css()
    assert (".lchip .t{color:#f3e2b4;font-weight:500;text-shadow:"
            "0 0 6px rgba(242,182,50,.55),0 0 14px rgba(242,182,50,.25)}") in css


def test_the_three_parts_are_separate_spans():
    """So a test can measure each colour, and so the dot is not part of either
    word."""
    assert '<span class="n">${cut(L)}</span><span class="s">·</span>' in TPL
    assert '<span class="t">${cut(name)}</span>' in TPL


def test_the_header_keeps_its_thin_rule():
    assert ".layerbar .rule{position:absolute;top:46px;inset-inline:0;"            "height:1px;background:var(--rule)}" in TPL


# -- L9 is a row, not a column -----------------------------------------------

def test_l9_has_its_own_layer_outside_the_sticky_header():
    """It is a row along the bottom. A chip for it in the header would name a
    column that does not exist."""
    assert '<div class="l9bar" id="l9bar"></div>' in TPL
    assert ".l9bar{position:absolute;inset:0;z-index:2;pointer-events:none}" in TPL
    i = TPL.index("bar.innerHTML = bands.map(")
    j = TPL.index("l9.innerHTML =", i)
    assert 'data-l="L9"' not in TPL[i:j], "no L9 chip among the column chips"
    assert 'data-l="L9"' in TPL[j:j + 300]


def test_the_l9_chip_sits_beside_ceg_on_its_row_s_centre_line():
    """Anchored to the node, not to the map's edge: L9 is a row, and a chip out
    at the edge named nothing in particular. It goes on the far side of CEG
    from the rest of the row, so it never lands between two of its own nodes."""
    assert "const ceg = byId.ceg;" in TPL
    assert "const outer = !others.length || ceg.x <= Math.min(...others);" in TPL
    assert "l9x = outer ? Math.max(8, ceg.x-16-14) : Math.min(W-8, ceg.x+16+14);" in TPL
    assert "left:${l9x.toFixed(1)}px;" in TPL
    assert "top:${l9y.toFixed(1)}px;transform:${shift}" in TPL
    assert "l9y = H-34;" in TPL, "the row the L9 nodes are drawn on"


def test_the_l9_chip_hangs_off_the_side_it_is_anchored_to():
    """Anchored right means the chip's right edge meets CEG; anchored left
    means its left edge does. Without the swap it would sit on top of the node
    it is naming."""
    assert ("const shift = l9anchor==='right' ? 'translate(-100%,-50%)' "
            ": 'translateY(-50%)';") in TPL


def test_the_shut_panel_carries_no_border():
    """The stage's second column is 0px when the panel is shut, but a 1px
    border made that element 1px wide -- one pixel past the viewport, and a
    horizontal scrollbar at every width. The border belongs to the open state,
    which is the only state with anything to divide."""
    assert ".panel{background:var(--panel);overflow:hidden;height:720px}" in TPL
    assert ".stage.open .panel{border-inline-start:1px solid var(--rule)}" in TPL


def test_l9_is_no_longer_painted_on_the_canvas():
    i = TPL.index("function draw(now){")
    assert "'L9 · '" not in TPL[i:i + 1500]


def test_the_node_label_boxes_are_published_for_the_collision_check():
    """The labels are painted, so they have no box the DOM can measure. The
    browser check reads these and asserts no chip lands on one."""
    assert "window.__labelBoxes = () => nodes.map(" in TPL
    assert "n.lw = ctx.measureText(" in TPL
    assert "x:n.x-(n.lw||0)/2, y:n.y+n.r+16-11" in TPL


# -- sticky, and mobile ------------------------------------------------------

def test_the_header_is_sticky_on_the_desktop():
    assert ".layerbar{position:sticky;top:0;height:0;" in TPL


def test_the_narrow_map_scrolls_sideways_and_the_header_rides_with_it():
    """At 390 the seven columns are 35px apart and no chip fits in 35px.
    Inside a scroll container a sticky top:0 sticks to the container rather
    than the page, so the header goes absolute there and travels with the map
    -- which the brief allows."""
    i = TPL.index("@media (max-width:900px){")
    body = TPL[i:TPL.index(".layerbar .rule{top:44px}", i)]
    assert "overflow-x:auto" in body and "min-width:900px" in body
    assert ".layerbar{position:absolute}" in body
    assert "font-size:.62rem" in body and "padding:4px 8px" in body


# -- the inner shadow, on canvas ---------------------------------------------

def inset_js() -> str:
    i = TPL.index("function insetInto(")
    return TPL[i:TPL.index("function draw(now){", i)]


def test_the_ring_subpath_starts_with_a_moveto():
    """arc() does not begin a subpath. Without the moveTo, canvas joins the
    rectangle's corner to the arc's start point and fills the wedge between
    them -- a hard diagonal band straight across every station. It shipped in
    the first build of this and was only visible in a 4x crop."""
    body = inset_js()
    assert re.search(r"g\.rect\([^)]*\);\s*(//[^\n]*\n\s*)*g\.moveTo\(x\+r, y\);"
                     r"\s*g\.arc\(", body), body[:400]


def test_the_shadow_is_the_specified_one():
    body = inset_js()
    assert "g.shadowColor='rgba(0,0,0,.55)'" in body
    assert "g.shadowOffsetY=2" in body
    assert "Math.min(6, r*0.5)" in body, "6 at the biggest station, less below"


def test_the_highlight_is_offset_up_and_left_and_fades_at_seventy_percent():
    body = inset_js()
    assert "const cx=x-r*0.30, cy=y-r*0.40;" in body
    assert "gr.addColorStop(0,'rgba(255,255,255,.10)')" in body
    assert "gr.addColorStop(0.7,'rgba(255,255,255,0)')" in body


def test_every_station_and_every_satellite_gets_it():
    i = TPL.index("function draw(now){")
    body = TPL[i:]
    assert "inset(n.x,n.y,n.r);" in body, "stations"
    assert "inset(x,y,sr);" in body, "satellites"


def test_the_stroke_colours_were_not_touched():
    """The brief kept them. The well goes under the stroke, not over it."""
    i = TPL.index("inset(n.x,n.y,n.r);")
    after = TPL[i:i + 400]
    assert "ctx.strokeStyle=(n===selected||n===hover)?tok('--ink'):tok('--ink3')" in after


def test_the_sprite_cache_is_invalidated_on_resize():
    """The sprites are rasterised at the current device pixel ratio."""
    i = TPL.index("function resize(){")
    assert "SPR={};" in TPL[i:i + 500]


def test_the_frame_cost_is_published_for_the_check_to_read():
    """rAF fires on vsync, so the interval between frames is 16.7 ms whether
    the work took one millisecond or fifteen. The check reads this instead."""
    assert "window.__frameMs=performance.now()-_fs;" in TPL


# -- the same treatment in SVG -----------------------------------------------

def test_the_filter_is_defined_once():
    assert TPL.count('<filter id="inset"') == 1
    assert TPL.count('<radialGradient id="hilite"') == 1
    assert EN.count('<filter id="inset"') == 1


def test_the_filter_is_the_specified_one():
    i = TPL.index('<filter id="inset"')
    body = TPL[i:TPL.index("</filter>", i)]
    assert 'x="-20%" y="-20%" width="140%" height="140%"' in TPL[i:i + 120]
    assert 'stdDeviation="3"' in body and 'dy="2"' in body
    assert 'operator="arithmetic" k2="-1" k3="1"' in body
    assert 'flood-opacity=".55"' in body


def test_the_gradient_is_offset_and_stops_at_seventy_percent():
    i = TPL.index('<radialGradient id="hilite"')
    body = TPL[i:TPL.index("</radialGradient>", i)]
    assert 'cx="35%" cy="30%" r="70%"' in TPL[i:i + 90]
    assert 'stop-opacity=".10"' in body and 'stop-opacity="0"' in body


@pytest.mark.parametrize("where", [
    'r="${r}" fill="#0b0e14" stroke="${col}" stroke-width="2" filter="url(#inset)"',
    'r="${R2R}" fill="#0b0e14" stroke="${col}"',
    'r="22" fill="#0b0e14" stroke="#e8ecf2" stroke-width="2.2" filter="url(#inset)"',
])
def test_the_constellation_nodes_are_inset(where):
    assert where in TPL


def test_every_inset_circle_has_a_highlight_two_pixels_inside_it():
    assert TPL.count('fill="url(#hilite)" pointer-events="none"') == 5


def test_the_countdown_ring_gets_an_inner_disc_to_be_inset():
    """It had none -- the number sat straight on the card. The disc is the
    thing the shadow is cast into."""
    assert TPL.count('<circle cx="59" cy="59" r="47" fill="#141922" '
                     'filter="url(#inset)"/>') == 2, "the countdown and the mark"


def test_the_english_page_carries_the_same_filter():
    assert bp.hebrew_runs(EN[EN.index("<filter"):EN.index("</defs>")]) == []
    assert 'filter="url(#inset)"' in EN
