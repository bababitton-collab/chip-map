"""Daily OHLC for every basket leg, from the day its question was signed.

    python chains/scripts/build_daily.py            # fetch what is missing
    python chains/scripts/build_daily.py --dry-run  # say what it would fetch
    python chains/scripts/build_daily.py --all      # every priced station too

WHAT THIS IS FOR
----------------
The price layer built by build_prices.py keeps one number a day: the adjusted
close, which is what every score and every line chart reads. A candle needs the
four raw prices of the session, and the vendor sends them in the same response
-- so this asks for the same bars again over a much shorter window and keeps
what the first pass threw away. One store, one schema; see chains/prices.py.

THE WINDOW IS THE COMMITMENT
----------------------------
A leg is fetched from the earliest ``committed_at`` of any question whose
basket names it -- the day the claim was signed and the first day a reader can
ask what the price did afterwards. Earlier bars are not needed by the record
page and are not requested.

CACHED, SO IT DOES NOT ASK TWICE
--------------------------------
A symbol whose stored window already carries candles up to the last stored
close is skipped entirely. A symbol with candles up to some earlier day is
fetched from the day after them, less an overlap. Only a symbol with no candles
at all in the window costs a full-window request.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chains import mapfile, prices                            # noqa: E402
from chains.paths import (api_token, commitments_path,        # noqa: E402
                          watch_path)
from chains.providers.eodhd import EODHDClient                # noqa: E402

# Re-asked before the newest stored candle, for the same reason the close layer
# does it: a late vendor correction lands on a day already stored.
OVERLAP_DAYS = 5


def legs_by_symbol(doc: dict, watch: list[dict],
                   commitments: list[dict]) -> dict[str, dict]:
    """{symbol: {"since": date, "legs": [(qid, node id), ...]}}.

    ``since`` is the earliest signature date among the questions that name the
    leg. A question with no commitment entry is skipped rather than dated from
    today: the point of the window is the signature, and a leg with no
    signature has nothing for this page to measure from.
    """
    symbol_of = {r["id"]: r["price_symbol"]
                 for coll in ("nodes", "subnodes") for r in doc.get(coll, [])
                 if r.get("price_symbol")}
    signed = {e["qid"]: e.get("committed_at") for e in commitments
              if e.get("committed_at")}
    out: dict[str, dict] = {}
    for w in watch:
        at = signed.get(w.get("id"))
        if not at:
            continue
        day = dt.date.fromisoformat(at[:10])
        for nid in list(w.get("win") or []) + list(w.get("lose") or []):
            sym = symbol_of.get(nid)
            if not sym:
                continue
            row = out.setdefault(sym, {"since": day, "legs": []})
            row["since"] = min(row["since"], day)
            row["legs"].append((w["id"], nid))
    return out


def plan(want: dict[str, dict]) -> list[dict]:
    """What each symbol needs: nothing, a tail, or the whole window."""
    rows = []
    for sym in sorted(want):
        since = want[sym]["since"]
        have = prices.bars(sym, since)
        last_close = prices.last_date(sym)
        newest_candle = have[-1]["date"] if have else None
        if newest_candle and last_close and newest_candle >= last_close:
            todo, frm = "cached", None
        elif newest_candle:
            todo = "tail"
            frm = newest_candle - dt.timedelta(days=OVERLAP_DAYS)
        else:
            todo, frm = "window", since
        rows.append({"symbol": sym, "since": since, "candles": len(have),
                     "newest_candle": newest_candle, "last_close": last_close,
                     "todo": todo, "from": frm,
                     "legs": len(want[sym]["legs"])})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan and ask the vendor for nothing")
    ap.add_argument("--all", action="store_true",
                    help="every priced station, not only basket legs")
    a = ap.parse_args()

    doc = mapfile.load()
    watch = json.loads(watch_path().read_text(encoding="utf-8"))
    commitments = json.loads(commitments_path().read_text(encoding="utf-8"))
    want = legs_by_symbol(doc, watch, commitments)
    if a.all:
        earliest = min((r["since"] for r in want.values()),
                       default=dt.date.today())
        for sym in prices.symbols_in_map(doc):
            want.setdefault(sym, {"since": earliest, "legs": []})
    rows = plan(want)

    need = [r for r in rows if r["todo"] != "cached"]
    print(f"{len(rows)} symbols named by a signed basket "
          f"({sum(r['legs'] for r in rows)} legs)")
    print(f"  cached {len(rows) - len(need)} · to fetch {len(need)}")
    for r in rows:
        print(f"  {r['symbol']:<12} since {r['since']} · candles "
              f"{r['candles']:>5} · newest {r['newest_candle'] or '—'} · "
              f"{r['todo']}")
    if a.dry_run or not need:
        if not need:
            print("nothing to fetch")
        return 0

    token = api_token()
    got = {}
    with EODHDClient(token, rate_per_min=900) as client:
        for r in need:
            sym = r["symbol"]
            try:
                kept, restated = prices.append(
                    sym, client.eod(sym, from_=r["from"].isoformat()))
                if restated:
                    kept = prices.store(sym, client.eod(sym, from_=prices.START))
                got[sym] = len(prices.bars(sym, r["since"]))
            except Exception as exc:                          # noqa: BLE001
                got[sym] = 0
                print(f"  {sym:<12} FAILED {type(exc).__name__}: {exc}"[:110])
    empty = [s for s, n in got.items() if not n]
    print(f"\ncandles now stored for {len(got) - len(empty)}/{len(got)} fetched")
    if empty:
        print("no clean daily series for: " + ", ".join(sorted(empty)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
