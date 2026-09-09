"""Assemble the JSON the page reads: rebased series, ratios, baskets, markers.

    python chains/scripts/build_page_json.py [--start 2019-01-01]

Weekly closes only. Daily stays in the store -- the page is a chart about
multi-year structural shifts and daily resolution would multiply the payload by
five for nothing a reader can see.

The payload keeps its diagnostics: bar counts, densities and coverage flags are
how a drawing decision is audited, and the page drops them client-side. An
earlier version moved them to a sidecar and shrank the file to 292 KB; that was
reverted because the page is built against this shape and a smaller file nobody
reads is worth less than a larger one somebody does.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chains import mapfile, prices, relative                  # noqa: E402
from chains.paths import out_dir                              # noqa: E402
from chains.scripts.build_prices import resolve_challenger    # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default=None)
    args = ap.parse_args()
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end) if args.end else date.today()

    doc = mapfile.load()
    rec = {r["id"]: r for c in ("nodes", "subnodes") for r in doc.get(c, [])}
    marks = relative.markers(doc)

    page: dict = {
        "map_version": doc.get("version"),
        "map_as_of": doc.get("as_of"),
        "window": {"start": str(start), "end": str(end), "frequency": "weekly"},
        "rules": doc.get("display_rules"),
        "chokepoints": [],
        "layers": [],
    }
    too_thin: list[dict] = []
    short_history: list[dict] = []
    lonely_gaps: list[dict] = []

    # -- per chokepoint --------------------------------------------------
    for cp in doc.get("chokepoints", []):
        entry: dict = {"id": cp["id"], "name": cp["name"],
                       "concentration": cp.get("concentration"),
                       "holders": [], "challengers": [], "ratios": [],
                       "markers": marks.get(cp["id"], [])}
        drawable_holders = 0
        for hid in cp.get("node_ids") or []:
            r = rec.get(hid, {"id": hid, "name": hid})
            sym = r.get("price_symbol")
            lab = relative.label_for(r)
            if not sym:
                entry["holders"].append({**lab, "id": hid, "series": None,
                                         "reason": "no price line"})
                continue
            pts, diag = relative.rebase(prices.load(sym), start, end)
            drawn = bool(pts) and diag.get("drawable")
            if drawn:
                drawable_holders += 1
                if diag.get("classification") == "short_history":
                    short_history.append({"chokepoint": cp["id"], "id": hid,
                                          "symbol": sym, **diag})
            else:
                too_thin.append({"chokepoint": cp["id"], "id": hid,
                                 "symbol": sym, **diag})
            entry["holders"].append({
                **lab, "id": hid,
                "series": pts if drawn else None,
                "reason": None if drawn else diag.get("reason"),
                "diagnostics": diag,
            })

        for c in (doc.get("challengers") or {}).get(cp["id"], []):
            sym = resolve_challenger(c)
            if not sym:
                entry["challengers"].append({
                    "name": c.get("name"), "series": None,
                    "reason": "no listed ticker", "stage": c.get("stage")})
                continue
            pts, diag = relative.rebase(prices.load(sym), start, end)
            drawn = bool(pts) and diag.get("drawable")
            if not drawn:
                too_thin.append({"chokepoint": cp["id"],
                                 "id": c.get("name"), "symbol": sym, **diag})
            elif diag.get("classification") == "short_history":
                short_history.append({"chokepoint": cp["id"],
                                      "id": c.get("name"), "symbol": sym, **diag})
            entry["challengers"].append({
                "name": c.get("name"), "symbol": sym, "stage": c.get("stage"),
                "series": pts if drawn else None,
                "reason": None if drawn else diag.get("reason"),
                "diagnostics": diag,
            })
            holder_sym = next(
                (rec[h].get("price_symbol") for h in cp.get("node_ids") or []
                 if rec.get(h, {}).get("price_symbol")), None)
            if holder_sym:
                rp, rd = relative.ratio(prices.load(holder_sym),
                                        prices.load(sym), start, end)
                entry["ratios"].append({
                    "holder_symbol": holder_sym, "challenger_symbol": sym,
                    "challenger": c.get("name"),
                    "series": rp or None,
                    "reason": None if rp else rd.get("reason"),
                })

        # a chokepoint whose ONLY holder cannot be drawn is a different problem
        holders_with_a_line = [h for h in entry["holders"] if h.get("series")]
        if entry["holders"] and not holders_with_a_line:
            lonely_gaps.append({
                "chokepoint": cp["id"], "name": cp["name"],
                "holders": [h["id"] for h in entry["holders"]],
                "why": [h.get("reason") for h in entry["holders"]],
            })
        page["chokepoints"].append(entry)

    # -- per layer baskets -----------------------------------------------
    for layer in doc.get("layers", []):
        syms = [r.get("price_symbol") for r in doc.get("nodes", [])
                if r.get("layer") == layer["id"] and r.get("price_symbol")]
        pts, diag = relative.basket(syms, start, end)
        page["layers"].append({
            "id": layer["id"], "name": layer.get("name"),
            "order": layer.get("order"),
            "series": pts or None,
            "reason": None if pts else diag.get("reason"),
            # a basket labelled "L9 energy" that is in fact three companies
            # says so, and names who was left out and why
            "member_count": diag.get("member_count", 0),
            "excluded": diag.get("excluded", []),
            "diagnostics": diag,
        })

    page["too_thin_to_draw"] = too_thin
    page["short_history"] = short_history
    page["chokepoints_with_no_drawable_holder"] = lonely_gaps

    out = out_dir()
    out.mkdir(parents=True, exist_ok=True)
    p = out / "chain_page.json"
    p.write_text(json.dumps(page, ensure_ascii=False, separators=(",", ":")),
                 encoding="utf-8")
    kb = p.stat().st_size / 1024

    print(f"wrote {p}  ({kb:,.0f} KB)")
    print(f"  chokepoints        : {len(page['chokepoints'])}")
    print(f"  layers             : {len(page['layers'])}")
    print(f"  markers            : {sum(len(v) for v in marks.values())}")
    print(f"  series too thin    : {len(too_thin)}")
    for t in too_thin:
        print(f"     {t['chokepoint']:<5} {str(t['id'])[:26]:<28} "
              f"{t['symbol']:<12} {t['bars']:>5} bars, "
              f"{t['weeks_with_a_bar']}/{t['weeks_in_window']} weeks, "
              f"{t.get('density_since_first_bar', 0):.0%} of its own life")
    short = [t for t in page["short_history"]]
    if short:
        print("")
        print(f"  drawn from a later start (NOT thin -- late listings): {len(short)}")
        for t in short:
            print(f"     {t['chokepoint']:<5} {str(t['id'])[:26]:<28} "
                  f"{t['symbol']:<12} from {t['first_bar']}, "
                  f"{t.get('density_since_first_bar', 0):.0%} of its own life")
    if lonely_gaps:
        print(f"\n  CHOKEPOINTS WITH NO DRAWABLE HOLDER: {len(lonely_gaps)}")
        for g in lonely_gaps:
            print(f"     {g['chokepoint']} {g['name'][:44]}: {g['why']}")
    else:
        print("\n  every chokepoint has at least one drawable holder")
    return 0


if __name__ == "__main__":
    sys.exit(main())
