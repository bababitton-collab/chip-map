"""Coverage probe: which of the map's companies can this subscription price?

    python chains/scripts/probe_coverage.py

READ ONLY. One request per symbol, a single recent bar -- no history is
downloaded and nothing is written to the price store. The rate limiter is the
vendored one in chains/providers.

This is a development probe, not part of the weekly build. See
chains/mapfile.py and tests/test_isolation.py.

WHY THE EXCHANGE LIST IS CHECKED FIRST
--------------------------------------
``GET /api/exchanges-list/`` returned 70 exchanges on 2026-09-08 and Tokyo,
Hong Kong, Singapore and Milan are not among them. Symbols listed only there
are reported as unavailable BY SUBSCRIPTION rather than probed one by one --
but the probe still runs for everything else, because an exchange being on the
list does not mean every symbol on it resolves.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chains import mapfile, paths                             # noqa: E402
from chains.paths import out_dir                              # noqa: E402
from chains.providers.eodhd import EODHDClient, EODHDError      # noqa: E402

# The five names asked for, in the EODHD form rather than the Yahoo form, plus
# controls. Without the controls a 403 is unreadable: it could mean "non-US
# fundamentals are not covered" or "fundamentals are not on this plan at all",
# and those call for completely different decisions.
FUNDAMENTALS_PROBE = [
    ("4063.TSE", "Shin-Etsu Chemical (Tokyo, not on plan)"),
    ("2802.TSE", "Ajinomoto (Tokyo, not on plan)"),
    ("6857.TSE", "Advantest (Tokyo, not on plan)"),
    ("042700.KO", "Hanmi Semiconductor (Korea, ON plan)"),
    ("0522.HK", "ASMPT (Hong Kong, not on plan)"),
    # controls, on exchanges the price probe proved are covered
    ("ASML.AS", "CONTROL: ASML on Euronext Amsterdam"),
    ("2330.TW", "CONTROL: TSMC on Taiwan"),
    ("AMAT.US", "CONTROL: Applied Materials, a US filer"),
]

# Where the map's suffix and the real listing disagree. Reported when used.
ALTERNATE_SUFFIX = {"TW": ["TWO"], "TWO": ["TW"], "KO": ["KQ"], "KQ": ["KO"]}


def api_key() -> str:
    """Kept as a name other modules import; the token now comes from one place.

    It used to fall back to reading a value out of a sibling project's .env.
    That fallback is exactly the laptop dependency this repository removes, so
    it is gone: the environment, or nothing.
    """
    return paths.api_token()


PROBE_WINDOW_DAYS = 365      # not 14: a thin OTC line can go a month unprinted


def probe_one(client: EODHDClient, ticker: str) -> tuple[bool, str | None, dict | None]:
    """One recent bar, over a window wide enough for a thinly traded line.

    The window was 14 days and that silently deleted real lines: TOKCF is Tokyo
    Ohka Kogyo, an exact name match, with 19 bars in 20 months. A window sized
    for a liquid name reports every illiquid one as non-existent -- and the
    illiquid ones are the whole population this is looking for.
    """
    frm = (date.today() - timedelta(days=PROBE_WINDOW_DAYS)).isoformat()
    try:
        rows = client.eod(ticker, from_=frm)
    except EODHDError as exc:
        return False, str(exc)[:120], None
    except Exception as exc:                              # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"[:120], None
    if not rows:
        return False, "empty response (symbol unknown or no bar in a year)", None
    bar = dict(rows[-1])
    bar["_bars_in_window"] = len(rows)
    return True, None, bar


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    doc = mapfile.load()
    ents = mapfile.entries(doc)
    chal = mapfile.challengers(doc)
    print(f"map: {doc.get('chain')} v{doc.get('version')} as_of {doc.get('as_of')}")
    print(f"nodes {len(doc.get('nodes', []))} | subnodes {len(doc.get('subnodes', []))}"
          f" | chokepoints {len(doc.get('chokepoints', []))}"
          f" | challenger entries {len(chal)}")

    todo = [e for e in ents if e.ticker]
    if args.limit:
        todo = todo[: args.limit]
    print(f"\nprobing {len(todo)} resolvable tickers, one request each\n")

    results: dict[str, dict] = {}
    with EODHDClient(api_key(), rate_per_min=900) as client:
        for i, e in enumerate(todo, 1):
            ok, err, bar = probe_one(client, e.ticker)
            used = e.ticker
            if not ok:
                # the map writes 6488.TW where the listing is 6488.TWO; try the
                # sibling exchange before calling it unfetchable, and say so
                base, _, suf = e.ticker.rpartition(".")
                for alt in ALTERNATE_SUFFIX.get(suf, []):
                    ok2, err2, bar2 = probe_one(client, f"{base}.{alt}")
                    if ok2:
                        ok, err, bar, used = True, None, bar2, f"{base}.{alt}"
                        break
            results[e.id] = {"ticker": used, "ok": ok, "error": err,
                             "resolved_via_alternate": used != e.ticker,
                             "last_date": (bar or {}).get("date"),
                             "close": (bar or {}).get("close")}
            if i % 25 == 0:
                print(f"   {i}/{len(todo)}")

        print("\n" + "=" * 96)
        print("FUNDAMENTALS PROBE -- five non-US names, one call each")
        print("=" * 96)
        fund: dict[str, dict] = {}
        for tick, name in FUNDAMENTALS_PROBE:
            try:
                raw = client._get(f"/fundamentals/{tick}", {})
                has_rev = bool(
                    ((raw or {}).get("Financials") or {}).get("Income_Statement")
                )
                fund[tick] = {"name": name, "ok": True,
                              "has_income_statement": has_rev,
                              "keys": sorted(list(raw or {}))[:8]}
                print(f"  {tick:<12} {name:<24} OK   income statement: {has_rev}")
            except Exception as exc:                       # noqa: BLE001
                msg = f"{type(exc).__name__}: {exc}"[:110]
                fund[tick] = {"name": name, "ok": False, "error": msg}
                print(f"  {tick:<12} {name:<24} FAIL {msg}")

    # -- the table -------------------------------------------------------
    print("\n" + "=" * 96)
    print("COVERAGE: ticker | exchange | fetchable | reason")
    print("=" * 96)
    rows = []
    for e in ents:
        r = results.get(e.id)
        if e.ticker and r:
            note = r["error"] or ("via alternate suffix"
                                  if r.get("resolved_via_alternate") else "")
            rows.append((e.kind, e.id, e.name, e.raw_ticker, e.exchange,
                         r["ticker"], r["ok"], note))
        else:
            rows.append((e.kind, e.id, e.name, e.raw_ticker, e.exchange,
                         "", False, e.reason or "not probed"))
    for kind, eid, name, raw, exch, tick, ok, why in sorted(rows, key=lambda r: (not r[6], r[0], r[1])):
        flag = "yes" if ok else "NO "
        print(f"  {eid[:22]:<23} {str(raw)[:16]:<17} {str(exch)[:18]:<19} "
              f"{tick[:14]:<15} {flag}  {why[:44]}")

    fetchable = sum(1 for r in rows if r[6])
    print("\n" + "=" * 96)
    print("COUNTS")
    print("=" * 96)
    print(f"  node+subnode entries      : {len(rows)}")
    print(f"  fetchable                 : {fetchable}")
    print(f"  not fetchable             : {len(rows) - fetchable}")
    print()
    for why, n in Counter(r[7] for r in rows if not r[6]).most_common():
        print(f"    {n:>4}  {why[:80]}")

    # -- what the map loses ----------------------------------------------
    priced = {r[1] for r in rows if r[6]}
    print("\n" + "=" * 96)
    print("WHAT EACH CHOKEPOINT LOSES")
    print("=" * 96)
    chal_by_cp: dict[str, list] = {}
    for c in chal:
        for cp in c.chokepoint_ids:
            chal_by_cp.setdefault(cp, []).append(c)
    lost_holder, lost_chal = [], []
    for cp in doc.get("chokepoints", []):
        cid, hold = cp["id"], list(cp.get("node_ids") or [])
        have = [h for h in hold if h in priced]
        miss = [h for h in hold if h not in priced]
        cs = chal_by_cp.get(cid, [])
        cs_tick = [c for c in cs if c.ticker]
        cs_priced = [c for c in cs_tick if c.id in priced or True]
        mark = "OK " if not miss else "GAP"
        print(f"  {mark} {cid:<5} {cp['name'][:38]:<39} "
              f"holders {len(have)}/{len(hold)}   "
              f"challengers with a ticker {len(cs_tick)}/{len(cs)}")
        if miss:
            lost_holder.append((cid, cp["name"], miss))
        if cs and not cs_tick:
            lost_chal.append((cid, cp["name"], len(cs)))
    print()
    print(f"  chokepoints missing at least one HOLDER   : {len(lost_holder)} of "
          f"{len(doc.get('chokepoints', []))}")
    for cid, nm, miss in lost_holder:
        print(f"     {cid:<5} {nm[:44]:<45} missing: {', '.join(miss)}")
    print(f"  chokepoints whose challengers are ALL unpriceable: {len(lost_chal)}")
    for cid, nm, n in lost_chal:
        print(f"     {cid:<5} {nm[:44]:<45} {n} challenger(s), none with a ticker")

    out = out_dir()
    out.mkdir(parents=True, exist_ok=True)
    path = out / "coverage_probe.json"
    path.write_text(json.dumps({
        "map": {"chain": doc.get("chain"), "version": doc.get("version"),
                "as_of": doc.get("as_of")},
        "counts": {"entries": len(rows), "fetchable": fetchable,
                   "not_fetchable": len(rows) - fetchable},
        "per_entry": [
            {"kind": k, "id": i, "name": n, "raw_ticker": rw, "exchange": ex,
             "eodhd_ticker": t, "fetchable": ok, "reason": why}
            for k, i, n, rw, ex, t, ok, why in rows
        ],
        "fundamentals_probe": fund,
        "chokepoints_missing_a_holder": [
            {"id": c, "name": n, "missing": m} for c, n, m in lost_holder
        ],
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
