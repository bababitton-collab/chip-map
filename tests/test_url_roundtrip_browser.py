"""State → URL → reload → the same state, in a real browser.

The unit tests beside this one check that the right keys are written and that
every one is validated on the way back in. They cannot check the thing that
actually matters: that a link someone copies opens the map they were looking
at. That needs a page that has run, a history entry that has been replaced,
and a second load that reads it.

Skips where there is no Chrome or no build, like the other browser tests.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.browser import Browser, Served, require

SITE = Path(__file__).resolve().parents[1] / "site"
DOM = "energy"

STATE = r"""
(() => {
  const rail = document.getElementById('srail');
  const stage = document.getElementById('stage');
  return JSON.stringify({
    search: rail.querySelector('.rq') ? rail.querySelector('.rq').value : null,
    filters: [...rail.querySelectorAll('.rf')]
               .reduce((o, s) => (o[s.dataset.f] = s.value, o), {}),
    count: rail.querySelector('.rcount') ? rail.querySelector('.rcount').textContent : null,
    rows: rail.querySelectorAll('.rstn').length,
    detail: !!rail.querySelector('.pin'),
    detailName: rail.querySelector('.pin h2') ? rail.querySelector('.pin h2').textContent : null,
    railOpen: stage.classList.contains('rail-open'),
    url: location.search,
    alive: !!document.getElementById('map'),
  });
})()
"""

# Drive the controls, let the URL be written, and report where it ended up.
DRIVE = r"""
(() => {
  const rail = document.getElementById('srail');
  const q = rail.querySelector('.rq');
  q.value = 'GE';
  q.dispatchEvent(new Event('input', {bubbles: true}));
  const pulse = [...rail.querySelectorAll('.rf')].find(s => s.dataset.f === 'pulse');
  pulse.value = 'tightening';
  pulse.dispatchEvent(new Event('change', {bubbles: true}));
  const r2 = document.getElementById('srail');
  return JSON.stringify({
    url: location.search,
    count: r2.querySelector('.rcount').textContent,
    rows: r2.querySelectorAll('.rstn').length,
  });
})()
"""


@pytest.fixture(scope="module")
def web():
    require()
    if not (SITE / DOM / "index.html").is_file():
        pytest.skip("no build in site/ to drive")
    served = Served(SITE, port=8934)
    browser = Browser(port=9446)
    try:
        yield served, browser
    finally:
        browser.close()
        served.close()


def test_setting_a_search_and_a_filter_writes_them_to_the_url(web):
    served, browser = web
    got = json.loads(browser.measure(served.url(f"{DOM}/"), 1500, 950, DRIVE,
                                     settle=3.0))
    assert "q=GE" in got["url"]
    assert "pulse=tightening" in got["url"]
    assert got["rows"] >= 1
    assert got["count"].endswith("stations")


def test_that_url_reopens_the_same_map(web):
    """The round trip. The second load is a cold one: it knows only the URL."""
    served, browser = web
    first = json.loads(browser.measure(served.url(f"{DOM}/"), 1500, 950, DRIVE,
                                       settle=3.0))
    back = json.loads(browser.measure(served.url(f"{DOM}/") + first["url"],
                                      1500, 950, STATE, settle=3.0))
    assert back["search"] == "GE"
    assert back["filters"]["pulse"] == "tightening"
    assert back["count"] == first["count"]
    assert back["rows"] == first["rows"]


def test_a_link_can_carry_an_open_station_and_an_open_rail(web):
    served, browser = web
    url = served.url(f"{DOM}/") + "?station=gev&rail=1"
    got = json.loads(browser.measure(url, 1200, 950, STATE, settle=3.0))
    assert got["detail"] is True
    assert got["detailName"] and "Vernova" in got["detailName"]
    assert got["railOpen"] is True


@pytest.mark.parametrize("query,why", [
    ("?pulse=banana", "a value that is not a pulse"),
    ("?layer=NOPE", "a layer the map does not have"),
    ("?station=nosuchstation", "an id that names nothing"),
    ("?rail=maybe", "a flag that is not a flag"),
    ("?q=" + "x" * 500, "a search longer than any name"),
    ("?%%zz=1", "a malformed query string"),
])
def test_a_bad_parameter_is_ignored_and_never_breaks_the_page(query, why, web):
    served, browser = web
    got = json.loads(browser.measure(served.url(f"{DOM}/") + query,
                                     1500, 950, STATE, settle=2.6))
    assert got["alive"], why
    assert got["filters"]["pulse"] in ("", "tightening", "eroding", "unmeasured")
    assert got["filters"]["layer"] == "" or got["filters"]["layer"].startswith("E")
    if "station" in query:
        assert got["detail"] is False
    if "rail=maybe" in query:
        assert got["railOpen"] is False
    if got["search"] is not None:
        assert len(got["search"]) <= 80


def test_the_recording_flags_are_not_added_to_a_normal_link(web):
    served, browser = web
    got = json.loads(browser.measure(served.url(f"{DOM}/"), 1500, 950, DRIVE,
                                     settle=3.0))
    for flag in ("rec=", "legacy=", "emph=", "freeze="):
        assert flag not in got["url"], flag
