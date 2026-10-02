"""The whole build, in dependency order.

    python -m chains.build_all [--domain semi] [--skip-prices]

    prices -> repair -> legs -> page -> fundamentals -> preregister -> live
          -> pages -> brief, brief_free

``legs`` is the one step that never stops the run: it prints the basket legs
that have gone more than a few sessions without a close (chains/liquidity.py)
and changes nothing.

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

from chains.paths import marks_path, out_dir, watch_en_path  # noqa: E402

PY = sys.executable


def steps(today: date, skip_prices: bool = False) -> list[tuple[str, list[str]]]:
    o = out_dir()
    ans = str(marks_path())
    out = [
        ("prices", ["chains/scripts/build_prices.py"]),
        ("repair", ["chains/scripts/repair_prices.py"]),
        # The four raw prices of a session, for the legs of every signed
        # basket, from the day each question was signed. Cached: a window
        # already carrying candles costs no request at all.
        ("daily", ["chains/scripts/build_daily.py"]),
        # A report line on the fresh prices: a basket leg gone quiet for more
        # than three sessions. It exits 0 whatever it finds.
        ("legs", ["-m", "chains.liquidity", "--stale"]),
        ("page", ["chains/scripts/build_page_json.py"]),
        ("fundamentals", ["chains/scripts/build_fundamentals.py"]),
        # Before anything is published: a question with no commitment, or
        # whose contract no longer hashes to the committed value, stops here.
        ("preregister", ["-m", "chains.preregister", "--check"]),
        # price_jump alarms (contract v3, chains/events.py) appended to
        # data/<domain>/alarms.jsonl before the snapshot ships them. CI carries
        # the file on the live branch, as it does the lagging history.
        ("alarm", ["scripts/scan_events.py", "alarm"]),
        ("live", ["-m", "chains.live_snapshot"]),
        # Today's lagging set appended to data/<domain>/lagging_history.json:
        # a record for a later forward test, never a score. A map with no
        # bottlenecks writes nothing. CI carries the file on the live branch.
        ("lagging", ["-m", "chains.lagging", "--snapshot"]),
        # Prices for /domains/ owners that are on no map (price-only, not map
        # nodes, no EW universe). Built once, during the root domain.
        ("owners", ["-m", "chains.owner_prices"]),
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
        # No Hebrew letter. Every map now declares languages: ["en"], so
        # publish_site drops brief-he.md with the rest of the Hebrew half
        # and nothing downstream reads one. Building it was work whose only
        # consumer had already been switched off -- and a file in out/ that
        # nothing publishes is a file somebody eventually wires back up by
        # mistake. chains/brief_he.py stays: it still writes a letter on
        # demand, it is simply not part of the build.
    ]
    return [s for s in out if not (skip_prices and s[0] == "prices")]


def outputs(today: date) -> list[str]:
    return ["commitments.json", "live.json", "live_en.json",
            "public-map-en.html", "track.json", "track_public.json",
            "track.html",
            f"brief-{today.isoformat()}.md",
            f"brief-free-{today.isoformat()}.md"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-prices", action="store_true",
                    help="build from the price cache; needs no token")
    ap.add_argument("--domain", default=None,
                    help="which map under data/ to build")
    ap.add_argument("--all-domains", action="store_true",
                    help="build every domain found under data/, in order")
    args = ap.parse_args()
    if args.domain and args.all_domains:
        print("--domain names one map and --all-domains means every map; "
              "pass one or the other.")
        return 2

    from chains import domains as registry
    if args.all_domains:
        todo = registry.discover()
        if not todo:
            print(f"no buildable domain under {registry.root()}: each one is "
                  f"a directory holding {', '.join(registry.REQUIRED)}.")
            return 1
    elif args.domain:
        todo = [registry.require(args.domain)]
    else:
        todo = [None]          # whatever the environment already says

    today = date.today()
    started = time.monotonic()
    for dom in todo:
        if dom:
            # Set for this process and every step it spawns: the steps are
            # separate interpreters and each asks chains.paths which domain
            # it is in. Set per iteration, so a run of several leaves each
            # step reading the one it is actually building.
            os.environ["CHIP_MAP_DOMAIN"] = dom
        rc = _one(today, args.skip_prices, started)
        if rc:
            return rc
    return 0


def _one(today: date, skip_prices: bool, started: float) -> int:
    """One domain, start to finish. The caller has already selected it."""
    from chains.paths import domain
    print(f"\ndomain: {domain()}")
    timings: list[tuple[str, float, int]] = []
    for name, argv in steps(today, skip_prices):
        t = time.monotonic()
        print(f"\n=== {name} " + "=" * (60 - len(name)))
        rc, lines = _run(argv)
        secs = round(time.monotonic() - t, 1)
        timings.append((name, secs, rc))
        if rc != 0:
            print(f"\nSTOPPED at {name} (exit {rc}) after {secs}s. "
                  f"Nothing downstream runs on stale upstream.")
            _explain(name, rc, lines)
            _summary(timings, today, started)
            return 1
    _summary(timings, today, started)
    return 0


TAIL = 60


def _run(argv: list[str]) -> tuple[int, list[str]]:
    """Run one step, streaming its output exactly as before, and keep it.

    Streamed, not captured: in CI the log IS the debugging material. Kept as
    well, so a failure can say what it was without anyone opening the log --
    the Actions log needs a sign-in, the step summary and annotations do not.
    The child writes UTF-8 whatever the console is, so a name with a
    non-ASCII character cannot be the thing that kills a step.
    """
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    p = subprocess.Popen([PY, *argv], cwd=str(REPO), env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    lines: list[str] = []
    for raw in p.stdout:
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        lines.append(line)
        print(line, flush=True)
    return p.wait(), lines


def _first_error(lines: list[str]) -> str:
    """The line that names the failure: an exception's own line, else the
    last thing the step said."""
    said = [x.strip() for x in lines if x.strip()]
    for x in reversed(said):
        head = x.split(":", 1)[0]
        if head.endswith(("Error", "Exception", "Exit", "Interrupt")) and " " not in head:
            return x
    return said[-1] if said else "the step exited with no output"


def _traceback(lines: list[str]) -> list[str]:
    starts = [i for i, x in enumerate(lines) if x.startswith("Traceback (most recent call last)")]
    return lines[starts[-1]:][:200] if starts else []


def _escape(text: str, prop: bool = False) -> str:
    """GitHub workflow-command escaping: %, CR and LF always; : and , in a property."""
    out = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return out.replace(":", "%3A").replace(",", "%2C") if prop else out


def explanation(name: str, rc: int, lines: list[str]) -> tuple[str, str]:
    """(step summary markdown, ::error annotation) for a failed step."""
    from chains.paths import domain
    first = _first_error(lines)
    tail = lines[-TAIL:]
    tb = _traceback(lines)
    md = [f"### build stopped at `{name}` ({domain()}), exit {rc}", "",
          f"**{first}**", "", f"Last {len(tail)} lines:", "", "```", *tail, "```"]
    if tb and tb != tail[-len(tb):]:
        md += ["", "Traceback:", "", "```", *tb, "```"]
    ann = f"::error title={_escape(f'{domain()}: {name}', prop=True)}::{_escape(first)}"
    return "\n".join(md) + "\n", ann


def _explain(name: str, rc: int, lines: list[str]) -> None:
    """Say why, where it can be read without opening the log."""
    md, ann = explanation(name, rc, lines)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(md)
    print(ann, flush=True)


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
