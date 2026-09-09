"""The whole build, in dependency order.

    python -m chains.build_all [--domain semi] [--skip-prices]

    prices -> repair -> page -> fundamentals -> live -> pages
          -> brief, brief_free -> brief_he, brief_he_free

NOTHING DOWNSTREAM RUNS ON STALE UPSTREAM
-----------------------------------------
Each step reads what the one before it wrote, so a failure stops the run rather
than letting the next step rebuild from last week's inputs and produce a
live.json that looks current and is not. Every step failing the run is the
point: a green build that quietly served a fortnight-old snapshot would be
worse than a red one.

REPAIR IS A STEP, NOT AN EVENT
------------------------------
The price step overwrites parquets with what the vendor sends, so a round-trip
repair applied once is undone by the next refresh. Proved on 2026-09-08: after
a fresh fetch the detector found the same 13 impossible prints again. Without
this step the chart breaks every week for a reason that was already fixed.

ONE DOMAIN PER RUN
------------------
``--domain`` selects which map under data/ is built, and every path the run
touches is namespaced by it -- except the price store, which is shared, because
two maps naming the same company should not download it twice. Building a
second map is running this again with a different name.

WHAT NEEDS THE TOKEN
--------------------
Only the first step. ``--skip-prices`` runs everything else against whatever is
already in the cache, which is what a local run does when it only wants to see
a page change.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from chains.paths import marks_path, out_dir, watch_en_path, watch_path  # noqa: E402

PY = sys.executable


def steps(today: date, skip_prices: bool = False) -> list[tuple[str, list[str]]]:
    o = out_dir()
    ans = str(marks_path())
    out = [
        ("prices", ["chains/scripts/build_prices.py"]),
        ("repair", ["chains/scripts/repair_prices.py"]),
        ("page", ["chains/scripts/build_page_json.py"]),
        ("fundamentals", ["chains/scripts/build_fundamentals.py"]),
        ("live", ["-m", "chains.live_snapshot"]),
        ("pages", ["-m", "chains.build_pages"]),
        # The forward test reads live_en.json, so it follows the snapshot.
        ("track", ["-m", "chains.track"]),
        ("brief", ["-m", "chains.brief", str(o / "live_en.json"),
                   str(watch_en_path()), ans,
                   str(o / f"brief-{today.isoformat()}.md")]),
        ("brief_free", ["-m", "chains.brief", str(o / "live_en.json"),
                        str(watch_en_path()), ans,
                        str(o / f"brief-free-{today.isoformat()}.md"),
                        "--free"]),
        ("brief_he", ["-m", "chains.brief_he", str(o / "live.json"),
                      str(watch_path()), ans,
                      str(o / f"brief-he-{today.isoformat()}.md")]),
        ("brief_he_free", ["-m", "chains.brief_he", str(o / "live.json"),
                           str(watch_path()), ans,
                           str(o / f"brief-he-free-{today.isoformat()}.md"),
                           "--free"]),
    ]
    return [s for s in out if not (skip_prices and s[0] == "prices")]


def outputs(today: date) -> list[str]:
    return ["live.json", "live_en.json", "public-map.html",
            "public-map-en.html", "track.json", "track.html",
            f"brief-{today.isoformat()}.md",
            f"brief-free-{today.isoformat()}.md",
            f"brief-he-{today.isoformat()}.md",
            f"brief-he-free-{today.isoformat()}.md"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-prices", action="store_true",
                    help="build from the price cache; needs no token")
    ap.add_argument("--domain", default=None,
                    help="which map under data/ to build (default: semi)")
    args = ap.parse_args()
    if args.domain:
        # Set for this process and every step it spawns: the steps are separate
        # interpreters and each one asks chains.paths which domain it is in.
        os.environ["CHIP_MAP_DOMAIN"] = args.domain

    today = date.today()
    from chains.paths import domain
    print(f"domain: {domain()}")
    started = time.monotonic()
    timings: list[tuple[str, float, int]] = []

    for name, argv in steps(today, args.skip_prices):
        t = time.monotonic()
        print(f"\n=== {name} " + "=" * (60 - len(name)))
        # Streamed, not captured. In CI the log IS the debugging material, and
        # a captured tail throws away the line that explains the failure.
        r = subprocess.run([PY, *argv], cwd=str(REPO))
        secs = round(time.monotonic() - t, 1)
        timings.append((name, secs, r.returncode))
        if r.returncode != 0:
            print(f"\nSTOPPED at {name} (exit {r.returncode}) after {secs}s. "
                  f"Nothing downstream runs on stale upstream.")
            _summary(timings, today, started)
            return 1

    _summary(timings, today, started)
    return 0


def _summary(timings, today, started) -> None:
    print("\n=== timings " + "=" * 55)
    for name, secs, rc in timings:
        print(f"  {name:<14} {secs:>7.1f}s  rc={rc}")
    print(f"  {'TOTAL':<14} {time.monotonic() - started:>7.1f}s")
    print("\n=== outputs " + "=" * 55)
    for name in outputs(today):
        p = out_dir() / name
        n = p.stat().st_size if p.exists() else None
        print(f"  {name:<26} {'MISSING' if n is None else f'{n:>9,} bytes'}")


if __name__ == "__main__":
    raise SystemExit(main())
