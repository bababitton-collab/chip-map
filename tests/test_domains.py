"""The domain layer: what counts as a domain, and that the first one did not move.

Two halves, and the second is the point of the first. Discovery has to find a
new industry without anything being edited; and the industry already published
has to come out of the engine exactly as it did before the engine learned
there could be others. A generalisation that quietly reflows the live site is
not a generalisation, it is a rewrite with a nicer name.
"""
from __future__ import annotations

import hashlib
import json
import re

import pytest

from chains import domains, live_snapshot, mapfile, paths, publish_site

MAP = paths.MAP_FILENAME
WATCH = paths.WATCH_FILENAME
WATCH_EN = paths.WATCH_EN_FILENAME


def _domain(root, name, *, whole: bool = True) -> None:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / MAP).write_text("{}", encoding="utf-8")
    if whole:
        (d / WATCH).write_text("[]", encoding="utf-8")
        (d / WATCH_EN).write_text("[]", encoding="utf-8")


# -- what counts as a domain -------------------------------------------------
def test_a_domain_is_a_directory_with_a_map_and_both_question_lists(tmp_path):
    _domain(tmp_path, "alpha")
    assert domains.missing("alpha", tmp_path) == []
    assert domains.is_domain("alpha", tmp_path)
    assert domains.discover(tmp_path) == ["alpha"]


def test_half_a_domain_is_not_discovered_and_says_what_it_lacks(tmp_path):
    """A map with no question list is a work in progress. Building it would
    fail three steps later with a missing-file traceback; not building it is
    the honest answer, and require() says why."""
    _domain(tmp_path, "beta", whole=False)
    assert domains.missing("beta", tmp_path) == [WATCH, WATCH_EN]
    assert domains.discover(tmp_path) == []
    with pytest.raises(SystemExit) as e:
        domains.require("beta", tmp_path)
    assert WATCH in str(e.value) and "beta" in str(e.value)


def test_a_directory_that_is_not_there_at_all_is_missing_everything(tmp_path):
    assert domains.missing("nothing", tmp_path) == list(domains.REQUIRED)
    assert not domains.is_domain("nothing", tmp_path)


def test_an_empty_or_absent_data_root_discovers_nothing_and_does_not_raise(tmp_path):
    assert domains.discover(tmp_path) == []
    assert domains.discover(tmp_path / "not-created") == []


def test_the_default_domain_leads_and_the_rest_follow_by_name(tmp_path):
    """The first one is first because of where it sorts, not because the
    engine knows its name: it is what a bare command builds, so it is what a
    report should lead with. Everything else is alphabetical."""
    for name in ("zulu", paths.DEFAULT_DOMAIN, "alpha", "mike"):
        _domain(tmp_path, name)
    assert domains.discover(tmp_path) == [
        paths.DEFAULT_DOMAIN, "alpha", "mike", "zulu"]


def test_without_the_default_domain_the_order_is_simply_alphabetical(tmp_path):
    for name in ("zulu", "alpha"):
        _domain(tmp_path, name)
    assert domains.discover(tmp_path) == ["alpha", "zulu"]


def test_the_optional_files_are_reported_but_never_required(tmp_path):
    """No commitments is an unregistered domain, no marks is one that has not
    answered anything yet, and no glossary is a glossary with no terms. Each
    absence already means something; none of them stops a build."""
    _domain(tmp_path, "alpha")
    assert domains.is_domain("alpha", tmp_path)
    assert domains.present("alpha", tmp_path) == [MAP, WATCH, WATCH_EN]
    (tmp_path / "alpha" / paths.COMMITMENTS_FILENAME).write_text(
        "[]", encoding="utf-8")
    assert paths.COMMITMENTS_FILENAME in domains.present("alpha", tmp_path)


def test_a_file_beside_the_directories_is_not_a_domain(tmp_path):
    _domain(tmp_path, "alpha")
    (tmp_path / "notes.md").write_text("x", encoding="utf-8")
    assert domains.discover(tmp_path) == ["alpha"]


# -- the live domain is found in the real tree -------------------------------
def test_the_repository_carries_at_least_the_default_domain():
    found = domains.discover()
    assert paths.DEFAULT_DOMAIN in found
    assert found[0] == paths.DEFAULT_DOMAIN
    assert publish_site.root_domain() == paths.DEFAULT_DOMAIN


# -- and it has not moved ----------------------------------------------------
# Byte-for-byte anchors for the domain that was already published. focus_for()
# is a pure function of the tracked map -- no clock, no price store, no out/ --
# so its bytes are a fact about the input and nothing else, which is what makes
# it the one artifact that can be pinned exactly.
GOLD = {
    "he": "9ef5397c13766438557ecbf4bfeb05c2241161292fef22f710a7550d2e1b8817",
    "en": "e16a03c5b9a3e030d16f70c9bf9503ae2b920f206af5c3dbb79f0d773b9eb29f",
}
MOVED = ("the first domain's output moved. If the map changed on purpose, "
         "update the hash here in the same commit and say so; if it did not, "
         "the engine change reflowed a published page.")


@pytest.mark.parametrize("lang", ["he", "en"])
def test_the_first_domains_derived_output_is_byte_for_byte_what_it_was(lang):
    blob = json.dumps(live_snapshot.focus_for(mapfile.load(), lang),
                      ensure_ascii=False, sort_keys=True).encode("utf-8")
    assert hashlib.sha256(blob).hexdigest() == GOLD[lang], MOVED


def test_the_first_domain_reads_the_same_paths_with_or_without_being_named():
    """Every helper grew a domain argument. Passing the name explicitly and
    leaving it out have to land on the same files, or the refactor moved the
    published map without anybody asking for it."""
    d = paths.DEFAULT_DOMAIN
    for fn in (paths.map_path, paths.watch_path, paths.watch_en_path,
               paths.answers_path, paths.marks_path, paths.commitments_path):
        assert fn() == fn(d), fn.__name__
    for fn in (paths.data_dir, paths.out_dir, paths.site_dir):
        assert fn() == fn(d) and fn().name == d, fn.__name__


def test_the_map_loads_identically_named_and_unnamed():
    assert mapfile.load() == mapfile.load(dom=paths.DEFAULT_DOMAIN)


def test_the_published_inventory_for_the_first_domain_is_unchanged():
    """What the site serves per domain, as a list. A generalisation that
    added or dropped a published file would show up here first."""
    assert [d for _s, d in publish_site.COPIES] == [
        "index.html", "he.html", "live_en.json", "live.json",
        "focus_en.json", "focus.json", "commitments.json",
        "track_public.json"]
    assert [d for _s, d in publish_site.TRACK_FILES] == [
        "index.html", "track.enc.json"]
    assert publish_site.TRACK_ASSETS == [
        "lightweight-charts.standalone.production.js",
        "lightweight-charts.LICENSE.txt"]


# -- a brand-new domain builds -----------------------------------------------
# The smallest map the engine accepts, written out here rather than copied from
# the live one: if this file drifts out of what the code needs, this test says
# so, and it doubles as the worked example a new industry is wired against.
FIXTURE_MAP = {
    "chain": "fixture", "as_of": "2026-09-01", "version": "1.0",
    "labels": {
        "brand": {"name": "Fixture"},
        "layers": {"L1": {"he": "ראשון", "en": "first"},
                   "L2": {"he": "שני", "en": "second"}},
        "lines": {"main": {"he": "ראשי", "en": "main", "color": "#8899aa"}},
        "lanes": {"one": {"he": "נתיב", "en": "lane one"}},
        "stages": {"research": {"he": "מחקר", "en": "research"}}},
    "layers": [{"id": "L1", "name": "First", "order": 1, "description": "d"},
               {"id": "L2", "name": "Second", "order": 2, "description": "d"}],
    "nodes": [
        {"id": "aaa", "name": "Alpha Co", "short": "AAA", "ticker": "AAA",
         "exchange": "US", "layer": "L1", "line": "main", "role": "r",
         "price_symbol": "AAA.US", "price_symbol_kind": "primary",
         "market_cap_usd_b": 10, "us_listed": True, "adr": False,
         "competitors": [], "key_suppliers": [], "customer_concentration": "",
         "notes": "", "segment_share": ""},
        {"id": "bbb", "name": "Beta Co", "short": "BBB", "ticker": "BBB",
         "exchange": "US", "layer": "L2", "line": "main", "role": "r",
         "price_symbol": "BBB.US", "price_symbol_kind": "primary",
         "market_cap_usd_b": 5, "us_listed": True, "adr": False,
         "competitors": [], "key_suppliers": [], "customer_concentration": "",
         "notes": "", "segment_share": ""}],
    "edges": [{"from": "aaa", "to": "bbb", "type": "supplies", "what": "parts",
               "group": "g1", "criticality": "high",
               "source": "https://example.invalid/e"}],
    "chokepoints": [{"id": "CP1", "name": "The narrow step",
                     "label": {"he": "צוואר", "en": "narrow step"},
                     "blurb": {"he": "הסבר", "en": "one holder"},
                     "node_ids": ["aaa"], "concentration": "one",
                     "geography": "somewhere", "dependents": ["bbb"],
                     "substitute": "none", "substitution_time": "years",
                     "source": "https://example.invalid/c"}],
    "subnodes": [], "sub_edges": [], "flows": [], "etfs": [],
    "vulnerable": [], "challengers": {}, "display_rules": {},
}
_ROW = {"id": "aaa_q1", "d": "2026-09-10", "confirmed": True, "tk": "AAA",
        "cps": ["CP1"], "win": ["aaa"], "lose": ["bbb"], "kind": "tide",
        "lane": "one", "leaks": []}
# The two lists differ in exactly the two translated fields, which is the whole
# reason there are two of them: the English build never opens the other one.
FIXTURE_HE = [{**_ROW, "who": "אלפא רבעון 1", "lbl": "אלפא"}]
FIXTURE_EN = [{**_ROW, "who": "Alpha Q1", "lbl": "Alpha"}]
HEBREW = re.compile(r"[֐-׿]")


@pytest.fixture
def fixture_domain(tmp_path, monkeypatch):
    """A whole domain nobody has ever built, in a temporary tree."""
    data, out = tmp_path / "data", tmp_path / "out"
    (data / "alpha").mkdir(parents=True)
    (out / "alpha").mkdir(parents=True)
    _w = lambda p, o: p.write_text(json.dumps(o, ensure_ascii=False),
                                  encoding="utf-8")
    _w(data / "alpha" / MAP, FIXTURE_MAP)
    _w(data / "alpha" / WATCH, FIXTURE_HE)
    _w(data / "alpha" / WATCH_EN, FIXTURE_EN)
    # What the price and fundamentals steps would have left behind. Neither
    # carries anything this test measures, and synthesising them is what keeps
    # it offline and deterministic.
    _w(out / "alpha" / "chain_page.json", {"chokepoints": []})
    _w(out / "alpha" / "chain_fundamentals.json", {})
    monkeypatch.setenv("CHIP_MAP_DATA", str(data))
    monkeypatch.setenv("CHIP_MAP_OUT", str(out))
    monkeypatch.setenv("CHIP_MAP_DOMAIN", "alpha")
    return data


def _text() -> dict:
    from chains import questions
    return {"aaa_q1": {f: f"fixture text: {f}" for f in questions.FIELDS}}


def test_a_new_domain_is_discovered_without_anything_being_edited(
        fixture_domain):
    assert domains.discover() == ["alpha"]
    assert paths.map_path().parent.name == "alpha"
    assert mapfile.load()["chain"] == "fixture"


@pytest.mark.parametrize("lang", ["he", "en"])
def test_the_smallest_valid_map_builds_a_snapshot(fixture_domain, lang):
    """The point of the whole exercise: an industry nobody wrote code for
    goes through the same engine and comes out as a snapshot."""
    import datetime as dt
    live = live_snapshot.build(today=dt.date(2026, 9, 16), lang=lang,
                               text=_text())
    assert len(live["nodes"]) == 2
    assert len(live["cps"]) == 1
    assert len(live["watch"]) == 1
    assert live["domain"] == "alpha"


def test_the_english_half_of_a_new_domain_carries_no_hebrew(fixture_domain):
    """Two lists rather than one with two columns, so the English build never
    opens the other file. A new domain inherits that rule for free -- and a
    domain that got it wrong is caught here rather than on the site."""
    import datetime as dt
    en = live_snapshot.build(today=dt.date(2026, 9, 16), lang="en",
                             text=_text())
    assert not HEBREW.search(json.dumps(en, ensure_ascii=False))
    he = live_snapshot.build(today=dt.date(2026, 9, 16), lang="he",
                             text=_text())
    assert HEBREW.search(json.dumps(he, ensure_ascii=False))


def test_a_new_domain_builds_the_page_the_site_serves(fixture_domain):
    """All the way to the artifact, not just to the data. A snapshot that
    builds and a page that does not would still mean editing Python to add an
    industry, which is the thing this is supposed to have stopped."""
    import datetime as dt

    from chains import build_pages
    out = paths.out_dir()
    for lang, name in (("en", "live_en.json"), ("he", "live.json")):
        live = live_snapshot.build(today=dt.date(2026, 9, 16), lang=lang,
                                   text=_text())
        (out / name).write_text(json.dumps(live, ensure_ascii=False),
                                encoding="utf-8")
    doc = mapfile.load()
    for lang, name in (("en", "focus_en.json"), ("he", "focus.json")):
        (out / name).write_text(
            json.dumps(live_snapshot.focus_for(doc, lang), ensure_ascii=False),
            encoding="utf-8")
    build_pages.build_public_en()
    page = out / "public-map-en.html"
    assert page.exists() and page.stat().st_size > 50_000
    assert not HEBREW.search(page.read_text(encoding="utf-8"))


def test_a_second_domain_does_not_disturb_the_first(fixture_domain):
    """Both are found, the default one leads, and each resolves to its own
    directory from the same process."""
    _domain(fixture_domain, paths.DEFAULT_DOMAIN)
    assert domains.discover() == [paths.DEFAULT_DOMAIN, "alpha"]
    assert paths.map_path("alpha").parent.name == "alpha"
    assert paths.map_path(paths.DEFAULT_DOMAIN).parent.name == \
        paths.DEFAULT_DOMAIN


def test_the_price_store_stays_shared_however_many_domains_there_are(
        monkeypatch, tmp_path):
    """Two maps naming the same company must not download it twice."""
    monkeypatch.setenv("CHIP_MAP_OUT", str(tmp_path))
    monkeypatch.delenv("CHIP_MAP_PRICES", raising=False)
    monkeypatch.setenv("CHIP_MAP_DOMAIN", "alpha")
    first = paths.prices_dir()
    monkeypatch.setenv("CHIP_MAP_DOMAIN", "zulu")
    assert paths.prices_dir() == first


# -- the leak gate reads each domain's own question text ---------------------
# Build #74 on main died here. `publish_site --all-domains` walks every map
# from ONE process and sets nothing in the environment, so the gate's fetch --
# which took no domain -- fell back to the first map's section of the corpus.
# Handed the second map's locked ids, it did not scan the wrong text and pass;
# it raised KeyError and took the deploy with it. The quieter half is worse:
# for as long as it lived, the second industry's sentences were never the ones
# being looked for, so its paywall was gated against a corpus that could not
# contain them.
#
# The two maps below both own a question called gev_q3 -- that collision is
# the whole reason the corpus is keyed by domain -- and each writes a
# different sentence under it. Scanning either site against the other's text
# is therefore not a near miss but a wrong answer, in both directions.
LEAK_CORPUS = {
    "alpha": {
        "gev_q3": {"q_en": "Does Alpha name a delivery date for the turbine?",
                   "yes_en": "A date inside the quarter is named on the call.",
                   "no_en": "", "why_en": ""},
        "alpha_only": {"q_en": "Does Alpha raise its capex line again?",
                       "yes_en": "", "no_en": "", "why_en": ""},
    },
    "beta": {
        "gev_q3": {"q_en": "Does Beta hold the reactor schedule for 2027?",
                   "yes_en": "The schedule is reaffirmed without a slip.",
                   "no_en": "", "why_en": ""},
        "beta_only": {"q_en": "Does Beta sign a second offtake agreement?",
                      "yes_en": "", "no_en": "", "why_en": ""},
    },
}


def _leak_site(root, dom, locked, published):
    """A published directory: a snapshot naming its locked rows, and whatever
    bytes we want the scanner to find (index.html is in PAYWALLED)."""
    site = root / dom
    site.mkdir(parents=True, exist_ok=True)
    (site / "live_en.json").write_text(
        json.dumps({"watch": [{"id": i, "locked": True} for i in locked]}),
        encoding="utf-8")
    (site / "index.html").write_text(published, encoding="utf-8")
    return site


@pytest.fixture
def leak_gate(monkeypatch):
    """The gate with its corpus stubbed, and the domain deliberately absent
    from the environment -- the condition CI publishes under."""
    from chains import questions
    monkeypatch.delenv("CHIP_MAP_DOMAIN", raising=False)
    asked = []

    def fetch(url=None, dom=None):
        asked.append(dom)
        # Mirrors the real fallback: no domain means the first map. That is
        # what made this a crash rather than a silent pass.
        got = LEAK_CORPUS[dom or paths.DEFAULT_DOMAIN]
        # And mirrors validate(), which hands back every field a record can
        # carry -- the scan reads all of them, in both languages.
        return {qid: {f: rec.get(f, "") for f in publish_site.FIELDS_CHECKED}
                for qid, rec in got.items()}

    monkeypatch.setattr(questions, "fetch", fetch)
    monkeypatch.setitem(LEAK_CORPUS, paths.DEFAULT_DOMAIN,
                        LEAK_CORPUS["alpha"])
    return asked


def test_two_domains_publish_from_one_process_each_against_its_own_text(
        tmp_path, leak_gate):
    """Both maps are scanned in a single process with nothing in the
    environment to say which is which, and each one's leak is found."""
    a = _leak_site(tmp_path, "alpha", ["gev_q3"],
                   "<p>Does Alpha name a delivery date for the turbine?</p>")
    b = _leak_site(tmp_path, "beta", ["gev_q3"],
                   "<p>Does Beta hold the reactor schedule for 2027?</p>")

    hits_a = publish_site.locked_text_in_site(a, "alpha")
    hits_b = publish_site.locked_text_in_site(b, "beta")

    assert leak_gate == ["alpha", "beta"], \
        "each domain must fetch its own text, not inherit the first map's"
    assert [h.split(" ")[0] for h in hits_a] == ["gev_q3"]
    assert [h.split(" ")[0] for h in hits_b] == ["gev_q3"]


def test_the_second_domain_is_not_judged_by_the_first_domains_sentences(
        tmp_path, leak_gate):
    """The same id, the other map's wording. Beta's site carrying ALPHA's
    gev_q3 sentence is not a leak of beta's paywall, and the scan must say so
    rather than raise -- and must still catch beta's own."""
    site = _leak_site(
        tmp_path, "beta", ["gev_q3", "beta_only"],
        "<p>Does Alpha name a delivery date for the turbine?</p>")
    assert publish_site.locked_text_in_site(site, "beta") == []

    leaked = _leak_site(
        tmp_path / "second", "beta", ["gev_q3", "beta_only"],
        "<p>Does Beta sign a second offtake agreement?</p>")
    assert [h.split(" ")[0] for h in
            publish_site.locked_text_in_site(leaked, "beta")] == ["beta_only"]


def test_a_clean_second_domain_passes_the_gate(tmp_path, leak_gate):
    site = _leak_site(tmp_path, "beta", ["gev_q3", "beta_only"],
                      "<p>Nothing anybody paid for.</p>")
    assert publish_site.locked_text_in_site(site, "beta") == []
