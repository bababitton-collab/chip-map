"""The answers Michael marks on the private board, on their way to the public one.

    python -m chains.answers        # check the file and print what is in it

TWO THINGS CROSS, NOT ONE
-------------------------
The payload carries ``answers`` -- what was marked -- and ``forecasts``, the
record of each mark being turned into a dated, directional claim. They are
validated separately and neither can fail the build.

A forecast is only a forecast if its baskets were fixed BEFORE the event. They
are: they live in data/watch.json, in git, with a commit date. So the incoming
row's baskets are not used to score anything -- they are compared against the
registered ones, and a row whose baskets have drifted is dropped and named. A
forward test whose hypothesis can be edited after the fact is a backtest
wearing a disguise, and this is the check that stops that happening quietly.

WHERE THE MARKS LIVE
--------------------
In git: ``data/<domain>/marks.json``, committed to main by a cloud task through
the contents API. A mark is a claim with a date on it, and in git it has a
commit hash, a diff and an author instead of a row in somebody's spreadsheet.
The forecast ledger's whole argument is that the baskets were registered before
the event; the marks that score them belong under the same discipline.

``ANSWERS_URL`` still works and is now a SECOND source, merged on top of the
file rather than replacing it -- and the file wins every conflict. That order
is the point: the repository is the record, and a link that is serving stale or
edited content cannot quietly overwrite what was committed. An unset
``ANSWERS_URL`` is silent and normal.

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

from chains.paths import (answers_path, answers_url, marks_path,
                          watch_path)

# The five the page's own <select> can produce. "open" is a real value, not a
# missing one: it means somebody looked and the question is still open.
STATUSES = frozenset({"yes", "no", "mixed", "none", "open"})

# ``auto`` marks a row a machine wrote rather than a person. It is optional and
# it defaults to false, because every row written before the field existed was
# written by hand. The page renders an auto row differently -- a tag and a
# dashed border -- so a reader can tell a mark that was checked from one that
# was inferred, and any manual edit clears the flag.
# ``basis`` records which of the two sentences the call actually matched --
# the card says what yes and no sound like, and a mark is worth more when it
# says which one it heard. ``evidence`` is the one line that justifies it.
# Both optional: every record written before they existed is still valid.
BASES = frozenset({"yes", "no", "unclear"})
MAX_EVIDENCE = 400

FIELDS = frozenset({"status", "note", "updated", "auto", "basis", "evidence"})

MAX_NOTE = 300          # what the page's input caps a note at

# A forecast is made only where the answer points somewhere. "mixed" and "none"
# are real answers and they are not directions: a question that was answered
# ambiguously, or not disclosed, supports no claim about which basket should
# outrun which. Rows carrying them are skipped, not failed.
DIRECTIONAL = frozenset({"yes", "no"})

FORECAST_FIELDS = frozenset({"id", "qid", "marked_at", "status", "direction",
                             "win", "lose", "benchmark", "horizons"})

# +1: the win basket is expected to outrun the lose basket. -1: reversed.
DIRECTIONS = {1: 1, -1: -1, "long": 1, "short": -1}

BENCHMARK = "EW_MAP"
HORIZONS = (5, 10, 20)

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
    basis = rec.get("basis")
    if basis is not None and basis not in BASES:
        return f"{qid}: basis {basis!r} is not one of {sorted(BASES)}"
    ev = rec.get("evidence")
    if ev is not None:
        if not isinstance(ev, str):
            return f"{qid}: evidence must be a string"
        if len(ev) > MAX_EVIDENCE:
            return f"{qid}: evidence is {len(ev)} chars, over {MAX_EVIDENCE}"
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


def registered_baskets() -> dict[str, tuple[list[str], list[str]]]:
    """The win/lose lists as committed in data/watch.json.

    This is the pre-registration. It is in git with a commit date, which is
    what makes a claim scored against it a forward test rather than a story
    told afterwards.
    """
    rows = json.loads(watch_path().read_text(encoding="utf-8"))
    return {r["id"]: (list(r.get("win") or []), list(r.get("lose") or []))
            for r in rows}


def check_forecast(rec: object, ids: set[str],
                   baskets: dict[str, tuple[list, list]]) -> str | None:
    """The reason this forecast cannot be used, or None if it can."""
    if not isinstance(rec, dict):
        return f"expected an object, got {type(rec).__name__}"
    fid = rec.get("id")
    if not isinstance(fid, str) or not fid:
        return "no id"
    extra = sorted(set(rec) - FORECAST_FIELDS)
    if extra:
        return f"{fid}: unexpected field(s) {extra}"
    qid = rec.get("qid")
    if qid not in ids:
        return f"{fid}: qid {qid!r} is not a question in the watch list"
    status = rec.get("status")
    if status not in STATUSES:
        return f"{fid}: status {status!r} is not one of {sorted(STATUSES)}"
    if status not in DIRECTIONAL:
        return (f"{fid}: status {status!r} supports no direction -- "
                f"no forecast is made from it")
    if rec.get("direction") not in DIRECTIONS:
        return (f"{fid}: direction {rec.get('direction')!r} is not one of "
                f"{sorted(DIRECTIONS, key=str)}")
    marked = rec.get("marked_at")
    if not isinstance(marked, str):
        return f"{fid}: marked_at must be an ISO string"
    try:
        _iso(marked)
    except ValueError:
        return f"{fid}: marked_at {marked!r} is not an ISO date"
    for side in ("win", "lose"):
        v = rec.get(side)
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            return f"{fid}: {side} must be a list of ids"
    if rec.get("benchmark") != BENCHMARK:
        return (f"{fid}: benchmark {rec.get('benchmark')!r} is not "
                f"{BENCHMARK!r}; nothing here scores against anything else")
    h = rec.get("horizons")
    if h is not None and list(h) != list(HORIZONS):
        return f"{fid}: horizons {h!r} are not {list(HORIZONS)}"
    reg_win, reg_lose = baskets.get(qid, ([], []))
    if (list(rec["win"]), list(rec["lose"])) != (reg_win, reg_lose):
        return (f"{fid}: baskets do not match the ones registered for {qid} "
                f"in the watch list. Registered win={reg_win} lose={reg_lose}; "
                f"received win={rec['win']} lose={rec['lose']}. A forecast "
                f"whose hypothesis moved after the event is not a forecast.")
    return None


def collect_forecasts(rows: object, ids: set[str] | None = None,
                      baskets: dict | None = None
                      ) -> tuple[list[dict], list[str]]:
    """The usable forecasts and the reasons the rest were dropped."""
    if rows is None:
        return [], []
    if not isinstance(rows, list):
        return [], [f"forecasts must be a list, got {type(rows).__name__}"]
    ids = known_ids() if ids is None else ids
    baskets = registered_baskets() if baskets is None else baskets
    good: list[dict] = []
    problems: list[str] = []
    seen: set[str] = set()
    for rec in rows:
        why = check_forecast(rec, ids, baskets)
        if why:
            problems.append(why)
            continue
        if rec["id"] in seen:
            problems.append(f"{rec['id']}: duplicate forecast id")
            continue
        seen.add(rec["id"])
        good.append({
            "id": rec["id"], "qid": rec["qid"], "marked_at": rec["marked_at"],
            "status": rec["status"],
            "direction": DIRECTIONS[rec["direction"]],
            # The REGISTERED baskets, not the received ones. They were just
            # proved equal; using the registered copy means the thing scored
            # is the thing in git even if that check is ever loosened.
            "win": list(baskets[rec["qid"]][0]),
            "lose": list(baskets[rec["qid"]][1]),
            "benchmark": BENCHMARK, "horizons": list(HORIZONS),
        })
    good.sort(key=lambda r: (r["marked_at"], r["id"]))
    return good, problems


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
                     "auto": bool(rec.get("auto", False)),
                     "basis": rec.get("basis"),
                     "evidence": (rec.get("evidence") or "").strip()}
    return good, problems


def _fetch(url: str) -> tuple[object, list[str]]:
    """GET the payload from a URL. Never raises, never fails the build.

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
        return None, ["httpx is not installed -- cannot fetch ANSWERS_URL"]
    try:
        r = httpx.get(url, timeout=HTTP_TIMEOUT, follow_redirects=True)
        if r.status_code != 200:
            return None, [f"ANSWERS_URL returned HTTP {r.status_code} "
                          f"-- nothing read"]
        return r.json(), []
    except ValueError:
        # A share link that has lost its permission serves an HTML sign-in
        # page with a 200. That is the common failure and it is not JSON.
        return None, ["ANSWERS_URL did not return JSON (a share link that is "
                      "no longer public serves HTML with a 200) -- "
                      "nothing read"]
    except Exception as e:                                # noqa: BLE001
        return None, [f"ANSWERS_URL unreachable ({type(e).__name__}: "
                      f"{str(e)[:120]}) -- nothing read"]


def _split(raw: object) -> tuple[object, object]:
    """The payload's two halves, in either shape.

    The exporter used to publish a bare mapping of answers. It now publishes
    {"answers": ..., "forecasts": ...}. Both are accepted, because the old
    shape is still what a hand-written file looks like and there is no reason
    to make that an error.
    """
    if isinstance(raw, dict) and ("answers" in raw or "forecasts" in raw):
        return raw.get("answers"), raw.get("forecasts")
    return raw, None


def _read_file(p: Path) -> tuple[object, list[str]]:
    """One JSON file, or a reason it could not be read. Never raises."""
    if not p.exists():
        return None, []
    try:
        return json.loads(p.read_text(encoding="utf-8")), []
    except json.JSONDecodeError as e:
        # A cloud task wrote something unparseable. Worth shouting about, and
        # still not worth losing the whole build over.
        return None, [f"{p} is not valid JSON ({e}) -- nothing read from it"]


def merge_sources(primary: tuple[dict, list], secondary: tuple[dict, list]
                  ) -> tuple[dict[str, dict], list[dict]]:
    """Two (answers, forecasts) pairs, with the primary winning.

    Answers merge per question id. Forecasts merge per forecast id and are
    never re-registered: a forecast already in the file keeps its entry, so a
    URL cannot restate a claim that is already committed. That is the same
    rule the baskets follow, applied to the row that points at them.
    """
    a1, f1 = primary
    a2, f2 = secondary
    answers = {**a2, **a1}
    seen = {f["id"] for f in f1}
    forecasts = list(f1) + [f for f in f2 if f["id"] not in seen]
    forecasts.sort(key=lambda r: (r["marked_at"], r["id"]))
    return answers, forecasts


def read(path: Path | None = None, ids: set[str] | None = None,
         url: str | None = None
         ) -> tuple[dict[str, dict], list[dict], list[str]]:
    """(answers, forecasts, problems), from whichever source is configured.

    A URL wins when one is set, because in CI there is no file: the job that
    marks the answers publishes them, and this build fetches them. The file
    path stays for a local run and for the case where the export is dropped
    next to the build instead of served.

    Neither source being present is not a problem. It is the normal state
    before the first export.
    """
    ids = known_ids() if ids is None else ids
    url = url if url is not None else answers_url()
    problems: list[str] = []

    # The file first, and it is the one that wins.
    raw, why = _read_file(path or marks_path())
    problems += why
    a_raw, f_raw = _split(raw if raw is not None else {})
    answers, p1 = collect(a_raw or {}, ids)
    forecasts, p2 = collect_forecasts(f_raw, ids)
    problems += p1 + p2

    # A local by-hand export, if somebody dropped one next to the build.
    extra, why = _read_file(answers_path())
    problems += why
    if extra is not None:
        b_raw, g_raw = _split(extra)
        b, p3 = collect(b_raw or {}, ids)
        g, p4 = collect_forecasts(g_raw, ids)
        problems += p3 + p4
        answers, forecasts = merge_sources((answers, forecasts), (b, g))

    # Then the URL, merged underneath both.
    if url:
        raw, why = _fetch(url)
        problems += why
        if raw is not None:
            c_raw, h_raw = _split(raw)
            c, p5 = collect(c_raw or {}, ids)
            h, p6 = collect_forecasts(h_raw, ids)
            problems += p5 + p6
            answers, forecasts = merge_sources((answers, forecasts), (c, h))

    return answers, forecasts, problems


def load(path: Path | None = None, ids: set[str] | None = None,
         on_problem=None, url: str | None = None) -> dict[str, dict]:
    """Just the answers. Every dropped row is reported, then skipped."""
    answers, _forecasts, problems = read(path, ids, url)
    report = print if on_problem is None else on_problem
    for why in problems:
        report(f"  answers: DROPPED {why}")
    return answers


def main() -> int:
    sources = [str(marks_path())]
    if answers_path().exists():
        sources.append(str(answers_path()))
    if answers_url():
        sources.append("ANSWERS_URL")
    answers, forecasts, problems = read()
    print(f"{' + '.join(sources)}")
    print(f"  {len(answers)} answers, {len(forecasts)} forecasts, "
          f"{len(problems)} dropped")
    by: dict[str, int] = {}
    for rec in answers.values():
        by[rec["status"]] = by.get(rec["status"], 0) + 1
    for k in sorted(by):
        print(f"  {k:<6} {by[k]}")
    n_auto = sum(1 for r in answers.values() if r["auto"])
    if n_auto:
        print(f"  {n_auto} of them marked auto")
    for f in forecasts:
        print(f"  forecast {f['id']:<18} {f['qid']:<12} {f['status']:<5} "
              f"dir {f['direction']:+d}  marked {f['marked_at'][:10]}")
    for why in problems:
        print(f"  DROPPED {why}", file=sys.stderr)
    # Loud by hand, quiet in the pipeline. A broken exporter should fail the
    # command a person runs to check it, even though it must not fail the
    # scheduled build that only consumes it.
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
