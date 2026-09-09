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
def test_the_english_page_hides_the_question_text(tmp_path):
    """The board tooltip prints the question on the private page. On the
    public one it points at the mail -- that is the product boundary."""
    out = tmp_path / "public-map-en.html"
    bp.build_public_en(live=LIVE_EN, out=out)
    page = out.read_text(encoding="utf-8")
    assert bp.PUB["en"]["pubq"] in page
    assert bp.BOARD_TOOLTIP_Q not in page


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


@needs_live
def test_a_drifted_replacement_constant_fails_the_build(tmp_path):
    """This is the bug that shipped. The .wrow constant had stopped matching
    the template, str.replace returned the page unchanged, and every public
    page went out with an empty 220px column. A no-op replacement is now a
    failed build."""
    src = tmp_path / "live-map-en.html"
    src.write_text(EN_TEMPLATE.read_text(encoding="utf-8")
                   .replace(bp.WROW_PRIVATE, ".wrow{display:grid;"),
                   encoding="utf-8", newline="\n")
    with pytest.raises(ValueError) as e:
        bp.build_public_en(template=src, live=LIVE_EN,
                           out=tmp_path / "out.html")
    assert "watch row grid" in str(e.value)


@needs_live
def test_the_public_page_is_not_the_private_one(tmp_path):
    """The status control and its four-column row belong to the private page."""
    out = tmp_path / "public-map-en.html"
    bp.build_public_en(live=LIVE_EN, out=out)
    page = out.read_text(encoding="utf-8")
    assert bp.WROW_PRIVATE not in page
    assert bp.WROW_PUBLIC in page


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
    t = HE_TEMPLATE.read_text(encoding="utf-8")
    assert "autotag" in t and "autohint" in t
    assert "autoSuffix" in t and "WT.auto" in t


def test_the_english_template_labels_an_auto_mark_in_english():
    t = EN_TEMPLATE.read_text(encoding="utf-8")
    assert "const WT = {auto:'auto'};" in t
    assert "autoSuffix:' (auto)'" in t
    assert bp.hebrew_runs(t) == []


def test_a_manual_edit_clears_the_auto_flag():
    """It is a person's mark now. Leaving the flag set would keep labelling it
    as machine-written for ever."""
    t = HE_TEMPLATE.read_text(encoding="utf-8")
    assert "auto:false}" in t, "the save path must write auto:false"


def test_the_watch_table_falls_back_to_the_exported_answers():
    """Without this the board colours a row that the table below it still
    shows as open -- and an auto mark, which only ever arrives in the export,
    would never be labelled at all."""
    t = HE_TEMPLATE.read_text(encoding="utf-8")
    assert "(D.answers||{})[w.id]" in t


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
