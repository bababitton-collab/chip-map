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

BG = "#0b0e14"          # odd bands, and the page
BAND2 = "#0e121a"       # even bands
INK2 = "#b3bccb"
INK3 = "#7d8797"


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


@pytest.mark.parametrize("band", [BG, BAND2])
def test_the_header_text_clears_seven_to_one_on_both_bands(band):
    assert contrast(INK2, band) >= 7


def test_ink3_could_not_have_been_used_for_the_l_number():
    """The brief asked for the L-number in --ink3 and for nothing in the header
    darker than #b3bccb. Those cannot both hold: --ink3 tops out at 5.8:1
    against pure black, so no dark band exists on which it reaches 7:1. The
    number is --ink2 at weight 400 and the name --ink2 at 500 -- weight
    separates them, not luminance."""
    assert contrast(INK3, "#000000") < 7
    assert contrast(INK3, BAND2) < 7
    assert 'color:var(--ink3)' not in _header_css()


def _header_css() -> str:
    i = TPL.index(".layerbar{")
    return TPL[i:TPL.index("@media (max-width:900px){.layerbar", i)]


def test_both_halves_of_the_label_are_ink2():
    css = _header_css()
    assert ".layerbar .lbl b{font-weight:400;color:var(--ink2)" in css
    assert ".layerbar .lbl i{font-style:normal;font-weight:500;color:var(--ink2)" in css


def test_the_label_is_mono_uppercase_at_the_specified_size():
    css = _header_css()
    assert 'font-family:"IBM Plex Mono",monospace' in css
    assert "font-size:.72rem" in css and "letter-spacing:.14em" in css
    assert "text-transform:uppercase" in css and "padding:14px" in css


def test_one_thin_rule_under_the_header_row():
    assert ".layerbar .rule{position:absolute;top:46px;inset-inline:0;" \
           "height:1px;background:var(--rule)}" in TPL


# -- the header sticks, the bands do not -------------------------------------

def test_the_label_layer_is_sticky_and_the_bands_are_not():
    """The bands are painted on the canvas, so they scroll with the map -- they
    are the map. Only the labels are pinned."""
    assert ".layerbar{position:sticky;top:0;height:0;" in TPL
    assert "position:sticky" not in TPL[TPL.index("canvas{"):TPL.index(".mapwrap{")]


def test_the_bar_has_no_height_of_its_own():
    """Otherwise it would push the canvas down instead of overlaying it."""
    assert "height:0" in _header_css()


def test_labels_may_wrap_on_a_narrow_screen():
    i = TPL.index("@media (max-width:900px){.layerbar")
    assert "white-space:normal" in TPL[i:i + 200]


def test_the_labels_are_dom_not_canvas():
    """A canvas label scrolls away with the pixels it is drawn on. L9 is not a
    column and keeps its painted label."""
    assert "function layerBar(){" in TPL
    assert "layerBar();" in TPL
    i = TPL.index("function draw(now){")
    body = TPL[i:TPL.index("function nodeAt(", i)] if "function nodeAt(" in TPL \
        else TPL[i:i + 4000]
    assert "fillText(L+' · '" not in body
    assert "'L9 · '" in body


def test_the_label_starts_at_its_band_in_either_direction():
    """The Hebrew page runs right to left and the English one left to right;
    the label sits at the start of its own band on both."""
    assert "getComputedStyle(document.documentElement).direction==='rtl'" in TPL
    assert "rtl ? (W-b.x1) : b.x0" in TPL
    assert "inset-inline-start" in TPL


# -- the bands ---------------------------------------------------------------

def test_seven_bands_alternate_two_tones():
    i = TPL.index("bands = cols.map(")
    body = TPL[i:i + 300]
    assert f"tone: i%2 ? '{BAND2}' : tok('--bg')" in body
    assert "const cols=['L1','L2','L3','L4','L5','L6','L7'];" in TPL


def test_the_outer_bands_reach_the_edges():
    assert "bands[0].x0 = 0; bands[bands.length-1].x1 = W;" in TPL


def test_the_bands_are_painted_before_everything_else():
    i = TPL.index("function draw(now){")
    body = TPL[i:i + 1400]
    assert body.index("bands.forEach(b=>{ ctx.fillStyle=b.tone;") \
        < body.index("edges.forEach") if "edges.forEach" in body else True
    assert "ctx.fillRect(b.x0,0,b.x1-b.x0,H)" in body


def test_no_border_between_bands():
    """The tone change is the boundary. A rule between columns would read as a
    grid the map does not have."""
    i = TPL.index("bands.forEach(b=>{ ctx.fillStyle=b.tone;")
    assert "strokeRect" not in TPL[i:i + 200]


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
