"""A tracking payload with one of each answered state, for the eye to check.

Three questions and nothing else: one scored yes, one reported mixed carrying
a note and a read, one still upcoming. Built through the real engine against
the real price store, so what the page renders is a payload the build could
have produced -- a hand-written JSON would prove only that the renderer can
read hand-written JSON.

    python tools/track_fixture.py            # writes the payload
    python tools/track_fixture.py --print    # and shows what it made
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# Run from anywhere: tools/ is not a package and the engine lives beside it.
sys.path.insert(0, str(REPO))
OUT = REPO / "out" / "semi" / "track-fixture.json"

# Real stations, so the price store has them and the members are real rows.
WATCH = [
    {"id": "scored_q", "who": "Scored Example Q3", "tk": "MU",
     "confirmed": True, "win": ["mu", "skhynix"], "lose": ["samsung"],
     "cps": [], "leaks": [], "lane": "hbm", "lbl": "Scored"},
    {"id": "reported_q", "who": "Reported Example Q1", "tk": "ORCL",
     "confirmed": True, "win": ["nvda", "amd"], "lose": [],
     "cps": [], "leaks": [], "lane": "cloud", "lbl": "Reported"},
    {"id": "upcoming_q", "who": "Upcoming Example Q4", "tk": "TSM",
     "confirmed": False, "win": ["tsmc"], "lose": ["intc"],
     "cps": [], "leaks": [], "lane": "logic", "lbl": "Upcoming"},
]

MARKS = {
    "scored_q": {
        "status": "yes", "basis": "yes", "auto": True,
        "note": "auto: confirmed — HBM4 shipments pulled into the quarter, "
                "guidance raised. Reuters call transcript, 2026-08-20",
        "evidence": "Reuters 2026-08-20: \"HBM4 revenue begins this quarter\"; "
                    "full-year guidance raised.",
    },
    "reported_q": {
        "status": "mixed", "basis": "unclear", "auto": True,
        "note": "auto: mixed — FY27 capex guidance held at $90-95B (not "
                "raised), but RPO up $26B QoQ — call transcript, 2026-09-08",
        "evidence": "Benzinga call transcript 2026-09-08: capex \"continue to "
                    "anticipate $90 to $95 billion\"; RPO up $26B.",
        "read": "The money is committed but the timing moved; the packaging "
                "queue is what changed, not the demand.",
    },
}


def build(today: dt.date | None = None) -> dict:
    from chains import forecast, mapfile, track

    doc = mapfile.load()
    today = today or dt.date.today()
    symbols = [n.get("price_symbol") for n in doc["nodes"]
               if n.get("price_symbol")]
    book = forecast.Book(symbols)
    cal = forecast.sessions([s for s in symbols if s.endswith(".US")])
    if len(cal) < 30:
        raise SystemExit("the price store has too little history for a "
                         "fixture; run the build first")

    # Dates that put each card in the state it is meant to demonstrate: the
    # scored one entered weeks ago, the reported one answered recently, the
    # upcoming one still ahead.
    watch = [dict(w) for w in WATCH]
    watch[0]["d"] = cal[-14].isoformat()
    watch[1]["d"] = cal[-4].isoformat()
    watch[2]["d"] = (today + dt.timedelta(days=21)).isoformat()
    marks = {k: dict(v) for k, v in MARKS.items()}
    marks["scored_q"]["updated"] = watch[0]["d"] + "T03:00:00Z"
    marks["reported_q"]["updated"] = watch[1]["d"] + "T03:00:00Z"

    fs = [{"id": "scored_q-f", "qid": "scored_q",
           "marked_at": watch[0]["d"], "status": "yes", "direction": 1,
           "win": watch[0]["win"], "lose": watch[0]["lose"],
           "benchmark": "EW_MAP", "horizons": [5, 10, 20]}]
    ledger = forecast.build(fs, doc, [], cal)
    return track.build(fs, ledger, watch, doc, marks, book, cal, today)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--print", action="store_true")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    data = build()
    p = Path(args.out)
    p.write_text(json.dumps(data, indent=1, ensure_ascii=False),
                 encoding="utf-8")
    print(f"wrote {p}  ({p.stat().st_size:,} bytes)")
    for r in data["forecasts"]:
        print(f"  {r['qid']:<12} state={r['state']:<10} "
              f"status={str(r.get('status')):<6} "
              f"members={len(r.get('members') or [])} "
              f"note={'yes' if r.get('note') else 'no'} "
              f"read={'yes' if r.get('read') else 'no'} "
              f"entry={r.get('entry_date')}")
    s = data["summary"]
    print(f"  summary: {s.get('n_answered')} answered · {s.get('n_scored')} "
          f"scored · {s.get('n_unscored')} no forecast")
    if args.print:
        print(json.dumps(data["forecasts"][1], indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
