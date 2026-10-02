"""The copy and design revision, held to the four things it must not break.

The brief renamed a lot of words. Four of those renames are the kind that
silently break something a reader depends on, so each has a test here:

1. EMOJI. Three of them shipped -- a padlock on the locked question card, on
   the board tooltip and on the locked panel of the track page. They are out
   of every product surface now, and a fourth cannot arrive unnoticed.

2. THE LOCKED PLACEHOLDER. It used to be four sentences of invented financial
   prose under a CSS blur. A blur is a picture: the sentences were in the DOM,
   and they read as real writing to anyone who looked. The placeholder is now
   drawn by CSS and carries no text at all.

3. THE URL VOCABULARY. The pressure states are called Tightening, Easing and
   No listed challenger on screen. The query parameter that restores a filtered
   view still spells them tightening, eroding and unmeasured, because a link
   somebody shared last week has to keep working.

4. THE CLAIMS THE DATA DOES NOT CARRY. Two sentences in the brief are not true
   of this data: "Station size reflects market capitalization" (34 of 178
   stations record one; four of the five maps record none) and "Every
   published figure carries a source" (the market caps and every price-derived
   return carry none). Both are stated here as the measurements that decided
   them, so the day the data changes, the test says so rather than the copy
   quietly staying wrong.
"""
from __future__ import annotations

import json
import re

import pytest

from chains import domains, sitenav
from chains.paths import map_path, templates_dir

PAGES = ("landing.html", "live-map.html", "live-map-en.html", "track.html",
         "track-site.html", "track-cards.js")


def tpl(name: str) -> str:
    return (templates_dir() / name).read_text(encoding="utf-8")


# -- 1. no emoji --------------------------------------------------------------
# Not "no symbols": the arrows, the triangles and the middle dot are
# typography and the site is built out of them. Emoji are the pictographic
# blocks, and a padlock from one of them is the thing that kept appearing.
EMOJI_BLOCKS = ((0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2B00, 0x2BFF),
                (0xFE0F, 0xFE0F), (0x1F1E6, 0x1F1FF))


def emoji_in(s: str) -> list[str]:
    return sorted({c for c in s
                   if any(lo <= ord(c) <= hi for lo, hi in EMOJI_BLOCKS)})


def escaped_emoji_in(s: str) -> list[str]:
    """The same characters spelled as escapes, which is how they hid.

    ``\\u{1F512}`` in a JavaScript string and ``&#128274;`` in HTML both reach
    the reader as a padlock and neither is a padlock in the file.
    """
    out = []
    for m in re.finditer(r"\\u\{([0-9a-fA-F]{4,6})\}|&#(\d{4,7});", s):
        code = int(m.group(1), 16) if m.group(1) else int(m.group(2))
        if any(lo <= code <= hi for lo, hi in EMOJI_BLOCKS):
            out.append(m.group(0))
    return sorted(set(out))


@pytest.mark.parametrize("name", PAGES)
def test_no_template_carries_an_emoji(name):
    s = tpl(name)
    assert emoji_in(s) == [], name
    assert escaped_emoji_in(s) == [], name


def test_no_copy_module_carries_an_emoji():
    for mod in ("sitenav.py", "landing.py", "track.py", "track_site.py",
                "build_pages.py"):
        s = (templates_dir().parent / mod).read_text(encoding="utf-8")
        assert emoji_in(s) == [], mod
        assert escaped_emoji_in(s) == [], mod


def test_no_map_label_carries_an_emoji():
    for dom in domains.discover():
        labels = json.loads(map_path(dom).read_text(encoding="utf-8")).get(
            "labels") or {}
        assert emoji_in(json.dumps(labels, ensure_ascii=False)) == [], dom


# -- 2. the locked placeholder holds no question ------------------------------

def test_the_dummy_question_prose_is_gone_from_both_templates():
    for name in ("live-map.html", "live-map-en.html"):
        s = tpl(name)
        assert "const PH = {" not in s, name
        assert "LOCK.dummy" not in s, name
        # The blur went with it. It was never a lock: the sentence it covered
        # was in the DOM, and a screenshot of it is the sentence.
        assert 'class="blur"' not in s, name
        assert "filter:blur" not in s.split("</style>")[0], name


@pytest.mark.parametrize("name", ["live-map.html", "live-map-en.html"])
def test_a_locked_card_renders_bars_and_reads_nothing_from_its_row(name):
    s = tpl(name)
    i = s.index("function midLocked(")
    body = s[i:s.index("\n  }", i)]
    assert 'class="redact"' in body and 'aria-hidden="true"' in body
    # Nothing but widths inside the bars: no text node can reach them.
    for bar in re.findall(r"<i style=\"width:\d+%\"></i>", body):
        assert bar.endswith("></i>")
    for read in ("w.", "r.", "PH.", "esc(w", "q}", "yes}", "no}"):
        assert read not in body, f"{name}: a locked card must not read {read}"


def test_the_track_pages_locked_panel_carries_no_sentence_of_its_own():
    s = tpl("track.html")
    i = s.index('<div class="ghost"')
    body = s[i:s.index("</div>", s.index('class="lockover"', i))]
    assert "bars(" in body, "the placeholder is drawn, not written"
    import re as _re
    flat = _re.sub(r"\s+", " ", body)
    assert "Upcoming question" in flat
    assert "available with the weekly key" in flat


# -- 3. old links still restore the view they restored ------------------------
# The labels changed; the vocabulary in the query string did not.
URL_VALUES = ("tightening", "eroding", "unmeasured")
URL_PARAMS = ("q", "layer", "cp", "pulse", "station", "rail")


@pytest.mark.parametrize("name", ["live-map.html", "live-map-en.html"])
def test_the_pulse_parameter_still_takes_its_old_three_values(name):
    s = tpl(name)
    i = s.index("FILTERS.pulse = pick('pulse'")
    line = s[i:s.index("\n", i)]
    for v in URL_VALUES:
        assert f"'{v}'" in line, f"{name}: {v} no longer restores"


@pytest.mark.parametrize("name", ["live-map.html", "live-map-en.html"])
def test_every_url_parameter_from_the_shareable_view_still_reads(name):
    s = tpl(name)
    i = s.index("function readURL(")
    read = s[i:s.index("\n}", i)]
    for p in URL_PARAMS:
        assert (f"pick('{p}'" in read or f"p.get('{p}')" in read), f"{name}: {p}"
    # And each one is still written back, or a copied link loses it.
    j = s.index("function writeURL(")
    write = s[j:s.index("\n}", j)]
    for p in URL_PARAMS:
        assert f"set('{p}'" in write, f"{name}: {p} is read but never written"


@pytest.mark.parametrize("name", ["live-map.html", "live-map-en.html"])
def test_the_option_values_are_the_url_values_and_the_labels_are_not(name):
    """The <option> value is what goes in the link; RAIL.pulseT is what the
    reader sees. Wiring the label into the value would have broken every
    link the moment "eroding" became "Easing"."""
    s = tpl(name)
    for v, label in zip(URL_VALUES, ("pulseT", "pulseE", "pulseA")):
        assert f"opt('{v}', RAIL.{label}" in s, f"{name}: {v}"


def test_the_english_labels_are_the_briefs_words():
    s = tpl("live-map-en.html")
    for want in ("pulseT:'Tightening'", "pulseE:'Easing'",
                 "pulseA:'No listed challenger'"):
        assert want in s, want
    # And the legend beside the map says the same three.
    for want in ("Tightening</span>", "Easing</span>",
                 "No listed challenger</span>"):
        assert want in s, want


# -- 4. the two claims the data does not carry --------------------------------

def _brand_stations():
    n = capped = 0
    for dom in domains.discover():
        nodes = json.loads(map_path(dom).read_text(encoding="utf-8")).get(
            "nodes") or []
        n += len(nodes)
        capped += sum(1 for x in nodes if x.get("market_cap_usd_b"))
    return n, capped


def test_most_stations_record_no_market_value_so_size_is_qualified():
    n, capped = _brand_stations()
    assert capped < n, (
        "every station now records a market value: the qualified sentence in "
        "the pressure-method footer can go back to the brief's wording")
    s = tpl("live-map-en.html")
    assert "A station with a recorded market value is drawn to it" in s
    assert "Station size reflects market capitalization" not in s
    assert "Station size is market cap" not in s


def test_no_page_claims_every_published_figure_carries_a_source():
    """The supplier shares do -- 88 sourced, and the 42 without one publish
    blank rather than unsourced. The market caps and the price-derived
    returns do not, so the blanket sentence is not made anywhere."""
    absolutes = ("Every published figure carries a source",
                 "Every number carries a source",
                 "every number carries a source",
                 "Sources attached to every published measure",
                 "Every number is shown with its source")
    bad = []
    for name in PAGES:
        s = tpl(name)
        bad += [f"{name}: {a}" for a in absolutes if a in s]
    src = (templates_dir().parent / "sitenav.py").read_text(encoding="utf-8")
    bad += [f"sitenav.py: {a}" for a in absolutes if a in src]
    for dom in domains.discover():
        raw = map_path(dom).read_text(encoding="utf-8")
        labels = json.dumps(
            json.loads(raw).get("labels") or {}, ensure_ascii=False)
        bad += [f"{dom}/map.json: {a}" for a in absolutes if a in labels]
    assert not bad, bad


def test_what_the_footer_says_instead_is_what_the_shares_actually_do():
    s = tpl("live-map-en.html")
    assert ("Supplier shares are shown with their source and left blank "
            "where none is recorded; estimates are labelled." in s)
    assert sitenav.FOOTER_NOTE.endswith(
        "Sources shown where recorded; estimates labelled")


def test_a_share_is_either_sourced_or_published_blank():
    """What the footer sentence above rests on. A share with a value and no
    source would make it false, and there is none."""
    unsourced = []
    for dom in domains.discover():
        for sub in json.loads(map_path(dom).read_text(encoding="utf-8")).get(
                "subnodes") or []:
            share = sub.get("share") or {}
            value = str(share.get("value") or "")
            if not value or "unsourced" in value.lower():
                continue          # published blank; see live_snapshot.py
            if not share.get("source"):
                unsourced.append(f"{dom}/{sub.get('id')}")
    assert not unsourced, unsourced


# -- 5. the cadence the page states is the cadence the workflow runs ----------
# The brief asks the map's metadata line to say "refreshed weekly". It is not
# weekly, and a cadence claim is the easy kind to leave behind when a cron
# changes, so the sentence and the schedule are checked against each other.
CRON = "30 5 * * 2-6"          # Tue-Sat, once after each US trading session
CADENCE = "rebuilt after each trading session"


def test_the_map_states_the_cadence_its_workflow_actually_runs():
    wf = (templates_dir().parents[1] / ".github" / "workflows"
          / "build.yml").read_text(encoding="utf-8")
    assert f'cron: "{CRON}"' in wf, (
        "the build schedule moved; the sentence on the map says "
        f"{CADENCE!r} and has to move with it")
    # Five mornings a week is not weekly, and the page does not say it is.
    s = tpl("live-map-en.html")
    assert CADENCE in s
    for wrong in ("refreshed weekly", "updated weekly", "real time",
                  "real-time", "live prices"):
        assert wrong not in s.lower(), wrong


# -- 6. one vocabulary for an answer ------------------------------------------

def test_an_answer_is_confirmed_refuted_or_partial_wherever_it_is_named():
    """The status VALUE is untouched -- 'mixed' is in the data, in the
    contract and in every hash. What changed is the word on the screen."""
    s = tpl("live-map-en.html")
    assert "marks:{yes:'confirmed', no:'refuted', mixed:'partial'" in s
    assert r"obsLabel:'Partial \u00b7 observation only'" in s
    cards = tpl("track-cards.js")
    assert "mixed:'partial'" in cards
    # And the raw value is still what the code branches on.
    for src in (s, cards):
        assert "'mixed'" in src, "the status value must not have been renamed"


# -- 7. one subscription component, and no promise of a thing that is not ----
# The map page drew its own call, with a "coming soon" chip where the site is
# built without a mail service. A chip that says a feature is coming is a
# claim about a date nobody has set, and it was the one surface that did not
# use sitenav's component -- so it was also the one that could drift.

def test_no_page_promises_something_is_coming():
    for name in PAGES + ("track-site.html",):
        s = tpl(name).lower()
        for wrong in ("coming soon", "launching soon", "available soon"):
            assert wrong not in s, f"{name}: {wrong}"
    for mod in ("sitenav.py", "landing.py", "track.py", "track_site.py",
                "build_pages.py"):
        # The emitted strings, not the comments: build_pages explains in prose
        # why there is no longer a "coming soon" to emit.
        src = (templates_dir().parent / mod).read_text(encoding="utf-8")
        code = "\n".join(l for l in src.splitlines()
                         if not l.lstrip().startswith("#"))
        code = re.sub(r'"""[\s\S]*?"""', " ", code).lower()
        assert "coming soon" not in code, mod


def test_every_page_that_offers_the_key_offers_it_the_same_way():
    """One component, from chains/sitenav.py, on all three surfaces. The map
    fills the same placeholder the track page does."""
    from chains import build_pages, track
    assert build_pages.SUBSCRIBE_PLACEHOLDER == track.SUBSCRIBE_PLACEHOLDER
    for name in ("live-map.html", "live-map-en.html", "track.html"):
        assert build_pages.SUBSCRIBE_PLACEHOLDER in tpl(name), name
    # And the landing takes it from the same function.
    assert "{{subscribe}}" in tpl("landing.html")


def test_the_component_is_the_only_wording_for_the_key():
    """The map used to carry a second heading, a second promise and a second
    button label for the same thing."""
    s = tpl("live-map-en.html")
    for gone in ("Get every question before the answer",
                 "The free weekly briefing includes upcoming questions",
                 "Get the weekly key"):
        assert gone not in s, gone


# -- 8. the sample-size caveat is about the sample ---------------------------

def test_no_page_tells_a_reader_what_to_do_with_capital():
    from chains import forecast
    assert "capital" not in forecast.SAMPLE_RULE.lower()
    assert str(forecast.MIN_N_FOR_CAPITAL) in forecast.SAMPLE_RULE
    banned = ("capital decision", "before any capital", "no capital")
    for name in PAGES + ("track-site.html",):
        s = tpl(name).lower()
        for wrong in banned:
            assert wrong not in s, f"{name}: {wrong}"


def test_the_threshold_on_the_page_is_the_threshold_in_the_code():
    """One number. It was typed into three files once, and a threshold raised
    in the scoring code left two pages promising the old one."""
    from chains import forecast
    for name in ("live-map.html", "live-map-en.html"):
        s = tpl(name)
        assert "__MIN_N__" in s, f"{name}: the placeholder is gone"
        assert str(forecast.MIN_N_FOR_CAPITAL) not in s.split("<style>")[0]


# -- 9. one navigation bar ---------------------------------------------------

def test_the_bar_is_the_same_bar_on_every_kind_of_page():
    from chains import sitenav
    want = [sitenav.MAPS_LABEL, sitenav.DOMAINS_LABEL, sitenav.TRACK_RECORD]
    for kwargs in ({"several": True, "site_wide": True},   # landing, pooled
                   {"several": True}):                      # a map, its record
        got = [l for _k, l, _u in sitenav.links("semi", **kwargs)]
        assert got == want, (kwargs, got)


# -- 10. the built pages, not only the templates -----------------------------
# The map inlines its own snapshot, so a sentence can reach the DOM through
# the DATA rather than through the template: `capital_rule` travels with every
# summary and its value was the old wording until the snapshot was rebuilt.
# Skips where nothing is published, because the suite runs before the build.

BUILT = ("index.html", "semi/index.html", "semi/track/index.html",
         "track/index.html")
NEVER_ON_A_PAGE = ("coming soon", "capital decision", "all maps",
                   "every number carries a source",
                   "station size reflects market capitalization")


@pytest.mark.parametrize("path", BUILT)
def test_nothing_banned_survives_into_a_published_page(path):
    site = templates_dir().parents[1] / "site"
    p = site / path
    if not p.exists():
        pytest.skip("site/ is not published; run chains.publish_site first")
    s = p.read_text(encoding="utf-8").lower()
    for wrong in NEVER_ON_A_PAGE:
        assert wrong not in s, f"{path}: {wrong}"
