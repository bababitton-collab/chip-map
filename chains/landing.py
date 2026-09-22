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
RAW = frozenset({"domains", "site_nav", "site_nav_css", "jsonld", "subscribe",
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


def forecast_benchmark_symbol(dom: str | None = None) -> str:
    """The symbol of this domain's second benchmark.

    Imported late and read per build: the landing page states it as a fact
    about how the record is measured, so naming another domain's index here
    would be a false statement rather than a stale label.
    """
    from chains import forecast
    return forecast.benchmark_for(dom)["symbol"]


def _domain_links(live: list[str], dom: str) -> str:
    """One link per map the site actually serves, the current one marked."""
    out = []
    for name in live:
        cur = ' aria-current="page"' if name == dom else ""
        out.append(f'<a href="/{html.escape(name, quote=True)}/"{cur}>'
                   f'{html.escape(name)}</a>')
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
    t = _blocks(t, "domains", len(names) > 1)
    values = {
        "domains": _domain_links(names, dom),
        "brand": f["brand"],
        "companies": str(f["companies"]),
        "chokepoints": str(f["chokepoints"]),
        "questions": str(f["questions"]),
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
        "site_nav": sitenav.html(dom, "home"),
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
