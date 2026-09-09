"""The answers Michael marks on the private board, on their way to the public one.

    python -m chains.answers        # check the file and print what is in it

THE GAP THIS BRIDGES
--------------------
The private artifact writes each answer into its own database collection
(``watch``), one document per question id, ``{status, note, updated}``. There is
no route from this laptop to that database: it is the artifact's own storage
and nothing outside the page can read it. So the crossing is a file. The Friday
cloud job exports the collection to ``<root>/chains/answers.json``; the
Saturday local job reads it, and every consumer here reads that file and
nothing else.

A BAD ROW IS DROPPED AND NAMED. IT DOES NOT STOP THE RUN.
---------------------------------------------------------
This is the deliberate choice, and it is the opposite of the one made first.
The two jobs are on opposite sides of a gap: the exporter runs on Friday in the
cloud, the reader runs on Saturday on a laptop, and nobody is watching in
between. A single malformed row failing the whole Saturday chain would mean no
snapshot, no pages and no brief -- everything lost to one bad status string in
one of thirty-nine rows.

So each row is checked on its own. A row that passes is embedded; a row that
does not is dropped and printed with the reason. The run continues with the
rows it can trust. What is NOT tolerated silently: the problems are printed
every time, and ``python -m chains.answers`` exits non-zero, so a broken
exporter is visible rather than merely survivable.

An absent file is not a problem at all. It is the normal state before the first
export, and "no answer is known" is exactly what an empty dict says.

NOTHING HERE INVENTS AN ANSWER
------------------------------
This module only reads and checks. No default status, no inferred answer, no
"probably yes because the leak said so". A question with no row is open, and
open is rendered as open. The forecast board's lean is a count of answers that
already exist; it is not a forecast, and there is no hypothesis under it.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

from chains.paths import answers_path, answers_url, watch_path

# The five the page's own <select> can produce. "open" is a real value, not a
# missing one: it means somebody looked and the question is still open.
STATUSES = frozenset({"yes", "no", "mixed", "none", "open"})

# ``auto`` marks a row a machine wrote rather than a person. It is optional and
# it defaults to false, because every row written before the field existed was
# written by hand. The page renders an auto row differently -- a tag and a
# dashed border -- so a reader can tell a mark that was checked from one that
# was inferred, and any manual edit clears the flag.
FIELDS = frozenset({"status", "note", "updated", "auto"})

MAX_NOTE = 300          # what the page's input caps a note at

# The answers may arrive as a file or as a URL. A share link is a redirect
# chain, so redirects are followed; and it is somebody else's server, so it
# gets a short timeout and no ability to fail the build.
HTTP_TIMEOUT = 10.0


def known_ids() -> set[str]:
    """The question ids an answer is allowed to refer to."""
    return {r["id"] for r in
            json.loads(watch_path().read_text(encoding="utf-8"))}


def _iso(value: str) -> None:
    """Accept a date or a timestamp; the page writes an ISO timestamp."""
    dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def check_row(qid: str, rec: object, ids: set[str]) -> str | None:
    """The reason this row cannot be used, or None if it can.

    The message names the id and the offending value, because the file is
    written by a job running somewhere else and this message is the only
    debugging material that reaches this side.
    """
    if qid not in ids:
        return (f"{qid}: no such question. Either the id is a typo or the "
                f"question was retired from the watch list.")
    if not isinstance(rec, dict):
        return f"{qid}: expected an object, got {type(rec).__name__}"
    extra = sorted(set(rec) - FIELDS)
    if extra:
        return (f"{qid}: unexpected field(s) {extra} -- the exporter's schema "
                f"changed and nothing here knows what they mean")
    status = rec.get("status")
    if status not in STATUSES:
        return f"{qid}: status {status!r} is not one of {sorted(STATUSES)}"
    note = rec.get("note") or ""
    if not isinstance(note, str):
        return f"{qid}: note must be a string, got {type(note).__name__}"
    if len(note) > MAX_NOTE:
        return f"{qid}: note is {len(note)} chars, over {MAX_NOTE}"
    auto = rec.get("auto", False)
    if not isinstance(auto, bool):
        return f"{qid}: auto must be true or false, got {auto!r}"
    updated = rec.get("updated")
    if updated is not None:
        if not isinstance(updated, str):
            return f"{qid}: updated must be an ISO string"
        try:
            _iso(updated)
        except ValueError:
            return f"{qid}: updated {updated!r} is not an ISO date"
    return None


def collect(raw: object, ids: set[str]) -> tuple[dict[str, dict], list[str]]:
    """Split the file into the rows that can be used and the reasons the rest
    cannot. Never raises: a caller mid-pipeline has nothing useful to do with
    an exception except stop, and stopping is what this is here to avoid."""
    if not isinstance(raw, dict):
        return {}, [f"the file must be an object keyed by question id, got "
                    f"{type(raw).__name__} -- no answers read"]
    good: dict[str, dict] = {}
    problems: list[str] = []
    for qid, rec in raw.items():
        why = check_row(qid, rec, ids)
        if why:
            problems.append(why)
            continue
        good[qid] = {"status": rec["status"], "note": rec.get("note") or "",
                     "updated": rec.get("updated"),
                     "auto": bool(rec.get("auto", False))}
    return good, problems


def read_url(url: str, ids: set[str]) -> tuple[dict[str, dict], list[str]]:
    """GET the answers from a URL. Never raises, never fails the build.

    The URL is a share link, which is a redirect chain ending at somebody
    else's file server. Three things follow, and all three are deliberate:
    redirects are followed; the timeout is short; and every failure -- DNS,
    TLS, a 404, a timeout, an HTML "sign in" page where JSON was expected --
    comes back as one logged line and an empty dict.

    The build must not depend on that server being up. Answers colour rows that
    are otherwise rendered open; losing them for a week costs the colour, and
    failing the build over them would cost the map.
    """
    try:
        import httpx
    except ImportError:                                   # pragma: no cover
        return {}, ["httpx is not installed -- cannot fetch ANSWERS_URL"]
    try:
        r = httpx.get(url, timeout=HTTP_TIMEOUT, follow_redirects=True)
        if r.status_code != 200:
            return {}, [f"ANSWERS_URL returned HTTP {r.status_code} "
                        f"-- no answers read"]
        raw = r.json()
    except ValueError:
        # A share link that has lost its permission serves an HTML sign-in
        # page with a 200. That is the common failure and it is not JSON.
        return {}, ["ANSWERS_URL did not return JSON (a share link that is no "
                    "longer public serves HTML with a 200) -- no answers read"]
    except Exception as e:                                # noqa: BLE001
        return {}, [f"ANSWERS_URL unreachable ({type(e).__name__}: "
                    f"{str(e)[:120]}) -- no answers read"]
    return collect(raw, ids)


def read(path: Path | None = None, ids: set[str] | None = None,
         url: str | None = None) -> tuple[dict[str, dict], list[str]]:
    """The answers and the problems, from whichever source is configured.

    A URL wins when one is set, because in CI there is no file: the cloud job
    that marks the answers publishes them, and this build fetches them. The
    file path stays for a local run and for the case where the export is
    dropped next to the build instead of served.

    Neither source being present is not a problem. It is the normal state
    before the first export, and "no answer is known" is what an empty dict
    says.
    """
    ids = known_ids() if ids is None else ids
    url = url if url is not None else answers_url()
    if url:
        return read_url(url, ids)
    p = path or answers_path()
    if not p.exists():
        return {}, []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        # The exporting job wrote something unparseable. Worth shouting about,
        # and still not worth losing the whole build over.
        return {}, [f"{p} is not valid JSON ({e}) -- no answers read"]
    return collect(raw, ids)


def load(path: Path | None = None, ids: set[str] | None = None,
         on_problem=None, url: str | None = None) -> dict[str, dict]:
    """The usable answers. Every dropped row is reported, then skipped."""
    good, problems = read(path, ids, url)
    report = print if on_problem is None else on_problem
    for why in problems:
        report(f"  answers: DROPPED {why}")
    return good


def main() -> int:
    url = answers_url()
    src = url or answers_path()
    if not url and not answers_path().exists():
        print(f"{src}: absent -- no answer is known yet, which is not an error")
        return 0
    good, problems = read()
    print(f"{src}: {len(good)} usable, {len(problems)} dropped")
    by: dict[str, int] = {}
    for rec in good.values():
        by[rec["status"]] = by.get(rec["status"], 0) + 1
    for k in sorted(by):
        print(f"  {k:<6} {by[k]}")
    n_auto = sum(1 for r in good.values() if r["auto"])
    if n_auto:
        print(f"  {n_auto} of them marked auto")
    for why in problems:
        print(f"  DROPPED {why}", file=sys.stderr)
    # Loud by hand, quiet in the pipeline. A broken exporter should fail the
    # command a person runs to check it, even though it must not fail the
    # scheduled build that only consumes it.
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
