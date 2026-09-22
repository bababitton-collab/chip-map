"""The per-question pages, on the way out: copied, and gated like everything else.

A page at /<domain>/track/<qid>/ is named after its question, so it cannot be
listed in the copy table ahead of time the way index.html is -- it is found.
That is convenient and it is exactly the kind of thing that quietly escapes a
gate, so both gates are tested on a found page here: no Hebrew in a file served
to English readers, and no locked question's sentence anywhere in it.
"""
from __future__ import annotations

import json

import pytest

from chains import publish_site


def _page(root, qid: str, body: str = "<h1>closed</h1>") -> None:
    d = root / qid
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text(f"<!doctype html><html><body>{body}"
                                  f"</body></html>", encoding="utf-8")


# -- the copy ----------------------------------------------------------------
def test_every_question_page_the_build_wrote_is_copied(tmp_path):
    built, site = tmp_path / "out" / "track", tmp_path / "site" / "track"
    _page(built, "orcl_q1")
    _page(built, "mu_fq4")
    site.mkdir(parents=True)
    got = publish_site.copy_detail_pages(built, site)
    assert got == ["track/mu_fq4/index.html", "track/orcl_q1/index.html"]
    assert (site / "orcl_q1" / "index.html").exists()
    assert (site / "mu_fq4" / "index.html").exists()


def test_with_no_question_pages_nothing_is_copied_and_nothing_breaks(tmp_path):
    site = tmp_path / "site" / "track"
    site.mkdir(parents=True)
    assert publish_site.copy_detail_pages(tmp_path / "missing", site) == []
    assert list(site.iterdir()) == []


def test_a_stray_file_beside_the_directories_is_not_a_page(tmp_path):
    built, site = tmp_path / "out" / "track", tmp_path / "site" / "track"
    built.mkdir(parents=True)
    (built / "notes.txt").write_text("x", encoding="utf-8")
    _page(built, "orcl_q1")
    site.mkdir(parents=True)
    assert publish_site.copy_detail_pages(built, site) == \
        ["track/orcl_q1/index.html"]
    assert not (site / "notes.txt").exists()


# -- the locked-text gate reaches them ---------------------------------------
LOCKED_SENTENCE = ("Will the company raise its full-year capital expenditure "
                   "guidance on this call and show the order book still "
                   "climbing?")


@pytest.fixture
def site(tmp_path, monkeypatch):
    """A published site with one locked question and one open one."""
    s = tmp_path / "site"
    (s / "track").mkdir(parents=True)
    (s / "live_en.json").write_text(json.dumps(
        {"watch": [{"id": "locked1", "locked": True}, {"id": "open1"}]}),
        encoding="utf-8")
    blank = {f: "" for f in publish_site.FIELDS_CHECKED}
    text = {"locked1": {**blank, publish_site.FIELDS_CHECKED[0]: LOCKED_SENTENCE},
            "open1": {**blank, publish_site.FIELDS_CHECKED[0]:
                      "An open question anybody may read in full today."}}
    monkeypatch.setattr("chains.questions.fetch", lambda url=None, dom=None: text)
    return s


def test_a_question_page_is_scanned_for_a_locked_sentence(site):
    _page(site / "track", "orcl_q1", f"<p>{LOCKED_SENTENCE}</p>")
    hits = publish_site.locked_text_in_site(site)
    assert hits, "a locked sentence on a found page went unnoticed"
    assert "track/orcl_q1/index.html" in hits[0] and "locked1" in hits[0]


def test_a_question_page_with_nothing_locked_on_it_passes(site):
    _page(site / "track", "orcl_q1",
          "<p>An open question anybody may read in full today.</p>")
    assert publish_site.locked_text_in_site(site) == []


# -- the vendored chart library ----------------------------------------------
def test_the_library_ships_in_the_repo_with_its_notice_and_its_licence():
    """Served from this host, so the pages depend on no CDN at read time. It
    is Apache-2.0: the notice stays in the file and the licence ships too."""
    from chains import record_page
    from chains.paths import templates_dir
    d = templates_dir() / "vendor"
    for name in record_page.VENDOR:
        assert (d / name).exists(), f"{name} is loaded by every question page"
    js = (d / record_page.VENDOR[0]).read_text(encoding="utf-8")
    assert "@license" in js and "Apache License 2.0" in js
    assert "Apache License" in \
        (d / record_page.VENDOR[1]).read_text(encoding="utf-8")


def test_one_list_of_assets_is_copied_and_the_other_is_published():
    """chains/track.py copies record_page.VENDOR into out/, publish_site
    copies TRACK_ASSETS out of it. Two lists that drift apart publish a page
    whose script is not there, so they are held equal here."""
    from chains import record_page
    assert publish_site.TRACK_ASSETS == list(record_page.VENDOR)
    for name in publish_site.TRACK_ASSETS:
        assert f"track/{name}" in publish_site.PAYWALLED, \
            f"{name} would ship unscanned for a locked question's text"


def test_each_group_of_contribution_bars_is_scaled_to_itself():
    """A share of the basket's return and a ring-2 leg's own move are
    different measures. Sizing both against one maximum lets a reader compare
    them by length, which is the one thing they cannot do -- and it squashes
    the basket's own bars to slivers beside a bigger ring-2 number."""
    import re
    from chains import record_page
    rec = {"legs": [
        {"tk": "IN", "ring": 1, "contribution": -1.0, "since_commit": -2.0},
        {"tk": "OUT", "ring": 2, "contribution": None, "since_commit": -10.0}]}
    out = record_page._contrib(rec)
    assert re.findall(r"width:([\d.]+)%", out) == ["50.00", "50.00"], \
        "the widest bar of each group fills its own half of the track"
    assert "cannot be compared by length" in out
    assert "1.00 percentage points" in out and "10.00 percentage points" in out


def test_the_chart_leaves_vertical_touch_to_the_page():
    """The crosshair has to work under a thumb, and the page has to keep
    scrolling under the same thumb. That is one axis each: horizontal touch
    belongs to the chart, vertical touch to the page. Turning handleScroll off
    wholesale looks like the safe choice and silently kills the touch readout,
    which is exactly the bug this pins."""
    from chains import record_page
    js = record_page.CHART_JS
    assert "horzTouchDrag:true" in js
    assert "vertTouchDrag:false" in js
    assert "handleScroll:false" not in js
    # And the readout does not wait for the library's tracking mode, which
    # answers a drag and not a tap. One touch shows the same row the crosshair
    # would have shown, read off the data already in the page.
    assert "addEventListener('touchstart'" in js
    assert "coordinateToLogical" in js
    assert "{passive:true}" in js, "a blocking listener would eat the scroll"


def test_the_library_carries_no_hebrew_into_the_english_pages():
    from chains import record_page
    from chains.build_pages import hebrew_runs
    from chains.paths import templates_dir
    for name in record_page.VENDOR:
        text = (templates_dir() / "vendor" / name).read_text(encoding="utf-8")
        assert hebrew_runs(text) == [], name
