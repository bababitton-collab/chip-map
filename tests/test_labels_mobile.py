"""Station names on a phone: nothing sits on a ring, and a tap opens the chain.

At 390 and 430px the map keeps its columns -- the canvas has a 900px minimum
inside a sideways scroll container -- so L4 is a column there exactly as it is
on a desktop, and NVIDIA's name sat on AVGO's ring at every width. A name whose
box would reach the next ring moves beside its dot instead, outward from the
column (right in English, left in Hebrew) on a dark plate. window.__labelBoxes
reports where each name went, so this can be measured rather than eyeballed.

The touch check drives the canvas with a real touchscreen: a tap opens focus
mode, a tap on empty canvas leaves it, and one tap is acted on exactly once --
window.__acts counts, so a device that reports both a touch and a mouse cannot
act twice unnoticed.

Skipped where Playwright or its Chromium is missing, and where the snapshots
have not been built.
"""
from __future__ import annotations

import json
import math

import pytest

from chains import build_pages as bp
from chains.paths import out_dir

pw = pytest.importorskip("playwright.sync_api")

LANGS = ("en", "he")
LIVE = {"en": out_dir() / bp.LIVE_EN, "he": out_dir() / bp.LIVE_HE}

pytestmark = pytest.mark.skipif(
    not all(p.exists() for p in LIVE.values()),
    reason="snapshots not built yet; run python -m chains.live_snapshot")

SIZES = [(390, 844), (430, 932), (900, 800), (1280, 900)]
CASES = [(lang, w) for lang in LANGS for w, _ in SIZES]
MIN_RING_GAP = 6        # between two rings in a column, as the layout keeps it
LBL_H = 14              # the label box, as the template draws it
LBL_GAP = 6             # a label beside a dot starts this far out from the ring
TOUCH_AT = (390, 844)

SETTLE = """() => document.fonts.ready.then(() => {
  dispatchEvent(new Event('resize'));
  return new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
})"""


def radius(node: dict) -> float:
    cap = node.get("cap")
    return max(7, min(24, 6 + 18 * math.sqrt(cap / 5516))) if cap else 7


def reach(node: dict, r: float, holders: set[str]) -> float:
    """How far the drawing reaches: a chokepoint holder's ring, or the outline."""
    return r + 5 + 1.25 if node["id"] in holders else r + 1


def centre(box: dict) -> dict:
    """The station's own centre, as the page publishes it beside the name box.

    Deriving it from the box instead is what made this fragile: the box sits
    beside the dot when the name would land on the ring below, and its width
    changes the moment the web font lands, so an inverted box can be a
    station's width out of date and a click lands on nothing.
    """
    return {"x": box["nx"], "y": box["ny"]}


def overlaps(a: dict, b: dict) -> bool:
    return (a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"]
            and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"])


def on_ring(box: dict, s: dict) -> bool:
    cx = min(max(s["x"], box["x"]), box["x"] + box["w"])
    cy = min(max(s["y"], box["y"]), box["y"] + box["h"])
    return math.hypot(s["x"] - cx, s["y"] - cy) <= s["reach"]


@pytest.fixture(scope="module")
def pages(tmp_path_factory):
    d = tmp_path_factory.mktemp("maps")
    en_tpl = d / "live-map-en.html"
    bp.build_en_template(dst=en_tpl)
    en, _ = bp.build_public_en(template=en_tpl, live=LIVE["en"],
                               out=d / "public-map-en.html")
    he, _ = bp.build_public_he(live=LIVE["he"], out=d / "public-map.html")
    return {"en": en, "he": he}


@pytest.fixture(scope="module")
def measured(pages):
    """Every (language, width) rendered once, as stations with their name boxes."""
    out = {}
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as e:                      # no browser downloaded
            pytest.skip(f"Playwright has no Chromium: {type(e).__name__}")
        try:
            for lang, path in pages.items():
                live = json.loads(LIVE[lang].read_text(encoding="utf-8"))
                nodes = {n["id"]: n for n in live["nodes"]}
                holders = {h["id"] for c in live["cps"] for h in c["holders"]}
                for w, h in SIZES:
                    page = browser.new_page(viewport={"width": w, "height": h})
                    page.goto(path.as_uri())
                    page.wait_for_function("window.__labelBoxes && window.__labelBoxes().length")
                    page.evaluate(SETTLE)
                    boxes = page.evaluate("() => window.__labelBoxes()")
                    page.close()
                    st = {}
                    for b in boxes:
                        n = nodes[b["id"]]
                        r = radius(n)
                        st[b["id"]] = dict(centre(b), id=b["id"], box=b, r=r,
                                           layer=n.get("layer"),
                                           reach=reach(n, r, holders))
                    out[(lang, w)] = st
        finally:
            browser.close()
    return out


def columns(st: dict) -> dict:
    """The stations of each column, top to bottom. L9 is a row, not a column."""
    cols: dict = {}
    for s in st.values():
        if s["layer"] and s["layer"] != "L9":
            cols.setdefault(s["layer"], []).append(s)
    return {L: sorted(g, key=lambda s: s["y"]) for L, g in cols.items()}


# -- nothing lands on anything ------------------------------------------------
@pytest.mark.parametrize("lang,width", CASES)
def test_no_station_name_sits_on_another_stations_ring(measured, lang, width):
    """The bug: NVIDIA's name under its dot reached AVGO's ring in L4."""
    st = measured[(lang, width)]
    bad = [(a["id"], b["id"]) for a in st.values() for b in st.values()
           if a["id"] != b["id"] and on_ring(a["box"], b)]
    assert bad == []


@pytest.mark.parametrize("lang,width", CASES)
def test_no_two_station_names_overlap(measured, lang, width):
    st = sorted(measured[(lang, width)].values(), key=lambda s: s["box"]["x"])
    bad = [(a["id"], b["id"]) for i, a in enumerate(st) for b in st[i + 1:]
           if overlaps(a["box"], b["box"])]
    assert bad == []


@pytest.mark.parametrize("lang,width", CASES)
def test_rings_in_a_column_keep_six_pixels(measured, lang, width):
    for L, g in columns(measured[(lang, width)]).items():
        for a, b in zip(g, g[1:]):
            gap = (b["y"] - b["reach"]) - (a["y"] + a["reach"])
            assert gap >= MIN_RING_GAP - 0.5, (L, a["id"], b["id"], round(gap, 2))


# -- and a name moves only when it has to -------------------------------------
@pytest.mark.parametrize("lang,width", CASES)
def test_a_name_leaves_its_dot_only_to_clear_the_next_ring(measured, lang, width):
    """Under the dot wherever the box fits; beside it exactly where it would
    reach the ring below. The last station in a column always has room."""
    for L, g in columns(measured[(lang, width)]).items():
        for a, b in zip(g, g[1:]):
            crowded = a["y"] + a["r"] + 5 + LBL_H > b["y"] - b["reach"] - 2
            assert (a["box"]["side"] != "below") == crowded, \
                (lang, width, L, a["id"], a["box"]["side"], round(a["y"], 1), round(b["y"], 1))
        assert g[-1]["box"]["side"] == "below", (L, g[-1]["id"])


@pytest.mark.parametrize("lang,width", CASES)
def test_a_moved_name_goes_outward_from_the_column(measured, lang, width):
    """Right where the page reads left to right, left where it reads right to
    left -- and never back across its own dot."""
    want = "left" if lang == "he" else "right"
    for s in measured[(lang, width)].values():
        side = s["box"]["side"]
        if side == "below":
            continue
        assert side == want, (s["id"], side)
        if want == "right":
            assert s["box"]["x"] >= s["x"] + s["r"] + LBL_GAP - 0.5, s["id"]
        else:
            assert s["box"]["x"] + s["box"]["w"] <= s["x"] - s["r"] - LBL_GAP + 0.5, s["id"]


# -- the tap ------------------------------------------------------------------
def _tap_target(page, sid: str, nodes: dict):
    """Where to put a finger for this station, with its column scrolled into view."""
    b = page.evaluate("id => window.__labelBoxes().find(b => b.id === id)", sid)
    c = centre(b)
    # Scroll by a delta, not to an absolute offset: in a right-to-left container
    # scrollLeft runs from 0 at the right edge into negative numbers, so
    # clamping it at 0 pins the map to its right edge and the finger lands off
    # the canvas entirely.
    page.evaluate("""x => { const w = document.querySelector('.mapwrap'); if (!w) return;
        const r = document.getElementById('map').getBoundingClientRect();
        w.scrollLeft += (r.left + x) - w.clientWidth / 2; }""", c["x"])
    r = page.evaluate("""() => { const r = document.getElementById('map').getBoundingClientRect();
        return {left: r.left, top: r.top, height: r.height}; }""")
    y = r["top"] + c["y"]
    vh = page.viewport_size["height"]
    if not 20 <= y <= vh - 20:
        page.evaluate("dy => window.scrollBy(0, dy)", y - vh / 2)
        r = page.evaluate("""() => { const r = document.getElementById('map').getBoundingClientRect();
            return {left: r.left, top: r.top, height: r.height}; }""")
    return r["left"] + c["x"], r["top"] + c["y"]


def _empty_spot(page):
    """A point on the canvas, inside the phone's screen, that focus mode drew
    nothing on: no supplier label, no caption, not the focused station."""
    f = page.evaluate("() => window.__focus()")
    r = page.evaluate("""() => { const q = document.getElementById('map').getBoundingClientRect();
        return {left: q.left, top: q.top, w: q.width, h: q.height}; }""")
    vp = page.viewport_size
    boxes = ([l["box"] for l in f["labels"]] + [l["box"] for l in f["labels2"]]
             + [c["box"] for c in f["captions"]] + [f["nameBox"]])
    for gy in range(20, int(r["h"]) - 20, 16):
        for gx in range(20, int(r["w"]) - 20, 16):
            x, y = r["left"] + gx, r["top"] + gy
            if not (12 <= x <= vp["width"] - 12 and 12 <= y <= vp["height"] - 12):
                continue
            if math.hypot(gx - f["centre"]["x"], gy - f["centre"]["y"]) < 160:
                continue
            if any(b["x0"] - 12 <= gx <= b["x1"] + 12 and b["y0"] - 12 <= gy <= b["y1"] + 12
                   for b in boxes):
                continue
            return x, y
    raise AssertionError("no empty spot on the canvas to tap")


@pytest.mark.parametrize("lang", LANGS)
def test_a_tap_opens_focus_leaves_it_and_acts_once(pages, lang):
    w, h = TOUCH_AT
    nodes = {n["id"]: n for n in json.loads(LIVE[lang].read_text(encoding="utf-8"))["nodes"]}
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as e:
            pytest.skip(f"Playwright has no Chromium: {type(e).__name__}")
        ctx = browser.new_context(viewport={"width": w, "height": h},
                                  device_scale_factor=3, is_mobile=True, has_touch=True)
        page = ctx.new_page()
        try:
            page.goto(pages[lang].as_uri())
            page.wait_for_function("window.__labelBoxes && window.__focus && window.__acts === 0")
            page.evaluate(SETTLE)

            x, y = _tap_target(page, "nvda", nodes)
            page.touchscreen.tap(x, y)
            page.wait_for_timeout(900)
            assert page.evaluate("() => window.__focus() && window.__focus().id") == "nvda"
            assert page.evaluate("() => window.__acts") == 1, "one tap, one action"

            # Empty canvas. Not the corner: the canvas is wider than the phone
            # and scrolled, so its left edge is off-screen. The point is picked
            # from what focus mode says it drew.
            page.touchscreen.tap(*_empty_spot(page))
            page.wait_for_timeout(900)
            assert page.evaluate("() => window.__focus()") is None
            assert page.evaluate("() => window.__acts") == 2
        finally:
            ctx.close()
            browser.close()
