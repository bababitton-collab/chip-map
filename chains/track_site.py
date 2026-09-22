"""The site-wide record: one page at /track/, across every map.

    site/track/index.html

WHY A SECOND RECORD PAGE
------------------------
Each map already has its own record at /<domain>/track/, and that page is the
one that can answer "how has this chain been called". What it cannot answer is
"how has this been called", full stop -- and that is the question a reader
arrives with. Split across two directories, the honest answer to it did not
exist anywhere on the site: a visitor could read 39 questions' worth of record
on one page and 14 on another and had to add them up themselves.

WHAT IS POOLED AND WHAT IS NOT
------------------------------
N and the hit rate pool. A hit is a yes/no outcome -- did the excess carry the
sign that was registered before the answer -- and that question means the same
thing on every map, whatever benchmark defined it.

The excess does NOT pool, and this page will not print a pooled one. Excess is
measured against each map's own equal-weight benchmark, built from that map's
priced nodes and nothing else. Averaging two maps' excesses answers "excess
over what?" with "over a mixture of two markets nobody holds". So the headline
carries N and the hit rate, and every excess on the page sits inside its own
map's block, beside that map's own second benchmark and no other.

WRITTEN ONCE, AFTER EVERY MAP
-----------------------------
Like the landing page, and for the same reason it had to be fixed there: a
page that counts across maps cannot be written halfway through publishing
them. It is written at the end of the walk, from the directories that are by
then all in place, and it goes through the same gates in the same breath --
see chains/publish_site.py.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

from chains import sitenav, track

TEMPLATE = "track-site.html"
DIRNAME = "track"


class TrackSiteError(ValueError):
    """The site-wide record cannot be written truthfully from what is there."""


def payloads(root: Path, names: list[str]) -> dict[str, dict]:
    """Each map's published free record, for the maps that have one.

    Read from what is published, never from out/: this page states a number
    about the site, and the site is the directory being served. A map whose
    record is not published yet is simply not in it -- it is not counted from
    somewhere else.
    """
    got = {}
    for name in names or []:
        p = root / name / "track_public.json"
        if not p.exists():
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except ValueError as e:
            raise TrackSiteError(f"{p} is not readable JSON ({e})") from None
        if isinstance(doc, dict):
            got[name] = doc
    return got


def _pct(v) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"


def _signed_pct(v) -> str:
    return "—" if v is None else f"{v * 100:+.2f}%"


def _interval(lo_hi) -> str:
    if not lo_hi:
        return ""
    lo, hi = lo_hi
    return f"{lo * 100:.0f}–{hi * 100:.0f}%"


def _headline(rec: dict) -> str:
    """N and the hit rate, with its interval when there is one.

    Below MIN_N_FOR_INTERVAL record_stats returns no interval and says why.
    The sentence it returns is printed rather than replaced: a range invented
    at small N is the one number on this page that would flatter it.
    """
    n = rec.get("n") or 0
    esc = html.escape
    bits = [f'<li><b>{n}</b> scored questions</li>']
    if rec.get("hit_rate") is None:
        bits.append('<li><b>—</b> hit rate</li>')
    else:
        span = _interval(rec.get("hit_rate_interval"))
        bits.append(f'<li><b>{_pct(rec["hit_rate"])}</b> hit rate'
                    + (f' <span class="ci">95% CI {span}</span>' if span
                       else "") + '</li>')
    bits.append(f'<li><b>{rec.get("primary_horizon")}</b> session horizon</li>')
    note = rec.get("note")
    if note:
        bits.append(f'<li class="note">{esc(str(note))}</li>')
    return "".join(bits)


def _blocks(per: dict, order: list[str], titles: dict) -> str:
    """One block per map: its own excess, against its own benchmarks."""
    esc = html.escape
    out = []
    for dom in order:
        b = per[dom]
        rec = b["record"]
        bench = (b.get("benchmark") or {}).get("label") or ""
        title = titles.get(dom) or dom
        rows = [
            ("scored", str(rec.get("n") or 0)),
            ("hit rate", _pct(rec.get("hit_rate"))),
            ("mean excess vs EW_MAP", _signed_pct(rec.get("mean_excess"))),
            ("median excess vs EW_MAP", _signed_pct(rec.get("median_excess"))),
        ]
        cells = "".join(f'<li><span>{esc(k)}</span><b>{esc(v)}</b></li>'
                        for k, v in rows)
        out.append(
            f'<li class="domrec">'
            f'<h3><a href="/{esc(dom)}/track/">{esc(title)}</a></h3>'
            f'<p class="bench">second benchmark: <b>{esc(bench)}</b>'
            f' — reported beside this map\'s numbers and pooled with nothing'
            f'</p>'
            f'<ul class="domstat">{cells}</ul>'
            f'<p class="more"><a href="/{esc(dom)}/track/">'
            f'Every question on this map →</a></p>'
            f'</li>')
    return "".join(out)


def render(root: Path, names: list[str], site_url: str,
           template: str | None = None) -> str:
    """The page, from the records published under ``root``."""
    from chains.paths import templates_dir
    docs = payloads(root, names)
    if not docs:
        raise TrackSiteError(
            "no map under the site has published a record, so there is "
            "nothing this page could say that would be true")
    data = track.pooled(docs)
    rec = data["record"]
    titles = {}
    for dom in data["domains"]:
        from chains.landing import _brand
        titles[dom] = _brand(dom, "title") or dom
    t = template if template is not None else (
        (templates_dir() / TEMPLATE).read_text(encoding="utf-8"))
    values = {
        "brand": sitenav.BRAND,
        "site_url": site_url,
        "site_nav": sitenav.html(data["domains"][0], "track"),
        "site_nav_css": sitenav.CSS,
        "analytics": sitenav.ANALYTICS,
        "headline": _headline(rec),
        "blocks": _blocks(data["by_domain"], data["domains"], titles),
        "n_maps": str(len(data["domains"])),
        "capital_rule": rec.get("capital_rule") or "",
        "excess_note": rec.get("excess") or "",
    }
    raw = {"site_nav", "site_nav_css", "analytics", "headline", "blocks"}

    import re

    def fill(m):
        key = m.group(1)
        if key not in values:
            raise TrackSiteError(f"the template asks for {{{{{key}}}}}, which "
                                 f"this build does not know how to derive")
        v = values[key]
        return v if key in raw else html.escape(str(v), quote=True)

    return re.sub(r"\{\{(\w+)\}\}", fill, t)


__all__ = ["render", "payloads", "TrackSiteError", "TEMPLATE", "DIRNAME"]
