"""/domains/: the domain tree, edge to materials, from data/domains/public.json.

The file is the public export written in the private research repo
(watchlist/export_public.py); only its whitelisted fields exist here. Owner
returns are the maps' own: the 52-week return each published map carries for
the node (live_en.json, px.r52w), so a chip here and the map card agree. An
owner on no map takes the same return from the nightly price-only feed
(chains/owner_prices.py) when it passes the liquidity gate; otherwise "—".

Descriptive only: a status says where a domain stands, never what will happen.
"""
from __future__ import annotations

import html as _html
import json
from pathlib import Path

LEVELS = (("edge", "Edge"), ("manufacturing", "Manufacturing"), ("development", "Development"),
          ("materials", "Materials"))
STATUS_CLASS = {"Constrained · not yet priced": "open", "Constrained · priced": "priced",
                "Constrained · no listed owner": "dim", "Gated by development": "dim", "Easing": "dim"}
FOOTER = "Status is descriptive, not a forecast. Forecasts are on the track record page."
TEMPLATE = "domains.html"


def esc(s) -> str:
    return _html.escape(str(s), quote=True)


def load(data_root: Path) -> dict:
    p = data_root / "domains" / "public.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"domains": []}


def owner_returns(site: Path, domains: list[str]) -> tuple[dict, dict]:
    """{yahoo ticker: r52w} from every published map, and {bottleneck id: (domain, station)}."""
    from chains.providers.yahoo import to_yahoo
    rets, where = {}, {}
    for dom in domains:
        live = site / dom / "live_en.json"
        if not live.exists():
            continue
        d = json.loads(live.read_text(encoding="utf-8"))
        for n in d.get("nodes", []):
            px = n.get("px") or {}
            if n.get("sym") and px.get("r52w") is not None:
                try:
                    rets.setdefault(to_yahoo(n["sym"]), px["r52w"])
                except Exception:  # noqa: BLE001 -- a symbol with no Yahoo spelling has no chip return
                    pass
        focus = site / dom / "focus_en.json"
        if focus.exists():
            bns = json.loads(focus.read_text(encoding="utf-8")).get("bottlenecks", [])
            by = {b["id"]: b for b in bns}
            for b in bns:
                if not public(b, by):          # the map does not render it, so nothing links to it
                    continue
                st = (b.get("owners") or b.get("hurt") or b.get("propagation") or [None])[0]
                where.setdefault(b["id"], (dom, st, b.get("name")))
    # owners on no map: the nightly price-only feed (chains/owner_prices.py), gated
    from chains.owner_prices import out_path
    if out_path().exists():
        for t, r in json.loads(out_path().read_text(encoding="utf-8")).get("owners", {}).items():
            if r.get("r52w") is not None:
                rets.setdefault(t, r["r52w"])
    return rets, where


def public(b: dict, by: dict) -> bool:
    """The map's own rule: a sourced pressure or rigidity, directly or via {see: id}."""
    def ok(k):
        f = b.get(k) or {}
        if f.get("see"):
            f = (by.get(f["see"]) or {}).get(k) or {}
        return bool(f.get("source_url"))
    return ok("pressure") or ok("rigidity")


def pct(v) -> str:
    return "—" if v is None else f"{'+' if v > 0 else ''}{v * 100:.0f}%"


def card(d: dict, names: dict, rets: dict, where: dict) -> str:
    edge = d["level"] == "edge"
    parts = [f'<article class="dcard{" edge" if edge else ""}" id="{esc(d["id"])}" data-id="{esc(d["id"])}" '
             f'data-limits="{esc(" ".join(d["limits_edge"]))}" '
             f'data-limited-by="{esc(" ".join(d.get("limited_by_edge") or []))}"'
             + (' tabindex="0" role="button" aria-pressed="false"' if edge else "") + ">",
             f'<h3>{esc(d["name"])}</h3>']
    if d.get("status_public"):
        parts.append(f'<span class="chip st-{STATUS_CLASS[d["status_public"]]}">{esc(d["status_public"])}</span>')
    if d["limits_edge"]:
        parts.append('<p class="row"><b>Limits:</b> '
                     + ", ".join(esc(names.get(e, e)) for e in d["limits_edge"]) + "</p>")
    if d["owners"]:
        parts.append('<p class="owners">' + "".join(
            f'<span class="tk">{esc(t)} <i>{pct(rets.get(t))}</i></span>' for t in d["owners"]) + "</p>")
    nc = d.get("next_check")
    if nc:
        parts.append(f'<p class="row next">Next check: <b>{esc(nc["date"])}</b> — {esc(nc["event"])}</p>')
    links = []
    for b in d.get("bottleneck_ids") or []:
        if b in where:
            dom, st, name = where[b]
            href = f"/{dom}/" + (f"?station={st}&rail=1" if st else "")
            links.append(f'<a href="{esc(href)}">{esc(name or b)}</a>')
    if links:
        parts.append('<p class="row maplinks"><b>On the map:</b> ' + " · ".join(links) + "</p>")
    parts.append("</article>")
    return "".join(parts)


def render(site: Path, data_root: Path, domains: list[str], template: str | None = None) -> str:
    from chains import sitenav
    from chains.paths import templates_dir
    doc = load(data_root)
    names = {d["id"]: d["name"] for d in doc["domains"]}
    rets, where = owner_returns(site, domains)
    bands = []
    for key, label in LEVELS:
        ds = [d for d in doc["domains"] if d["level"] == key]
        if not ds:
            continue
        bands.append(f'<section class="band" data-level="{key}"><p class="eyebrow">{esc(label)}</p>'
                     f'<div class="grid">{"".join(card(d, names, rets, where) for d in ds)}</div></section>')
    t = template if template is not None else (templates_dir() / TEMPLATE).read_text(encoding="utf-8")
    first = domains[0] if domains else "semi"
    values = {"{{nav}}": sitenav.html(first, "domains", several=len(domains) > 1, site_wide=True),
              "{{nav_css}}": sitenav.CSS, "{{analytics}}": sitenav.ANALYTICS,
              "{{bands}}": "".join(bands), "{{footer}}": esc(FOOTER), "{{as_of}}": esc(doc.get("as_of", "")),
              "{{brand}}": esc(sitenav.BRAND)}
    for k, v in values.items():
        t = t.replace(k, v)
    return t


def write(site: Path, data_root: Path, domains: list[str]) -> Path | None:
    if not (data_root / "domains" / "public.json").exists():
        return None
    out = site / "domains" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(site, data_root, domains), encoding="utf-8", newline="\n")
    return out
