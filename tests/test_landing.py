"""The front door, and the claims the site makes about itself.

Every number on the landing page is read from the published files, every
capability sentence appears only when the file that proves it does, the
free/paid answer is held to chains/access.py, and the "recorded before the
answer" promise is held to the marks and the commitments.
"""
from __future__ import annotations

import json
import re
import shutil

import pytest

from chains import (access, build_pages, landing, live_snapshot, preregister,
                    publish_site, sitenav, track)
from chains.answers import PRIMARY_HORIZON
from chains.mapfile import load as load_map
from chains.paths import (commitments_path, marks_path, templates_dir,
                          watch_path)

MAP = load_map()
WATCH = json.loads(watch_path().read_text(encoding="utf-8"))
COMMITS = json.loads(commitments_path().read_text(encoding="utf-8"))
URL = "https://linchpinsignal.com/"


def _site(tmp_path, *, commitments=True, track_public=True, live=None):
    d = tmp_path / "semi"
    d.mkdir(parents=True, exist_ok=True)
    # The labels in the shape the build actually publishes: already English,
    # built by the same function that writes live_en.json.
    live = live or {"nodes": MAP["nodes"], "cps": MAP["chokepoints"],
                    "watch": WATCH,
                    "labels": live_snapshot.labels_for(MAP, "en")}
    (d / "live_en.json").write_text(json.dumps(live), encoding="utf-8")
    if commitments:
        shutil.copyfile(commitments_path(), d / "commitments.json")
    if track_public:
        (d / "track_public.json").write_text(
            json.dumps({"forecasts": [], "n_resolved": 0}), encoding="utf-8")
    return d


def _page(tmp_path, **kw):
    return landing.render(_site(tmp_path, **kw), "semi", URL)


def _text(html):
    """What a reader sees: tags gone, entities decoded, whitespace folded."""
    import html as _h
    body = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S)
    return _h.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))).strip()


# -- the hero and the proof strip -----------------------------------------------

def test_the_hero_leads_with_the_value_and_both_calls(tmp_path):
    html = _page(tmp_path)
    assert "<h1>The physical supply chain behind AI — mapped.</h1>" in html
    assert '<a class="primary" href="/semi/">Explore the map</a>' in html
    assert '<a class="secondary" href="/semi/track/">See the track record</a>' in html
    assert "See the live record" not in html
    assert html.index("<h1>") < html.index('class="proof"') < html.index('class="cta"')


def test_the_hero_sub_is_the_short_one(tmp_path):
    html = _page(tmp_path)
    i = html.index('<p class="sub">')
    sub = _text(html[i:html.index("</p>", i)])
    assert sub == ("See who supplies whom — and where it breaks. Every forecast's "
                   "scoring rules are set before the answer. No backtests.")
    bare = _text(_page(tmp_path / "bare", commitments=False))
    assert "See who supplies whom — and where it breaks. No backtests." in bare


def test_the_three_steps_sit_above_the_full_explanation(tmp_path):
    html = _page(tmp_path)
    assert html.index('<section id="steps"') < html.index('<section id="how">')
    i = html.index('<section id="steps"')
    strip = _text(html[i:html.index("</section>", i)])
    assert strip == (
        "01 Map Who supplies whom across the AI supply chain, and where the "
        "chokepoints are. "
        "02 Question Dated questions across the chain, each with yes/no criteria "
        "set before the answer. "
        "03 Score When the answer lands, the forecast is measured against the "
        "market — pre-registered, so anyone can verify it.")
    # The detailed prose is still all there, beneath it.
    for h in ("The chain, in layers", "Semiconductor chokepoints",
              "Dated questions", "Scored forward against the market",
              "Pre-registered and verifiable", "Forward testing, no backtests"):
        assert f"<h3>{h}</h3>" in html, h


def test_the_score_step_only_claims_verification_with_its_proof(tmp_path):
    html = _page(tmp_path, track_public=False)
    i = html.index('<section id="steps"')
    strip = _text(html[i:html.index("</section>", i)])
    assert strip.endswith("the forecast is measured against the market.")
    assert "verify" not in strip.lower()


def test_the_proof_strip_is_read_from_the_published_data(tmp_path):
    text = _text(_page(tmp_path))
    for s in (f"{len(MAP['nodes'])} companies",
              f"{len(MAP['chokepoints'])} chokepoints",
              f"{len(WATCH)} dated questions", "No backtests"):
        assert s in text, s


def test_a_different_snapshot_gives_different_numbers(tmp_path):
    live = {"nodes": MAP["nodes"][:3], "cps": MAP["chokepoints"][:2],
            "watch": WATCH[:4], "labels": live_snapshot.labels_for(MAP, "en")}
    text = _text(_page(tmp_path, live=live))
    assert "3 companies" in text and "2 chokepoints" in text
    assert "4 dated questions" in text


def test_every_node_counted_as_a_company_is_a_listed_one():
    assert all(n.get("ticker") for n in MAP["nodes"])


# -- how it works: each sentence against the code and data ----------------------

def test_the_layers_are_the_maps_own(tmp_path):
    text = _text(_page(tmp_path))
    layers = MAP["labels"]["layers"]
    order = sorted(layers, key=lambda k: int(k[1:]))
    assert f"in {len(order)} layers: " in text
    for k in order:
        assert layers[k]["en"] in text, k


def test_the_published_label_shape_and_the_maps_shape_read_the_same(tmp_path):
    """live_en.json carries labels already in English; map.json carries both
    languages. The page must not depend on which one it was handed."""
    flat = live_snapshot.labels_for(MAP, "en")
    assert all(isinstance(v, str) for v in flat["layers"].values())
    base = {"nodes": MAP["nodes"], "cps": MAP["chokepoints"], "watch": WATCH}
    a = _text(landing.render(_site(tmp_path / "a", live=dict(base, labels=flat)),
                             "semi", URL))
    b = _text(landing.render(_site(tmp_path / "b",
                                   live=dict(base, labels=MAP["labels"])),
                             "semi", URL))
    assert a == b


def test_the_chokepoint_examples_are_chokepoints_on_the_map(tmp_path):
    names = " ".join(c["name"] for c in MAP["chokepoints"]).lower()
    for example in ("euv lithography", "hbm", "advanced packaging"):
        assert example in names, example
    assert "such as EUV lithography, HBM memory and advanced packaging" in \
        _text(_page(tmp_path))


def test_the_page_never_says_every_question_sits_on_a_chokepoint(tmp_path):
    assert not all(r.get("cps") for r in WATCH), "the data would allow it"
    text = _text(_page(tmp_path)).lower()
    assert "paired with" in text and "dated questions across the chain" in text
    for phrase in ("every dated question sits", "each question sits on",
                   "all questions are on"):
        assert phrase not in text


def test_the_basket_sentence_follows_the_observation_only_rows(tmp_path):
    n = sum(1 for r in WATCH if r.get("observe_only"))
    assert n > 0
    assert f"Observation-only questions ({n} today)" in _text(_page(tmp_path))
    live = {"nodes": MAP["nodes"], "cps": MAP["chokepoints"],
            "watch": [r for r in WATCH if not r.get("observe_only")],
            "labels": live_snapshot.labels_for(MAP, "en")}
    assert "Observation-only" not in _text(_page(tmp_path, live=live))


def test_the_scoring_sentence_is_the_scoring_code(tmp_path):
    text = _text(_page(tmp_path))
    assert (f"primary horizon of {PRIMARY_HORIZON} trading sessions"
            in text)
    diag = [h for h in preregister.CONTRACT_HORIZONS if h != PRIMARY_HORIZON]
    assert (", ".join(map(str, diag[:-1])) + f" and {diag[-1]} sessions are "
            "kept as diagnostics") in text
    assert preregister.BENCHMARKS["sox"] in text and "(EW_MAP)" in text
    assert "EW_MAP" in preregister.BENCHMARKS["ew"]


# -- capabilities appear only with their proof ------------------------------------

PREREG_WORDS = ("SHA-256", "commitments.json", "track_public.json", "Verify",
                "scoring rules are set before the answer",
                "with its verification", "anyone can verify it")


def test_with_both_files_the_preregistration_is_described(tmp_path):
    text = _text(_page(tmp_path))
    for w in PREREG_WORDS:
        assert w in text, w
    n_valid = sum(1 for e in COMMITS if e["valid_preregistration"])
    assert f"{n_valid} of the {len(COMMITS)} questions committed so far" in text


@pytest.mark.parametrize("missing", ["commitments", "track_public"])
def test_without_either_file_nothing_about_it_is_claimed(tmp_path, missing):
    html = _page(tmp_path, **{missing: False})
    text = _text(html)
    for w in PREREG_WORDS:
        assert w not in text, (missing, w)
    assert "SHA-256" not in html, "not even in the meta description"


def test_every_registered_forecast_was_committed_before_its_answer():
    """What the hero line and the nav descriptor promise, held to the data: a
    forecast registered against a question whose commitment came on or after
    its answer date fails the build rather than sitting under that promise."""
    marks = json.loads(marks_path().read_text(encoding="utf-8"))
    by = {e["qid"]: e for e in COMMITS}
    late = [f["qid"] for f in marks.get("forecasts", [])
            if not by.get(f["qid"], {}).get("valid_preregistration")]
    assert late == []


# -- the FAQ ----------------------------------------------------------------------

def test_the_faq_asks_the_four_questions(tmp_path):
    html = _page(tmp_path)
    for q in ("What is Linchpin Signal?", "How are forecasts registered?",
              "What's free, and what needs the key?",
              "Is this investment advice?"):
        assert f"<h3>{q}</h3>" in html, q


def test_the_advice_answer_is_exact(tmp_path):
    assert ("No. Linchpin Signal publishes questions and measurements, not "
            "recommendations. It is not investment advice.") in _text(_page(tmp_path))


SUBSCRIBE_FAQ = (" Subscribe (free), confirm in the first email, and the key "
                 "arrives in the welcome email right after.")


def test_the_free_and_key_answer_is_held_to_access_py(tmp_path, monkeypatch):
    monkeypatch.delenv("SUBSCRIBE_EMBED_URL", raising=False)
    text = _text(_page(tmp_path))
    assert ("Everything is free. The map, every chokepoint, the calendar, and "
            "every resolved question with its verification are open. The "
            "questions still ahead — their wording, baskets and live board — "
            "unlock with a key sent in the weekly mail." + SUBSCRIBE_FAQ) in text
    bare = _text(_page(tmp_path / "bare", commitments=False))
    assert "every resolved question are open" in bare, \
        "verification is claimed only with its proof"
    monkeypatch.setattr(access, "tier", lambda item, ctx=None: "free")
    with pytest.raises(landing.LandingError, match="access.py"):
        _page(tmp_path)


def _track_page():
    return track.render(track.public({"summary": {}, "forecasts": []}))


def test_no_public_page_describes_a_charge(tmp_path):
    """The product is free. The questions ahead need the key from the weekly
    mail, and no English page may say they cost anything."""
    en = tmp_path / "live-map-en.html"
    build_pages.build_en_template(dst=en)
    tpl = (templates_dir() / "track.html").read_text(encoding="utf-8")
    i = tpl.index("// ---- the locked panel")
    locked = re.sub(r"\s+", " ", tpl[i:tpl.index("// ---- the key", i)])
    assert "Unlocks with the key from the weekly mail." in locked
    pages = {"landing": _text(_page(tmp_path)),
             "track": build_pages.visible_text(_track_page()),
             "track locked panel": locked,
             "map": en.read_text(encoding="utf-8")}
    for name, body in pages.items():
        low = body.lower()
        for word in ("paid", "subscribers:", "subscribers pay", "pricing",
                     "checkout"):
            assert word not in low, (name, word)
    assert "Key from the mail" in _track_page() and ">Unlock</button>" in \
        _track_page()


# -- the subscribe slot: dormant until SUBSCRIBE_EMBED_URL is set ------------------

EMBED = "https://linchpinsignal.substack.com/embed"


def test_the_live_publication_is_the_configured_form(monkeypatch):
    from chains import paths
    assert paths.SUBSCRIBE_EMBED_URL == EMBED
    monkeypatch.delenv("SUBSCRIBE_EMBED_URL", raising=False)
    assert paths.subscribe_embed_url() == EMBED


def test_without_the_embed_url_neither_page_offers_a_signup(tmp_path,
                                                            monkeypatch):
    monkeypatch.setenv("SUBSCRIBE_EMBED_URL", "")
    assert SUBSCRIBE_FAQ.strip() not in _text(_page(tmp_path))
    for html in (_page(tmp_path), _track_page()):
        assert "<iframe" not in html
        assert sitenav.SUBSCRIBE_LABEL not in html
        assert sitenav.SUBSCRIBE_CONFIRM not in html
        assert "mailkey" not in build_pages.visible_text(html)
        assert "subscribe" not in build_pages.visible_text(html).lower()


def test_the_signup_links_to_the_publication_not_to_the_embed():
    """The embed path is what the site is configured with; the link is the page
    a reader can actually open. No path is invented on the way."""
    assert sitenav.subscribe_link(EMBED) == "https://linchpinsignal.substack.com"
    assert sitenav.subscribe_link("https://x.example/") == "https://x.example/"


def test_with_the_embed_url_both_pages_call_out_under_the_label(
        tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCRIBE_EMBED_URL", EMBED)
    assert sitenav.SUBSCRIBE_LABEL == \
        "Get the key — subscribe to the weekly mail (free)"
    # The embed is double opt-in: the confirm step is said before the call.
    assert sitenav.SUBSCRIBE_CONFIRM == ("Confirm in the first email — the key "
                                         "arrives in the welcome email right after.")
    land, trk = _page(tmp_path), _track_page()
    link = 'href="https://linchpinsignal.substack.com"'
    for html in (land, trk):
        # Not a frame. Substack serves the embed as its own white page, and a
        # cross-origin frame cannot be restyled from here, so on these dark
        # pages it landed as a white rectangle. A link keeps the page dark.
        assert "<iframe" not in html
        assert link in html
        assert 'target="_blank" rel="noopener"' in html
        assert "background:#fff" not in html
        assert "max-width:480px" in html
        assert sitenav.SUBSCRIBE_LABEL in _text(html)
        assert sitenav.SUBSCRIBE_CONFIRM in _text(html)
        assert sitenav.SUBSCRIBE_CTA in _text(html)
        assert (html.index(sitenav.SUBSCRIBE_LABEL)
                < html.index(sitenav.SUBSCRIBE_CONFIRM) < html.index(link))
    assert SUBSCRIBE_FAQ.strip() in _text(land)
    # Beside the call to the track record, and beside the key field.
    assert (land.index("See the track record</a>") < land.index(link)
            < land.index("</header>"))
    assert (trk.index('placeholder="Key from the mail"') < trk.index(link)
            < trk.index('<div id="full">'))


@pytest.mark.parametrize("embed", ["", EMBED])
def test_both_pages_pass_the_gates_with_or_without_the_slot(tmp_path,
                                                           monkeypatch, embed):
    monkeypatch.setenv("SUBSCRIBE_EMBED_URL", embed)
    land, trk = _page(tmp_path), _track_page()
    for html in (land, trk):
        assert build_pages.hebrew_runs(html) == []
        assert build_pages.render_faults(html) == []
    # The slot adds its own block (and, on the landing, its FAQ sentence) and
    # nothing else, so whatever the locked-text gate decides about the page
    # without it, it decides about the page with it.
    block = sitenav.subscribe_html(embed or None)
    monkeypatch.setenv("SUBSCRIBE_EMBED_URL", "")
    assert (land.replace(block, "").replace(SUBSCRIBE_FAQ, "")
            == _page(tmp_path))
    assert trk.replace(block, "") == _track_page()
    for r in WATCH:
        assert r.get("who", "") == "" or f">{r['who']}<" not in block


def test_the_embed_url_must_be_https(monkeypatch):
    from chains import paths
    monkeypatch.setenv("SUBSCRIBE_EMBED_URL", "javascript:alert(1)")
    with pytest.raises(SystemExit):
        paths.subscribe_embed_url()
    monkeypatch.setenv("SUBSCRIBE_EMBED_URL", "   ")
    assert paths.subscribe_embed_url() is None


def test_no_absolute_or_return_claims(tmp_path):
    text = _text(_page(tmp_path)).lower()
    for phrase in ("everyone depends", "will move", "beat the market",
                   "outperform", "guarantee", "alpha", "statistically significant"):
        assert phrase not in text, phrase


# -- SEO, structure, and nothing that tracks ---------------------------------------

def test_title_description_canonical_and_keywords(tmp_path):
    html = _page(tmp_path)
    assert re.search(r"<title>[^<]*AI supply chain map[^<]*</title>", html)
    assert '<meta name="description" content="' in html
    assert f'<link rel="canonical" href="{URL}">' in html
    text = _text(html)
    for kw in ("AI supply chain", "semiconductor chokepoints",
               "semiconductor supply chain map", "HBM", "EUV",
               "advanced packaging", "AI infrastructure", "Forward testing"):
        assert kw.lower() in (text + html).lower(), kw


def test_json_ld_is_website_and_organization(tmp_path):
    html = _page(tmp_path)
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    data = json.loads(m.group(1))
    assert {d["@type"] for d in data} == {"WebSite", "Organization"}
    assert all(d["url"] == URL and d["name"] == "Linchpin Signal" for d in data)


def test_the_page_is_static_and_its_only_tracker_is_plausible(tmp_path):
    """One external script origin, exactly https://plausible.io, and only the
    shared snippet and the form's one event call. Take those out and the page
    is what it was: static, with nothing else that tracks."""
    html = _page(tmp_path)
    srcs = re.findall(r"<script\b[^>]*\bsrc=\"([^\"]+)\"", html)
    assert srcs and all(s.startswith(sitenav.ANALYTICS_ORIGIN + "/")
                        for s in srcs), srcs
    assert html.count(sitenav.ANALYTICS) == 1
    event = f'<script>{sitenav.event_js("subscribe_form_view")}</script>'
    html = html.replace(sitenav.ANALYTICS, "", 1).replace(event, "", 1)
    scripts = re.findall(r"<script\b[^>]*>", html)
    assert scripts == ['<script type="application/ld+json">']
    for word in ("gtag", "analytics", "googletagmanager", "plausible", "fbq",
                 "matomo", "segment.io"):
        assert word not in html.lower(), word


def test_the_landing_passes_the_hebrew_gate_and_carries_no_question_text(tmp_path):
    html = _page(tmp_path)
    assert build_pages.hebrew_runs(html) == []
    for r in WATCH:
        assert r.get("who", "") == "" or f">{r['who']}<" not in html


def test_the_landing_is_published_and_gated_at_the_root():
    assert "../index.html" in publish_site.GATED
    assert "../index.html" in publish_site.PAYWALLED
    assert hasattr(publish_site, "write_landing")
    assert not hasattr(publish_site, "write_root_redirect")


# -- Track Record: first-class on all three pages -----------------------------------

NAV = ('<a class="rec" href="/semi/track/"', sitenav.TRACK_RECORD,
       sitenav.TRACK_RECORD_DESCRIPTOR)


def test_track_record_is_in_the_landing_nav(tmp_path):
    html = _page(tmp_path)
    for s in NAV:
        assert s in html, s
    assert sitenav.TRACK_RECORD == "Track Record"
    assert sitenav.TRACK_RECORD_DESCRIPTOR == "Every forecast recorded before the answer."


def test_track_record_is_in_the_track_page_nav_and_the_title_stays():
    page = track.render(track.public({"summary": {}, "forecasts": []}))
    for s in NAV:
        assert s in page, s
    assert 'aria-current="page">Track Record</a>' in page
    assert "<title>Forward test" in page
    assert "__SITE_NAV" not in page


def _map_page(live='{"nodes":[],"cps":[]}'):
    tpl = (templates_dir() / build_pages.TEMPLATE_EN).read_text(encoding="utf-8")
    return build_pages.public_page(tpl, live, build_pages.PUB["en"])


def test_track_record_is_in_the_map_nav():
    page = _map_page()
    for s in NAV:
        assert s in page, s


def test_the_map_leads_with_the_value_and_the_calls_above_the_instructions():
    page = _map_page()
    i_value = page.index('<p class="value">')
    i_cta = page.index('<div class="valuecta">')
    i_how = page.index('<div class="sub">Raw materials on the left')
    assert i_value < i_cta < i_how
    assert 'href="#stage">Explore the map</a>' in page
    assert 'href="/semi/track/">See the live record</a>' in page
    assert '<a class="fwd" href="track/">Forward test →</a>' not in page


def test_the_map_names_the_track_record_one_way():
    """The nav says Track Record, so the link inside the page does too, and no
    "Forward test" label is left on the public map -- including in the cards
    the build inlines into it."""
    page = build_pages._inline_cards(_map_page())
    assert '<a class="fwd inline" href="track/">Track Record →</a>' in page
    assert "<h2>Track Record</h2>" in page
    assert "Forward test" not in page


def test_the_track_page_keeps_its_own_title():
    page = track.render(track.public({"summary": {}, "forecasts": []}))
    assert "<title>Forward test" in page


def test_the_map_description_counts_come_from_the_snapshot():
    live = json.dumps({"nodes": [{}] * 3, "cps": [{}] * 2})
    assert "3 stations, 2 chokepoints" in _map_page(live)
    assert "49 stations" not in _map_page(live)


# -- more than one map ---------------------------------------------------------
# The front door leads to every map the site serves. Its headline numbers are
# the site's, not the first map's: when the second industry arrived, the page
# went on quoting one map's question count while linking to both, which
# undercounts the thing the link points at.
#
# publish_site writes this page from the root domain's publish only, so the
# numbers come from whichever map happens to be root. That is one map's
# accident of sort order deciding what the site says about itself, and the
# test below pins the page against it: rendered from either map, the proof
# strip has to read the same.
ENERGY = "energy"


def _two_sites(tmp_path):
    """Two published directories, as --all-domains leaves them."""
    semi = _site(tmp_path)
    other = tmp_path / ENERGY
    other.mkdir(parents=True, exist_ok=True)
    emap = load_map(dom=ENERGY)
    ewatch = json.loads(
        (watch_path(ENERGY)).read_text(encoding="utf-8"))
    (other / "live_en.json").write_text(json.dumps(
        {"nodes": emap["nodes"], "cps": emap["chokepoints"], "watch": ewatch,
         "labels": live_snapshot.labels_for(emap, "en")}), encoding="utf-8")
    return semi, other, len(ewatch)


def _both(tmp_path, dom="semi"):
    semi, _other, n = _two_sites(tmp_path)
    src = semi if dom == "semi" else tmp_path / dom
    return landing.render(src, dom, URL, live=["semi", ENERGY]), n


def test_every_published_map_gets_a_card(tmp_path):
    html_, _n = _both(tmp_path)
    for dom in ("semi", ENERGY):
        title = ((load_map(dom=dom)["labels"]["brand"].get("title") or {})
                 .get("en"))
        assert f'<a href="/{dom}/"' in html_, dom
        assert f'<a href="/{dom}/track/">Track Record</a>' in html_, dom
        assert title and title in html_, dom


def test_each_card_carries_that_maps_own_description(tmp_path):
    """The blurb is the map's sentence about itself, not the engine's."""
    html_, _n = _both(tmp_path)
    for dom in ("semi", ENERGY):
        value = ((load_map(dom=dom)["labels"]["brand"].get("value") or {})
                 .get("en"))
        assert value, f"{dom} declares no value line to show"
        assert value in _text(html_), dom


def test_each_card_counts_that_maps_own_questions(tmp_path):
    html_, n_energy = _both(tmp_path)
    text = _text(html_)
    assert f"{len(WATCH)} dated questions" in text
    assert f"{n_energy} dated questions" in text


def test_the_headline_counts_every_map(tmp_path):
    """39 + 14, added up here rather than typed into the template."""
    html_, n_energy = _both(tmp_path)
    text = _text(html_)
    total = len(WATCH) + n_energy
    assert f"{total} dated questions" in text
    emap = load_map(dom=ENERGY)
    assert (f"{len(MAP['nodes']) + len(emap['nodes'])} companies") in text
    assert (f"{len(MAP['chokepoints']) + len(emap['chokepoints'])} "
            f"chokepoints") in text
    assert "2 maps" in text


def test_the_headline_does_not_depend_on_which_map_rendered_it(tmp_path):
    """The root domain renders it, and which map that is, is sort
    order. The page must read the same either way."""
    from_semi, _n = _both(tmp_path, "semi")
    from_energy, _n = _both(tmp_path, ENERGY)
    strip = lambda h: re.search(r'class="proof".*?</ul>', h, re.S).group(0)
    assert strip(from_semi) == strip(from_energy)


def test_a_second_maps_benchmark_is_named_as_its_own(tmp_path):
    """The scoring sentence stops naming one index for every map, and each
    card carries the benchmark that map is actually scored against."""
    html_, _n = _both(tmp_path)
    text = _text(html_)
    assert landing.forecast_benchmark_label(ENERGY) in text
    assert "PHLX Semiconductor Sector Index" not in text, \
        "one industry's index must not be stated as fact for every map"


def test_one_map_still_reads_exactly_as_it_did(tmp_path):
    """The whole multi-map apparatus is conditional: a site serving a single
    map must be byte-for-byte the page it was."""
    one = landing.render(_site(tmp_path), "semi", URL)
    assert one == landing.render(_site(tmp_path), "semi", URL, live=["semi"])
    assert '<li class="mapcard">' not in one and "2 maps" not in one


# -- the front door is written after every map, not during the first ----------
# Shipped wrong once, in build #76. The page counts across every map and reads
# those numbers from the published directories beside it, so WHEN it is
# written decides what it can see. It was written inside the root domain's
# publish -- first, into a site/ that a fresh checkout leaves empty -- so the
# second map's directory did not exist yet, its card could not be drawn, and
# no later publish came back: only the root domain ever wrote this file. The
# live site advertised one map and 39 questions while serving two maps and 53,
# with the second map's own pages published and reachable one directory away.
#
# Nothing was stale and nothing was cached. The file was correct for the
# instant it was written and never written again. This test starts from an
# empty directory, which is the only condition that shows it.

def _published(root, dom, nodes, cps, watch):
    d = root / dom
    d.mkdir(parents=True, exist_ok=True)
    (d / "live_en.json").write_text(json.dumps(
        {"nodes": nodes, "cps": cps, "watch": watch,
         "labels": live_snapshot.labels_for(load_map(dom=dom), "en")}),
        encoding="utf-8")
    return d


@pytest.fixture
def walked(tmp_path, monkeypatch):
    """--all-domains against an empty site/, with publish reduced to what it
    leaves behind: the snapshot the front door reads."""
    from chains import domains as registry
    root = tmp_path / "site"
    names = ["semi", ENERGY]
    order = []
    emap = load_map(dom=ENERGY)
    ewatch = json.loads(watch_path(ENERGY).read_text(encoding="utf-8"))
    rows = {"semi": (MAP["nodes"], MAP["chokepoints"], WATCH),
            ENERGY: (emap["nodes"], emap["chokepoints"], ewatch)}

    def fake_publish(dst=None, dom=None, landing=True):
        order.append(("publish", dom))
        assert not landing, \
            "a walk must not write the front door inside a domain's publish"
        return _published(root, dom, *rows[dom]), []

    monkeypatch.setattr(registry, "discover", lambda *a, **k: list(names))
    monkeypatch.setattr(publish_site, "site_root", lambda: root)
    monkeypatch.setattr(publish_site, "site_dir", lambda d=None: root / d)
    monkeypatch.setattr(publish_site, "publish", fake_publish)
    monkeypatch.setattr(publish_site, "locked_text_in_site",
                        lambda *a, **k: [])
    real_write = publish_site.write_landing

    def watched(src, dom, live=None):
        order.append(("front door", dom))
        return real_write(src, dom, live)

    monkeypatch.setattr(publish_site, "write_landing", watched)
    assert publish_site.main(["--all-domains"]) == 0
    return root, order, len(ewatch)


def test_the_front_door_is_written_once_and_last(walked):
    _root, order, _n = walked
    assert order == [("publish", "semi"), ("publish", ENERGY),
                     ("front door", "semi")]


def test_the_front_door_names_every_map_from_an_empty_site(walked):
    root, _order, n_energy = walked
    html_ = (root / "index.html").read_text(encoding="utf-8")
    for dom in ("semi", ENERGY):
        assert f'<a href="/{dom}/"' in html_, dom
    assert html_.count('<li class="mapcard">') == 2
    text = _text(html_)
    assert f"{len(WATCH) + n_energy} dated questions" in text
    assert "2 maps" in text
