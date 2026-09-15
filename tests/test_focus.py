"""Focus mode on the map, in a real browser.

A click on a station dims the map, brings the station to the middle of the
screen and sets every supplier linked straight into it on arcs around it, each
under its full name. Rendered at 900 to 2560px on both maps, with Shin-Etsu,
TSMC and NVDA each clicked on a freshly loaded page, and held to the page's own
record of what it drew (window.__focus):

  (a) no two labels -- names, group captions, the station's own name -- overlap,
  (b) every label is inside the viewport,
  (c) no name is shortened,
  (d) the click did not open the side panel.

At 1280px and wider Shin-Etsu's suppliers all fit. Narrower, suppliers that do
not fit are counted into "+N more" instead of being squeezed in.

Skipped where Playwright or its Chromium is missing -- CI installs neither --
and where the snapshots and focus files have not been built.
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
FOCUS = {"en": out_dir() / bp.FOCUS_EN, "he": out_dir() / bp.FOCUS_HE}

pytestmark = pytest.mark.skipif(
    not all(p.exists() for p in [*LIVE.values(), *FOCUS.values()]),
    reason="snapshots or focus files not built yet; run python -m chains.live_snapshot")

VIEWPORTS = [(900, 800), (1280, 900), (1920, 1080), (2560, 1440)]
STATIONS = ["shinetsu", "tsmc", "nvda"]

SETTLE = """() => document.fonts.ready.then(() => {
  dispatchEvent(new Event('resize'));
  return new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
})"""

GEOMETRY = """id => { const c = document.getElementById('map').getBoundingClientRect();
  return {left: c.left, top: c.top, box: window.__labelBoxes().find(b => b.id === id)}; }"""

STAGE_OPEN = "() => document.getElementById('stage').classList.contains('open')"


def radius(node: dict) -> float:
    cap = node.get("cap")
    return max(7, min(24, 6 + 18 * math.sqrt(cap / 5516))) if cap else 7


def click_station(page, sid: str, node: dict) -> None:
    """A real click on the station's centre, scrolled into view first, then
    long enough for the 300ms focus animation to land."""
    g = page.evaluate(GEOMETRY, sid)
    b = g["box"]
    cx, cy = b["x"] + b["w"] / 2, b["y"] - 5 - radius(node)
    vh = page.viewport_size["height"]
    if not 20 <= g["top"] + cy <= vh - 20:
        page.evaluate("dy => window.scrollBy(0, dy)", g["top"] + cy - vh / 2)
        g = page.evaluate(GEOMETRY, sid)
    page.mouse.click(g["left"] + cx, g["top"] + cy)
    page.wait_for_timeout(900)


def open_page(browser, path, w: int, h: int):
    page = browser.new_page(viewport={"width": w, "height": h})
    page.goto(path.as_uri())
    page.wait_for_function(
        "window.__labelBoxes && window.__focus && document.querySelector('#l9bar .lchip')")
    page.evaluate(SETTLE)
    return page


def nodes_for(lang: str) -> dict:
    return {n["id"]: n for n in json.loads(LIVE[lang].read_text(encoding="utf-8"))["nodes"]}


def expected_total(lang: str, sid: str) -> int:
    f = json.loads(FOCUS[lang].read_text(encoding="utf-8"))
    return len({r["from"] for r in f["up"] if r["to"] == sid and r["from"] != sid})


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
def browser():
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch(headless=True)
        except Exception as e:                      # no browser downloaded
            pytest.skip(f"Playwright has no Chromium: {type(e).__name__}")
        yield b
        b.close()


@pytest.fixture(scope="module")
def measured(pages, browser):
    out = {}
    for lang, path in pages.items():
        nodes = nodes_for(lang)
        for w, h in VIEWPORTS:
            for sid in STATIONS:
                page = open_page(browser, path, w, h)
                try:
                    click_station(page, sid, nodes[sid])
                    out[(lang, w, sid)] = page.evaluate("() => window.__focus()")
                finally:
                    page.close()
    return out


CASES = [(l, w, s) for l in LANGS for w, _ in VIEWPORTS for s in STATIONS]


def _boxes(f: dict) -> list[tuple[str, str, dict]]:
    return ([("label", l["text"], l["box"]) for l in f["labels"]]
            + [("second tier", l["text"], l["box"]) for l in f["labels2"]]
            + [("caption", c["text"], c["box"]) for c in f["captions"]]
            + [("station name", f["id"], f["nameBox"])])


def _intersect(a: dict, b: dict) -> bool:
    return (a["x0"] < b["x1"] and b["x0"] < a["x1"]
            and a["y0"] < b["y1"] and b["y0"] < a["y1"])


@pytest.mark.parametrize("lang,width,sid", CASES)
def test_d_the_click_focuses_without_opening_the_panel(measured, lang, width, sid):
    f = measured[(lang, width, sid)]
    assert f and f["id"] == sid and f["animDone"]
    assert f["panelOpen"] is False


@pytest.mark.parametrize("lang,width,sid", CASES)
def test_a_no_two_labels_overlap(measured, lang, width, sid):
    boxes = _boxes(measured[(lang, width, sid)])
    for i, (ka, ta, a) in enumerate(boxes):
        for kb, tb, b in boxes[i + 1:]:
            assert not _intersect(a, b), (ka, ta, kb, tb)


@pytest.mark.parametrize("lang,width,sid", CASES)
def test_a_labels_keep_clear_of_the_dimmed_layer_tags(measured, lang, width, sid):
    """The layer tags stay on screen, dimmed, and are drawn over the canvas: a
    supplier name or a caption under one would be half hidden."""
    f = measured[(lang, width, sid)]
    assert f["tags"], "the layer tags are measured"
    for kind, text, b in _boxes(f):
        if kind == "station name":
            continue
        for t in f["tags"]:
            assert not _intersect(b, t), (kind, text, t)


@pytest.mark.parametrize("lang,width,sid", CASES)
def test_a_group_caption_sits_beside_its_own_names_or_on_their_radius(measured, lang, width, sid):
    """Beside the names where there is room; otherwise a chip further out, on the
    group's own side of the station, at its angular centre."""
    f = measured[(lang, width, sid)]
    cx, cy = f["centre"]["x"], f["centre"]["y"]
    for c in f["captions"]:
        mine = [l for l in f["labels"] + f["labels2"] if l["group"] == c["key"]]
        assert mine, c
        b = c["box"]
        if not c["chip"]:
            u = {"x0": min(l["box"]["x0"] for l in mine), "x1": max(l["box"]["x1"] for l in mine),
                 "y0": min(l["box"]["y0"] for l in mine), "y1": max(l["box"]["y1"] for l in mine)}
            gap = max(u["y0"] - b["y1"], b["y0"] - u["y1"], 0)
            assert b["x0"] <= u["x1"] and u["x0"] <= b["x1"] and gap <= 6, (c["text"], b, u)
        else:
            assert b["y1"] - b["y0"] <= 18, "a small chip"
            ga = math.atan2(sum(math.sin(math.atan2(l["y"] - cy, l["x"] - cx)) for l in mine),
                            sum(math.cos(math.atan2(l["y"] - cy, l["x"] - cx)) for l in mine))
            ca = math.atan2((b["y0"] + b["y1"]) / 2 - cy, (b["x0"] + b["x1"]) / 2 - cx)
            off = abs((ca - ga + math.pi) % (2 * math.pi) - math.pi)
            assert off <= 0.75, (c["text"], "at its group's angular centre", round(off, 2))
            # The layout measures its radius with x compressed by the screen's
            # aspect, so pixel distances only bound it loosely: the chip is at
            # least as far out as the nearest of its group's dots.
            nearest = min(math.hypot(l["x"] - cx, l["y"] - cy) for l in mine)
            assert math.hypot((b["x0"] + b["x1"]) / 2 - cx, (b["y0"] + b["y1"]) / 2 - cy) >= nearest, \
                (c["text"], "outside its group's dots")


@pytest.mark.parametrize("lang,width,sid", CASES)
def test_every_group_present_has_a_visible_caption(measured, lang, width, sid):
    f = measured[(lang, width, sid)]
    groups = {l["group"] for l in f["labels"] + f["labels2"] if l["group"]}
    keys = {c["key"] for c in f["captions"]}
    assert groups <= keys, f"groups with no caption: {groups - keys}"
    left, top = f["canvas"]["left"], f["canvas"]["top"]
    for c in f["captions"]:
        b = c["box"]
        assert b["x0"] + left >= -0.5 and b["x1"] + left <= f["vw"] + 0.5, c
        assert b["y0"] + top >= -0.5 and b["y1"] + top <= f["vh"] + 0.5, c


@pytest.mark.parametrize("lang,width", [(l, w) for l in LANGS for w, _ in VIEWPORTS if w >= 1280])
def test_shin_etsu_shows_the_spruce_pine_producers_beneath_the_crucible_makers(measured, lang, width):
    f = measured[(lang, width, "shinetsu")]
    kids = {l["id"]: l for l in f["labels2"]}
    for sid in ("sibelco_spruce_pine", "quartz_corp"):
        assert sid in kids, f"{sid} not drawn; second tier {sorted(kids)}"
        k = kids[sid]
        assert k["cp"] is True, "amber ring and amber label"
        assert k["parent"] == "quartz_crucibles"
        assert k["text"] == k["name"] and "…" not in k["text"], "fully readable"
    assert f["more2"] == 0 and len(f["labels2"]) == f["total2"]


@pytest.mark.parametrize("lang,width,sid", CASES)
def test_the_canvas_grows_before_anything_is_counted_into_more(measured, lang, width, sid):
    f = measured[(lang, width, sid)]
    assert f["canvas"]["height"] <= max(f["growMax"], f["baseH"]) + 1
    if f["more"] or f["more2"]:
        assert f["canvas"]["height"] >= min(f["growMax"], 10 ** 6) - 1 or f["growMax"] <= f["baseH"], \
            "suppliers were counted into +N more while the canvas could still grow"


@pytest.mark.parametrize("lang,width,sid", CASES)
def test_no_two_focus_labels_carry_the_same_company_name(measured, lang, width, sid):
    f = measured[(lang, width, sid)]
    names = [l["name"].casefold() for l in f["labels"] + f["labels2"]]
    assert len(names) == len(set(names)), sorted({n for n in names if names.count(n) > 1})


@pytest.mark.parametrize("lang", LANGS)
def test_every_subnode_with_a_note_shows_it_in_its_panel_row(pages, browser, lang):
    """A name cut to a name keeps the rest where a reader can find it: the
    Details panel row for that entry."""
    from chains.paths import map_path
    doc = json.loads(map_path().read_text(encoding="utf-8"))
    live = json.loads(LIVE[lang].read_text(encoding="utf-8"))
    # A chokepoint no station holds has no panel to open; see the next test.
    held = {s["id"] for c in live["cps"] if c["holders"] for s in c["subs"]}
    noted = {s["id"]: s for s in doc["subnodes"] if s.get("note") and s["id"] in held}
    nodes = nodes_for(lang)
    shown = set()
    page = open_page(browser, pages[lang], 1920, 1080)
    try:
        for c in live["cps"]:
            ids = {s["id"] for s in c["subs"]} & set(noted)
            if not ids or not c["holders"]:
                continue
            holder = c["holders"][0]["id"]
            click_station(page, holder, nodes[holder])
            page.keyboard.press("Enter")
            page.wait_for_timeout(300)
            rows = page.evaluate("""() => [...document.querySelectorAll('#panel .sub')].map(r => ({
                name: (r.querySelector('b') || {}).innerText || '',
                note: (r.querySelector('.nt') || {}).innerText || ''}))""")
            for sid in ids:
                got = [r["note"] for r in rows if r["name"] == noted[sid]["name"]]
                assert noted[sid]["note"] in got, (c["id"], sid, got)
                shown.add(sid)
            page.keyboard.press("Escape")
            page.wait_for_timeout(600)
    finally:
        page.close()
    assert shown == set(noted), f"never shown: {sorted(set(noted) - shown)}"


def test_the_notes_with_no_panel_to_show_in_are_the_known_seven():
    """KNOWN GAP, awaiting a decision. CP12 (critical minerals) is held by no
    station, so nothing on the map opens its panel and its supplier rows -- and
    the notes under them -- are shown nowhere. That was already so before the
    names were cleaned. Pinned so the gap cannot quietly grow."""
    from chains.paths import map_path
    doc = json.loads(map_path().read_text(encoding="utf-8"))
    live = json.loads(LIVE["en"].read_text(encoding="utf-8"))
    held = {s["id"] for c in live["cps"] if c["holders"] for s in c["subs"]}
    orphans = {s["id"] for s in doc["subnodes"] if s.get("note") and s["id"] not in held}
    assert orphans == {"cn_antimony", "cn_gallium_primary", "cn_rare_earth_magnets", "cn_tungsten",
                       "sunresin", "teck_trail", "umicore_ge"}
    assert {c["id"] for c in live["cps"] if not c["holders"]} == {"CP12"}


@pytest.mark.parametrize("lang,width,sid", CASES)
def test_the_map_is_dimmed_to_twelve_percent(measured, lang, width, sid):
    assert measured[(lang, width, sid)]["dim"] == pytest.approx(0.88)


@pytest.mark.parametrize("lang,width,sid", CASES)
def test_b_every_label_is_inside_the_viewport(measured, lang, width, sid):
    f = measured[(lang, width, sid)]
    left, top = f["canvas"]["left"], f["canvas"]["top"]
    for kind, text, b in _boxes(f):
        assert b["x0"] + left >= -0.5 and b["x1"] + left <= f["vw"] + 0.5, (kind, text, b)
        assert b["y0"] + top >= -0.5 and b["y1"] + top <= f["vh"] + 0.5, (kind, text, b)


@pytest.mark.parametrize("lang,width,sid", CASES)
def test_c_no_name_is_shortened(measured, lang, width, sid):
    f = measured[(lang, width, sid)]
    for label in f["labels"] + f["labels2"]:
        assert label["text"] == label["name"], label
        assert "…" not in label["text"]


@pytest.mark.parametrize("lang,width,sid", CASES)
def test_every_supplier_is_drawn_or_counted_in_more(measured, lang, width, sid):
    f = measured[(lang, width, sid)]
    assert f["total"] == expected_total(lang, sid)
    assert len(f["labels"]) + f["more"] == f["total"]
    focus = json.loads(FOCUS[lang].read_text(encoding="utf-8"))
    assert f["total2"] == len({(r["from"], r["to"]) for r in focus["under"] if r["at"] == sid})
    assert len(f["labels2"]) + f["more2"] == f["total2"]
    if width < 1280:
        assert f["rings"] <= 2


@pytest.mark.parametrize("lang,width", [(l, w) for l in LANGS for w, _ in VIEWPORTS if w >= 1280])
def test_shin_etsu_fits_whole_at_1280_and_wider(measured, lang, width):
    f = measured[(lang, width, "shinetsu")]
    assert f["more"] == 0 and len(f["labels"]) == f["total"] == 7


@pytest.mark.parametrize("lang,width,sid", CASES)
def test_chokepoint_suppliers_are_marked(measured, lang, width, sid):
    live = json.loads(LIVE[lang].read_text(encoding="utf-8"))
    holders = {h["id"] for c in live["cps"] for h in c["holders"]}
    for label in measured[(lang, width, sid)]["labels"]:
        if label["station"]:
            assert label["cp"] == (label["id"] in holders), label["id"]


TPL_SRC = (bp.templates_dir() if hasattr(bp, "templates_dir") else None)


def _template() -> str:
    from chains.paths import templates_dir
    return (templates_dir() / "live-map.html").read_text(encoding="utf-8")


def test_every_focus_label_sits_on_a_solid_box_and_the_satellites_are_gone():
    import re
    tpl = _template()
    assert "F_BG='rgba(11,14,20,.85)', F_BOX=3, F_DIM=0.88" in tpl
    i = tpl.index("function drawFocus(now){")
    body = tpl[i:tpl.index("\nfunction focusHit(", i)]
    assert "strokeText" not in body and "fLabel(" in body
    assert "html.focusing .l9bar{opacity:.12}" in tpl
    for gone in (r"\bsats\b", r"\bsatT\b", r"__satBoxes", r"satArc", r"satLabels"):
        assert not re.search(gone, tpl), gone


def test_recording_films_focus_mode_unless_legacy_is_asked_for():
    tpl = _template()
    assert "const LEGACY = REC && /[?&]legacy=1(?:&|$)/.test(location.search);" in tpl
    i = tpl.index("cv.addEventListener('click'")
    end = "const n=nodeAt(x,y); if(n) enterFocus(n); else close(); });"
    click = tpl[i:tpl.index(end, i) + len(end)]
    assert "if(LEGACY){ const n=nodeAt(x,y); if(n) open(n); else close(); return; }" in click
    assert "if(REC){" not in click, "a plain ?rec=1 click goes to focus mode"


def test_details_enter_escape_and_refocus(pages, browser):
    nodes = nodes_for("en")
    page = open_page(browser, pages["en"], 1280, 900)
    try:
        click_station(page, "tsmc", nodes["tsmc"])
        f = page.evaluate("() => window.__focus()")
        assert f["id"] == "tsmc" and not f["panelOpen"]
        page.keyboard.press("Enter")
        page.wait_for_timeout(300)
        assert page.evaluate(STAGE_OPEN), "Enter opens the panel"
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        assert page.evaluate("() => window.__focus()") is None, "Escape leaves focus mode"
        assert not page.evaluate(STAGE_OPEN)

        click_station(page, "tsmc", nodes["tsmc"])
        page.click(".focusui .fdetails")
        page.wait_for_timeout(300)
        assert page.evaluate(STAGE_OPEN), "Details opens the panel"
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)

        click_station(page, "tsmc", nodes["tsmc"])
        f = page.evaluate("() => window.__focus()")
        target = next(l for l in f["labels"] if l["station"])
        page.mouse.click(f["canvas"]["left"] + target["x"], f["canvas"]["top"] + target["y"])
        page.wait_for_timeout(900)
        assert page.evaluate("() => window.__focus()")["id"] == target["id"], "a station supplier re-focuses"
    finally:
        page.close()
