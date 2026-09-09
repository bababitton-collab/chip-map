"""The English page must not contain a Hebrew character, and the board must
survive the public build.

Two different failures. The first is a rule about the product: the public page
is English and a Hebrew string in it is a defect no reader can work around. The
second is the ordinary risk of building a page by string surgery -- a splice
that silently removes the forecast board leaves a page that still loads, still
looks right at a glance, and has lost the thing the build was for.
"""
from __future__ import annotations

import pytest

from chains import build_pages as bp
from chains.paths import out_dir, templates_dir

EN_TEMPLATE = templates_dir() / bp.TEMPLATE_EN
HE_TEMPLATE = templates_dir() / bp.TEMPLATE_HE
LIVE_EN = out_dir() / bp.LIVE_EN

needs_live = pytest.mark.skipif(
    not LIVE_EN.exists(),
    reason=f"{LIVE_EN} not built yet; run python -m chains.live_snapshot")


# -- the gate ---------------------------------------------------------------

def test_the_gate_finds_a_hebrew_character():
    assert bp.hebrew_runs("the lock is <b>מתהדק</b> this week")


def test_the_gate_passes_clean_english():
    assert bp.hebrew_runs("The lock is tightening this week — 13w +4.2%") == []


def test_assert_no_hebrew_names_where_it_found_it():
    with pytest.raises(ValueError) as e:
        bp.assert_no_hebrew("a page with מילה in it", "public-map-en.html")
    assert "public-map-en.html" in str(e.value)


@needs_live
def test_build_public_en_refuses_a_template_with_hebrew_in_it(tmp_path):
    """The real end-to-end gate: one Hebrew word survives into the English
    template, and no file is written."""
    poisoned = tmp_path / "live-map-en.html"
    text = EN_TEMPLATE.read_text(encoding="utf-8")
    poisoned.write_text(text.replace("<h2>The Forecast Board</h2>",
                                     "<h2>לוח החיזוי</h2>"),
                        encoding="utf-8", newline="\n")
    out = tmp_path / "public-map-en.html"
    with pytest.raises(ValueError) as e:
        bp.build_public_en(template=poisoned, live=LIVE_EN, out=out)
    assert "Hebrew" in str(e.value)
    assert not out.exists(), "an oversight wrote the file anyway"


@needs_live
def test_the_real_english_page_has_no_hebrew(tmp_path):
    out = tmp_path / "public-map-en.html"
    bp.build_public_en(live=LIVE_EN, out=out)
    assert bp.hebrew_runs(out.read_text(encoding="utf-8")) == []


# -- the board survives the build -------------------------------------------

@needs_live
def test_the_english_page_carries_the_forecast_board(tmp_path):
    out = tmp_path / "public-map-en.html"
    bp.build_public_en(live=LIVE_EN, out=out)
    page = out.read_text(encoding="utf-8")
    assert "The Forecast Board" in page
    assert "BOARD.render" in page


@needs_live
def test_the_board_tooltip_obeys_the_lock_rather_than_a_public_variant(tmp_path):
    """The tooltip used to be stripped by the public build. Both pages now
    obey the same rule -- text only where the row is open -- so the tooltip
    reads BT.locked for a locked row on either page, and there is no public
    variant that could be built wrong and leak."""
    out = tmp_path / "public-map-en.html"
    bp.build_public_en(live=LIVE_EN, out=out)
    page = out.read_text(encoding="utf-8")
    assert "w.locked? BT.locked : w.q" in page
    assert not hasattr(bp, "BOARD_TOOLTIP_Q"), (
        "the public-only substitution is gone; the rule lives in the data")


@needs_live
def test_each_public_page_fetches_its_own_snapshot(tmp_path):
    """An English page fetching live.json would swap its English watch rows
    for Hebrew ones the moment the fetch succeeded -- a page that passes the
    static gate and breaks the rule in the browser."""
    en = tmp_path / "en.html"
    bp.build_public_en(live=LIVE_EN, out=en)
    page = en.read_text(encoding="utf-8")
    assert "fetch('live_en.json'" in page
    assert "fetch('live.json'" not in page
    assert "claude.use('db')" not in page, "the db read must be gone"


# -- the translation fails loudly -------------------------------------------

def test_a_reworded_hebrew_string_fails_the_translation(tmp_path):
    """A pair that matches nothing is the silent path to a Hebrew sentence on
    the English page, so it is the loud path instead."""
    src = tmp_path / "live-map.html"
    text = HE_TEMPLATE.read_text(encoding="utf-8")
    src.write_text(text.replace("html{direction:rtl}", "html{direction:RTL}"),
                   encoding="utf-8", newline="\n")
    with pytest.raises(ValueError) as e:
        bp.build_en_template(src=src, dst=tmp_path / "out.html")
    assert "translation pair" in str(e.value)
    assert not (tmp_path / "out.html").exists()


def test_the_translation_of_the_real_template_is_complete(tmp_path):
    dst = tmp_path / "live-map-en.html"
    _, _, left = bp.build_en_template(dst=dst)
    assert left == [], f"Hebrew survived translation: {left[:5]}"


def test_the_translated_template_keeps_the_board(tmp_path):
    dst = tmp_path / "live-map-en.html"
    bp.build_en_template(dst=dst)
    page = dst.read_text(encoding="utf-8")
    assert "The Forecast Board" in page
    assert "BOARD.render" in page


# -- auto marks are labelled, in both languages -----------------------------
# An auto mark and a checked mark colour the board identically. A reader who
# cannot tell them apart is reading a stronger claim than the page is making,
# so the difference is labelled rather than hidden.

def test_the_hebrew_template_labels_an_auto_mark():
    """The table that carried the tag is gone; the rule is not. An answered
    card a machine marked is drawn dashed and labelled, and the board's hints
    still carry their suffix."""
    t = HE_TEMPLATE.read_text(encoding="utf-8")
    assert "autohint" in t and "autoSuffix" in t
    assert "stroke-dasharray=\"6 5\"" in t and "T.auto" in t


def test_the_english_template_labels_an_auto_mark_in_english():
    t = EN_TEMPLATE.read_text(encoding="utf-8")
    assert "auto:'auto'" in t
    assert "autoSuffix:' (auto)'" in t
    assert bp.hebrew_runs(t) == []


@needs_live
def test_the_english_public_page_keeps_the_boards_auto_labelling(tmp_path):
    """The public page has no watch table -- the teaser replaces that whole
    block, and WT goes with it. What it does have is the board, and the board
    still has to say which of its marks a machine made."""
    out = tmp_path / "public-map-en.html"
    bp.build_public_en(live=LIVE_EN, out=out)
    page = out.read_text(encoding="utf-8")
    assert "autoSuffix:' (auto)'" in page
    assert "autohint" in page
    assert bp.hebrew_runs(page) == []


@needs_live
def test_the_public_page_leaves_no_reference_to_the_table_it_removed(tmp_path):
    """WT is defined inside the block the teaser replaces. A reference to it
    surviving outside that block would be a ReferenceError at load, which on
    this page means a blank map."""
    out = tmp_path / "public-map-en.html"
    bp.build_public_en(live=LIVE_EN, out=out)
    page = out.read_text(encoding="utf-8")
    assert "WT.auto" not in page and "const WT" not in page


# -- the forecast ledger -----------------------------------------------------

def test_the_hebrew_template_has_the_ledger_section():
    t = HE_TEMPLATE.read_text(encoding="utf-8")
    assert 'id="ltiles"' in t and 'id="lcards"' in t
    assert "יומן התחזיות" in t


def test_the_english_template_has_the_ledger_in_english():
    t = EN_TEMPLATE.read_text(encoding="utf-8")
    assert "The Forecast Ledger" in t
    assert "N=30 before any capital decision" in t
    assert bp.hebrew_runs(t) == []


def test_the_ledger_never_prints_the_question_text():
    """The ledger names the question and shows the answer that was marked. The
    question itself is the product boundary and it is not in this section --
    on either page, so the public build does not have to strip it."""
    t = HE_TEMPLATE.read_text(encoding="utf-8")
    i = t.index("// ---- the forecast ledger ----")
    j = t.index("// ---- question cards ----", i)
    assert "${w.q}" not in t[i:j]


@needs_live
def test_the_public_english_page_carries_the_ledger(tmp_path):
    out = tmp_path / "public-map-en.html"
    bp.build_public_en(live=LIVE_EN, out=out)
    page = out.read_text(encoding="utf-8")
    assert "The Forecast Ledger" in page and 'id="lcards"' in page
    assert bp.hebrew_runs(page) == []


@needs_live
def test_the_ledger_survives_the_public_build_intact(tmp_path):
    """It sits before the block the teaser replaces. A splice that swallowed
    it would leave a page that still loads and has quietly lost the record."""
    out = tmp_path / "public-map.html"
    bp.build_public_he(live=out_dir() / bp.LIVE_HE, out=out)
    page = out.read_text(encoding="utf-8")
    assert "// ---- the forecast ledger ----" in page
    assert 'id="ltiles"' in page


# -- one visual language -----------------------------------------------------

def test_the_english_template_uses_plain_words_not_field_names():
    """"Holder" and "challenger" are the names of fields in the data. Nobody
    reading a map should have to learn them."""
    t = EN_TEMPLATE.read_text(encoding="utf-8")
    assert "controls the chokepoint" in t
    assert "trying to replace them" in t
    assert "Buys from" in t and "Sells to" in t
    assert "Others in this layer" in t


def test_the_legend_asks_two_questions():
    for tpl, first, second in (
        (HE_TEMPLATE, "איזה קו?", "האם השוק לוחץ על צוואר הבקבוק?"),
        (EN_TEMPLATE, "Which line?",
         "Is the market pressing on the chokepoint?")):
        t = tpl.read_text(encoding="utf-8")
        assert first in t and second in t


def test_the_ring_colours_are_not_reused_by_any_line():
    """The ring means one thing -- market pressure -- and it can only mean one
    thing if no line wears the same colour. --packaging used to BE --amber and
    --network was within a few points of --erode, so the legend's two rows
    were showing the same swatch for different ideas."""
    import re
    t = HE_TEMPLATE.read_text(encoding="utf-8")
    hexes = dict(re.findall(r"--([a-z]+):(#[0-9a-fA-F]{6})", t))
    rings = {hexes[k] for k in ("tight", "erode", "amber")}
    lines = {hexes[k] for k in ("logic", "memory", "packaging", "network",
                                "power", "cloud")}
    assert not (rings & lines), f"a line reuses a ring colour: {rings & lines}"

    def rgb(h):
        return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))

    for lc in lines:
        for rc in rings:
            d = sum(abs(a - b) for a, b in zip(rgb(lc), rgb(rc)))
            assert d > 60, f"{lc} is too close to the ring colour {rc} ({d})"


def test_the_edge_tooltip_never_invents_a_product():
    """It uses what the map records, or the line's own name. Nothing else."""
    t = HE_TEMPLATE.read_text(encoding="utf-8")
    i = t.index("function edgeSentence(")
    body = t[i:t.index("\n}", i)]
    assert "e.what" in body and "LHE[a.line]" in body


def test_the_edge_tooltip_is_marked_so_it_can_be_told_from_a_station_one():
    assert 'class="edgetip"' in HE_TEMPLATE.read_text(encoding="utf-8")


def test_only_a_chokepoint_gets_a_ring():
    """pulseOf returns null for a station that holds none, and the ring is
    drawn from it. A station with no chokepoint has nothing to say about
    market pressure and must not appear to."""
    t = HE_TEMPLATE.read_text(encoding="utf-8")
    i = t.index("function pulseOf(n){")
    assert "if(!n.cp||!n.cp.length) return null;" in t[i:i + 300]


def test_the_sponsor_line_excludes_a_company_that_holds_the_chokepoint():
    """GE Vernova sponsors a challenge against CP11, which it also holds. It
    is not attacking itself."""
    t = HE_TEMPLATE.read_text(encoding="utf-8")
    assert "!(c.holders||[]).some(x=>x.id===n.id)" in t


# -- the brand ---------------------------------------------------------------

def test_the_brand_comes_from_the_data_not_the_template():
    """A second map published under a different name should be a second JSON
    file, not a second template."""
    t = HE_TEMPLATE.read_text(encoding="utf-8")
    assert 'id="brand"' in t and 'id="maptitle"' in t and 'id="story"' in t
    assert "(D.labels||{}).brand" in t


def test_the_static_title_is_the_brand_alone():
    """It is the same in both languages, so it needs no translation pair, and
    a crawler that never runs the script still sees the name. header() adds
    the map's own title once the data is in."""
    for tpl in (HE_TEMPLATE, EN_TEMPLATE):
        assert "<title>Linchpin Signal</title>" in tpl.read_text(encoding="utf-8")


def test_the_map_carries_the_brand_in_both_languages():
    from chains.mapfile import load
    b = (load().get("labels") or {}).get("brand") or {}
    assert b.get("name")
    for field in ("title", "story", "footer"):
        assert b[field].get("he") and b[field].get("en"), field


@needs_live
def test_the_english_page_shows_the_brand_and_no_hebrew(tmp_path):
    out = tmp_path / "public-map-en.html"
    bp.build_public_en(live=LIVE_EN, out=out)
    page = out.read_text(encoding="utf-8")
    assert "Linchpin Signal" in page
    assert bp.hebrew_runs(page) == []
