"""The semi map's twelve columns, measured in a real browser.

The 2026-10-01 closure split L1, L4 and L6 into L1/L1b, L4/L4b and
L6/L6b/L6c. Eleven columns share the width at 1440, so the failure to guard
is the one this page has had before: a station's name drawn over another
name, or over another station's ring. The page exports every label box
(window.__labelBoxes) after layout; this reads them.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.browser import Browser, Served, require

SITE = Path(__file__).resolve().parents[1] / "site"
DOM = "semi"
JS = """JSON.stringify({boxes: window.__labelBoxes||[],
  chips: [...document.querySelectorAll('#layerbar .lchip')].map(e=>{const r=e.getBoundingClientRect();
    return {l:e.dataset.l, x0:r.left, x1:r.right}}),
  l9: (()=>{const e=document.querySelector('#l9bar .lchip'); if(!e) return null;
    const r=e.getBoundingClientRect(), c=document.querySelector('canvas').getBoundingClientRect();
    return {bottom:r.bottom-c.top, h:c.height}})()})"""


@pytest.fixture(scope="module")
def web():
    require()
    if not (SITE / DOM / "index.html").is_file():
        pytest.skip("no build in site/ to drive")
    served = Served(SITE, port=8936)
    browser = Browser(port=9448)
    try:
        yield served, browser
    finally:
        browser.close()
        served.close()


def overlaps(a, b):
    return (a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"]
            and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"])


def on_ring(box, n):
    dx = n["cx"] - max(box["x"], min(n["cx"], box["x"] + box["w"]))
    dy = n["cy"] - max(box["y"], min(n["cy"], box["y"] + box["h"]))
    return dx * dx + dy * dy < n["rr"] * n["rr"]


@pytest.mark.parametrize("width", [1440, 1280, 1200])
def test_no_name_touches_another_name_or_ring(web, width):
    served, browser = web
    got = json.loads(browser.measure(served.url(f"{DOM}/"), width, 1000, JS, settle=5))
    bx = got["boxes"]
    assert bx, "the page exported no label boxes"
    names = [(p["id"], q["id"]) for i, p in enumerate(bx) for q in bx[i + 1:] if overlaps(p, q)]
    rings = [(p["id"], q["id"]) for p in bx for q in bx if p["id"] != q["id"] and on_ring(p, q)]
    assert names == [] and rings == [], (names, rings)


@pytest.mark.parametrize("width", [1440, 1280])
def test_the_column_chips_do_not_collide_and_l9_sits_on_its_row(web, width):
    served, browser = web
    got = json.loads(browser.measure(served.url(f"{DOM}/"), width, 1000, JS, settle=5))
    ch = got["chips"]
    assert {c["l"] for c in ch} >= {"L1", "L1b", "L4", "L4b", "L6", "L6b", "L6c"}
    hit = [(a["l"], b["l"]) for i, a in enumerate(ch) for b in ch[i + 1:]
           if a["x1"] > b["x0"] and b["x1"] > a["x0"]]
    assert hit == []
    # The L9 tag belongs above the bottom row, not floating up the map.
    assert got["l9"] and got["l9"]["bottom"] > got["l9"]["h"] * 0.8
