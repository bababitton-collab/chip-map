"""Audit every question's baskets against the map: who else moves on the answer.

    python tools/audit_baskets.py              # writes data/semi/audit_baskets_v2.md
    python tools/audit_baskets.py --out PATH   # somewhere else
    python tools/audit_baskets.py --show-text  # also prints each trigger sentence

It reads and it reports. It changes no data file and runs no preregistration.
EODHD_API_TOKEN, when set, adds each leg's traded volume and the search for a
better listing; without it those columns say so.

WHAT IT CHECKS
--------------
For each question in data/semi/watch.json:

  1. The reporter rule. When the question is about the reporter's own
     results -- its ticker is the row's ``tk`` and the English yes wording
     names its own numbers (revenue, guidance, shipments, orders ...) -- the
     reporter has to be in a basket. Capex and gauge questions, where the
     reporter is the customer whose spending is being read (REPORTER_EXEMPT),
     are listed as exempt.
  2. No station in both win and lose.
  3. Every basket leg is priced fresh: a close in live_en.json dated within
     FRESH_DAYS of the snapshot, and not stale by the tracking card's rule
     (more than track.STALE_AFTER sessions without a close). Every leg's
     three-month average daily volume and traded value come from EODHD; a leg
     trading under THIN_USD a day is thin. For each stale or thin leg the
     most liquid listing EODHD covers is proposed: the primary exchange if the
     plan carries it, else another US line of the same company -- or "no
     liquid line".
  4. The first review's checks, kept: for every company in a basket, its
     direct suppliers and customers, its competitors (``competes`` and
     ``substitutes`` edges, co-holders of a chokepoint, that chokepoint's
     challengers) and the subnodes that supply it, each traded one not in a
     basket listed as a candidate; the tide/share keyword check on the
     wording; and whether the commitment is locked, unchanged or needs a
     re-commit.

The summary adds the single-leg baskets that remain, the first-order direct
suppliers and customers still missing -- a ``supplies`` edge between a basket
company and another station, not a subnode and not a supplier's supplier --
with the edge and its source, and the stale or thin legs with their proposed
fix.

THE QUESTION TEXT STAYS OUT OF GIT
----------------------------------
The wording is the product. It lives behind QUESTIONS_URL, and this report is
committed to a public repository. So the report quotes a trigger sentence only
for questions whose text is already free on the site -- everything answered,
plus the next one up (chains/questions.open_ids). For every other question it
gives verdicts, counts and matched keywords. --show-text prints every trigger
sentence to the terminal, never to the file, and a leak scan refuses to write
a report that carries any locked sentence.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from chains import exchanges, forecast, preregister, questions, track  # noqa: E402
from chains.paths import commitments_path, map_path, out_dir, watch_en_path, watch_path  # noqa: E402

OUT = REPO / "data" / "semi" / "audit_baskets_v2.md"

# ----------------------------------------------------------------- thresholds
FRESH_DAYS = 7              # a leg's last close, calendar days before the snapshot
THIN_USD = 250_000          # three-month average daily traded value, in US dollars
ADV_DAYS = 91               # "three months" of daily bars

# The reporter is the customer whose spending is read, not a company reporting
# on its own business being scored -- so the rule does not apply.
REPORTER_EXEMPT = {
    "orcl_q1": "capex gauge: Oracle's AI spending is read for its suppliers",
    "googl_q3": "capex gauge: Alphabet's AI spending is read for its suppliers",
    "amzn_q3": "capex gauge: Amazon's AI spending is read for its suppliers",
}
OWN_TERMS = [r"revenues?", r"sales", r"guid(e|es|ed|ance)", r"margins?", r"earnings", r"eps", r"profits?",
             r"results?", r"shipments?", r"orders?", r"bookings?", r"backlog", r"outlook", r"forecasts?",
             r"quarter(ly)?", r"half[- ]year", r"h[12]", r"q[1-4]", r"utili[sz]ation", r"inventor(y|ies)",
             r"units?", r"beat", r"miss(es|ed)?"]
OWN_RE = re.compile(r"\b(" + "|".join(OWN_TERMS) + r")\b", re.I)
# A reporting period in the row's short name -- "TSMC Q3", "Micron FQ4",
# "Shin-Etsu H1", "Siemens Energy FY" -- says the question is about the
# reporter's own results even where the yes wording uses none of the words above.
PERIOD_RE = re.compile(r"\b(F?Q[1-4]|H[12]|FY\d*|full[- ]year|half[- ]year)\b|\(full\)", re.I)
EXCHANGE_SUFFIX = re.compile(r"\.(KS|T|TW|TWO|DE)$", re.I)

# ----------------------------------------------------------------- listings
# One record per company that the map carries as a subnode, a group member or
# a challenger, and that needs a person's word rather than the map's ticker
# field. status: listed | private | node. ``eodhd`` is the symbol the price
# store could fetch today; ``fallback`` is a US OTC line where the home
# exchange is not on the plan (Tokyo is not -- chains/exchanges.py).
LISTINGS: dict[str, dict] = {
    "wacker": dict(company="Wacker Chemie", status="node", ticker="WCH", exchange="Xetra",
                   eodhd="WCH.XETRA", fallback=None, in_map="node wacker (promoted 2026-09-15); subnode wacker",
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
    "siltronic": dict(company="Siltronic", status="node", ticker="WAF", exchange="Xetra",
                      eodhd="WAF.XETRA", fallback=None,
                      in_map="node siltronic (promoted 2026-09-15); challenger at CP6",
                      source="https://www.siltronic.com/en/investors/information-on-the-share.html"),
    "sk_siltron": dict(company="SK Siltron", status="private", ticker=None, exchange=None,
                       eodhd=None, fallback=None, in_map="challenger at CP6 only",
                       note="unlisted; SK Inc signed the sale of 70.6% to Doosan on 2026-07-31, closing expected by Jan-2027",
                       source="https://www.koreaherald.com/article/10827471"),
    "nsig": dict(company="NSIG (National Silicon Industry Group)", status="node", ticker="688126",
                 exchange="Shanghai (STAR)", eodhd="688126.SHG", fallback=None,
                 in_map="node nsig (promoted 2026-09-15); challenger at CP6",
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
        # A row's tk is written the way the company is best known to the
        # reader -- TSM, SHECY -- which is often the US line rather than the
        # home ticker the node carries. So the station answers to all three.
        self.by_ticker: dict[str, str] = {}
        for n in doc["nodes"]:
            for t in (n.get("ticker"), str(n.get("price_symbol") or "").split(".")[0], n["id"]):
                if t:
                    self.by_ticker.setdefault(self.bare(t), n["id"])

    @staticmethod
    def bare(ticker: str | None) -> str:
        return EXCHANGE_SUFFIX.sub("", str(ticker or "")).strip().upper()

    def reporter(self, tk: str | None) -> str | None:
        """The station a row's ticker names, the way tests/test_leaks.py reads it."""
        return self.by_ticker.get(self.bare(tk)) if tk else None

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

    def first_order(self, basket: set[str], reporter: str | None = None) -> list[dict]:
        """``supplies`` edges between a basket company and a station outside
        every basket of the question. Subnodes and suppliers' suppliers are not
        first order and are not here. ``to_reporter`` marks the edges that end
        on the reporting company itself."""
        out, seen = [], set()
        for e in self.doc.get("edges", []):
            if e.get("type") != "supplies" or e["from"] not in self.nodes or e["to"] not in self.nodes:
                continue
            for inside, other, rel in ((e["to"], e["from"], "supplier"), (e["from"], e["to"], "customer")):
                if inside in basket and other not in basket and (other, inside) not in seen:
                    seen.add((other, inside))
                    src = e.get("source")
                    out.append(dict(company=other, of=inside, relation=rel, what=e.get("what", ""),
                                    source="; ".join(src) if isinstance(src, list) else (src or ""),
                                    as_of=e.get("as_of") or "", criticality=e.get("criticality") or "",
                                    to_reporter=inside == reporter))
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
        if r["status"] in ("listed", "node"):
            detail = f"{r['ticker']} {r['exchange']}; " + (f"EODHD {r['eodhd']}" if r["eodhd"] else
                                                          f"unpriced on EODHD; fallback {r['fallback'] or 'none'}")
        else:
            detail = r["status"] + (f" ({r['note']})" if r.get("note") else "")
        return dict(label=f"{r['company']}", map_id=map_id, status=r["status"],
                    priced=r["eodhd"], detail=detail, source=r["source"])


TRADED = {"node", "listed"}


# ----------------------------------------------------------------- prices
class Liquidity:
    """Three months of daily bars per symbol from EODHD, and the search for
    another listing of the same company. Nothing here is written anywhere;
    without a token every number is None and the report says so."""

    STOP = {"co", "co.", "ltd", "ltd.", "inc", "inc.", "corp", "corp.", "corporation", "company", "holdings",
            "group", "the", "plc", "ag", "se", "sa", "nv", "limited", "adr"}

    def __init__(self, token: str | None, as_of: dt.date):
        self.as_of = as_of
        self.client = None
        self.note = "EODHD_API_TOKEN not set: volume and alternative listings not checked"
        self._adv: dict[str, dict | None] = {}
        self._fx: dict[str, float | None] = {"USD": 1.0}
        if token:
            from chains.providers.eodhd import EODHDClient, silence_http_logging
            silence_http_logging()
            self.client = EODHDClient(token, rate_per_min=600)
            self.note = ""

    def close(self) -> None:
        if self.client:
            self.client.close()

    def _bars(self, symbol: str, days: int) -> list[dict]:
        frm = (self.as_of - dt.timedelta(days=days)).isoformat()
        try:
            return self.client.eod(symbol, from_=frm, to=self.as_of.isoformat())
        except Exception as e:                                  # noqa: BLE001 -- reported, not raised
            print(f"  EODHD {symbol}: {type(e).__name__}")
            return []

    def fx(self, cur: str | None) -> float | None:
        cur = (cur or "USD").upper()
        if cur in self._fx or not self.client:
            return self._fx.get(cur)
        rate = None
        rows = self._bars(f"{cur}USD.FOREX", 14)
        if rows and rows[-1].get("close"):
            rate = float(rows[-1]["close"])
        else:
            inv = self._bars(f"USD{cur}.FOREX", 14)
            if inv and inv[-1].get("close"):
                rate = 1.0 / float(inv[-1]["close"])
        self._fx[cur] = rate
        return rate

    def adv(self, symbol: str, currency: str | None) -> dict | None:
        """{shares, value_usd, sessions, last} over the last three months, or None."""
        if not self.client:
            return None
        if symbol in self._adv:
            return self._adv[symbol]
        rows = [r for r in self._bars(symbol, ADV_DAYS) if r.get("volume") is not None]
        if not rows:
            self._adv[symbol] = None
            return None
        shares = sum(float(r["volume"]) for r in rows) / len(rows)
        value = sum(float(r["volume"]) * float(r.get("close") or 0) for r in rows) / len(rows)
        rate = self.fx(currency)
        got = dict(shares=shares, value_usd=None if rate is None else value * rate, sessions=len(rows),
                   last=rows[-1]["date"], currency=(currency or "USD").upper(),
                   zero_days=sum(1 for r in rows if not r["volume"]))
        self._adv[symbol] = got
        return got

    def search_us_lines(self, name: str) -> list[dict]:
        """US listings EODHD knows for a company, matched on its distinctive name."""
        if not self.client:
            return []
        tokens = [t for t in re.split(r"[\s,]+", name.lower()) if t and t not in self.STOP]
        if not tokens:
            return []
        queries = [" ".join(tokens), tokens[0]]
        found: dict[str, dict] = {}
        for q in dict.fromkeys(queries):
            try:
                rows = self.client._get(f"/search/{urllib.parse.quote(q)}", {"limit": 50, "type": "stock"})
            except Exception as e:                              # noqa: BLE001
                print(f"  EODHD search {q!r}: {type(e).__name__}")
                continue
            for r in rows if isinstance(rows, list) else []:
                if r.get("Exchange") != "US":
                    continue
                # Every distinctive word of the name: "Tokyo" alone matched
                # Tokyo Electron for Tokyo Ohka Kogyo.
                listed = str(r.get("Name") or "").lower()
                if not all(re.search(rf"\b{re.escape(t)}\b", listed) for t in tokens):
                    continue
                found.setdefault(f"{r['Code']}.US", dict(symbol=f"{r['Code']}.US", name=r.get("Name"),
                                                         currency=r.get("Currency") or "USD",
                                                         last=r.get("previousCloseDate")))
        return list(found.values())


class Legs:
    """Each basket leg's price as the snapshot and the tracking card see it."""

    def __init__(self, mp: Map, live: dict, liq: Liquidity):
        self.mp, self.liq = mp, liq
        self.as_of = dt.date.fromisoformat(live["as_of"])
        self.live = {n["id"]: n for n in live["nodes"]}
        node_syms = [n["price_symbol"] for n in mp.doc["nodes"] if n.get("price_symbol")]
        self.book = forecast.Book(sorted(set(node_syms)))
        self.cal = forecast.sessions([s for s in node_syms if s.endswith(".US")])
        self._cache: dict[str, dict] = {}

    def check(self, leg: str) -> dict:
        if leg in self._cache:
            return self._cache[leg]
        node = self.mp.nodes.get(leg) or {}
        sym = node.get("price_symbol")
        px = (self.live.get(leg) or {}).get("px") or {}
        last = px.get("last")
        days = (self.as_of - dt.date.fromisoformat(last)).days if last else None
        sessions = (track._stale(self.book, sym, self.cal[-1], self.cal)
                    if sym and self.book.has(sym) and self.cal else None)
        problems = []
        if not sym:
            problems.append("no price symbol")
        if last is None:
            problems.append("no price row in live_en.json")
        elif days > FRESH_DAYS:
            problems.append(f"last close {days} days before the snapshot (> {FRESH_DAYS})")
        if sessions is not None and sessions > track.STALE_AFTER:
            problems.append(f"stale on the card: {sessions} sessions without a close (> {track.STALE_AFTER})")
        adv = self.liq.adv(sym, px.get("cur")) if sym else None
        thin = bool(adv and adv["value_usd"] is not None and adv["value_usd"] < THIN_USD)
        got = dict(leg=leg, name=node.get("name", leg), symbol=sym, kind=node.get("price_symbol_kind"),
                   last=last, days=days, sessions=sessions, stale=bool(problems), problems=problems,
                   adv=adv, thin=thin, fix=None)
        if got["stale"] or thin:
            got["fix"] = self.propose(node, adv)
        self._cache[leg] = got
        return got

    def propose(self, node: dict, current: dict | None) -> str:
        """The most liquid listing EODHD covers: the primary exchange if the plan
        carries it, else another US line -- or "no liquid line"."""
        if not self.liq.client:
            return "not checked (" + self.liq.note + ")"
        sym = node.get("price_symbol")
        cands, notes = [], []
        home, why = exchanges.resolve(str(node.get("ticker") or ""), node.get("exchange"))
        if home and home != sym:
            cands.append(dict(symbol=home, currency=None, origin="primary exchange"))
        elif not home:
            notes.append(f"primary {node.get('ticker')} not covered ({why})")
        for r in self.liq.search_us_lines(node.get("name", "")):
            if r["symbol"] != sym:
                cands.append(dict(symbol=r["symbol"], currency=r["currency"], origin=f"US line ({r['name']})"))
        best = None
        for c in cands:
            a = self.liq.adv(c["symbol"], c["currency"] or (self.live.get(node["id"], {}).get("px") or {}).get("cur"))
            if not a or a["value_usd"] is None:
                continue
            fresh = (self.as_of - dt.date.fromisoformat(a["last"])).days <= FRESH_DAYS
            c.update(adv=a, fresh=fresh)
            if fresh and (best is None or a["value_usd"] > best["adv"]["value_usd"]):
                best = c
        cur_val = (current or {}).get("value_usd") or 0
        tried = ", ".join(c["symbol"] for c in cands) or "none found"
        if best and best["adv"]["value_usd"] >= THIN_USD and best["adv"]["value_usd"] > cur_val:
            return (f"switch to **{best['symbol']}** ({best['origin']}): "
                    f"US${best['adv']['value_usd']:,.0f}/day, last close {best['adv']['last']}"
                    + (f"; {'; '.join(notes)}" if notes else ""))
        if best and best["adv"]["value_usd"] > cur_val:
            return (f"no liquid line -- best is {best['symbol']} ({best['origin']}) at "
                    f"US${best['adv']['value_usd']:,.0f}/day, still under US${THIN_USD:,}; tried {tried}"
                    + (f"; {'; '.join(notes)}" if notes else ""))
        return "no liquid line -- tried " + tried + (f"; {'; '.join(notes)}" if notes else "")


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


def reporter_check(mp: Map, row: dict, text: dict | None) -> dict:
    qid = row["id"]
    if row.get("observe_only"):
        return dict(state="n/a", reporter=None, why="observe-only policy question")
    rep = mp.reporter(row.get("tk"))
    if rep is None:
        return dict(state="n/a", reporter=None, why=f"the reporter ({row.get('tk') or 'no ticker'}) is not a station")
    if qid in REPORTER_EXEMPT:
        return dict(state="exempt", reporter=rep, why=REPORTER_EXEMPT[qid])
    if not text:
        return dict(state="unknown", reporter=rep, why="question text unavailable")
    words = sorted({m.group(0).lower() for m in OWN_RE.finditer(text.get("yes_en") or "")})
    period = PERIOD_RE.search(row.get("who") or "")
    if period:
        words.append(f"reporting period '{period.group(0)}' in the title")
    if not words:
        return dict(state="n/a", reporter=rep, why="neither the title nor the yes wording is about the reporter's own numbers")
    inside = rep in (row.get("win") or []) or rep in (row.get("lose") or [])
    return dict(state="ok" if inside else "FAIL", reporter=rep, words=words,
                why=("in the " + ("win" if rep in (row.get("win") or []) else "lose") + " basket") if inside
                else "about its own numbers, and in neither basket")


def commit_status(row: dict, text: dict | None, entry: dict | None, today: dt.date) -> tuple[str, str]:
    """(status key, sentence): locked | unchanged | changed | free | unchecked."""
    if not entry:
        return "free", "free -- not committed yet"
    past = dt.date.fromisoformat(row["d"]) < today
    rev = (f"; revised {entry['revised_at']}, replacing {len(entry.get('history') or [])} earlier hash"
           if entry.get("revised_at") else "")
    try:
        sha = preregister.commitment(row, text)["sha256"] if text else None
    except preregister.PreregisterError:
        sha = None
    if past:
        tail = ("" if sha is None else " (contract unchanged)" if sha == entry["sha256"]
                else " -- **CONTRACT CHANGED after its answer date**")
        return "locked", f"LOCKED -- committed {entry['committed_at']}{rev}, answer date passed: do not touch{tail}"
    if sha is None:
        return "unchecked", f"committed {entry['committed_at']}{rev}; contract not re-hashed (text unavailable)"
    if sha == entry["sha256"]:
        return "unchanged", f"committed {entry['committed_at']}{rev}; contract unchanged -- nothing to re-commit"
    return "changed", (f"**CHANGED** since {entry['committed_at']} -- needs "
                       f"`python -m chains.preregister --write --recommit {row['id']}` before {row['d']}")


def audit_question(mp: Map, legs: Legs, row: dict, committed: dict, today: dt.date, text: dict | None,
                   open_ids: set[str]) -> dict:
    qid, kind = row["id"], row.get("kind")
    win, lose = list(row.get("win") or []), list(row.get("lose") or [])
    in_basket = set(win) | set(lose)
    past = dt.date.fromisoformat(row["d"]) < today
    entry = committed.get(qid)
    status, locked = commit_status(row, text, entry, today)
    if row.get("observe_only"):
        shape = "observe-only (empty by design)"
    elif not win and not lose:
        shape = "EMPTY"
    elif not win or not lose:
        shape = "single-leg (" + ("no win" if not win else "no lose") + ")"
    else:
        shape = "both legs"

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
    rep = reporter_check(mp, row, text)
    return dict(row=row, win=win, lose=lose, past=past, committed=bool(entry), status=status, locked=locked,
                legs=shape, candidates=candidates, untraded=untraded, conflicts=conflicts, kind=kind_check(text),
                public_text=qid in open_ids, valid=(entry or {}).get("valid_preregistration"),
                reporter=rep, both=sorted(set(win) & set(lose)),
                prices=[legs.check(i) for i in win + lose],
                first_order=[] if row.get("observe_only") else mp.first_order(in_basket, rep.get("reporter")))


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


def money(v: float | None) -> str:
    return "--" if v is None else f"US${v:,.0f}"


def adv_cell(p: dict) -> tuple[str, str]:
    a = p["adv"]
    if not a:
        return "--", "--"
    shares = f"{a['shares']:,.0f}" + (f" ({a['zero_days']} zero-volume days)" if a["zero_days"] else "")
    return shares, money(a["value_usd"])


def render(mp: Map, audits: list[dict], today: dt.date, legs: Legs, liq: Liquidity) -> str:
    n = dict(empty=0, single=0, observe=0, mismatch=0, by_hand=0, locked=0, unchanged=0, changed=0, free=0,
             unchecked=0, with_cands=0, rep_fail=0, rep_ok=0, rep_exempt=0, rep_na=0, both=0, fo=0)
    for a in audits:
        k, mm, bh = kind_line(a)
        a["kind_md"] = k
        n["mismatch"] += mm
        n["by_hand"] += bh
        n["empty"] += a["legs"] == "EMPTY"
        n["single"] += a["legs"].startswith("single-leg")
        n["observe"] += a["legs"].startswith("observe-only")
        n[a["status"]] += 1
        n["with_cands"] += bool(a["candidates"])
        st = a["reporter"]["state"]
        n["rep_fail"] += st == "FAIL"
        n["rep_ok"] += st == "ok"
        n["rep_exempt"] += st == "exempt"
        n["rep_na"] += st in ("n/a", "unknown")
        n["both"] += bool(a["both"])
        n["fo"] += bool(a["first_order"])
    flagged: dict[str, dict] = {}
    for a in audits:
        for p in a["prices"]:
            if p["stale"] or p["thin"]:
                flagged.setdefault(p["leg"], dict(p, questions=[]))["questions"].append(a["row"]["id"])

    out = [f"# Basket audit v2 -- {today.isoformat()}", "",
           "Generated by `tools/audit_baskets.py` on the committed tree, after the basket revision of "
           "2026-09-15. It reads and reports, and changes no data file. Four checks per question: (1) the "
           "reporter rule, (2) no station in both win and lose, (3) every leg priced fresh and traded "
           "enough, (4) the first review's candidates, kind check and commitment status.", "",
           f"Prices: `live_en.json` as of {legs.as_of.isoformat()}. A leg is **stale** when its last close is "
           f"more than {FRESH_DAYS} days before the snapshot or the tracking card marks it (more than "
           f"{track.STALE_AFTER} sessions without a close). A leg is **thin** when its three-month average "
           f"daily traded value on EODHD is under US${THIN_USD:,}. A proposed fix is the most liquid listing "
           "EODHD covers: the primary exchange where the plan carries it (Tokyo is not carried -- "
           "`chains/exchanges.py`), else another US line of the same company. German regional lines exist for "
           "several Tokyo names but are not ADR lines and are not proposed."
           + (f" {liq.note}." if liq.note else ""), "",
           "Question wording is quoted only for questions whose text is already free on the site; for the "
           "rest the checks show verdicts, counts and matched keywords.", "",
           "## Summary", "",
           "| | count |", "|---|---|",
           f"| questions | {len(audits)} |",
           f"| (1) reporter rule: reporter in a basket | {n['rep_ok']} |",
           f"| (1) reporter rule: **fails** (about its own numbers, in no basket) | {n['rep_fail']} |",
           f"| (1) reporter rule: exempt (capex/gauge) | {n['rep_exempt']} |",
           f"| (1) reporter rule: does not apply (policy, industry body, not a station) | {n['rep_na']} |",
           f"| (2) a station in both win and lose | {n['both']} |",
           f"| (3) stale or thin legs (distinct stations) | {len(flagged)} |",
           f"| questions with a first-order supplier/customer outside the baskets | {n['fo']} |",
           f"| single-leg baskets | {n['single']} |",
           f"| empty baskets (not observe-only) | {n['empty']} |",
           f"| observe-only (empty by design) | {n['observe']} |",
           f"| probable kind mismatch | {n['mismatch']} |",
           f"| kind needs a look by hand (both keyword kinds) | {n['by_hand']} |",
           f"| locked (committed, date passed) | {n['locked']} |",
           f"| committed, contract unchanged | {n['unchanged']} |",
           f"| committed, contract CHANGED (needs --recommit) | {n['changed']} |",
           f"| committed, not re-hashed (text unavailable) | {n['unchecked']} |",
           f"| free (not committed) | {n['free']} |",
           f"| questions with at least one traded candidate to add | {n['with_cands']} |", ""]

    fails = [a for a in audits if a["reporter"]["state"] == "FAIL"]
    exempt = [a for a in audits if a["reporter"]["state"] == "exempt"]
    out += ["### (1) Reporter rule", ""]
    out += ([f"- **fails:** `{a['row']['id']}` -- {md_escape(a['row']['who'])}: {a['reporter']['why']} "
             f"(own-number words: {', '.join(a['reporter']['words'])})" for a in fails]
            or ["- No question about its reporter's own numbers leaves the reporter out."])
    out += [f"- exempt: `{a['row']['id']}` -- {a['reporter']['why']}" for a in exempt] + [""]
    both = [a for a in audits if a["both"]]
    out += ["### (2) Win and lose", ""]
    out += ([f"- `{a['row']['id']}`: {names(mp, a['both'])} in both baskets" for a in both]
            or ["- No station is in both win and lose on any question."]) + [""]

    single = [a for a in audits if a["legs"].startswith("single-leg")]
    out += ["### Single-leg baskets remaining", ""]
    for a in single:
        k = a["row"].get("kind")
        verdict = "fine for tide" if k == "tide" else "**share question with one side -- check**"
        out.append(f"- `{a['row']['id']}` ({k}, {a['legs']}): {verdict}")
    if not single:
        out.append("- none")
    out.append("")

    n_fo = sum(len(a["first_order"]) for a in audits)
    n_rep = sum(1 for a in audits for f in a["first_order"] if f["to_reporter"])
    out += ["### First-order suppliers and customers still missing", "",
            "A `supplies` edge in the map between a basket company and another station, where that station is "
            "in neither basket. Subnodes and suppliers' suppliers are left out on purpose. "
            f"{n_fo} such edges across {n['fo']} questions; {n_rep} of them end on the reporting company itself "
            "and are listed first.", ""]
    rep_rows = [(a, f) for a in audits for f in a["first_order"] if f["to_reporter"]]
    out += ["#### Direct suppliers and customers of the reporter itself", ""]
    if rep_rows:
        out += ["| question | kind | reporter | missing station | relation | edge carries | criticality | source | as of |",
                "|---|---|---|---|---|---|---|---|---|"]
        for a, f in rep_rows:
            out.append(f"| `{a['row']['id']}` | {a['row'].get('kind')} | {md_escape(mp.name(f['of']))} (`{f['of']}`) | "
                       f"{md_escape(mp.name(f['company']))} (`{f['company']}`) | {f['relation']} of {f['of']} | "
                       f"{md_escape(f['what'][:90])} | {f['criticality']} | {md_escape(f['source'])} | {f['as_of'] or '--'} |")
    else:
        out.append("None.")
    out += ["", "#### Direct suppliers and customers of the other basket companies", ""]
    other_rows = [(a, f) for a in audits for f in a["first_order"] if not f["to_reporter"]]
    if other_rows:
        out += ["| question | kind | basket company | missing station | relation | edge carries | criticality | source | as of |",
                "|---|---|---|---|---|---|---|---|---|"]
        for a, f in sorted(other_rows, key=lambda af: (af[0]["row"]["d"], af[0]["row"]["id"], af[1]["of"],
                                                       af[1]["relation"], af[1]["company"])):
            out.append(f"| `{a['row']['id']}` | {a['row'].get('kind')} | {md_escape(mp.name(f['of']))} (`{f['of']}`) | "
                       f"{md_escape(mp.name(f['company']))} (`{f['company']}`) | {f['relation']} of {f['of']} | "
                       f"{md_escape(f['what'][:90])} | {f['criticality']} | {md_escape(f['source'])} | {f['as_of'] or '--'} |")
    else:
        out.append("None.")
    out.append("")

    out += ["### Stale or thin legs, with the proposed fix", ""]
    if flagged:
        out += ["| leg | symbol | last close | days stale | sessions stale | 3-mo ADV (shares) | 3-mo avg traded value | flag | questions | proposed fix |",
                "|---|---|---|---|---|---|---|---|---|---|"]
        for leg, p in sorted(flagged.items(), key=lambda kv: kv[0]):
            shares, value = adv_cell(p)
            flag = " + ".join(x for x in ("stale" if p["stale"] else "", "thin" if p["thin"] else "") if x)
            out.append(f"| {md_escape(p['name'])} (`{leg}`) | {p['symbol']} | {p['last'] or '--'} | "
                       f"{'--' if p['days'] is None else p['days']} | {'--' if p['sessions'] is None else p['sessions']} | "
                       f"{shares} | {value} | {flag} | {', '.join(f'`{q}`' for q in p['questions'])} | "
                       f"{md_escape(p['fix'] or '')} |")
    else:
        out.append("None.")
    out += ["", "## Questions", ""]

    for a in audits:
        r = a["row"]
        rp = a["reporter"]
        rep_line = {"ok": f"ok -- {mp.name(rp['reporter'])} (`{rp['reporter']}`) {rp['why']}",
                    "FAIL": f"**FAILS** -- {mp.name(rp['reporter'])} (`{rp['reporter']}`) is {rp['why']}",
                    "exempt": f"exempt -- {rp['why']}"}.get(rp["state"], f"does not apply -- {rp['why']}")
        if rp.get("words"):
            rep_line += f" (own-number words in the yes wording: {', '.join(rp['words'])})"
        price_bits = []
        for p in a["prices"]:
            tag = "ok" if not (p["stale"] or p["thin"]) else " + ".join(
                x for x in ("STALE" if p["stale"] else "", "THIN" if p["thin"] else "") if x)
            val = money(p["adv"]["value_usd"]) + "/day" if p["adv"] else "volume n/a"
            price_bits.append(f"`{p['leg']}` {p['symbol']} last {p['last'] or '--'}, {val}: {tag}")
        out += [f"### `{r['id']}` -- {md_escape(r['who'])} ({r['d']})", "",
                f"- **Commitment:** {a['locked']}" + ("" if a["valid"] in (None, True) else
                                                      " -- note: its commitment is marked not a valid preregistration"),
                f"- **Kind:** {a['kind_md']}",
                f"- **Baskets ({a['legs']}):** win {names(mp, a['win'])}; lose {names(mp, a['lose'])}",
                f"- **(1) Reporter rule:** {rep_line}",
                "- **(2) Win and lose:** " + (f"**{names(mp, a['both'])} in both**" if a["both"] else "disjoint"),
                "- **(3) Leg prices:** " + ("; ".join(price_bits) if price_bits else "no legs")]
        if a["first_order"]:
            out.append("- **First-order outside the baskets:** " + "; ".join(
                f"{mp.name(f['company'])} (`{f['company']}`), {f['relation']} of {f['of']}" for f in a["first_order"]))
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
    ap.add_argument("--out", type=Path, default=OUT, help=f"where to write the report (default {OUT})")
    a = ap.parse_args(argv)
    today = dt.date.today()
    rows = json.loads(watch_path().read_text(encoding="utf-8"))
    # The English list carries the same ids and dates with English names; the
    # report is English, and watch.json names some rows in Hebrew.
    who_en = {r["id"]: r.get("who") for r in json.loads(watch_en_path().read_text(encoding="utf-8"))}
    rows = [dict(r, who=who_en.get(r["id"]) or r["who"]) for r in rows]
    committed = {c["qid"]: c for c in json.loads(commitments_path().read_text(encoding="utf-8"))}
    mp = Map(json.loads(map_path().read_text(encoding="utf-8")))
    live = json.loads((out_dir() / "live_en.json").read_text(encoding="utf-8"))
    try:
        texts = questions.fetch()
    except questions.QuestionsError as e:
        print(f"question text unavailable, kind and reporter checks skipped: {e}")
        texts = {}
    open_ids = questions.open_ids(rows, today)
    liq = Liquidity(os.environ.get("EODHD_API_TOKEN", "").strip() or None, dt.date.fromisoformat(live["as_of"]))
    try:
        legs = Legs(mp, live, liq)
        audits = [audit_question(mp, legs, r, committed, today, texts.get(r["id"]), open_ids) for r in rows]
        for au in audits:
            r = au["row"]
            kc = au["kind"]
            bad = [p["leg"] for p in au["prices"] if p["stale"] or p["thin"]]
            print(f"{r['id']:<16} {r['d']}  kind={r.get('kind'):<5} win={r.get('win')} lose={r.get('lose')} "
                  f"reporter={au['reporter']['state']} both={au['both']} flagged_legs={bad} "
                  f"first_order={len(au['first_order'])} status={au['status']} expected={kc.get('expected')}")
            if a.show_text and kc.get("sentence"):
                print(f"    trigger ({kc['field']}): {kc['sentence']}")
        report = render(mp, audits, today, legs, liq)
    finally:
        liq.close()
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
        raise SystemExit(f"refusing to write {a.out}: locked question text would leak ({sorted(set(leaks))[:5]})")
    a.out.write_text(report, encoding="utf-8", newline="\n")
    print(f"\nwrote {a.out}  (no locked question text in it: checked {len(texts)} questions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
