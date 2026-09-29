"""The 390px phone, in a real browser: the gutter, the nav, and no sideways scroll.

Three of the brief's requirements are layout facts, not strings, and none of
them can be checked by reading the CSS. "At least 20px of horizontal padding"
depends on which rule wins at that width. "TRACK RECORD and the brand must not
touch or clip at 390" depends on the loaded font, the number of nav items --
the map page has one more than the landing page -- and the flex wrap. And a
two-pixel horizontal scroll is invisible in the source and obvious on a phone.

The map page was failing all three: its nav is inserted above the first screen
rather than inside it, so it inherited no gutter at all and ran 0 to 390, with
the brand against the left edge and the track-record border off the right.

Skips where the machine has no Chrome, like every other browser check here.
"""
from __future__ import annotations

import json

import pytest

from tests.browser import Browser, Served, require

PHONE = 390
MIN_GUTTER = 20
PAGES = ["", "semi/", "semi/track/", "track/"]


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    from pathlib import Path
    require()
    site = Path(__file__).resolve().parents[1] / "site"
    if not (site / "index.html").exists():
        pytest.skip("site/ is not published; run chains.publish_site first")
    for p in PAGES:
        if not (site / p / "index.html").exists():
            pytest.skip(f"site/{p} is not published")
    srv = Served(site, port=8936)
    br = Browser(port=9447)
    yield br, srv
    br.close()
    srv.close()


NAV = """
(() => {
  const nav = document.querySelector('.sitenav');
  const de = document.documentElement;
  if (!nav) return {missing: true};
  const items = [...nav.children].map(c => {
    const r = c.getBoundingClientRect();
    return {cls: c.className || c.tagName, left: r.left, right: r.right,
            height: r.height, text: c.textContent.trim()};
  });
  return {
    hscroll: de.scrollWidth - de.clientWidth,
    width: de.clientWidth,
    items: items,
    // Every item wide enough to hit, and none of them off either edge.
    minLeft: Math.min(...items.map(i => i.left)),
    maxRight: Math.max(...items.map(i => i.right)),
  };
})()
"""


@pytest.mark.parametrize("path", PAGES)
def test_nothing_starts_closer_than_twenty_pixels_to_the_edge(live, path):
    br, srv = live
    got = br.measure(srv.url(path), PHONE, 844, NAV)
    assert not got.get("missing"), f"{path}: no site nav"
    assert got["minLeft"] >= MIN_GUTTER, (
        f"{path}: something starts {got['minLeft']}px from the left edge")
    assert got["maxRight"] <= PHONE - MIN_GUTTER, (
        f"{path}: something reaches {PHONE - got['maxRight']}px from the "
        f"right edge")


@pytest.mark.parametrize("path", PAGES)
def test_no_page_scrolls_sideways_on_a_phone(live, path):
    br, srv = live
    got = br.measure(srv.url(path), PHONE, 844, NAV)
    assert got["hscroll"] == 0, f"{path}: {got['hscroll']}px of sideways scroll"


@pytest.mark.parametrize("path", PAGES)
def test_every_nav_link_is_a_forty_four_pixel_target(live, path):
    br, srv = live
    got = br.measure(srv.url(path), PHONE, 844, NAV)
    small = [i["text"] for i in got["items"]
             if i["cls"] != "navdesc" and i["height"] < 44]
    assert not small, f"{path}: {small} are under 44px"


@pytest.mark.parametrize("path", PAGES)
def test_the_trust_line_takes_its_own_row_and_the_links_keep_theirs(live, path):
    """It is the widest item in the bar. On one row with the three links it
    pushed the brand against the edge, which is how the clipping started."""
    br, srv = live
    got = br.measure(srv.url(path), PHONE, 844, NAV)
    desc = [i for i in got["items"] if i["cls"] == "navdesc"]
    assert desc, f"{path}: the trust line is not in the nav"
    d = desc[0]
    assert d["right"] - d["left"] > PHONE * 0.7, (
        f"{path}: the trust line is not on a row of its own")


LAYOUT = """
(() => {
  const de = document.documentElement;
  const out = [];
  // A dense table is meant to scroll inside its own card on a phone, and its
  // full width is the point. What matters is that the scroller's box obeys
  // the gutter, which it is measured for in its own right.
  const scrolls = el => {
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const o = getComputedStyle(p).overflowX;
      if (o === 'auto' || o === 'scroll') return true;
    }
    return false;
  };
  for (const el of document.querySelectorAll(
      'h1,h2,h3,p,li,table,figure,.card,.mapcard,.tile,.domrec,.foot,.top')) {
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) continue;
    if (scrolls(el)) continue;
    // The content box, not the border box. A full-bleed strip whose own
    // padding holds the gutter is exactly what the rule asks for; it is the
    // ink inside it that may not start at the edge.
    const cs = getComputedStyle(el);
    const left = r.left + parseFloat(cs.paddingLeft || 0);
    const right = r.right - parseFloat(cs.paddingRight || 0);
    if (left < %d - 0.5 || right > %d - %d + 0.5)
      out.push([el.tagName + '.' + (el.className || ''),
                Math.round(left), Math.round(right),
                el.textContent.trim().slice(0, 40)]);
  }
  return {hscroll: de.scrollWidth - de.clientWidth, bad: out.slice(0, 12)};
})()
""" % (MIN_GUTTER, PHONE, MIN_GUTTER)


@pytest.mark.parametrize("path", PAGES)
def test_no_text_or_card_begins_inside_the_gutter(live, path):
    """The brief's rule, applied to the elements a reader actually reads.

    The map's own canvas and its sideways scrollers are deliberately full
    bleed and are not in the selector: a strip that scrolls horizontally
    inside itself is the point of that strip.
    """
    br, srv = live
    got = br.measure(srv.url(path), PHONE, 844, LAYOUT)
    assert got["bad"] == [], json.dumps(got["bad"], indent=1)
