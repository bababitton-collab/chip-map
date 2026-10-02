"""The event log's hands: rules, capture, the daily alarm, and the tally.

    python scripts/scan_events.py rules [--write]     rule count and hashes; write new ones
    python scripts/scan_events.py add --bottleneck B --type T --date YYYY-MM-DD \
        --what TEXT --url URL --source-type primary|analyst|media [--dry-run]
    python scripts/scan_events.py amend ID --reason TEXT [--ineligible] [--classify C]
    python scripts/scan_events.py alarm [--dry-run]   price_jump on every priced map node (alarms.jsonl)
    python scripts/scan_events.py mint                minted forecasts and their scores
    python scripts/scan_events.py check               rule hashes; log is append-only vs HEAD

captured_at is always now (UTC): the log is what we knew, when we knew it.
See chains/events.py for the contract.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHIP_MAP_DOMAIN", "semi")

from chains import events as E, mapfile  # noqa: E402
from chains.sessions import Line  # noqa: E402

NOW = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
STAMP = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")


def _committed(path: Path) -> str:
    rel = path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    r = subprocess.run(["git", "show", f"HEAD:{rel}"], capture_output=True, text=True, encoding="utf-8")
    return r.stdout if r.returncode == 0 else ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="scan_events")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("rules")
    p.add_argument("--write", action="store_true")
    p = sub.add_parser("add")
    for k in ("bottleneck", "type", "date", "what", "url", "source-type"):
        p.add_argument(f"--{k}", required=k != "url")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("amend")
    p.add_argument("id")
    p.add_argument("--reason", required=True)
    p.add_argument("--ineligible", action="store_true")
    p.add_argument("--classify", choices=E.CLASSES)
    p = sub.add_parser("alarm")
    p.add_argument("--dry-run", action="store_true")
    sub.add_parser("mint")
    sub.add_parser("check")
    a = ap.parse_args(argv)
    doc = mapfile.load()
    log_path = E.events_path()

    if a.cmd == "rules":
        old = E.load_rules()
        new = E.build_rules(doc, NOW.date().isoformat(), old.get("ew_universe"))
        merged, changed = E.merge_rules(old, new)
        for r in merged["rules"]:
            dm = r["direction_map"]
            print(f"{r['sha256']}  {r['bottleneck_id']:<24} "
                  f"T up {','.join(dm['tightening']['up']) or '-'} / down {','.join(dm['tightening']['down']) or '-'}"
                  f" | R up {','.join(dm['resolving']['up']) or '-'} / down {','.join(dm['resolving']['down']) or '-'}")
        print(f"{len(merged['rules'])} rules; universe {merged['ew_universe']['sha256'][:12]} "
              f"({merged['ew_universe']['n']} symbols)")
        if changed:
            print("REFUSED: committed rules would change: " + ", ".join(changed))
            return 1
        if a.write:
            E.rules_path().write_text(json.dumps(merged, indent=1, ensure_ascii=False) + "\n",
                                      encoding="utf-8", newline="\n")
            print(f"wrote {E.rules_path()}")
        return 0

    if a.cmd == "add":
        ev = E.capture(bottleneck=a.bottleneck, event_type=a.type, event_date=a.date, what=a.what,
                       source_url=a.url, source_type=a.source_type, captured_at=STAMP,
                       doc=doc, rules_doc=E.load_rules())
        print(json.dumps(ev, indent=1, ensure_ascii=False))
        if not a.dry_run:
            E.append(log_path, ev)
        return 0

    if a.cmd == "amend":
        rec = {"amends": a.id, "at": STAMP, "reason": a.reason}
        if a.ineligible:
            rec["eligible"] = False
        if a.classify:
            rec["classification"] = a.classify
        E.append(log_path, rec)
        return 0

    if a.cmd == "alarm":
        got = E.alarms(doc, NOW, E.read_log(), Line)
        for x in got:
            print(f"price_jump {x['node']:<16} {x['symbol']:<12} {x['session']}  {x['move']}  "
                  f"investigate by {x['investigate_by']}")
            if not a.dry_run:
                E.append(E.alarms_path(), x)
        print(f"alarm: {len(got)} new")
        return 0

    if a.cmd == "mint":
        for row in E.display():
            if row["kind"] == "event":
                print(json.dumps(row, ensure_ascii=False))
        return 0

    probs = E.rule_problems(E.load_rules())
    if log_path.exists():
        probs += E.append_only_problems(_committed(log_path), log_path.read_text(encoding="utf-8"))
    print("\n".join(probs) or "events: no problems")
    return 1 if probs else 0


if __name__ == "__main__":
    raise SystemExit(main())
