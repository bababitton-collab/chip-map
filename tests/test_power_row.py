"""The power row and the header chips on the landscape map, in a real browser.

L9 is a row along the bottom, not a column. Its six stations run in equal steps
from under L4 to under L7, and its chip sits above the row, centred on ETN,
its bottom edge 10px over the top of ETN's ring -- lifted straight up only if
a station, a ring or a label would touch it. The layer chips across the top
keep 12px between neighbours, leaving their columns only where two names do
not fit.

This renders the built pages at widths from the 900px minimum up to 2560px and
measures what a screenshot shows: the painted station labels (the page
publishes their boxes as ``window.__labelBoxes``), the stations' rings, and
the chips' DOM boxes. Link lines are not checked against the L9 chip: they run
behind it, and the chip is opaque.

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
TAG_ON = "etn"
TAG_GAP = 10
CHIP_GAP = 12

MEASURE = """() => {
  const c = document.getElementById('map').getBoundingClientRect();
  const box = el => { const r = el.getBoundingClientRect();
    return {x: r.left - c.left, y: r.top - c.top, w: r.width, h: r.height}; };
  const chips = [...document.querySelectorAll('#layerbar .lchip')].map(el =>
    Object.assign(box(el), {L: el.dataset.l, cx: +el.dataset.cx,
                            left: parseFloat(el.style.left)}));
  const tag = document.querySelector('#l9bar .lchip');
  return {W: c.width, H: c.height, chips, tag: tag ? box(tag) : null,
          labels: window.__labelBoxes()};
}"""

SETTLE = """() => document.fonts.ready.then(() => {
  dispatchEvent(new Event('resize'));
  return new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
})"""


def radius(node: dict) -> float:
    cap = node.get("cap")
    return max(7, min(24, 6 + 18 * math.sqrt(cap / 5516))) if cap else 7


def reach(node: dict, r: float, holders: set[str]) -> float:
    """How far the station's drawing reaches: a chokepoint holder's ring at
    r+5 with a 2.5px stroke, or the station's own 2px outline."""
    return r + 5 + 1.25 if node["id"] in holders else r + 1


def overlaps(a: dict, b: dict) -> bool:
    """Strict: boxes that only touch along an edge do not overlap."""
    return (a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"]
            and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"])


def touches(a: dict, b: dict) -> bool:
    """Contact counts: a shared edge is touching."""
    return (a["x"] <= b["x"] + b["w"] and b["x"] <= a["x"] + a["w"]
            and a["y"] <= b["y"] + b["h"] and b["y"] <= a["y"] + a["h"])


def hits_station(rect: dict, s: dict) -> bool:
    cx = min(max(s["x"], rect["x"]), rect["x"] + rect["w"])
    cy = min(max(s["y"], rect["y"]), rect["y"] + rect["h"])
    return (math.hypot(s["x"] - cx, s["y"] - cy) <= s["reach"]
            or touches(rect, s["label"]))


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
                live = json.loads(LIVE[lang].read_text(encoding="utf-8"))
                nodes = {n["id"]: n for n in live["nodes"]}
                holders = {h["id"] for c in live["cps"] for h in c["holders"]}
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
                        stations[b["id"]] = {
                            "power": n.get("layer") == "L9",
                            "x": b["x"] + b["w"] / 2, "y": b["y"] - 5 - r,
                            "reach": reach(n, r, holders), "label": b}
                    m["cols"] = {c["L"]: c["cx"] for c in m["chips"]}
                    out[(lang, w)] = dict(m, stations=stations)
        finally:
            browser.close()
    return out


CASES = [(lang, w) for lang in ("en", "he") for w, _ in VIEWPORTS]


def _row(m):
    return {k: s for k, s in m["stations"].items() if s["power"]}


# -- the power row -----------------------------------------------------------------

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


# -- the L9 chip -------------------------------------------------------------------

@pytest.mark.parametrize("lang,width", CASES)
def test_the_l9_chip_sits_above_etn_centred_on_it(measured, lang, width):
    """Centred on ETN on both maps -- the Hebrew one is mirrored, and ETN is
    still under the chip -- with its bottom edge 10px over ETN's ring, and
    higher only if something would touch it there."""
    m = measured[(lang, width)]
    tag, s = m["tag"], m["stations"][TAG_ON]
    assert abs(tag["x"] + tag["w"] / 2 - s["x"]) < 1, (tag, s["x"])
    target = s["y"] - s["reach"] - TAG_GAP
    bottom = tag["y"] + tag["h"]
    assert bottom <= target + 0.6, ("below 10px over ETN's ring", bottom, target)
    at_target = dict(tag, y=target - tag["h"])
    if not any(hits_station(at_target, t) for t in m["stations"].values()):
        assert abs(bottom - target) < 0.6, ("lifted with nothing in the way",
                                            bottom, target)


@pytest.mark.parametrize("lang,width", CASES)
def test_the_l9_chip_touches_no_station(measured, lang, width):
    """No ring, no label, no station anywhere on the map -- ETN's own ring and
    label and the stations above it included."""
    m = measured[(lang, width)]
    tag = m["tag"]
    assert tag and tag["w"] > 0
    for k, s in m["stations"].items():
        assert not hits_station(tag, s), (k, tag, s)


# -- the header chips --------------------------------------------------------------

def _header(m):
    return sorted(m["chips"], key=lambda c: c["x"])


@pytest.mark.parametrize("lang,width", CASES)
def test_neighbouring_header_chips_keep_twelve_pixels(measured, lang, width):
    chips = _header(measured[(lang, width)])
    assert len(chips) == 7
    for a, b in zip(chips, chips[1:]):
        gap = b["x"] - (a["x"] + a["w"])
        assert gap >= CHIP_GAP - 0.1, (a["L"], b["L"], round(gap, 2))


@pytest.mark.parametrize("lang,width", CASES)
def test_a_header_chip_leaves_its_column_only_to_make_room(measured, lang,
                                                           width):
    """Centred on its column wherever it fits. Chips that had to move sit
    exactly 12px from a neighbour, and each run of them is shifted
    symmetrically: its chips' offsets from their columns sum to zero."""
    chips = _header(measured[(lang, width)])
    gaps = [b["x"] - (a["x"] + a["w"]) for a, b in zip(chips, chips[1:])]
    runs, run = [], [chips[0]]
    for g, c in zip(gaps, chips[1:]):
        if abs(g - CHIP_GAP) <= 0.3:
            run.append(c)
        else:
            runs.append(run)
            run = [c]
    runs.append(run)
    for r in runs:
        offsets = [c["left"] - c["cx"] for c in r]
        if len(r) == 1:
            assert abs(offsets[0]) <= 0.1, (r[0]["L"], offsets[0])
        else:
            assert abs(sum(offsets)) <= 0.1 * len(r), ([c["L"] for c in r], offsets)
