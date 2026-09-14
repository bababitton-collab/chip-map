"""Audit every question's baskets against the map: who else moves on the answer.

    python tools/audit_baskets.py              # writes data/semi/audit_baskets.md
    python tools/audit_baskets.py --show-text  # also prints each trigger sentence

Phase A of the basket review. It reads and it reports. It changes no data file
and runs no preregistration.

WHAT IT CHECKS
--------------
For each question in data/semi/watch.json, and for every company in its win
and lose baskets:

  * the company's direct suppliers and direct customers (``supplies`` edges),
  * its competitors: ``competes``/``substitutes`` edges, the other holders of
    a chokepoint it holds, and that chokepoint's challengers,
  * the subnodes that supply it (tier 1) and the subnodes that supply those
    (tier 2), through ``supplies_to`` and ``sub_edges``.

Every one of them that is publicly traded and not already in a basket of the
question is a candidate to ADD, with the reason and the side it would most
likely take. A node is traded by definition (every node carries a price
symbol). A subnode is judged from LISTINGS below -- a curated list with a
ticker, an exchange and a source for each company -- and, where the list has no
entry, from the map's own ticker field, marked "verify".

The kind check is a keyword rule on the question's wording: industry-wide
volume, price or demand reads as a tide; one company winning, qualifying,
taking or losing share reads as a share question.

THE QUESTION TEXT STAYS OUT OF GIT
----------------------------------
The wording is the product. It lives behind QUESTIONS_URL, and this report is
committed to a public repository. So the report quotes a trigger sentence only
for questions whose text is already free on the site -- everything answered,
plus the next one up (chains/questions.open_ids). For every other question it
gives the verdict and how many keywords of each kind matched. --show-text
prints every trigger sentence to the terminal, never to the file.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from chains import exchanges, questions  # noqa: E402
from chains.paths import commitments_path, map_path, watch_en_path, watch_path  # noqa: E402

OUT = REPO / "data" / "semi" / "audit_baskets.md"

# ----------------------------------------------------------------- listings
# One record per company that the map carries as a subnode, a group member or
# a challenger, and that needs a person's word rather than the map's ticker
# field. status: listed | private | node. ``eodhd`` is the symbol the price
# store could fetch today; ``fallback`` is a US OTC line where the home
# exchange is not on the plan (Tokyo is not -- chains/exchanges.py).
LISTINGS: dict[str, dict] = {
    "wacker": dict(company="Wacker Chemie", status="listed", ticker="WCH", exchange="Xetra",
                   eodhd="WCH.XETRA", fallback=None, in_map="subnode wacker",
                   source="https://www.wacker.com/cms/en-us/investor-relations/investor-relations.html"),
    "ferrotec": dict(company="Ferrotec", status="listed", ticker="6890", exchange="Tokyo",
                     eodhd=None, fallback="FRRZF (US OTC, verify on EODHD)",
                     in_map="member of subnodes cz_pullers and quartz_crucibles",
                     source="https://www.marketscreener.com/quote/stock/FERROTEC-CORPORATION-11551535/"),
    "hemlock": dict(company="Hemlock Semiconductor", status="private", ticker=None, exchange=None,
                    eodhd=None, fallback=None, in_map="subnode hemlock",
                    note="Corning 80.5%, Shin-Etsu Handotai 19.5%",
                    source="https://hscpoly.com/corporate-overview.html"),
    "sibelco": dict(company="Sibelco", status="private", ticker=None, exchange=None,
                    eodhd=None, fallback=None, in_map="subnode sibelco_spruce_pine",
                    note="owned by Belgian families; MarketScreener lists an ISIN (BE0944264663) -- verify there is no quotation",
                    source="https://www.sibelco.com/en/about-us/history"),
    "quartz_corp": dict(company="The Quartz Corp", status="private", ticker=None, exchange=None,
                        eodhd=None, fallback=None, in_map="subnode quartz_corp",
                        note="joint venture of Imerys and Norsk Mineral",
                        source="https://www.thequartzcorp.com/articles/history"),
    "momentive": dict(company="Momentive Technologies", status="private", ticker=None, exchange=None,
                      eodhd=None, fallback=None, in_map="member of subnode quartz_crucibles",
                      note="principal shareholder formed by Wonik QnC and SJL Partners",
                      source="https://www.crainscleveland.com/manufacturing/momentive-quartz-technologies-now-its-own-plots-growth-strategy/"),
    "coorstek": dict(company="CoorsTek", status="private", ticker=None, exchange=None,
                     eodhd=None, fallback=None, in_map="member of subnode quartz_crucibles",
                     note="owned by the Coors family",
                     source="https://www.coorstek.com/en/about/history/"),
    "fujimi": dict(company="Fujimi", status="listed", ticker="5384", exchange="Tokyo",
                   eodhd=None, fallback="FUJXF (US OTC; the map prices it as FUJXF.US)",
                   in_map="subnodes fujimi, fujimi_wafer",
                   source="https://finance.yahoo.com/quote/FUJXF/"),
    "tokuyama": dict(company="Tokuyama", status="listed", ticker="4043", exchange="Tokyo",
                     eodhd=None, fallback="TKYMF (US OTC, not yet in the map; verify on EODHD)",
                     in_map="subnode tokuyama",
                     source="https://finance.yahoo.com/quote/TKYMF/"),
    "resonac": dict(company="Resonac (formerly Showa Denko)", status="listed", ticker="4004", exchange="Tokyo",
                    eodhd=None, fallback="SHWDY (US OTC ADR; the map prices it as SHWDY.US)",
                    in_map="subnode resonac_ncf; member of abf_epoxy",
                    source="https://www.otcmarkets.com/stock/SHWDY/profile"),
    "sumco": dict(company="SUMCO", status="node", ticker="3436", exchange="Tokyo",
                  eodhd=None, fallback="SUOPY.US (the node's price symbol)", in_map="node sumco",
                  source="map.json node sumco"),
    "siltronic": dict(company="Siltronic", status="listed", ticker="WAF", exchange="Xetra",
                      eodhd="WAF.XETRA", fallback=None, in_map="challenger at CP6 only",
                      source="https://www.siltronic.com/en/investors/information-on-the-share.html"),
    "sk_siltron": dict(company="SK Siltron", status="private", ticker=None, exchange=None,
                       eodhd=None, fallback=None, in_map="challenger at CP6 only",
                       note="unlisted; SK Inc signed the sale of 70.6% to Doosan on 2026-07-31, closing expected by Jan-2027",
                       source="https://www.koreaherald.com/article/10827471"),
    "nsig": dict(company="NSIG (National Silicon Industry Group)", status="listed", ticker="688126",
                 exchange="Shanghai (STAR)", eodhd="688126.SHG", fallback=None, in_map="challenger at CP6 only",
                 note="the code is 688126; 688072 is not NSIG",
                 source="https://english.sse.com.cn/markets/equities/list/overview/?COMPANY_CODE=688126&STOCK_CODE=688126"),
    "jsr": dict(company="JSR", status="private", ticker=None, exchange=None,
                eodhd=None, fallback=None, in_map="subnode jsr",
                note="delisted from Tokyo 2024-06-25 after the JIC tender offer",
                source="https://www.jpx.co.jp/english/news/1023/20240605-11.html"),
    "ajinomoto": dict(company="Ajinomoto", status="node", ticker="2802", exchange="Tokyo",
                      eodhd=None, fallback="AJNMY.US (the node's price symbol)", in_map="node ajinomoto",
                      source="map.json node ajinomoto"),
    "entegris": dict(company="Entegris", status="node", ticker="ENTG", exchange="NASDAQ",
                     eodhd="ENTG.US", fallback=None, in_map="node entegris",
                     source="map.json node entegris"),
}

# Map subnode ids and challenger names that the curated records speak for.
LISTING_FOR_SUBNODE = {"wacker": "wacker", "hemlock": "hemlock", "sibelco_spruce_pine": "sibelco",
                       "quartz_corp": "quartz_corp", "fujimi": "fujimi", "fujimi_wafer": "fujimi",
                       "tokuyama": "tokuyama", "resonac_ncf": "resonac", "jsr": "jsr"}
LISTING_FOR_CHALLENGER = [("Siltronic", "siltronic"), ("SK Siltron", "sk_siltron"),
                          ("NSIG", "nsig"), ("JSR", "jsr")]
# Grouped subnodes: the members, each as a listing key or a plain note.
GROUPS = {
    "quartz_crucibles": ["node:shinetsu (Shin-Etsu Quartz Products)", "momentive", "ferrotec", "coorstek"],
    "cz_pullers": ["PVA TePla -- TPE.XETRA (priced in the map)", "ferrotec",
                   "Jinglong -- 300316.SHE (priced in the map)", "Linton -- private (map)"],
}

# The order the "Promotion candidates" table lists the curated records in.
PROMOTION_ORDER = ["wacker", "ferrotec", "hemlock", "sibelco", "quartz_corp", "momentive", "coorstek",
                   "fujimi", "tokuyama", "resonac", "sumco", "siltronic", "sk_siltron", "nsig", "jsr",
                   "ajinomoto", "entegris"]

# ----------------------------------------------------------------- kind rule
TIDE_TERMS = [r"shipments?", r"recover(y|s|ed)?", r"capacity", r"pric(e|es|ing)", r"demand",
              r"volumes?", r"utili[sz]ation", r"capex", r"orders?", r"bookings?", r"backlog", r"inventor(y|ies)"]
SHARE_TERMS = [r"wins?", r"won", r"qualif(y|ies|ied|ication)", r"takes? share", r"market share",
               r"share gains?", r"loses?", r"lost", r"second[- ]source", r"displac(e|es|ed|ing)",
               r"switch(es|ed)?", r"award(s|ed)?", r"sole[- ]source", r"design wins?"]
TIDE_RE = [re.compile(rf"\b{t}\b", re.I) for t in TIDE_TERMS]
SHARE_RE = [re.compile(rf"\b{t}\b", re.I) for t in SHARE_TERMS]


def kind_check(text: dict | None) -> dict:
    """The expected kind from the English wording: the question first, then
    what yes and no sound like if the question itself names neither."""
    if not text:
        return {"expected": None, "why": "text unavailable (QUESTIONS_URL not set or unreachable)"}
    for field in ("q_en", "yes_en", "no_en"):
        s = text.get(field) or ""
        tide = [m for r in TIDE_RE for m in r.finditer(s)]
        share = [m for r in SHARE_RE for m in r.finditer(s)]
        if not tide and not share:
            continue
        first = min(tide + share, key=lambda m: m.start())
        sentences = re.split(r"(?<=[.?!])\s+", s)
        at, trigger = 0, s
        for sent in sentences:
            if at <= first.start() < at + len(sent) + 1:
                trigger = sent
                break
            at += len(sent) + 1
        expected = ("tide" if tide and not share else "share" if share and not tide else "mixed")
        return {"expected": expected, "field": field, "n_tide": len(tide), "n_share": len(share),
                "words": sorted({m.group(0).lower() for m in tide + share}), "sentence": trigger.strip()}
    return {"expected": None, "why": "no keyword of either kind in the question, yes or no wording"}


# ----------------------------------------------------------------- the map
class Map:
    def __init__(self, doc: dict):
        self.doc = doc
        self.nodes = {n["id"]: n for n in doc["nodes"]}
        self.subs = {s["id"]: s for s in doc.get("subnodes", [])}
        self.node_by_symbol = {n["price_symbol"]: n["id"] for n in doc["nodes"] if n.get("price_symbol")}
        self.cps = doc.get("chokepoints", [])
        self.challengers = doc.get("challengers") or {}

    def name(self, eid: str) -> str:
        if eid in self.nodes:
            return self.nodes[eid]["name"]
        if eid in self.subs:
            return self.subs[eid]["name"]
        return eid

    def relations(self, x: str) -> list[dict]:
        """Everything linked to node x, as {key, relation, via}."""
        out: list[dict] = []
        for e in self.doc.get("edges", []):
            t = e.get("type")
            if t == "supplies" and e["to"] == x:
                out.append({"key": e["from"], "relation": "supplier", "via": e.get("what", "")})
            elif t == "supplies" and e["from"] == x:
                out.append({"key": e["to"], "relation": "customer", "via": e.get("what", "")})
            elif t in ("competes", "substitutes") and x in (e["from"], e["to"]):
                other = e["to"] if e["from"] == x else e["from"]
                out.append({"key": other, "relation": "competitor", "via": f"{t}: {e.get('what', '')}"})
        for c in self.cps:
            if x not in c["node_ids"]:
                continue
            for h in c["node_ids"]:
                if h != x:
                    out.append({"key": h, "relation": "competitor", "via": f"co-holder of {c['id']}"})
            for ch in self.challengers.get(c["id"], []):
                key = ch.get("sponsor") or f"challenger:{ch['name']}"
                out.append({"key": key, "relation": "competitor",
                            "via": f"challenger at {c['id']}: {ch['name']}", "challenger": ch})
        tier1 = {s["id"] for s in self.subs.values() if s.get("supplies_to") == x}
        tier1 |= {e["from"] for e in self.doc.get("sub_edges", []) if e["to"] == x and e["from"] in self.subs}
        tier1 -= set(self.nodes)
        for sid in sorted(tier1):
            out.append({"key": sid, "relation": "subnode supplier (tier 1)", "via": self.subs[sid].get("what", "")})
        tier2: dict[str, str] = {}
        for e in self.doc.get("sub_edges", []):
            if e["to"] in tier1 and e["from"] in self.subs and e["from"] not in tier1 and e["from"] not in self.nodes:
                tier2.setdefault(e["from"], e["to"])
        for s in self.subs.values():
            if s.get("supplies_to") in tier1 and s["id"] not in tier1 and s["id"] not in self.nodes:
                tier2.setdefault(s["id"], s["supplies_to"])
        for sid, via in sorted(tier2.items()):
            out.append({"key": sid, "relation": "subnode supplier (tier 2)",
                        "via": f"supplies {self.name(via)}"})
        return out

    def listing(self, key: str, challenger: dict | None = None) -> dict:
        """Who this is and whether it trades: {label, map_id, status, priced, detail, source}."""
        if key in self.nodes:
            n = self.nodes[key]
            return dict(label=n["name"], map_id=key, status="node", priced=n.get("price_symbol"),
                        detail=f"node, priced as {n.get('price_symbol')}", source="map.json")
        if key.startswith("challenger:"):
            name = key.split(":", 1)[1]
            for needle, lk in LISTING_FOR_CHALLENGER:
                if needle.lower() in name.lower():
                    return self._curated(lk, map_id=None, label=name)
            tp = str((challenger or {}).get("ticker_or_private") or "")
            status = "private" if tp.lower().startswith(("private", "n/a", "state")) or not tp else "verify"
            return dict(label=name, map_id=None, status=status, priced=None,
                        detail=f"challenger; ticker_or_private: {tp or 'blank'}" + ("" if status == "private" else " (verify)"),
                        source="map.json challengers")
        s = self.subs.get(key)
        if s is None:
            return dict(label=key, map_id=None, status="verify", priced=None, detail="not in the map", source="")
        if s.get("price_symbol") in self.node_by_symbol:
            nid = self.node_by_symbol[s["price_symbol"]]
            return dict(label=s["name"], map_id=nid, status="node", priced=s["price_symbol"],
                        detail=f"same listing as node {nid}", source="map.json")
        if key in LISTING_FOR_SUBNODE:
            return self._curated(LISTING_FOR_SUBNODE[key], map_id=key, label=s["name"])
        if key in GROUPS:
            members = []
            for m in GROUPS[key]:
                if m in LISTINGS:
                    r = LISTINGS[m]
                    members.append(f"{r['company']} -- {r['status']}"
                                   + (f" {r['ticker']} {r['exchange']}" if r["status"] == "listed" else ""))
                else:
                    members.append(m)
            return dict(label=s["name"], map_id=key, status="group", priced=s.get("price_symbol"),
                        detail="group of companies: " + "; ".join(members), source="see Promotion candidates")
        ticker = str(s.get("ticker") or "")
        if ticker.lower().startswith(("private", "state", "n/a", "various")) or not ticker:
            return dict(label=s["name"], map_id=key, status="private", priced=None,
                        detail=f"map ticker field: {ticker or 'blank'}", source="map.json (verify)")
        if s.get("price_symbol"):
            return dict(label=s["name"], map_id=key, status="listed", priced=s["price_symbol"],
                        detail=f"{ticker} {s.get('exchange') or ''}; priced as {s['price_symbol']} ({s.get('price_symbol_kind')})",
                        source="map.json (verify)")
        sym, why = exchanges.resolve(ticker.split(" ")[0].split("/")[0].strip(), s.get("exchange"))
        return dict(label=s["name"], map_id=key, status="listed", priced=None,
                    detail=f"{ticker} {s.get('exchange') or ''}; unpriced ({why or 'no price symbol in the map'})",
                    source="map.json (verify)")

    def _curated(self, lk: str, map_id: str | None, label: str) -> dict:
        r = LISTINGS[lk]
        if r["status"] == "listed":
            detail = f"{r['ticker']} {r['exchange']}; " + (f"EODHD {r['eodhd']}" if r["eodhd"] else
                                                          f"unpriced on EODHD; fallback {r['fallback'] or 'none'}")
        else:
            detail = r["status"] + (f" ({r['note']})" if r.get("note") else "")
        return dict(label=f"{r['company']}", map_id=map_id, status=r["status"],
                    priced=r["eodhd"], detail=detail, source=r["source"])


TRADED = {"node", "listed"}


# ----------------------------------------------------------------- one question
def side_for(relation: str, basket: str, kind: str) -> str:
    """The side a linked company would most likely take, and why."""
    if relation == "supplier" or relation == "subnode supplier (tier 1)":
        return basket
    if relation == "subnode supplier (tier 2)":
        return f"second ring ({basket})"
    if relation == "customer":
        return f"second ring ({basket})"
    if relation == "competitor":
        if kind == "tide":
            return basket                         # the tide lifts the rival too
        return "lose" if basket == "win" else "win"
    return "?"


def audit_question(mp: Map, row: dict, committed: dict, today: dt.date, text: dict | None,
                   open_ids: set[str]) -> dict:
    qid, kind = row["id"], row.get("kind")
    win, lose = list(row.get("win") or []), list(row.get("lose") or [])
    in_basket = set(win) | set(lose)
    date = dt.date.fromisoformat(row["d"])
    past = date < today
    entry = committed.get(qid)
    if entry and past:
        locked = "LOCKED -- committed and its answer date has passed: do not touch"
    elif entry:
        locked = (f"needs `python -m chains.preregister --write --recommit {qid}` before {row['d']} "
                  f"(committed {entry['committed_at']})")
    else:
        locked = "free -- not committed yet"
    if row.get("observe_only"):
        legs = "observe-only (empty by design)"
    elif not win and not lose:
        legs = "EMPTY"
    elif not win or not lose:
        legs = "single-leg (" + ("no win" if not win else "no lose") + ")"
    else:
        legs = "both legs"

    candidates: dict[str, dict] = {}
    untraded: dict[str, dict] = {}
    conflicts: list[str] = []
    for basket, members in (("win", win), ("lose", lose)):
        for x in members:
            for rel in mp.relations(x):
                info = mp.listing(rel["key"], rel.get("challenger"))
                ident = info["map_id"] or info["label"]
                if info["map_id"] in in_basket:
                    if rel["relation"] == "competitor" and kind == "tide" and \
                            ((basket == "win" and info["map_id"] in lose) or (basket == "lose" and info["map_id"] in win)):
                        conflicts.append(f"{mp.name(info['map_id'])} is in {'LOSE' if basket == 'win' else 'WIN'} "
                                         f"but is a competitor ({rel['via']}) of {mp.name(x)} in {basket.upper()} "
                                         f"on a tide question -- a tide moves both the same way")
                    continue
                reason = f"{rel['relation']} of {mp.name(x)}" + (f" -- {rel['via'][:70]}" if rel["via"] else "")
                bucket = candidates if info["status"] in TRADED else untraded
                slot = bucket.setdefault(ident, dict(info, sides=set(), reasons=[]))
                slot["sides"].add(side_for(rel["relation"], basket, kind))
                if reason not in slot["reasons"]:
                    slot["reasons"].append(reason)
    kc = kind_check(text)
    public_text = qid in open_ids
    return dict(row=row, win=win, lose=lose, past=past, committed=bool(entry), locked=locked, legs=legs,
                candidates=candidates, untraded=untraded, conflicts=conflicts, kind=kc,
                public_text=public_text, valid=(entry or {}).get("valid_preregistration"))


# ----------------------------------------------------------------- the report
def md_escape(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def names(mp: Map, ids: list[str]) -> str:
    return ", ".join(f"{mp.name(i)} (`{i}`)" for i in ids) if ids else "--"


def kind_line(a: dict) -> tuple[str, bool, bool]:
    """(markdown, probable mismatch, needs a look by hand)."""
    kc, current = a["kind"], a["row"].get("kind")
    exp = kc.get("expected")
    if exp is None:
        return f"current **{current}**; expected: not decided -- {kc.get('why')}", False, False
    mismatch = exp in ("tide", "share") and exp != current
    by_hand = exp == "mixed"
    verdict = ("**probable mismatch**" if mismatch else "check by hand (both kinds of keyword)" if by_hand
               else "consistent")
    counts = f"{kc['n_tide']} tide / {kc['n_share']} share keyword(s) in `{kc['field']}`"
    if a["public_text"]:
        detail = f"{counts}: {', '.join(kc['words'])}. Trigger: \"{md_escape(kc['sentence'])}\""
    else:
        detail = f"{counts}; wording withheld -- locked on the site"
    return f"current **{current}**, expected **{exp}** -- {verdict}. {detail}", mismatch, by_hand


def render(mp: Map, audits: list[dict], today: dt.date) -> str:
    rows = []
    n = dict(empty=0, single=0, observe=0, mismatch=0, by_hand=0, locked=0, recommit=0, free=0, with_cands=0)
    for a in audits:
        k, mm, bh = kind_line(a)
        a["kind_md"] = k
        n["mismatch"] += mm
        n["by_hand"] += bh
        n["empty"] += a["legs"] == "EMPTY"
        n["single"] += a["legs"].startswith("single-leg")
        n["observe"] += a["legs"].startswith("observe-only")
        n["locked"] += a["committed"] and a["past"]
        n["recommit"] += a["committed"] and not a["past"]
        n["free"] += not a["committed"]
        n["with_cands"] += bool(a["candidates"])
    out = [f"# Basket audit -- {today.isoformat()}", "",
           "Generated by `tools/audit_baskets.py` (Phase A: it reads and reports, and changes no data file). "
           "For every company in a question's win and lose baskets it lists the map's suppliers, customers, "
           "competitors and supplying subnodes, and flags each one that is publicly traded but in no basket "
           "of that question. \"Side\" is the likely placement: a supplier goes with the company it supplies; "
           "a competitor goes with it on a tide and against it on a share question; customers and tier-2 "
           "subnodes are second ring. Baskets can hold priced nodes only, so a listed subnode has to be "
           "promoted to a node before it can be added.", "",
           "Question wording is quoted only for questions whose text is already free on the site; for the "
           "rest the kind check shows its verdict and keyword counts. Run with `--show-text` to see every "
           "trigger sentence in the terminal.", "",
           "## Summary", "",
           "| | count |", "|---|---|",
           f"| questions | {len(audits)} |",
           f"| empty baskets (not observe-only) | {n['empty']} |",
           f"| single-leg baskets | {n['single']} |",
           f"| observe-only (empty by design) | {n['observe']} |",
           f"| probable kind mismatch | {n['mismatch']} |",
           f"| kind needs a look by hand (both keyword kinds) | {n['by_hand']} |",
           f"| locked (committed, date passed) | {n['locked']} |",
           f"| needs --recommit (committed, date ahead) | {n['recommit']} |",
           f"| free (not committed) | {n['free']} |",
           f"| questions with at least one traded candidate to add | {n['with_cands']} |", "",
           "## Questions", ""]
    for a in audits:
        r = a["row"]
        out += [f"### `{r['id']}` -- {md_escape(r['who'])} ({r['d']})", "",
                f"- **Locked?** {a['locked']}" + ("" if a["valid"] in (None, True) else
                                                   " -- note: its commitment is marked not a valid preregistration"),
                f"- **Kind:** {a['kind_md']}",
                f"- **Baskets ({a['legs']}):** win {names(mp, a['win'])}; lose {names(mp, a['lose'])}"]
        for c in a["conflicts"]:
            out.append(f"- **Conflict:** {c}")
        out.append("")
        direct = {k: c for k, c in a["candidates"].items()
                  if any(not s.startswith("second ring") for s in c["sides"])}
        ring2 = {k: c for k, c in a["candidates"].items() if k not in direct}
        if direct:
            out += ["| side | candidate | map id | trades as | reason |", "|---|---|---|---|---|"]
            for ident, c in sorted(direct.items(),
                                   key=lambda kv: (sorted(kv[1]["sides"])[0], kv[1]["label"])):
                sides = sorted(s for s in c["sides"] if not s.startswith("second ring"))
                out.append(f"| {' / '.join(sides)} | {md_escape(c['label'])} | "
                           f"{('`' + c['map_id'] + '`') if c['map_id'] else '--'} | {md_escape(c['detail'])} | "
                           f"{md_escape('; '.join(c['reasons'][:3]))} |")
        else:
            out.append("No traded win or lose candidate outside the baskets.")
        if ring2:
            listed = "; ".join(
                f"{md_escape(c['label'])}" + (f" (`{c['map_id']}`)" if c["map_id"] else "")
                + f" -- {md_escape(c['reasons'][0].split(' -- ')[0])}"
                for c in sorted(ring2.values(), key=lambda c: c["label"]))
            out += ["", f"Second ring, traded (customers and tier-2 subnodes): {listed}"]
        if a["untraded"]:
            linked = "; ".join(f"{md_escape(c['label'])} ({c['status']})" for c in
                               sorted(a["untraded"].values(), key=lambda c: c["label"]))
            out += ["", f"Also linked, not addable as they stand: {linked}"]
        out.append("")

    out += ["## Promotion candidates", "",
            "Companies the map carries as subnodes, group members or challengers, with a person-checked "
            "listing. EODHD covers Xetra, Shanghai, Shenzhen, Korea and Taiwan on this plan; it does not "
            "cover Tokyo, Hong Kong, Singapore, Milan or India (`chains/exchanges.py`), so a Tokyo listing "
            "prices only through a US OTC line where one exists.", "",
            "| company | in the map | status | ticker | exchange | EODHD today | fallback | note | source |",
            "|---|---|---|---|---|---|---|---|---|"]
    for lk in PROMOTION_ORDER:
        r = LISTINGS[lk]
        out.append(f"| {md_escape(r['company'])} | {md_escape(r['in_map'])} | {r['status']} | {r['ticker'] or '--'} | "
                   f"{r['exchange'] or '--'} | {r['eodhd'] or ('not covered' if r['status'] == 'listed' else '--')} | "
                   f"{md_escape(r['fallback'] or '--')} | {md_escape(r.get('note') or '')} | {r['source']} |")
    out += ["", "### Other traded subnodes (from the map's own ticker fields -- verify)", "",
            "| subnode | map id | trades as |", "|---|---|---|"]
    curated_ids = set(LISTING_FOR_SUBNODE) | set(GROUPS)
    for sid, s in sorted(mp.subs.items(), key=lambda kv: kv[1]["name"]):
        if sid in curated_ids:
            continue
        info = mp.listing(sid)
        if info["status"] == "listed":
            out.append(f"| {md_escape(s['name'])} | `{sid}` | {md_escape(info['detail'])} |")
    out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--show-text", action="store_true",
                    help="print each trigger sentence to the terminal (never to the file)")
    a = ap.parse_args(argv)
    today = dt.date.today()
    rows = json.loads(watch_path().read_text(encoding="utf-8"))
    # The English list carries the same ids and dates with English names; the
    # report is English, and watch.json names some rows in Hebrew.
    who_en = {r["id"]: r.get("who") for r in json.loads(watch_en_path().read_text(encoding="utf-8"))}
    rows = [dict(r, who=who_en.get(r["id"]) or r["who"]) for r in rows]
    committed = {c["qid"]: c for c in json.loads(commitments_path().read_text(encoding="utf-8"))}
    mp = Map(json.loads(map_path().read_text(encoding="utf-8")))
    try:
        texts = questions.fetch()
    except questions.QuestionsError as e:
        print(f"question text unavailable, kind check skipped: {e}")
        texts = {}
    open_ids = questions.open_ids(rows, today)
    audits = [audit_question(mp, r, committed, today, texts.get(r["id"]), open_ids) for r in rows]
    for au in audits:
        r = au["row"]
        kc = au["kind"]
        print(f"{r['id']:<16} {r['d']}  {r['who'][:28]:<28} kind={r.get('kind'):<5} "
              f"win={r.get('win')} lose={r.get('lose')} observe_only={bool(r.get('observe_only'))} "
              f"committed={au['committed']} past={au['past']} expected={kc.get('expected')} "
              f"candidates={len(au['candidates'])}")
        if a.show_text and kc.get("sentence"):
            print(f"    trigger ({kc['field']}): {kc['sentence']}")
    report = render(mp, audits, today)
    # Belt and braces, the same test the site's own leak scan applies: no
    # sentence of a question that is locked on the site may reach this file,
    # which is committed to a public repository.
    leaks = []
    for qid, t in texts.items():
        if qid in open_ids:
            continue
        for field, value in t.items():
            for part in [value or ""] + re.split(r"(?<=[.?!])\s+", value or ""):
                if len(part.strip()) >= 25 and part.strip() in report:
                    leaks.append(f"{qid}.{field}")
    if leaks:
        raise SystemExit(f"refusing to write {OUT}: locked question text would leak ({sorted(set(leaks))[:5]})")
    OUT.write_text(report, encoding="utf-8", newline="\n")
    print(f"\nwrote {OUT}  (no locked question text in it: checked {len(texts)} questions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
