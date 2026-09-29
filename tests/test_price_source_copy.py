"""What the site says the prices are, held to what fetches them.

The page said "Prices are EODHD end-of-day data" for weeks after the EODHD
subscription was cancelled and chains/providers/yahoo.py took over. Nothing
broke, because nothing checked: the sentence was a string in a template and
the fetch was a module nobody compared it against.

That is the same failure as the preregistration copy in
[test_prereg_claims.py] -- a claim the data underneath it contradicts -- and
it is caught the same way, by reading the claim off the shipped page and the
fact off the code.
"""
from __future__ import annotations

import json

import pytest

from chains import domains, prices, record_page, track
from chains.paths import templates_dir

DEAD = "EODHD"
LIVE = "Yahoo Finance"


def _templates():
    return sorted(p for p in templates_dir().iterdir()
                  if p.suffix in (".html", ".js"))


# -- the claim is gone from everything that ships -----------------------------
def test_no_template_names_the_dead_vendor():
    named = [p.name for p in _templates()
             if DEAD in p.read_text(encoding="utf-8")]
    assert named == [], f"{DEAD} is cancelled; these still say so: {named}"


def test_the_rendered_track_page_names_the_live_source():
    page = track.render(track.public({"summary": {}, "forecasts": []}))
    assert DEAD not in page
    assert "Prices use Yahoo Finance end-of-day market data." in page


def test_the_method_paragraph_on_a_question_page_names_the_live_source():
    """record_page.METHOD is the long-form explanation under a closed
    question. It carried the same sentence and the same error."""
    text = record_page.method_text()
    assert DEAD not in text
    assert text.startswith("Every price is Yahoo Finance end-of-day.")


@pytest.mark.parametrize("dom", domains.discover())
def test_the_method_paragraph_says_it_for_every_map(dom):
    assert DEAD not in record_page.method_text(dom)


# -- the claim matches the code that actually fetches -------------------------
def test_the_named_source_is_the_one_the_price_path_uses():
    """The copy names Yahoo Finance. If the fetch moves again this fails here,
    next to the sentence, rather than silently on the page."""
    from chains.providers import yahoo
    assert "finance.yahoo.com" in yahoo.BASE_URL
    assert hasattr(yahoo, "YahooClient")


def test_nothing_in_the_fetch_path_still_calls_the_dead_vendor():
    """Comments may record the history -- the code may not call it."""
    import inspect

    from chains.providers import yahoo
    code = "\n".join(l for l in inspect.getsource(yahoo).splitlines()
                     if not l.lstrip().startswith("#"))
    assert "eodhistoricaldata" not in code
    assert "EODHD_API_TOKEN" not in code


# -- and it cannot come back through the build --------------------------------
def test_every_page_renderer_that_describes_prices_is_covered():
    """The sentence lived in two places, a template and a python string, and a
    test that read templates alone would have passed while the question pages
    still said it. These are the two renderers that describe prices; both are
    rendered above, so a third would have to be added here deliberately.
    """
    sources = {
        "chains/templates/track.html": (templates_dir() / "track.html"),
        "chains/record_page.py": (templates_dir().parent / "record_page.py"),
    }
    for name, path in sources.items():
        body = path.read_text(encoding="utf-8")
        assert DEAD not in body, name
        assert LIVE in body, f"{name} no longer names the price source"


def test_a_build_on_this_machine_did_not_ship_it():
    """Belt and braces, and skipped where there is no build.

    CI runs the suite before the build, so this cannot be the guard -- the
    checks above are. It catches the case where a local build predates a copy
    fix and gets published by hand.

    site/, not out/. Every price_note in map.json records which vendor did or
    did not carry a listing, and that provenance is true history; it lands in
    out/chain_page.json and is not published. What ships is the claim, and
    the claim is what has to be right.
    """
    name = "site"
    root = templates_dir().parents[1] / name
    if not root.is_dir():
        pytest.skip(f"no {name}/ on this machine")
    hits = []
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix not in (".html", ".json", ".md", ".js"):
            continue
        try:
            body = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if DEAD in body:
            hits.append(str(p.relative_to(root)))
    assert hits == [], f"{DEAD} is in {name}/: {hits}"
