"""The power row on the landscape map, measured in a real browser.

L9 is a row along the bottom, not a column. Packed under L7/L6 its six
stations ran into each other at 1920px and the L9 chip sat on three of them.
This renders the built pages at widths from the 900px minimum up to 2560px and
measures what a screenshot shows: the painted station labels (the page
publishes their boxes as ``window.__labelBoxes``), the stations' rings, and
the chip's DOM box.

The map's script is a closure, so a station's radius is not readable from
outside. It is recomputed here from the landscape formula, and the check that
every power station comes out on the row's line (H-34) is what keeps that copy
honest.

Skipped where Playwright or its Chromium is missing -- CI installs neither --
and where the snapshots have not been built.
"""
from __future__ import annotations

import json
import math

import pytest

from chains import build_pages as bp
from chains.paths import out_dir

pw = pytest.importorskip("playwright.sync_api")

LIVE = {"en": out_dir() / bp.LIVE_EN, "he": out_dir() / bp.LIVE_HE}

pytestmark = pytest.mark.skipif(
    not all(p.exists() for p in LIVE.values()),
    reason="snapshots not built yet; run python -m chains.live_snapshot")

# Wider than tall at every width. At 900x1000 the canvas takes 82vh and the
# map turns portrait, where there is no power row to measure.
VIEWPORTS = [(900, 800), (1280, 900), (1920, 1080), (2560, 1440)]
ROW_FROM_BOTTOM = 34
# The station the row starts from, under L4, and the chip's anchor.
FIRST = "hwm"

MEASURE = """() => {
  const c = document.getElementById('map').getBoundingClientRect();
  const box = el => { const r = el.getBoundingClientRect();
    return {x: r.left - c.left, y: r.top - c.top, w: r.width, h: r.height}; };
  const cols = {};
  document.querySelectorAll('#layerbar .lchip').forEach(el => {
    const b = box(el); cols[el.dataset.l] = b.x + b.w / 2; });
  const chip = document.querySelector('#l9bar .lchip');
  return {W: c.width, H: c.height, cols, chip: chip ? box(chip) : null,
          labels: window.__labelBoxes()};
}"""

SETTLE = """() => document.fonts.ready.then(() => {
  dispatchEvent(new Event('resize'));
  return new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
})"""


def radius(node: dict) -> float:
    cap = node.get("cap")
    return max(7, min(24, 6 + 18 * math.sqrt(cap / 5516))) if cap else 7


def overlaps(a: dict, b: dict) -> bool:
    """Strict: boxes that only touch along an edge do not overlap."""
    return (a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"]
            and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"])


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
    """Every (language, width) rendered once, as station geometry."""
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
                    page = browser.new_page(viewport={"width": w, "height": h})
                    page.goto(path.as_uri())
                    page.wait_for_function(
                        "window.__labelBoxes && document.querySelector('#l9bar .lchip')")
                    page.evaluate(SETTLE)
                    m = page.evaluate(MEASURE)
                    page.close()
                    stations = {}
                    for b in m["labels"]:
                        n = nodes[b["id"]]
                        r = radius(n)
                        cx, cy = b["x"] + b["w"] / 2, b["y"] - 5 - r
                        stations[b["id"]] = {
                            "power": n.get("layer") == "L9", "x": cx, "y": cy,
                            "ring": {"x": cx - r, "y": cy - r, "w": 2 * r, "h": 2 * r},
                            "label": b}
                    out[(lang, w)] = dict(m, stations=stations)
        finally:
            browser.close()
    return out


CASES = [(lang, w) for lang in ("en", "he") for w, _ in VIEWPORTS]


def _row(m):
    return {k: s for k, s in m["stations"].items() if s["power"]}


@pytest.mark.parametrize("lang,width", CASES)
def test_the_power_stations_sit_on_the_row_line(measured, lang, width):
    m = measured[(lang, width)]
    row = _row(m)
    assert len(row) == 6
    for k, s in row.items():
        assert abs(s["y"] - (m["H"] - ROW_FROM_BOTTOM)) < 0.6, (k, s["y"], m["H"])


@pytest.mark.parametrize("lang,width", CASES)
def test_the_power_row_runs_from_l4_to_l7_in_equal_steps(measured, lang, width):
    m = measured[(lang, width)]
    xs = sorted(s["x"] for s in _row(m).values())
    ends = sorted((m["cols"]["L4"], m["cols"]["L7"]))
    assert abs((xs[-1] - xs[0]) - (ends[1] - ends[0])) < 1, (xs, ends)
    # The header chips mark the columns. On the Hebrew page at the 900px
    # minimum the canvas overflows right-to-left and the header row is drawn
    # off it, so the ends are compared with the chips only where the chips are
    # on the canvas; the span above holds either way.
    if all(0 <= x <= m["W"] for x in m["cols"].values()):
        assert abs(xs[0] - ends[0]) < 1 and abs(xs[-1] - ends[1]) < 1, (xs, ends)
    gaps = [b - a for a, b in zip(xs, xs[1:])]
    assert max(gaps) - min(gaps) < 0.5, gaps


@pytest.mark.parametrize("lang,width", CASES)
def test_no_two_power_labels_overlap(measured, lang, width):
    row = _row(measured[(lang, width)])
    ids = sorted(row, key=lambda k: row[k]["x"])
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            assert not overlaps(row[a]["label"], row[b]["label"]), (a, b)


@pytest.mark.parametrize("lang,width", CASES)
def test_the_l9_chip_touches_no_station(measured, lang, width):
    m = measured[(lang, width)]
    chip = m["chip"]
    assert chip and chip["w"] > 0
    for k, s in m["stations"].items():
        assert not overlaps(chip, s["ring"]), (k, "ring", chip, s["ring"])
        assert not overlaps(chip, s["label"]), (k, "label", chip, s["label"])


@pytest.mark.parametrize("lang,width", CASES)
def test_the_l9_chip_sits_outside_the_first_station(measured, lang, width):
    """Left of HWM on the English map. The Hebrew source mirrors the columns,
    so there HWM is the rightmost station and the chip sits on its right --
    outside the row either way, never between two stations."""
    m = measured[(lang, width)]
    row, chip = _row(m), m["chip"]
    s = row[FIRST]
    near = [s["ring"], s["label"]]
    if lang == "en":
        assert s["x"] == min(t["x"] for t in row.values())
        assert chip["x"] + chip["w"] <= min(b["x"] for b in near)
    else:
        assert s["x"] == max(t["x"] for t in row.values())
        assert chip["x"] >= max(b["x"] + b["w"] for b in near)
