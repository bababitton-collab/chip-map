"""Satellites: the suppliers drawn around a clicked station, in a real browser.

Up to 8 keep the layout they always had, exactly: tests/fixtures/
satellites_small.json holds their positions and labels as the page drew them
before rings existed, captured with the same clicks this file makes. Past 8
they sit on rings -- two for 9 to 16, three for 17 or more -- with at least
22px between neighbouring dots, and every label is placed clear of every other
label, every dot and the station's ring.

Rendered at 900 to 2560px on both maps. Each station is clicked on a freshly
loaded page: opening the panel narrows the canvas, so a click that follows
another would lay out against a different width. NVDA holds no chokepoint and
draws no satellites; it is clicked anyway, to check that nothing is drawn.

Skipped where Playwright or its Chromium is missing -- CI installs neither --
and where the snapshots have not been built. If the map's data changes a
fixture station, regenerate the fixture from the page before touching the
layout code, never after.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from chains import build_pages as bp
from chains.paths import out_dir

pw = pytest.importorskip("playwright.sync_api")

LIVE = {"en": out_dir() / bp.LIVE_EN, "he": out_dir() / bp.LIVE_HE}
FIXTURE = Path(__file__).parent / "fixtures" / "satellites_small.json"

pytestmark = pytest.mark.skipif(
    not all(p.exists() for p in LIVE.values()),
    reason="snapshots not built yet; run python -m chains.live_snapshot")

VIEWPORTS = [(900, 800), (1280, 900), (1920, 1080), (2560, 1440)]
CROWDED = {"shinetsu": 17, "tsmc": 27, "nvda": 0}
SMALL = ["hoya", "tok", "snps", "cdns", "ajinomoto"]
GAP = 22

SETTLE = """() => document.fonts.ready.then(() => {
  dispatchEvent(new Event('resize'));
  return new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
})"""

GEOMETRY = """id => { const c = document.getElementById('map').getBoundingClientRect();
  return {left: c.left, top: c.top, box: window.__labelBoxes().find(b => b.id === id)}; }"""


def radius(node: dict) -> float:
    cap = node.get("cap")
    return max(7, min(24, 6 + 18 * math.sqrt(cap / 5516))) if cap else 7


def click_station(page, sid: str, node: dict) -> None:
    """A real click on the station's centre, scrolled into view first."""
    g = page.evaluate(GEOMETRY, sid)
    b = g["box"]
    cx, cy = b["x"] + b["w"] / 2, b["y"] - 5 - radius(node)
    vh = page.viewport_size["height"]
    if not 20 <= g["top"] + cy <= vh - 20:
        page.evaluate("dy => window.scrollBy(0, dy)", g["top"] + cy - vh / 2)
        g = page.evaluate(GEOMETRY, sid)
    page.mouse.click(g["left"] + cx, g["top"] + cy)
    page.wait_for_timeout(300)


def measure(browser, path: Path, w: int, h: int, sid: str, node: dict) -> dict:
    page = browser.new_page(viewport={"width": w, "height": h})
    try:
        page.goto(path.as_uri())
        page.wait_for_function(
            "window.__labelBoxes && window.__satBoxes && document.querySelector('#l9bar .lchip')")
        page.evaluate(SETTLE)
        click_station(page, sid, node)
        return page.evaluate("() => window.__satBoxes()")
    finally:
        page.close()


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
    out = {}
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as e:                      # no browser downloaded
            pytest.skip(f"Playwright has no Chromium: {type(e).__name__}")
        try:
            for lang, path in pages.items():
                nodes = {n["id"]: n for n in json.loads(
                    LIVE[lang].read_text(encoding="utf-8"))["nodes"]}
                for w, h in VIEWPORTS:
                    for sid in [*CROWDED, *SMALL]:
                        out[(lang, w, sid)] = measure(browser, path, w, h, sid,
                                                      nodes[sid])
        finally:
            browser.close()
    return out


LANGS = ("en", "he")
CROWDED_CASES = [(l, w, s) for l in LANGS for w, _ in VIEWPORTS for s in CROWDED]
SMALL_CASES = [(l, w, s) for l in LANGS for w, _ in VIEWPORTS for s in SMALL]


def _hit(box: dict, x: float, y: float, r: float) -> bool:
    dx = x - max(box["x0"], min(x, box["x1"]))
    dy = y - max(box["y0"], min(y, box["y1"]))
    return dx * dx + dy * dy < r * r


def _intersect(a: dict, b: dict) -> bool:
    return (a["x0"] < b["x1"] and b["x0"] < a["x1"]
            and a["y0"] < b["y1"] and b["y0"] < a["y1"])


# -- crowded stations ----------------------------------------------------------------

@pytest.mark.parametrize("lang,width,sid", CROWDED_CASES)
def test_the_click_opens_the_station_with_all_its_suppliers(measured, lang,
                                                            width, sid):
    m = measured[(lang, width, sid)]
    assert m["station"] and m["station"]["id"] == sid
    assert len(m["sats"]) == CROWDED[sid]


@pytest.mark.parametrize("lang,width,sid", CROWDED_CASES)
def test_the_rings_follow_the_count(measured, lang, width, sid):
    sats = measured[(lang, width, sid)]["sats"]
    n = len(sats)
    if n <= 8:
        return
    rings = {s["ring"] for s in sats}
    assert len(rings) == (2 if n <= 16 else 3), (n, rings)


@pytest.mark.parametrize("lang,width,sid", CROWDED_CASES)
def test_every_dot_keeps_22px_from_its_neighbours(measured, lang, width, sid):
    sats = measured[(lang, width, sid)]["sats"]
    for i, a in enumerate(sats):
        for b in sats[i + 1:]:
            d = math.hypot(a["x"] - b["x"], a["y"] - b["y"])
            assert d >= GAP - 0.01, (a["label"], b["label"], round(d, 2))


@pytest.mark.parametrize("lang,width,sid", CROWDED_CASES)
def test_no_two_labels_intersect_and_none_is_dropped(measured, lang, width, sid):
    sats = measured[(lang, width, sid)]["sats"]
    labs = [s["lab"] for s in sats]
    assert all(lab and not lab.get("hidden") for lab in labs)
    for i, a in enumerate(labs):
        for b in labs[i + 1:]:
            assert not _intersect(a["box"], b["box"]), (a["text"], b["text"])


@pytest.mark.parametrize("lang,width,sid", CROWDED_CASES)
def test_labels_clear_every_dot_and_the_station_ring(measured, lang, width, sid):
    m = measured[(lang, width, sid)]
    st = m["station"]
    for s in m["sats"]:
        box = s["lab"]["box"]
        assert not _hit(box, st["x"], st["y"], st["ring"]), s["label"]
        for t in m["sats"]:
            assert not _hit(box, t["x"], t["y"], t["r"]), (s["label"], t["label"])


@pytest.mark.parametrize("lang,width,sid", CROWDED_CASES)
def test_a_nudged_label_keeps_a_leader_line(measured, lang, width, sid):
    for s in measured[(lang, width, sid)]["sats"]:
        assert s["lab"]["leader"] == s["lab"]["nudged"], s["label"]


@pytest.mark.parametrize("lang,width", [(l, w) for l in LANGS
                                        for w, _ in VIEWPORTS if w >= 1280])
def test_the_spruce_pine_labels_are_drawn_whole(measured, lang, width):
    sats = measured[(lang, width, "shinetsu")]["sats"]
    for want in ("Sibelco", "Quartz Corp"):
        s = next(s for s in sats if s["label"] == want)
        assert s["lab"]["text"] == want, (want, s["lab"]["text"])


# -- stations with 8 or fewer: exactly as before ---------------------------------------

@pytest.mark.parametrize("lang,width,sid", SMALL_CASES)
def test_a_small_station_is_laid_out_exactly_as_before(measured, lang, width, sid):
    want = json.loads(FIXTURE.read_text(encoding="utf-8"))[f"{lang}/{width}/{sid}"]
    got = measured[(lang, width, sid)]["sats"]
    assert 0 < len(got) == len(want) <= 8
    for g, e in zip(got, want):
        assert abs(g["x"] - e["x"]) < 0.01 and abs(g["y"] - e["y"]) < 0.01, (g, e)
        assert (g["tier"], g["label"]) == (e["tier"], e["label"])
        assert g["lab"] is None and g["ring"] is None, "drawn by the old label code"
