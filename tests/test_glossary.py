"""The glossary: what it matches, and what it is not allowed to say.

A definition explains a word that is already on the page. It never adds a fact,
a number or an opinion the map does not already carry -- and that is enforced
rather than trusted, because a glossary that can smuggle in a figure is a
second, unsourced dataset wearing a helpful hat.
"""
from __future__ import annotations

import json

import pytest

from chains import glossary as g

TERMS = [
    {"id": "hbm", "label": "HBM", "match": ["HBM", "HBM3E", "HBM4"],
     "en": "Memory stacked beside the processor.", "he": "זיכרון."},
    {"id": "highna", "label": "High-NA", "match": ["High-NA", "High NA"],
     "en": "The next step in lithography.", "he": "ליתוגרפיה."},
    {"id": "na", "label": "NA", "match": ["NA"],
     "en": "Numerical aperture.", "he": "מפתח."},
    {"id": "capex", "label": "capex", "match": ["capex"],
     "en": "Money spent on plant and equipment.", "he": "השקעות."},
    {"id": "fy", "label": "FY27", "match": ["FY27"],
     "en": "A company fiscal year.", "he": "שנת כספים."},
    {"id": "inp", "label": "InP", "match": ["InP"],
     "en": "A substrate material.", "he": "מצע."},
    {"id": "test", "label": "test", "match": ["test"],
     "en": "A trial.", "he": "ניסוי."},
    {"id": "rpo", "label": "RPO", "match": ["RPO"],
     "en": "Work sold and not yet delivered.", "he": "צבר."},
]


# -- the loader --------------------------------------------------------------

def write(tmp_path, doc):
    p = tmp_path / "glossary.json"
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return p


def test_an_absent_file_is_an_empty_glossary_not_a_failure(tmp_path):
    """A glossary is an addition to a map, not a requirement of one."""
    assert g.load(path=tmp_path / "nope.json") == []


def test_a_good_file_loads(tmp_path):
    p = write(tmp_path, {"version": 1, "as_of": "2026-09-10", "terms": TERMS})
    assert [t["id"] for t in g.load(path=p)] == [t["id"] for t in TERMS]


def test_unparseable_json_says_so(tmp_path):
    p = tmp_path / "glossary.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(g.GlossaryError) as e:
        g.load(path=p)
    assert "not valid JSON" in str(e.value)


def test_two_terms_may_not_share_an_id():
    """A card names a definition by id, so a duplicate makes the tooltip a
    coin toss."""
    with pytest.raises(g.GlossaryError) as e:
        g.validate(TERMS + [dict(TERMS[0])])
    assert "coin toss" in str(e.value)


@pytest.mark.parametrize("lang", ["en", "he"])
def test_both_languages_must_be_present(lang):
    """Both pages show the same terms; one language missing is one page with
    an empty tooltip."""
    bad = dict(TERMS[0], **{lang: ""})
    with pytest.raises(g.GlossaryError) as e:
        g.validate([bad])
    assert lang in str(e.value)


def test_a_term_needs_a_label():
    with pytest.raises(g.GlossaryError):
        g.validate([dict(TERMS[0], label="")])


def test_a_term_needs_at_least_one_match_string():
    with pytest.raises(g.GlossaryError):
        g.validate([dict(TERMS[0], match=[])])


def test_an_empty_match_string_is_refused():
    """It would match at every position in every sentence."""
    with pytest.raises(g.GlossaryError) as e:
        g.validate([dict(TERMS[0], match=["HBM", "  "])])
    assert "every position" in str(e.value)


# -- what it finds -----------------------------------------------------------

@pytest.mark.parametrize("text,want", [
    ("HBM4 capacity is coming", ["hbm"]),
    ("HBM3E stacks", ["hbm"]),
    ("High-NA EUV tools", ["highna"]),
    ("High NA is the same term", ["highna"]),
    ("FY27 capex guidance", ["fy", "capex"]),
    ("Capex at the start of a sentence", ["capex"]),
    ("CAPEX shouting is still capex", ["capex"]),
    ("InP substrates", ["inp"]),
    ("the latest results", []),
    ("contest and protest and testing", []),
    ("", []),
])
def test_find(text, want):
    assert g.find(text, TERMS) == want


def test_a_lowercase_match_is_case_insensitive_and_a_capitalised_one_is_not():
    """"Capex" at the start of a sentence is still capex. "inp" in the middle
    of one is not InP."""
    assert g.find("capex", TERMS) == ["capex"]
    assert g.find("CAPEX", TERMS) == ["capex"]
    assert g.find("InP", TERMS) == ["inp"]
    assert g.find("inp", TERMS) == []
    assert g.find("hbm", TERMS) == []


def test_the_longest_match_wins():
    """"High-NA" is one term and not also the "NA" inside it."""
    assert g.find("High-NA", TERMS) == ["highna"]
    assert "na" not in g.find("High-NA optics", TERMS)


def test_a_bare_na_still_matches_on_its_own():
    assert g.find("the NA of the lens", TERMS) == ["na"]


def test_order_is_first_appearance():
    assert g.find("capex, then HBM, then RPO", TERMS) == ["capex", "hbm", "rpo"]


def test_at_most_four_per_card():
    text = "HBM and capex and FY27 and InP and RPO and High-NA"
    got = g.find(text, TERMS)
    assert len(got) == g.MAX_PER_CARD == 4
    assert got == ["hbm", "capex", "fy", "inp"], "the first four, in order"


def test_a_term_appearing_twice_is_listed_once():
    assert g.find("HBM now and HBM later", TERMS) == ["hbm"]


def test_no_glossary_finds_nothing():
    assert g.find("HBM and capex", []) == []


# -- how it marks up the text ------------------------------------------------

def test_mark_wraps_each_occurrence():
    got = g.mark("FY27 capex guidance", TERMS)
    assert '<abbr class="gl" data-gl="fy">FY27</abbr>' in got
    assert '<abbr class="gl" data-gl="capex">capex</abbr>' in got


def test_mark_escapes_the_sentence_but_not_its_own_tags():
    got = g.mark("capex & <b>bold</b>", TERMS)
    assert "&amp;" in got and "&lt;b&gt;" in got
    assert '<abbr class="gl"' in got


def test_mark_with_no_glossary_returns_escaped_text():
    assert g.mark("a & b", []) == "a &amp; b"


def test_mark_respects_the_ids_it_is_given():
    """The page is told WHICH terms a card shows; it only places them."""
    got = g.mark("FY27 capex guidance", TERMS)
    assert got.count("<abbr") == 2


# -- a definition invents nothing --------------------------------------------

DOC = {"nodes": [{"role": "HBM is about 47% of a Blackwell board"}],
       "note": "capacity through 2027"}
QS = {"a": {"q_en": "Does it reach $380M in revenue"}}


def test_a_definition_may_repeat_a_number_the_map_already_states():
    terms = [{"id": "x", "label": "x", "match": ["x"],
              "en": "About 47% of the board.", "he": "כ-47%."}]
    assert g.numbers_without_a_source(terms, DOC, QS) == []


def test_a_definition_may_repeat_a_number_a_question_states():
    terms = [{"id": "x", "label": "x", "match": ["x"],
              "en": "The $380M line.", "he": "$380M."}]
    assert g.numbers_without_a_source(terms, DOC, QS) == []


def test_a_definition_may_not_introduce_one():
    """The moment a definition carries a figure nobody else states, the
    glossary has become a second dataset -- unsourced, and read as if it were
    the first."""
    terms = [{"id": "x", "label": "x", "match": ["x"],
              "en": "Roughly 91% of the market.", "he": "טקסט."}]
    bad = g.numbers_without_a_source(terms, DOC, QS)
    assert [(t, lang) for t, lang, _n in bad] == [("x", "en")]
    assert bad[0][2].replace(" ", "") == "91%"


def test_a_spelled_out_number_counts_as_a_number():
    """"three years" is as much a claim as "3 years"."""
    terms = [{"id": "x", "label": "x", "match": ["x"],
              "en": "It takes three years.", "he": "טקסט."}]
    assert g.numbers_without_a_source(terms, DOC, QS)


def test_a_definition_with_no_numbers_is_always_fine():
    terms = [{"id": "x", "label": "x", "match": ["x"],
              "en": "Memory stacked beside the processor.", "he": "טקסט."}]
    assert g.numbers_without_a_source(terms, DOC, QS) == []


@pytest.mark.parametrize("text,found", [
    ("$380M of revenue", ["$380M"]),
    ("98% of supply", ["98%"]),
    ("a 3nm process", ["3nm"]),
    ("by 2027", ["2027"]),
    ("no numbers here", []),
])
def test_which_figures_are_picked_out(text, found):
    got = [n.replace(" ", "") for n in g.numbers_in(text)]
    assert got == found


# -- the real file, whatever it says today -----------------------------------

def test_the_shipped_glossary_validates():
    """Vacuous while data/<domain>/glossary.json is absent, and the check that
    catches it the day one lands."""
    assert isinstance(g.load(), list)


def test_no_shipped_definition_invents_a_number():
    """The gate the brief asked for: a figure in a definition that appears
    nowhere in the map or in a question fails the build, naming the term."""
    from chains import mapfile
    terms = g.load()
    if not terms:
        pytest.skip("no glossary in this domain yet")
    try:
        from chains import questions
        qs = questions.fetch()
    except Exception:
        qs = {}
    bad = g.numbers_without_a_source(terms, mapfile.load(), qs)
    assert bad == [], (
        "these figures appear in a definition and nowhere else: "
        + "; ".join(f"{t} ({lang}): {n}" for t, lang, n in bad))


# -- the wiring --------------------------------------------------------------

def test_the_page_is_handed_only_what_it_needs():
    """One language, and no ``he`` key to pick the wrong one out of."""
    page = g.for_page(TERMS, "en")
    assert page["hbm"] == {"label": "HBM",
                           "def": "Memory stacked beside the processor."}
    assert all(set(v) == {"label", "def"} for v in page.values())
    from chains import build_pages
    assert build_pages.hebrew_runs(json.dumps(page, ensure_ascii=False)) == []


def test_the_hebrew_page_gets_the_hebrew_side():
    page = g.for_page(TERMS, "he")
    assert page["hbm"]["def"] == "זיכרון."


def test_the_snapshot_ships_the_glossary_and_the_per_row_terms():
    import inspect

    from chains import live_snapshot
    src = inspect.getsource(live_snapshot)
    assert '"glossary": {t["id"]' in src
    assert 'r["terms"] = found' in src


def test_a_locked_row_gets_no_terms():
    """It has no text, so it has no terms and no Terms line: nothing to reveal
    and nothing to leak."""
    import inspect

    from chains import live_snapshot
    src = inspect.getsource(live_snapshot)
    i = src.index('gl = glossary.load()')
    # the terms loop runs after locked rows have had their text stripped
    assert src.index('r.pop(k, None)') < i


def test_both_pages_and_the_track_cards_mark_their_text():
    from chains.paths import templates_dir
    tpl = (templates_dir() / "live-map.html").read_text(encoding="utf-8")
    cards = (templates_dir() / "track-cards.js").read_text(encoding="utf-8")
    js = (templates_dir() / "glossary.js").read_text(encoding="utf-8")
    assert "__GLOSSARY_JS__" in tpl
    assert "GL.mark" in tpl and "GL.chips" in tpl
    assert "GL.mark" in cards and "GL.chips" in cards
    assert "window.GL = " in js


def test_the_station_panel_marks_its_role_sentence():
    from chains.paths import templates_dir
    tpl = (templates_dir() / "live-map.html").read_text(encoding="utf-8")
    assert "GL.mark(n.role" in tpl


def test_the_matcher_ships_no_hebrew_character():
    """It has a word-boundary test that covers the Hebrew block, and the
    English page refuses any character in it -- so the range is written as
    escapes."""
    from chains import build_pages
    from chains.paths import templates_dir
    js = (templates_dir() / "glossary.js").read_text(encoding="utf-8")
    assert build_pages.hebrew_runs(js) == []
    assert "\\u0590-\\u05FF" in js


def test_both_letters_close_with_the_terms_they_used():
    import inspect

    from chains import brief, brief_he
    for mod in (brief, brief_he):
        src = inspect.getsource(mod)
        assert "glossary.find(" in src
        assert "sent.append(w)" in src, "only rows the letter actually printed"
