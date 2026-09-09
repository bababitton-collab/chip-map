"""Null round-trip bad prints across the chains store.

    python chains/scripts/repair_prices.py [--dry-run]

MUST RUN AFTER EVERY PRICE REFRESH. build_prices.py overwrites each symbol's
parquet with what the vendor sent, so a repair applied once is undone the next
time prices are pulled -- the 13 impossible prints found on 2026-09-08 would
have come back the following Saturday and every Saturday after. The repair is a
pipeline step, not an event.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chains import mapfile, prices, repair                    # noqa: E402
from chains.scripts.build_prices import resolve_challenger    # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    doc = mapfile.load()
    syms = sorted({s for s in
                   prices.symbols_in_map(doc)
                   + prices.challenger_symbols(doc, resolve_challenger)
                   if prices.path_for(s).exists()})
    found = repair.scan_all(syms)
    print(f"scanned {len(syms)} series, found {found.height} impossible prints")
    for r in found.iter_rows(named=True):
        print(f"  {r['symbol']:<14} {r['date']}  {r['adj_close']:>14,.4f} "
              f"{r['currency']}")
    n = repair.repair(found, dry_run=args.dry_run)
    if n and not args.dry_run:
        print(f"nulled {n} bars; backup {repair.backup_path()}")
        left = repair.scan_all(syms).height
        print(f"re-scan after repair: {left} remaining")
        if left:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
