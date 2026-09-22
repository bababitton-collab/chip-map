"""The site's front door: a static landing page, built from what is published.

    python -m chains.publish_site        # writes site/index.html through this

EVERY NUMBER IS READ, NOT TYPED
-------------------------------
The proof strip and the prose read their counts from the files published beside
the page -- the snapshot (companies, chokepoints, dated questions, layers) and
commitments.json (how many questions were committed before their answer date).
The horizons and the benchmark symbol come from the scoring code itself. A
number typed into the template would be true on the day it was typed.

EVERY CAPABILITY IS CONDITIONAL ON ITS PROOF
--------------------------------------------
The sentences about public pre-registration and browser verification are drawn
only when commitments.json AND track_public.json are among the published files.
A page that described a Verify button with nothing behind it would be the one
claim on the site a reader could not check.

THE FREE/KEY ANSWER IS HELD TO chains/access.py
-----------------------------------------------
Everything is free; the questions still ahead open with the key from the weekly
mail. The FAQ states that line in words. check_access() asks access.py the same
questions before the page is written, and refuses to write it if the answers
no longer match -- so the rule cannot move without the page moving with it.

The copy lives in chains/templates/landing.html; this module holds no domain
vocabulary of its own.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

from chains import access, preregister, sitenav
from chains.answers import PRIMARY_HORIZON

TEMPLATE = "landing.html"

# Filled without escaping: markup and JSON this module builds itself.
RAW = frozenset({"map_cards",
                 "site_nav", "site_nav_css", "jsonld", "subscribe",
                 "analytics"})


class LandingError(ValueError):
    """The landing page cannot be written truthfully from what is published."""


def _read(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _series(items: list[str]) -> str:
    items = [str(i) for i in items]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def check_access() -> None:
    """The page's free/key answer, asked of chains/access.py."""
    answered = {"answered": True}
    claims = [
        ("the map is free", access.is_free("map")),
        ("the calendar is free", access.is_free("calendar_row")),
        ("the next question's text is free",
         access.is_free("question_text", {"nearest": True})),
        ("a resolved question is free in full",
         all(access.is_free(k, answered) for k in access.KINDS)),
        ("a question ahead needs the key", not access.is_free("question_text")),
        ("the prices behind a question ahead need the key",
         not access.is_free("member_prices")
         and not access.is_free("forecast_active", {"nearest": True})),
        ("a question ahead keeps its contract bytes",
         not access.is_free("contract", {"nearest": True})),
    ]
    wrong = [c for c, ok in claims if not ok]
    if wrong:
        raise LandingError(
            "the landing page's free/key answer no longer matches "
            "chains/access.py: " + "; ".join(wrong))


def facts(dom_dir: Path, dom: str | None = None) -> dict:
    """Everything the page states, read from the files in ``dom_dir``.

    ``dom`` names the map those files came from. It is needed for the phrases
    the map holds for itself -- the benchmark and the words this industry uses
    -- which are read from the map rather than from the published directory.
    """
    live = _read(dom_dir / "live_en.json")
    if not isinstance(live, dict):
        raise LandingError(f"{dom_dir / 'live_en.json'} is missing: the "
                           f"landing page's numbers are read from it")
    labels = live.get("labels") or {}
    layers = labels.get("layers") or {}
    order = sorted(layers, key=lambda k: int(re.sub(r"\D", "", k) or 0))
    watch = live.get("watch") or []
    commits = _read(dom_dir / "commitments.json")
    public = _read(dom_dir / "track_public.json")
    f = {
        "brand": (labels.get("brand") or {}).get("name") or sitenav.BRAND,
        "companies": len(live.get("nodes") or []),
        "chokepoints": len(live.get("cps") or []),
        "questions": len(watch),
        "observe_only": sum(1 for r in watch if r.get("observe_only")),
        # The published snapshot has already chosen its language, so a label
        # is a plain string there; the map itself keeps {"he", "en"}. Either
        # shape is read, so the page cannot depend on which file it was fed.
        "layers": [v for v in ((layers[k] if isinstance(layers[k], str)
                                else (layers[k] or {}).get("en"))
                               for k in order) if v],
        "primary_horizon": PRIMARY_HORIZON,
        "diagnostic_horizons": [h for h in preregister.CONTRACT_HORIZONS
                                if h != PRIMARY_HORIZON],
        # This domain's second benchmark, not the first domain's. The landing
        # page states it as fact beside the scoring rule, so a stale name here
        # would be a false statement about how the record is measured.
        "sox": forecast_benchmark_symbol(dom),
        # The words that name THIS industry, from its own map. They are not
        # defaulted in Python on purpose: a default here would be one domain's
        # vocabulary living in the engine, which is the thing the map exists
        # to hold. A map that declares none gets an empty phrase rather than
        # another industry's.
        "chokepoint_kind": _copy(dom, "chokepoint_kind"),
        "chokepoint_examples": _copy(dom, "chokepoint_examples"),
        "prereg": (isinstance(commits, list) and bool(commits)
                   and isinstance(public, dict)
                   and isinstance(public.get("forecasts"), list)),
    }
    if f["prereg"]:
        if {e.get("primary_horizon") for e in commits} != {PRIMARY_HORIZON}:
            raise LandingError("commitments.json names a primary horizon the "
                               "scoring code does not")
        f["n_committed"] = len(commits)
        f["n_valid"] = sum(1 for e in commits
                           if e.get("valid_preregistration"))
    return f


def _blocks(t: str, name: str, keep: bool) -> str:
    pat = re.compile(r"<!--IF:" + name + r"-->(.*?)<!--END:" + name + r"-->",
                     re.S)
    return pat.sub(lambda m: m.group(1) if keep else "", t)


def _jsonld(brand: str, url: str) -> str:
    data = [{"@context": "https://schema.org", "@type": "WebSite",
             "name": brand, "url": url},
            {"@context": "https://schema.org", "@type": "Organization",
             "name": brand, "url": url}]
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def _copy(dom: str | None, key: str) -> str:
    """One phrase this industry uses for itself, from its own map.

    Read from the map rather than defaulted here: a default would be one
    industry's vocabulary living in the engine, which is exactly what the
    labels block exists to hold. A map that declares nothing gets an empty
    phrase -- never another industry's words.
    """
    from chains import mapfile
    try:
        block = (mapfile.load(dom=dom).get("labels") or {}).get("copy") or {}
    except (FileNotFoundError, ValueError):
        return ""
    return str(block.get(key) or "").strip()


def forecast_benchmark_label(dom: str | None = None) -> str:
    """What a page prints for this domain's second benchmark. The symbol is
    what is priced; the label is what a reader is shown."""
    from chains import forecast
    return forecast.benchmark_for(dom)["label"]


def forecast_benchmark_symbol(dom: str | None = None) -> str:
    """The symbol of this domain's second benchmark.

    Imported late and read per build: the landing page states it as a fact
    about how the record is measured, so naming another domain's index here
    would be a false statement rather than a stale label.
    """
    from chains import forecast
    return forecast.benchmark_for(dom)["symbol"]


# What the front door said while there was one map. Kept exactly, and used
# exactly when there is still one: a site serving a single map must read
# byte for byte as it read before any of this existed. With several maps
# neither sentence is true of the site -- "the physical supply chain",
# singular, describes one of them -- so the words come from data/site.json,
# beside the maps they are about rather than typed into the engine.
ONE_MAP_TITLE = "The physical supply chain behind AI — mapped."
ONE_MAP_LEAD = "See who supplies whom — and where it breaks."


def hero(many: bool) -> tuple[str, str]:
    """The headline and its lead. Falls back to the one-map wording when the
    site file says nothing, so adding the file is what changes the page --
    never its absence."""
    if not many:
        return ONE_MAP_TITLE, ONE_MAP_LEAD
    from chains import sitefile
    return (sitefile.copy("hero", "title", default=ONE_MAP_TITLE),
            sitefile.copy("hero", "lead", default=ONE_MAP_LEAD))


def _brand(dom: str, key: str) -> str:
    """One sentence a map keeps about itself, in English."""
    from chains import mapfile
    try:
        block = ((mapfile.load(dom=dom).get("labels") or {})
                 .get("brand") or {}).get(key)
    except (FileNotFoundError, ValueError):
        return ""
    if isinstance(block, dict):
        block = block.get("en")
    return str(block or "").strip()


def map_cards(root: Path, names: list[str], dom: str,
              dom_dir: Path) -> list[dict]:
    """One entry per map the site actually serves, read from what is served.

    A name discovered under data/ but not yet published is left out rather
    than described from the repository. Every number on this page is read
    from the files sitting beside it -- see the module docstring -- and a
    card counting questions out of data/ would be the one claim here with
    nothing published behind it. On an --all-domains run the first map's
    publish therefore writes a page naming one map and the last one's
    rewrites it naming all of them, which is the same order the numbers
    themselves settle in.

    The name, the blurb and the benchmark come from each map's own file: a
    second industry describes itself, or the engine describes it in the
    first industry's words.
    """
    found = []
    for name in names or []:
        d = root / name
        live = _read(d / "live_en.json")
        if not isinstance(live, dict):
            continue
        found.append((name, d, live))
    if not found:
        # Rendered against a single published directory -- every test, and
        # any site serving one map. The page then says exactly what it said
        # before there was a second one.
        live = _read(dom_dir / "live_en.json")
        found = [(dom, dom_dir, live if isinstance(live, dict) else {})]
    cards = []
    for name, _d, live in found:
        cards.append({
            "name": name,
            "title": _brand(name, "title") or name,
            "blurb": _brand(name, "value"),
            "bench": forecast_benchmark_label(name),
            "companies": len(live.get("nodes") or []),
            "chokepoints": len(live.get("cps") or []),
            "questions": len(live.get("watch") or []),
        })
    return cards


def _map_cards_html(cards: list[dict], dom: str) -> str:
    """The cards, one per map, the current one marked."""
    def esc(s):
        return html.escape(str(s), quote=True)

    out = []
    for c in cards:
        cur = ' aria-current="page"' if c["name"] == dom else ""
        blurb = f'<p class="blurb">{esc(c["blurb"])}</p>' if c["blurb"] else ""
        out.append(
            f'<li class="mapcard">'
            f'<h3><a href="/{esc(c["name"])}/"{cur}>{esc(c["title"])}</a></h3>'
            f'{blurb}'
            f'<ul class="mapstat">'
            f'<li><b>{c["questions"]}</b> dated questions</li>'
            f'<li><b>{c["companies"]}</b> companies</li>'
            f'<li><b>{c["chokepoints"]}</b> chokepoints</li>'
            f'<li>scored against <b>{esc(c["bench"])}</b></li>'
            f'</ul>'
            f'<p class="maplinks"><a href="/{esc(c["name"])}/">Map</a> · '
            f'<a href="/{esc(c["name"])}/track/">Track Record</a></p>'
            f'</li>')
    return "".join(out)


def render(dom_dir: Path, dom: str, site_url: str,
           template: str | None = None,
           live: list[str] | None = None) -> str:
    """The page. ``dom_dir`` is the published directory it describes.

    ``live`` is every map the site serves. The index of them is drawn only
    when there is more than one: with a single map a list of one is furniture
    that says nothing, and leaving it out keeps the page a reader already
    knows byte-for-byte what it was.
    """
    from chains.paths import subscribe_embed_url, templates_dir
    check_access()
    f = facts(dom_dir, dom)
    t = template if template is not None else (
        (templates_dir() / TEMPLATE).read_text(encoding="utf-8"))
    t = _blocks(t, "prereg", f["prereg"])
    t = _blocks(t, "observe", f["observe_only"] > 0)
    # The FAQ's "subscribe" sentence, like the form, only with a form to use.
    subscribe = subscribe_embed_url()
    t = _blocks(t, "subscribe", bool(subscribe))
    names = list(live or [])
    # Every map the site actually serves, and the totals across them. The
    # counts in the hero and the prose describe the SITE, so on a two-map
    # site they are the sum -- a headline that quoted one map's question
    # count while linking to both would undercount the thing it points at,
    # and a number typed in would go stale the first time either map grew.
    cards = map_cards(dom_dir.parent, names, dom, dom_dir)
    many = len(cards) > 1
    t = _blocks(t, "domains", many)
    t = _blocks(t, "onemap", not many)
    totals = {k: sum(c[k] for c in cards)
              for k in ("companies", "chokepoints", "questions")}
    hero_title, hero_lead = hero(many)
    values = {
        "hero_title": hero_title,
        "hero_lead": hero_lead,
        "map_cards": _map_cards_html(cards, dom),
        "n_maps": str(len(cards)),
        "cur_title": _brand(dom, "title") or dom,
        "brand": f["brand"],
        "companies": str(totals["companies"]),
        "chokepoints": str(totals["chokepoints"]),
        "questions": str(totals["questions"]),
        "observe_only": str(f["observe_only"]),
        "n_layers": str(len(f["layers"])),
        "layers": _series(f["layers"]),
        "primary_horizon": str(f["primary_horizon"]),
        "diagnostic_horizons": _series(f["diagnostic_horizons"]),
        "sox": f["sox"],
        # Derived in facts() with the rest, and handed to the template here:
        # fill() raises on a key it cannot find, so a phrase that stops at
        # facts() stops the build rather than rendering an empty gap.
        "chokepoint_kind": f["chokepoint_kind"],
        "chokepoint_examples": f["chokepoint_examples"],
        "n_committed": str(f.get("n_committed", "")),
        "n_valid": str(f.get("n_valid", "")),
        "map_href": f"/{dom}/",
        "track_href": f"/{dom}/track/",
        "commitments_href": f"/{dom}/commitments.json",
        "track_public_href": f"/{dom}/track_public.json",
        "site_url": site_url,
        # The front door belongs to the site, not to the first map. With
        # several maps its bar leads to the choice and to the pooled
        # record; the condition is the one that already decides the cards.
        "site_nav": sitenav.html(dom, "home", several=many,
                                 site_wide=True),
        "site_nav_css": sitenav.CSS,
        "jsonld": _jsonld(f["brand"], site_url),
        "analytics": sitenav.ANALYTICS,
        # Empty when SUBSCRIBE_EMBED_URL is: no form, no copy.
        "subscribe": sitenav.subscribe_html(subscribe),
    }

    def fill(m):
        key = m.group(1)
        if key not in values:
            raise LandingError(f"the template asks for {{{{{key}}}}}, which "
                               f"this build does not know how to derive")
        v = values[key]
        return v if key in RAW else html.escape(v, quote=True)

    out = re.sub(r"\{\{(\w+)\}\}", fill, t)
    if "<!--IF:" in out or "<!--END:" in out:
        raise LandingError("an unclosed conditional block in the template")
    return out


__all__ = ["render", "facts", "check_access", "LandingError", "TEMPLATE"]
