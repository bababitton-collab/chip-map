"""The Stations drawer overlays the map; it does not redraw it.

Between 1024 and 1439 the rail opens from a button. It used to do that as a
grid column, which took 300px out of the canvas: at 1200 the map went from
1200 to 900, every layer column narrowed with it, and four of energy's layer
names broke mid-word -- REACTOR/S, TURBINE/S, EQUIPME/NT, GENERAT/ION.

That shipped. P1's label tests and its round-3 screenshots were all taken with
the drawer shut, so nothing looked at the map in the state a reader puts it in
by pressing the button on it.

Two things are asserted here, both with the drawer open: the canvas is exactly
as wide as it was with the drawer shut, and no layer label breaks inside a
word.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.browser import Browser, Served, require

SITE = Path(__file__).resolve().parents[1] / "site"
DOM = "energy"
DRAWER_WIDTHS = (1024, 1200, 1439)

# Canvas width and every mid-word break, with the drawer in whichever state
# the caller asked for.
PROBE = r"""
(() => {
  if (%(open)s) {
    const b = document.getElementById('railbtn');
    if (b && !document.getElementById('stage').classList.contains('rail-open')) b.click();
  }
  const chips = [...document.querySelectorAll('#layerbar .lchip')];
  const labels = chips.map(chip => {
    const w = document.createTreeWalker(chip, NodeFilter.SHOW_TEXT);
    const ch = []; let n;
    while ((n = w.nextNode())) {
      if (n.parentElement && n.parentElement.closest('.vh')) continue;
      for (let i = 0; i < n.data.length; i++) {
        const r = document.createRange(); r.setStart(n, i); r.setEnd(n, i + 1);
        const b = r.getBoundingClientRect();
        ch.push({c: n.data[i], top: Math.round(b.top), wd: b.width});
      }
    }
    for (let i = 1; i < ch.length; i++)
      if (ch[i-1].c === '­' && ch[i-1].wd > 0 && i + 1 < ch.length)
        ch[i].top = ch[i+1].top;
    const lines = [];
    ch.forEach(c => { const l = lines[lines.length - 1];
      if (!l || l.top !== c.top) lines.push({top: c.top, t: c.c}); else l.t += c.c; });
    const drop = t => t.replace(/^.*·/, '').replace(/­/g, '');
    const bad = [];
    for (let i = 1; i < lines.length; i++) {
      const a = lines[i-1].t, b = lines[i].t;
      if (/\s$/.test(a) || /^\s/.test(b)) continue;   // a space
      if (/­$/.test(a)) continue;                // a soft hyphen
      if (/·\s*$/.test(a)) continue;             // after the "E1 ·" prefix
      bad.push(drop((a.match(/\S+$/) || [''])[0]) + '|' + (b.match(/^\S+/) || [''])[0]);
    }
    return {lines: lines.map(l => l.t.replace(/­/g, '-')), bad};
  });
  const cv = document.getElementById('map');
  const rail = document.getElementById('srail');
  const stage = document.getElementById('stage');
  const cs = rail ? getComputedStyle(rail) : null;
  return JSON.stringify({
    canvasW: Math.round(cv.getBoundingClientRect().width),
    midWord: labels.flatMap(l => l.bad),
    lines: labels.map(l => l.lines),
    drawerOpen: stage.classList.contains('rail-open'),
    railPosition: cs ? cs.position : null,
    railWidth: rail ? Math.round(rail.getBoundingClientRect().width) : 0,
  });
})()
"""


@pytest.fixture(scope="module")
def web():
    require()
    if not (SITE / DOM / "index.html").is_file():
        pytest.skip("no build in site/ to drive")
    served = Served(SITE, port=8935)
    browser = Browser(port=9447)
    try:
        yield served, browser
    finally:
        browser.close()
        served.close()


def probe(web, width, open_):
    served, browser = web
    return json.loads(browser.measure(
        served.url(f"{DOM}/"), width, 950,
        PROBE % {"open": "true" if open_ else "false"}, settle=3.0))


@pytest.mark.parametrize("width", DRAWER_WIDTHS)
def test_opening_the_drawer_does_not_narrow_the_canvas(width, web):
    shut = probe(web, width, False)
    open_ = probe(web, width, True)
    assert open_["drawerOpen"] is True, "the button did not open the drawer"
    assert open_["canvasW"] == shut["canvasW"], (
        f"{width}: the canvas went {shut['canvasW']} -> {open_['canvasW']} "
        f"when the drawer opened")


@pytest.mark.parametrize("width", DRAWER_WIDTHS)
def test_no_layer_label_breaks_mid_word_with_the_drawer_open(width, web):
    got = probe(web, width, True)
    assert got["midWord"] == [], (
        f"{width}, drawer open: {got['midWord']}; lines={got['lines']}")


@pytest.mark.parametrize("width", DRAWER_WIDTHS)
def test_the_drawer_is_positioned_over_the_map(width, web):
    got = probe(web, width, True)
    assert got["railPosition"] == "absolute", got["railPosition"]
    assert got["railWidth"] == 300


def test_above_1440_the_rail_is_docked_and_the_canvas_makes_room(web):
    """The docked case is the one where narrowing the canvas is correct: the
    rail is beside the map, not over it, and nothing is hidden behind it."""
    got = probe(web, 1500, False)
    assert got["railPosition"] == "static"
    assert got["railWidth"] == 300
    assert got["midWord"] == []
