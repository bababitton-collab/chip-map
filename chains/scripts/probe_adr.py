"""Recover the unpriceable holders through their US depositary receipts.

    python chains/scripts/probe_adr.py            # probe and report
    python chains/scripts/probe_adr.py --write    # also write the candidate map

Writes a CANDIDATE map to <root>/chains/out/semi_chain_v2.1_candidate.json.
Nothing touches the tracked map until the report is accepted; point
CHIP_MAP_PATH at the candidate to try it.

Each entry gains:
    price_symbol       the symbol actually priced, or null
    price_symbol_kind  primary | adr | otc | none
    price_note         set where the line is unsponsored, thin, or renamed

``ticker`` is left alone: it is the primary listing and it is what the page
displays. The price line is a separate fact from the identity.

VERIFICATION IS TWO-SIDED
-------------------------
A candidate is accepted only when a recent bar comes back AND EODHD's own name
for the symbol matches the company. A symbol that prices cleanly but belongs to
another company is the one outcome worse than a gap, because it shows as a line
rather than as a hole.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chains import adr, mapfile                                # noqa: E402
from chains.paths import map_path, out_dir                     # noqa: E402
from chains.paths import api_token                             # noqa: E402
from chains.scripts.probe_coverage import probe_one            # noqa: E402
from chains.providers.eodhd import EODHDClient                   # noqa: E402

# Decided by Michael, 2026-09-08, on the four fields the parser could not read.
PROSE_DECISIONS: dict[str, dict] = {
    "vacuumschmelze": {
        "price_symbol": None, "price_symbol_kind": "none",
        "price_note": "private (Ara Partners); Proterial private (Bain)",
    },
    "mo_si_targets": {
        "price_symbol": None, "price_symbol_kind": "none",
        "price_note": "private (Plansee AT); Tosoh listed in Tokyo only",
    },
    "cz_pullers": {
        "price_symbol": "TPE.XETRA", "price_symbol_kind": "primary",
        "price_note": ("category node, not one company: PVA TePla (TPE.XETRA) "
                       "is the priceable representative and Jinglong "
                       "(300316.SHE) is a second member"),
        "members": ["TPE.XETRA", "300316.SHE"],
    },
    # Judgment, not parsing. Flagged in the report for confirmation.
    "resonac_ncf": {
        "price_symbol": "SHWDY.US", "price_symbol_kind": "adr",
        "price_note": ("Resonac was Showa Denko until 2023 and the US line "
                       "still carries the old name -- a rename, not a wrong "
                       "company. 132 bars in 20 months, thin."),
        "decision": "renamed company, confirm",
    },
    "abf_epoxy": {
        "price_symbol": "MBSHY.US", "price_symbol_kind": "adr",
        "price_note": ("category node listing four Tokyo tickers; Mitsubishi "
                       "Gas Chemical is the priceable representative. Thin: "
                       "59 bars in 20 months."),
        "decision": "category node, representative chosen, confirm",
    },
    "pet_carrier": {
        "price_symbol": "TRYIY.US", "price_symbol_kind": "adr",
        "price_note": ("category node (Toray, Toyobo, Mitsubishi); Toray is "
                       "the priceable representative."),
        "decision": "category node, representative chosen, confirm",
    },
    "tok": {
        "price_symbol": "TOKCF.US", "price_symbol_kind": "otc",
        "price_note": ("VERY thinly traded: 19 bars in 20 months, last print "
                       "2026-08-24. Usable for a rebased line, not for any "
                       "statement about price behaviour."),
        "decision": "thin line, confirm",
    },
    "abf_silica": {
        "price_symbol": None, "price_symbol_kind": "none",
        "price_note": ("Admatechs private (Toyota Tsusho); Denka is Tokyo-only "
                       "-- an OTC line is tried at probe time and this is "
                       "overwritten if one verifies"),
        "try_name": "Denka",
    },
}


def us_symbol_index(client: EODHDClient) -> list[tuple[str, str]]:
    rows = client.symbols("US")
    return [(str(r.get("Code", "")).strip().upper(), str(r.get("Name", "")))
            for r in rows if r.get("Code")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    doc = mapfile.load()
    ents = mapfile.entries(doc)
    blocked = [e for e in ents
               if e.reason and "not in the EODHD" in e.reason]
    print(f"unpriceable by exchange: {len(blocked)}")

    results: dict[str, dict] = {}
    mismatches: list[dict] = []
    renamed: list[dict] = []

    with EODHDClient(api_token(), rate_per_min=900) as client:
        print("fetching the US symbol list (one call)...")
        index = us_symbol_index(client)
        by_code = dict(index)
        df = adr.token_frequency(index)
        print(f"  {len(index):,} US symbols, {len(df):,} distinct name tokens")
        for probe in ("tokyo", "japan", "carrier", "advantest", "lasertec"):
            print(f"     '{probe}' appears in {df.get(probe, 0)} names")
        print()

        for e in blocked:
            decided = PROSE_DECISIONS.get(e.id)
            name = decided.get("try_name") if decided else None
            company = name or e.name

            candidates: list[str] = []
            known = adr.KNOWN_LINES.get(e.id)
            if known:
                candidates.append(known)
            for m in adr.search_us_list(company, index, df, limit=4):
                if m.symbol not in candidates:
                    candidates.append(m.symbol)

            chosen = None
            for sym in candidates:
                vendor = by_code.get(sym.upper())
                if vendor is None:
                    continue
                m = adr.score_candidate(sym, company, vendor, df)
                ok, err, bar = probe_one(client, f"{sym}.US")
                if not ok:
                    continue
                on_your_list = (known is not None and sym == known)
                if not m.confident and not on_your_list:
                    mismatches.append({
                        "id": e.id, "company": company, "symbol": sym,
                        "vendor_name": vendor, "score": round(m.score, 2),
                        "shared_tokens": m.shared,
                        "rare_shared_tokens": m.rare_shared,
                        "verdict": "prices cleanly but the name does not match "
                                   "-- NOT assigned, needs a person",
                    })
                    continue
                if not m.confident:
                    # A symbol Michael supplied by name. It prices, but the
                    # vendor's name does not match by tokens -- usually a
                    # rename (ASMPT was ASM Pacific Technology). Taken, because
                    # it is his decision, and flagged loudly so it stays HIS
                    # decision rather than becoming a silent one.
                    renamed.append({
                        "id": e.id, "company": company, "symbol": sym,
                        "vendor_name": vendor, "score": round(m.score, 2),
                        "verdict": "on your list, priced, name differs -- "
                                   "taken as a rename, please confirm",
                    })
                chosen = {
                    "price_symbol": f"{sym}.US",
                    "price_symbol_kind": "adr",
                    "name_matched": bool(m.confident),
                    "price_note": f"US line for {vendor}; home listing "
                                  f"{e.raw_ticker} is not on EODHD"
                                  + ("" if m.confident else
                                     " -- VENDOR NAME DIFFERS, taken from your"
                                     " list as a rename"),
                    "vendor_name": vendor,
                    "match_score": round(m.score, 2),
                    "last_date": (bar or {}).get("date"),
                }
                break

            if chosen is None and decided:
                chosen = {k: v for k, v in decided.items()
                          if k not in ("try_name",)}
            results[e.id] = chosen or {
                "price_symbol": None, "price_symbol_kind": "none",
                "price_note": f"no verified US line; {e.reason}",
            }

    # -- inherit a line where the map says it is the same company --------
    # Several subnodes ARE a node already matched, seen from a different
    # chokepoint: ajinomoto_ref and ajinomoto_plants both carry 2802.T. That is
    # identity by the map's own primary ticker, not another name guess.
    by_ticker: dict[str, tuple[str, dict]] = {}
    for e in blocked:
        r = results.get(e.id) or {}
        key = e.raw_ticker.strip()
        if r.get("price_symbol") and key and key not in by_ticker:
            by_ticker[key] = (e.id, r)
    inherited = []
    for e in blocked:
        r = results.get(e.id) or {}
        if r.get("price_symbol"):
            continue
        src = by_ticker.get(e.raw_ticker.strip())
        if not src:
            continue
        src_id, src_r = src
        results[e.id] = {
            "price_symbol": src_r["price_symbol"],
            "price_symbol_kind": src_r.get("price_symbol_kind", "adr"),
            "price_note": (f"same company as '{src_id}' -- both carry primary "
                           f"ticker {e.raw_ticker}. " + src_r.get("price_note", "")),
            "vendor_name": src_r.get("vendor_name", ""),
            "inherited_from": src_id,
        }
        inherited.append((e.id, src_id, src_r["price_symbol"]))

    # -- report ----------------------------------------------------------
    recovered = [k for k, v in results.items() if v.get("price_symbol")]
    print("=" * 92)
    print("DEPOSITARY-RECEIPT RECOVERY")
    print("=" * 92)
    for e in blocked:
        r = results[e.id]
        sym = r.get("price_symbol") or "-"
        kind = r.get("price_symbol_kind", "none")
        vn = r.get("vendor_name", "")
        print(f"  {e.id:<22} {e.name[:30]:<32} {sym:<12} {kind:<8} {vn[:30]}")
    print()
    print(f"  recovered: {len(recovered)} of {len(blocked)}")
    if inherited:
        print()
        print("  inherited by primary ticker (same company, another chokepoint):")
        for eid, src, sym in inherited:
            print(f"     {eid:<22} <- {src:<20} {sym}")
    decided = [(k, v) for k, v in results.items() if v.get("decision")]
    if decided:
        print()
        print("=" * 92)
        print("JUDGMENT CALLS -- RECORDED, NOT BURIED. CONFIRM THESE.")
        print("=" * 92)
        for k, v in decided:
            print(f"  {k:<22} {str(v.get('price_symbol')):<12} {v['decision']}")
            print(f"     {v['price_note'][:86]}")

    if renamed:
        print()
        print("=" * 92)
        print("ON YOUR LIST, PRICES, BUT THE VENDOR NAME DIFFERS -- CONFIRM")
        print("=" * 92)
        for m in renamed:
            print(f"  {m['id']:<22} {m['symbol']:<8} map says "
                  f"{m['company'][:24]:<26} vendor says {m['vendor_name'][:34]}")

    if mismatches:
        print()
        print("=" * 92)
        print("PRICED BUT THE NAME DID NOT MATCH -- NOT ASSIGNED")
        print("=" * 92)
        for m in mismatches:
            print(f"  {m['id']:<22} tried {m['symbol']:<8} "
                  f"shared {str(m['shared_tokens'])[:24]:<26} "
                  f"vendor says: {m['vendor_name'][:38]}")

    out = out_dir()
    out.mkdir(parents=True, exist_ok=True)
    (out / "adr_probe.json").write_text(json.dumps(
        {"recovered": results, "name_mismatches": mismatches,
         "on_your_list_name_differs": renamed},
        indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {out / 'adr_probe.json'}")

    if args.write:
        cand = json.loads(Path(map_path()).read_text(encoding="utf-8"))
        cand["version"] = "2.1"
        cand["price_symbols_added"] = str(date.today())
        for coll in ("nodes", "subnodes"):
            for rec in cand.get(coll, []):
                r = results.get(rec.get("id"))
                if r:
                    rec["price_symbol"] = r.get("price_symbol")
                    rec["price_symbol_kind"] = r.get("price_symbol_kind")
                    if r.get("price_note"):
                        rec["price_note"] = r["price_note"]
                    if r.get("members"):
                        rec["price_members"] = r["members"]
        p = out / "semi_chain_v2.1_candidate.json"
        p.write_text(json.dumps(cand, indent=1, ensure_ascii=False),
                     encoding="utf-8")
        print(f"wrote candidate map {p}")
        print("  try it with:  set CHIP_MAP_PATH=" + str(p))
    return 0


if __name__ == "__main__":
    sys.exit(main())
