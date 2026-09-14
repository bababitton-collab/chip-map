"""Plausible: once on every public page, never on anything private.

The snippet lives in chains/sitenav.py and each public page's <head> takes it
from there. The pages checked here are held to the list chains/publish_site.py
actually ships, so a new public page that forgets the snippet fails this file
rather than going out uncounted. The private map and the mail carry none.
"""
from __future__ import annotations

import json
import re
import shutil

import pytest

from chains import build_pages as bp
from chains import landing, publish_site, sitenav, track
from chains.paths import REPO_ROOT, commitments_path, out_dir, templates_dir

SNIPPET = """<!-- Privacy-friendly analytics by Plausible -->
<script async src="https://plausible.io/js/pa-pY3vdi9LyMCXS_gJTVNhu.js"></script>
<script>
  window.plausible=window.plausible||function(){(plausible.q=plausible.q||[]).push(arguments)},plausible.init=plausible.init||function(i){plausible.o=i||{}};
  plausible.init()
</script>"""

LIVE_EN = out_dir() / bp.LIVE_EN
LIVE_HE = out_dir() / bp.LIVE_HE
needs_live = pytest.mark.skipif(
    not (LIVE_EN.exists() and LIVE_HE.exists()),
    reason="snapshots not built yet; run python -m chains.live_snapshot")

# Every call to plausible() with arguments: the snippet's own plumbing
# (plausible.q, plausible.init) does not match.
CALL = re.compile(r"\bplausible\(([^)]*)\)")


def test_the_snippet_is_verbatim():
    assert sitenav.ANALYTICS == SNIPPET
    assert sitenav.ANALYTICS_ORIGIN == "https://plausible.io"


def _public_pages(tmp_path) -> dict[str, str]:
    """Every public HTML page, built the way the build builds it, keyed by
    where publish_site puts it."""
    dom = tmp_path / "semi"
    dom.mkdir()
    shutil.copyfile(LIVE_EN, dom / "live_en.json")
    shutil.copyfile(commitments_path(), dom / "commitments.json")
    (dom / "track_public.json").write_text(
        json.dumps({"forecasts": [], "n_resolved": 0}), encoding="utf-8")
    en_tpl = tmp_path / "live-map-en.html"
    bp.build_en_template(dst=en_tpl)
    en, _ = bp.build_public_en(template=en_tpl, live=LIVE_EN,
                               out=tmp_path / "public-map-en.html")
    he, _ = bp.build_public_he(live=LIVE_HE, out=tmp_path / "public-map.html")
    return {
        "index.html": landing.render(dom, "semi", "https://linchpinsignal.com/"),
        "semi/index.html": en.read_text(encoding="utf-8"),
        "semi/he.html": he.read_text(encoding="utf-8"),
        "semi/track/index.html": track.render(
            track.public({"summary": {}, "forecasts": []})),
    }


def _published_html() -> set[str]:
    return ({"index.html"}
            | {f"semi/{d}" for _s, d in publish_site.COPIES if d.endswith(".html")}
            | {f"semi/track/{d}" for _s, d in publish_site.TRACK_FILES
               if d.endswith(".html")})


@needs_live
def test_every_public_page_carries_the_snippet_exactly_once(tmp_path):
    pages = _public_pages(tmp_path)
    assert set(pages) == _published_html(), "a public page is not checked here"
    for name, html in pages.items():
        assert html.count(SNIPPET) == 1, name
        head = html[:html.index("</head>")]
        assert SNIPPET in head, f"{name}: the snippet is not in <head>"


@needs_live
def test_the_only_external_script_origin_is_plausible(tmp_path):
    for name, html in _public_pages(tmp_path).items():
        for src in re.findall(r"<script\b[^>]*\bsrc=\"([^\"]+)\"", html):
            assert (not re.match(r"(?i)^(https?:)?//", src)
                    or src.startswith(sitenav.ANALYTICS_ORIGIN + "/")), (name, src)


@needs_live
def test_events_are_the_two_names_and_carry_no_props(tmp_path):
    seen = set()
    for name, html in _public_pages(tmp_path).items():
        for args in CALL.findall(html):
            m = re.fullmatch(r"'([a-z_]+)'", args.strip())
            assert m and m.group(1) in sitenav.EVENTS, (name, args)
            seen.add(m.group(1))
    assert seen == {"unlock_success", "subscribe_form_view"}


def test_unlock_success_fires_after_a_key_decrypts():
    body = (templates_dir() / "track.html").read_text(encoding="utf-8")
    i = body.index("async function tryKey")
    ok = body[i:body.index("return true;", i)]
    assert ok.index("await open(k)") < ok.index("show(data)") < \
        ok.index(sitenav.event_js("unlock_success"))
    assert body.count("plausible('unlock_success')") == 1


def test_subscribe_form_view_fires_only_with_the_form():
    assert sitenav.subscribe_html(None) == ""
    block = sitenav.subscribe_html("https://linchpinsignal.substack.com/embed")
    assert block.count(sitenav.event_js("subscribe_form_view")) == 1
    assert block.index("</iframe>") < block.index("subscribe_form_view")
    with pytest.raises(ValueError):
        sitenav.event_js("page_view_with_email")


@needs_live
def test_the_private_map_carries_none():
    tpl = (templates_dir() / bp.TEMPLATE_HE).read_text(encoding="utf-8")
    page = bp.private_page(tpl, LIVE_HE.read_text(encoding="utf-8"))
    assert "plausible" not in page.lower()


def test_the_mail_builders_carry_none():
    for mod in ("brief.py", "brief_he.py"):
        src = (REPO_ROOT / "chains" / mod).read_text(encoding="utf-8")
        assert "ANALYTICS" not in src and "plausible.io" not in src, mod


# -- the files a local build actually wrote ---------------------------------------

def _fresh(p) -> bool:
    """Built after the last change to what builds it; a stale file from before
    the snippet existed says nothing about the build."""
    sources = [templates_dir() / "live-map.html", templates_dir() / "track.html",
               REPO_ROOT / "chains" / "sitenav.py", REPO_ROOT / "chains" / "build_pages.py"]
    return p.exists() and p.stat().st_mtime >= max(s.stat().st_mtime for s in sources)


@pytest.mark.parametrize("name,count", [
    ("public-map-en.html", 1), ("public-map.html", 1), ("track.html", 1),
    ("live-map.built.html", 0)])
def test_the_built_output(name, count):
    p = out_dir() / name
    if not _fresh(p):
        pytest.skip(f"{p.name} not built since the last template change")
    assert p.read_text(encoding="utf-8").count(SNIPPET) == count


def test_the_built_mail_carries_none():
    briefs = sorted(out_dir().glob("brief*.md"))
    if not briefs:
        pytest.skip("no brief built")
    for p in briefs:
        assert "plausible" not in p.read_text(encoding="utf-8").lower(), p.name
