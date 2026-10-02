"""H1 -- does the second ring move after the first ring has reacted? (historical)

    python scripts/h1_backtest.py coverage   # EDGAR events per reporter, no returns
    python scripts/h1_backtest.py run        # only if the coverage gate passed

Pre-registered in hypotheses-and-evaluation-2026-10-01.md, with Amendment 1
(2026-10-02, 07:10 UTC, before any result): event dates come from SEC EDGAR
results filings, and the filing acceptance timestamp is the report timestamp.
Nothing else in the design is changed here:

  reporters   priced semi nodes with >= 1 priced node linked by a "supplies"
              edge (supplier or customer). Mixed-exposure links -- a node that
              is both a supplier and a customer of the reporter -- are dropped.
              "reported" (media-only) and "hurt" links are not supplies edges.
  events      8-K Item 2.02 (US filers); the 6-K that furnishes quarterly
              results (foreign issuers with US listings). One per
              reporter-quarter: the earliest in the calendar quarter.
              2019-01-01 to 2026-06-30.
  session 0   the first session that closes after the acceptance timestamp,
              in the listing's own calendar (its own price dates).
  s           sign(reporter return - EW_MAP return), sessions 0-1
  outcome     s * (EW basket return - EW_MAP return), sessions 2-21, each
              member on its own market's sessions. EW_MAP excludes the
              reporter and the basket.
  placebo     200 random same-size baskets from priced nodes with no edge to
              the reporter, same dates; per-event paired difference =
              linked - mean(placebo). Seed fixed.
  SE          week-clustered: mean per calendar week, then SE across weeks.
  bar         paired difference over 2-21 > 0, week-clustered t >= 3.0,
              effect >= +0.50 pp, positive in 2019-21, 2022-23 and 2024-26.
  diagnostic  horizons 2-6, 2-11, 2-41. Missing price = missing, never zero.

Known weakness, restated: the map's edges are as known in 2026, not at the
time of each event (look-ahead). It biases toward finding an effect.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import random
import re
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from chains import edgar, mapfile, prices  # noqa: E402
from chains.paths import map_path  # noqa: E402

START, END = dt.date(2019, 1, 1), dt.date(2026, 6, 30)
EXPECTED = 30                      # quarters in the window
COVERAGE_MIN = 0.5
REPORTERS_MIN = 20
SEED = 20261002
PLACEBO_N = 200
TEST_H = (2, 21)
DIAG_H = ((2, 6), (2, 11), (2, 41))
SUBPERIODS = (("2019-21", 2019, 2021), ("2022-23", 2022, 2023), ("2024-26", 2024, 2026))
CACHE = REPO / "out" / "h1"
REPORT = REPO / "reports"
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SUB_FILE = "https://data.sec.gov/submissions/{name}"
DOC = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
RESULTS_6K = (
    re.compile(r"\b(first|second|third|fourth)[\s-]+quarter\b|\bQ[1-4]\b|\b[1-4]Q\s?\d{2}\b", re.I),
    re.compile(r"\b(results|earnings|net income|net profit|financial statements)\b", re.I),
)
MONTHLY_6K = re.compile(r"\b(monthly|net revenues? for (january|february|march|april|may|june|july|"
                        r"august|september|october|november|december))\b", re.I)


# ------------------------------------------------------------------ the population
def population(doc: dict) -> dict:
    nodes = {n["id"]: n for n in doc["nodes"]}
    priced = {i for i, n in nodes.items()
              if n.get("price_symbol") and n.get("price_symbol_kind") != "none"
              and prices.load(n["price_symbol"]).height}
    sup = [(e["from"], e["to"]) for e in doc.get("edges", []) if e.get("type") == "supplies"]
    out = {}
    for r in sorted(priced):
        suppliers = {a for a, b in sup if b == r and a in priced and a != r}
        customers = {b for a, b in sup if a == r and b in priced and b != r}
        mixed = suppliers & customers
        basket = sorted((suppliers | customers) - mixed)
        if basket:
            out[r] = {"basket": basket, "mixed": sorted(mixed),
                      "edge_nodes": sorted(suppliers | customers)}
    return out


def us_ticker(n: dict) -> str | None:
    """The listing EDGAR would know: a plain US ticker, else the US price line."""
    t = str(n.get("ticker") or "")
    if t and re.fullmatch(r"[A-Z][A-Z.\-]{0,6}", t) and "." not in t:
        return t
    s = str(n.get("price_symbol") or "")
    return s[:-3] if s.endswith(".US") else None


# ------------------------------------------------------------------ EDGAR
class Sec:
    def __init__(self):
        self.c = edgar._client()

    def get(self, url, kind="json"):
        for attempt in range(4):
            time.sleep(edgar.SLEEP_BETWEEN)
            r = self.c.get(url)
            if r.status_code == 200:
                return r.json() if kind == "json" else r.text
            if r.status_code in (429, 503):
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 404:
                return None
            raise edgar.EdgarError(f"{url}: HTTP {r.status_code}")
        raise edgar.EdgarError(f"{url}: rate-limited after retries")


def filings(sec: Sec, cik: int) -> list[dict]:
    """Every filing in the submissions record, recent and paginated."""
    sub = sec.get(SUBMISSIONS.format(cik=cik))
    if not sub:
        return []
    blocks = [sub["filings"]["recent"]] + [
        sec.get(SUB_FILE.format(name=f["name"])) for f in sub["filings"].get("files", [])]
    out = []
    for b in blocks:
        if not b:
            continue
        for i in range(len(b["accessionNumber"])):
            out.append({k: (b.get(k) or [None] * len(b["accessionNumber"]))[i]
                        for k in ("accessionNumber", "form", "filingDate", "acceptanceDateTime",
                                  "items", "primaryDocument", "primaryDocDescription")})
    return out


def _text(sec: Sec, url: str) -> str:
    return re.sub(r"<[^>]+>", " ", sec.get(url, kind="text") or "")[:20000]


def _results(text: str) -> bool:
    return not MONTHLY_6K.search(text) and all(p.search(text) for p in RESULTS_6K)


def is_results_6k(sec: Sec, cik: int, f: dict) -> bool:
    """The cover document says it, or one of its Exhibit 99 documents does.
    Many issuers furnish the release as EX-99.1 behind a one-page cover."""
    acc = f["accessionNumber"].replace("-", "")
    if _results(_text(sec, DOC.format(cik=cik, acc=acc, doc=f["primaryDocument"]))):
        return True
    idx = sec.get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/index.json")
    items = ((idx or {}).get("directory") or {}).get("item") or []
    ex = [i["name"] for i in items if re.search(r"ex[-_]?99|exhibit99|ex991", i["name"], re.I)
          and i["name"].lower().endswith((".htm", ".html", ".txt"))][:3]
    return any(_results(_text(sec, DOC.format(cik=cik, acc=acc, doc=e))) for e in ex)


def results_events(sec: Sec, cik: int) -> tuple[str, list[dict]]:
    """('8-K' | '6-K' | 'none', events in the window, earliest per quarter)."""
    fs = [f for f in filings(sec, cik)
          if f["filingDate"] and START.isoformat() <= f["filingDate"] <= END.isoformat()]
    k8 = [f for f in fs if f["form"] in ("8-K", "8-K/A") and "2.02" in str(f.get("items") or "")]
    kind, picked = ("8-K", k8) if k8 else ("none", [])
    if not k8:
        k6 = [f for f in fs if f["form"] == "6-K"]
        hits = []
        for f in k6:
            if is_results_6k(sec, cik, f):
                hits.append(f)
        if hits:
            kind, picked = "6-K", hits
    by_q = {}
    for f in sorted(picked, key=lambda f: f["acceptanceDateTime"] or f["filingDate"]):
        d = dt.date.fromisoformat(f["filingDate"])
        by_q.setdefault((d.year, (d.month - 1) // 3), f)
    return kind, [{"accession": f["accessionNumber"], "form": f["form"],
                   "filed": f["filingDate"], "accepted": f["acceptanceDateTime"]}
                  for f in by_q.values()]


def coverage() -> int:
    doc = mapfile.load(map_path("semi"))
    pop = population(doc)
    nodes = {n["id"]: n for n in doc["nodes"]}
    ciks = edgar.ticker_to_cik()
    sec = Sec()
    rows, excluded = [], []
    for r, p in pop.items():
        n = nodes[r]
        t = us_ticker(n)
        cik = ciks.get(t) if t else None
        if not cik:
            excluded.append({"id": r, "name": n["name"], "ticker": n.get("ticker"),
                             "why": "no EDGAR filer for its listing" if t else "no US listing"})
            continue
        kind, ev = results_events(sec, cik)
        if not ev:
            excluded.append({"id": r, "name": n["name"], "ticker": n.get("ticker"), "cik": cik,
                             "why": "EDGAR filer with no results filings (8-K 2.02 / results 6-K) in the window"})
            continue
        rows.append({"id": r, "name": n["name"], "us_ticker": t, "cik": cik, "form": kind,
                     "events": ev, "found": len(ev), "expected": EXPECTED,
                     "coverage": round(len(ev) / EXPECTED, 3), "basket": p["basket"],
                     "mixed_dropped": p["mixed"]})
        print(f"  {r:16} {t:6} {kind:4} {len(ev):3}/{EXPECTED}", flush=True)
    good = [x for x in rows if x["coverage"] >= COVERAGE_MIN]
    out = {"generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "window": [START.isoformat(), END.isoformat()], "expected_per_reporter": EXPECTED,
           "population": len(pop), "with_events": len(rows), "coverage_ge_50pct": len(good),
           "gate": "PASS" if len(good) >= REPORTERS_MIN else "STOP",
           "reporters": rows, "excluded": excluded,
           "below_50pct": [x["id"] for x in rows if x["coverage"] < COVERAGE_MIN]}
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "coverage.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"\npopulation {len(pop)} | with EDGAR results events {len(rows)} | >=50% coverage {len(good)} "
          f"| gate {out['gate']} (needs {REPORTERS_MIN})")
    return 0 if out["gate"] == "PASS" else 2


# ------------------------------------------------------------------ the computation
from bisect import bisect_right  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

UTC = dt.timezone.utc
ET = ZoneInfo("America/New_York")
# Each market's regular close, local time. Tokyo moved from 15:00 to 15:30 on
# 2024-11-05.
CLOSE = {"US": ("America/New_York", (16, 0)), "T": ("Asia/Tokyo", (15, 0)),
         "TW": ("Asia/Taipei", (13, 30)), "TWO": ("Asia/Taipei", (13, 30)),
         "KO": ("Asia/Seoul", (15, 30)), "KQ": ("Asia/Seoul", (15, 30)),
         "XETRA": ("Europe/Berlin", (17, 30)), "SHE": ("Asia/Shanghai", (15, 0)),
         "SHG": ("Asia/Shanghai", (15, 0)), "MI": ("Europe/Rome", (17, 30)),
         "BR": ("Europe/Brussels", (17, 30)), "PA": ("Europe/Paris", (17, 30)),
         "LSE": ("Europe/London", (16, 30)), "AU": ("Australia/Sydney", (16, 0)),
         "TO": ("America/Toronto", (16, 0)), "HK": ("Asia/Hong_Kong", (16, 0))}
WINDOWS = {"0-1": (0, 1), "2-6": (2, 6), "2-11": (2, 11), "2-21": (2, 21), "2-41": (2, 41)}
OUTCOMES = ("2-6", "2-11", "2-21", "2-41")


def close_utc(suffix: str, d: dt.date) -> float:
    tz, (h, m) = CLOSE[suffix]
    if suffix == "T" and d >= dt.date(2024, 11, 5):
        h, m = 15, 30
    return dt.datetime(d.year, d.month, d.day, h, m, tzinfo=ZoneInfo(tz)).timestamp()


class Line:
    """One listing's adjusted closes, each stamped with its own market's close."""

    def __init__(self, symbol: str):
        df = prices.load(symbol)
        rows = [(d, c) for d, c in zip(df["date"].to_list(), df["adj_close"].to_list()) if c]
        suffix = symbol.rsplit(".", 1)[-1]
        self.closes = [c for _, c in rows]
        self.ts = [close_utc(suffix, d) for d, _ in rows]
        self.dates = [d for d, _ in rows]

    def session0(self, ts: float) -> int:
        """Index of the first session that closes strictly after ``ts``."""
        return bisect_right(self.ts, ts)

    def ret(self, ts: float, a: int, b: int) -> float | None:
        """Return over sessions a..b (inclusive) after the event. Missing = None."""
        i0 = self.session0(ts)
        lo, hi = i0 + a - 1, i0 + b
        if lo < 0 or hi >= len(self.closes):
            return None
        return self.closes[hi] / self.closes[lo] - 1


def accepted_utc(ev: dict) -> tuple[float, bool]:
    """EDGAR's acceptanceDateTime is UTC, as its "Z" says. Checked against
    known releases: NVIDIA 2024-02-21 21:22Z = 4:22 pm EST, Intel 2024-01-25
    21:07Z = 4:07 pm EST, Micron 2024-03-20 20:00Z = 4:00 pm EDT.
    Missing: assume after the US close on the filing date, and flag it."""
    raw = ev.get("accepted")
    if raw:
        t = dt.datetime.fromisoformat(raw.replace("Z", "").split(".")[0])
        return t.replace(tzinfo=UTC).timestamp(), False
    d = dt.date.fromisoformat(ev["filed"])
    return dt.datetime(d.year, d.month, d.day, 16, 1, tzinfo=ET).timestamp(), True


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def excl_mean(rets: dict, drop: set) -> float | None:
    return mean(v for k, v in rets.items() if k not in drop)


def clustered(rows: list[dict], key: str) -> dict:
    """Week-clustered: mean per calendar week, then SE across weeks."""
    by: dict[tuple, list] = {}
    for r in rows:
        if r.get(key) is not None:
            by.setdefault(r["week"], []).append(r[key])
    wm = [sum(v) / len(v) for v in by.values()]
    k = len(wm)
    if k < 2:
        return {"weeks": k, "mean": wm[0] if wm else None, "se": None, "t": None}
    m = sum(wm) / k
    se = statistics.stdev(wm) / math.sqrt(k)
    return {"weeks": k, "mean": m, "se": se, "t": (m / se) if se else None}


def summary(rows: list[dict], h: str) -> dict:
    ev = [r for r in rows if r["linked"].get(h) is not None and r["paired"].get(h) is not None]
    flat = [{"week": r["week"], "linked": r["linked"][h], "placebo": r["placebo"][h],
             "paired": r["paired"][h]} for r in ev]
    c = clustered(flat, "paired")
    return {"n_events": len(ev), "n_weeks": c["weeks"],
            "linked_mean": mean(x["linked"] for x in flat),
            "placebo_mean": mean(x["placebo"] for x in flat),
            "paired_mean_events": mean(x["paired"] for x in flat),
            "paired_mean_weeks": c["mean"], "paired_se_weeks": c["se"], "t_week_clustered": c["t"],
            "hit_rate_linked": (sum(1 for x in flat if x["linked"] > 0) / len(flat)) if flat else None}


def run() -> int:
    cov = json.loads((CACHE / "coverage.json").read_text(encoding="utf-8"))
    if cov["gate"] != "PASS":
        print("coverage gate did not pass; nothing is computed")
        return 2
    doc = mapfile.load(map_path("semi"))
    nodes = {n["id"]: n for n in doc["nodes"]}
    pop = population(doc)
    priced = sorted({i for i, n in nodes.items() if n.get("price_symbol")
                     and n.get("price_symbol_kind") != "none" and prices.load(n["price_symbol"]).height})
    lines = {i: Line(nodes[i]["price_symbol"]) for i in priced}
    edged = {}
    for e in doc.get("edges", []):
        edged.setdefault(e["from"], set()).add(e["to"])
        edged.setdefault(e["to"], set()).add(e["from"])
    rng = random.Random(SEED)
    rows, flagged, skipped = [], [], []
    for rep in sorted(cov["reporters"], key=lambda x: x["id"]):
        r = rep["id"]
        basket = pop[r]["basket"]
        pool = sorted(i for i in priced if i != r and i not in edged.get(r, set()))
        for ev in sorted(rep["events"], key=lambda x: x["filed"]):
            ts, flag = accepted_utc(ev)
            if flag:
                flagged.append({"reporter": r, "filed": ev["filed"]})
            rets = {w: {i: lines[i].ret(ts, *ab) for i in priced} for w, ab in WINDOWS.items()}
            rr = rets["0-1"].get(r)
            mm = excl_mean(rets["0-1"], {r, *basket})
            if rr is None or mm is None:
                skipped.append({"reporter": r, "filed": ev["filed"], "why": "no reaction price"})
                continue
            s = (rr - mm > 0) - (rr - mm < 0)
            i0 = lines[r].session0(ts)
            d0 = lines[r].dates[i0] if i0 < len(lines[r].dates) else None
            iso = d0.isocalendar() if d0 else None
            row = {"reporter": r, "filed": ev["filed"], "accepted": ev.get("accepted"),
                   "session0": d0.isoformat() if d0 else None, "year": d0.year if d0 else None,
                   "week": (iso[0], iso[1]) if iso else None, "s": s,
                   "linked": {}, "placebo": {}, "paired": {}}
            draws = [rng.sample(pool, len(basket)) for _ in range(PLACEBO_N)] \
                if len(pool) >= len(basket) else []
            for h in OUTCOMES:
                R = rets[h]
                b = mean(R.get(i) for i in basket)
                m = excl_mean(R, {r, *basket})
                lk = None if b is None or m is None else s * (b - m)
                pl = []
                for d in draws:
                    pb = mean(R.get(i) for i in d)
                    pm = excl_mean(R, {r, *d})
                    if pb is not None and pm is not None:
                        pl.append(s * (pb - pm))
                pmean = mean(pl)
                row["linked"][h] = lk
                row["placebo"][h] = pmean
                row["paired"][h] = None if lk is None or pmean is None else lk - pmean
            rows.append(row)
    result = {"horizons": {h: summary(rows, h) for h in OUTCOMES},
              "subperiods": {name: {h: summary([x for x in rows if x["year"] and lo <= x["year"] <= hi], h)
                                    for h in OUTCOMES} for name, lo, hi in SUBPERIODS}}
    t = result["horizons"]["2-21"]
    sub_pos = {name: (result["subperiods"][name]["2-21"]["paired_mean_weeks"] or 0) > 0
               for name, _, _ in SUBPERIODS}
    checks = {"paired_gt_0": (t["paired_mean_weeks"] or 0) > 0,
              "t_ge_3": (t["t_week_clustered"] or 0) >= 3.0,
              "effect_ge_0.50pp": (t["paired_mean_weeks"] or 0) >= 0.005,
              "positive_all_subperiods": all(sub_pos.values())}
    verdict = "PASS" if all(checks.values()) else "FAIL"
    out = {"generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "seed": SEED, "placebo_n": PLACEBO_N, "verdict": verdict, "checks": checks,
           "subperiod_positive": sub_pos, "n_events": len(rows),
           "n_weeks_2_21": t["n_weeks"], "result": result,
           "flagged_missing_timestamp": flagged, "skipped_events": skipped,
           "coverage": [{k: x[k] for k in ("id", "us_ticker", "form", "found", "expected", "coverage")}
                        for x in cov["reporters"]],
           "excluded": cov["excluded"], "events": rows}
    REPORT.mkdir(exist_ok=True)
    (REPORT / "h1_backtest_2026-10.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    write_report(out, cov)
    print(verdict_line(out))
    return 0


def pct(x):
    return "n/a" if x is None else f"{x * 100:+.2f}%"


def verdict_line(out) -> str:
    t = out["result"]["horizons"]["2-21"]
    tv = "n/a" if t["t_week_clustered"] is None else f"{t['t_week_clustered']:.2f}"
    return (f"H1 (sessions 2-21): {out['verdict']} -- paired difference {pct(t['paired_mean_weeks'])} "
            f"(week-clustered t = {tv}, {t['n_events']} events, {t['n_weeks']} weeks); "
            f"bar: > 0, t >= 3.0, >= +0.50 pp, positive in 2019-21, 2022-23, 2024-26 "
            f"({', '.join(f'{k} {pct(out['result']['subperiods'][k]['2-21']['paired_mean_weeks'])}' for k in out['subperiod_positive'])})")


def write_report(out, cov) -> None:
    L = ["# H1 historical test -- second-ring lag after reports", "",
         f"Generated {out['generated']}. Seed {out['seed']}, {out['placebo_n']} placebo baskets per event.",
         "Pre-registered in hypotheses-and-evaluation-2026-10-01.md; event source per Amendment 1 "
         "(SEC EDGAR results filings, acceptance timestamp). Numbers only.", "",
         "## Verdict", "", verdict_line(out), "",
         "Checks: " + ", ".join(f"{k} {'yes' if v else 'no'}" for k, v in out["checks"].items()), "",
         "## Sample", "",
         f"- Events: {out['n_events']} (one per reporter-quarter, 2019-01-01 to 2026-06-30)",
         f"- Independent weeks (2-21): {out['n_weeks_2_21']}",
         f"- Events with a missing acceptance timestamp (assumed after the US close): "
         f"{len(out['flagged_missing_timestamp'])}",
         f"- Events skipped for a missing reaction price: {len(out['skipped_events'])}", "",
         "## Per horizon (2-21 is the test; 2-6, 2-11, 2-41 are diagnostics)", "",
         "| horizon | events | weeks | linked mean | placebo mean | paired (week mean) | t (week-clustered) | hit rate |",
         "|---|---|---|---|---|---|---|---|"]
    def line(h, s):
        tv = "n/a" if s["t_week_clustered"] is None else f"{s['t_week_clustered']:.2f}"
        hr = "n/a" if s["hit_rate_linked"] is None else f"{s['hit_rate_linked'] * 100:.1f}%"
        return (f"| {h} | {s['n_events']} | {s['n_weeks']} | {pct(s['linked_mean'])} | {pct(s['placebo_mean'])} "
                f"| {pct(s['paired_mean_weeks'])} | {tv} | {hr} |")
    for h in OUTCOMES:
        L.append(line(h, out["result"]["horizons"][h]))
    for name, _, _ in SUBPERIODS:
        L += ["", f"### {name}", "",
              "| horizon | events | weeks | linked mean | placebo mean | paired (week mean) | t (week-clustered) | hit rate |",
              "|---|---|---|---|---|---|---|---|"]
        for h in OUTCOMES:
            L.append(line(h, out["result"]["subperiods"][name][h]))
    L += ["", "## Coverage (EDGAR results filings found per reporter; 30 expected)", "",
          "| reporter | US ticker | form | found | coverage |", "|---|---|---|---|---|"]
    for x in sorted(out["coverage"], key=lambda x: -x["coverage"]):
        L.append(f"| {x['id']} | {x['us_ticker']} | {x['form']} | {x['found']}/{x['expected']} | {x['coverage'] * 100:.0f}% |")
    L += ["", "Below 50% coverage: " + (", ".join(cov["below_50pct"]) or "none"), "",
          "## Excluded reporters (Amendment 1: no EDGAR results filings)", ""]
    L += [f"- {x['name']} ({x.get('ticker')}): {x['why']}" for x in out["excluded"]]
    L += ["", "## Declared weaknesses (restated from the pre-flight)", "",
          "- Edge look-ahead: the map's edges are as known in 2026, not as they were at the time of each event. "
          "This biases toward finding an effect.",
          "- Survivorship: only currently listed nodes are included.",
          "- Event-date and time-zone mapping: EDGAR acceptance time is read as UTC (checked against three "
          "known releases); "
          "a results 6-K is identified by keywords in its cover or Exhibit 99 documents.",
          "- Earnings seasons cluster events, so there are few independent weeks.",
          "- Horizons examined: 2-6, 2-11, 2-21, 2-41 (four); only 2-21 is the test."]
    (REPORT / "h1_backtest_2026-10.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "coverage":
        raise SystemExit(coverage())
    if cmd == "run":
        raise SystemExit(run())
    print(__doc__)
    raise SystemExit(1)
