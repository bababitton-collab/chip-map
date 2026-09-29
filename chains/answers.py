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
                             "win", "lose", "benchmark", "horizons", "order"})

# +1: the win basket is expected to outrun the lose basket. -1: reversed.
DIRECTIONS = {1: 1, -1: -1, "long": 1, "short": -1}

BENCHMARK = "EW_MAP"
HORIZONS = (5, 10, 20)

# Order 1 is the registered basket: the claim somebody made by hand. Order 2 is
# its second ring -- the same claim's mechanical consequence, read off the map's
# supply edges. They are never pooled. A direct hit rate and an indirect one
# answer different questions, and averaging them would answer neither.
#
# The indirect ring gets a fourth horizon. A second-order effect arrives
# through somebody else's order book -- a quarter of wafer starts, not a press
# release -- and 20 sessions is short for that. 40 is added, not substituted:
# the first three stay so the two orders can be read side by side at the
# horizons they share.
HORIZONS_R2 = (5, 10, 20, 40)
ORDERS = {1: HORIZONS, 2: HORIZONS_R2}

# The one horizon that is the headline, frozen before the first scored
# forecast and written into every question's pre-registered contract. The
# others are secondary -- read beside it, never a second chance to be right.
# The official N counts questions, never horizons: one event is one
# observation however many sessions it is read at.
PRIMARY_HORIZON = 20
DEFAULT_ORDER = 1
R2_SUFFIX = "-r2"

# The answers may arrive as a file or as a URL. A share link is a redirect
# chain, so redirects are followed; and it is somebody else's server, so it
# gets a short timeout and no ability to fail the build.
HTTP_TIMEOUT = 10.0


class MintError(RuntimeError):
    """A forecast that cannot be registered without misstating the claim.

    Everything else in this module degrades: a bad row is dropped with a
    reason and the build goes on, because a build that stops takes the whole
    site down over one question. This does not degrade. Minting a contract-v2
    question from the wrong basket would put a number on the record under a
    hash that promised a different one, and there is no version of that worth
    shipping.
    """


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


def twin_id(qid: str, marked_at: str) -> str:
    """The indirect forecast's id, derived from the mark it follows.

    Derived rather than random so that creating it twice is impossible: the
    same mark on the same day always names the same row.
    """
    return f"{qid}-{marked_at[:10]}{R2_SUFFIX}"


def registered_ring2() -> dict[str, tuple[list[str], list[str]]]:
    """The second-ring baskets a contract-v2 question registered BY HAND.

    Only v2 questions appear here. For them this is the scored basket, typed
    into watch.json, hashed into the contract and committed before the answer
    date -- a pre-registration in exactly the sense the first ring is, and not
    a derivation of anything.
    """
    from chains import preregister
    out = {}
    for r in json.loads(watch_path().read_text(encoding="utf-8")):
        if preregister.is_v2(r):
            out[r["id"]] = preregister.ring2_of(r)
    return out


def derived_baskets() -> dict[str, tuple[list[str], list[str]]]:
    """The order-2 baskets, from whichever source the question registered.

    TWO KINDS OF SECOND RING, AND THEY ARE NOT THE SAME CLAIM
    ---------------------------------------------------------
    A contract-v1 question has no second ring of its own, so its twin is
    DERIVED: a pure function of watch.json and map.json, both in git with
    commit dates. There is no way to write an indirect basket without first
    committing an edge that produces it. It is also the weaker of the two --
    it says what the map happens to record, not what anybody claimed.

    A contract-v2 question REGISTERED one, by hand, before the answer date,
    and it is hashed into the contract. That basket is the scored claim, so
    it is what the twin is minted from. It is never re-derived and never
    reconciled against the map's edges: the map's edges did not make this
    claim and cannot amend it.

    v2 wins where both could apply. A v2 question whose twin came out of the
    edge derivation would be scored on a basket nobody signed.
    """
    from chains import mapfile, preregister, rings
    doc = mapfile.load()
    by_ticker = {str(n.get("ticker", "")).upper(): n["id"]
                 for n in doc.get("nodes", []) if n.get("ticker")}
    out = {}
    for r in json.loads(watch_path().read_text(encoding="utf-8")):
        if preregister.is_v2(r):
            out[r["id"]] = preregister.ring2_of(r)
            continue
        got = rings.second_ring(doc, r.get("win") or [], r.get("lose") or [],
                                by_ticker.get(str(r.get("tk") or "").upper()))
        out[r["id"]] = (got["win2"], got["lose2"])
    return out


def check_forecast(rec: object, ids: set[str],
                   baskets: dict[str, tuple[list, list]],
                   baskets2: dict[str, tuple[list, list]] | None = None,
                   ring2: dict[str, tuple[list, list]] | None = None
                   ) -> str | None:
    """The reason this forecast cannot be used, or None if it can.

    ``ring2`` is the REGISTERED second ring, for contract-v2 questions only.
    A question in it is held to its contract; a question absent from it has a
    derived second ring, which is frozen instead. See the order-2 branch.
    """
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
    order = rec.get("order", DEFAULT_ORDER)
    if order not in ORDERS:
        return (f"{fid}: order {order!r} is not one of {sorted(ORDERS)} -- "
                f"1 is the registered basket, 2 is its second ring")
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
    want_h = ORDERS[order]
    h = rec.get("horizons")
    if h is not None and list(h) != list(want_h):
        return (f"{fid}: horizons {h!r} are not {list(want_h)} "
                f"(order {order})")
    if order == 1:
        reg_win, reg_lose = baskets.get(qid, ([], []))
        if (list(rec["win"]), list(rec["lose"])) != (list(reg_win),
                                                     list(reg_lose)):
            return (f"{fid}: baskets do not match the ones registered for "
                    f"{qid} in the watch list. Registered win={reg_win} "
                    f"lose={reg_lose}; received win={rec['win']} "
                    f"lose={rec['lose']}. A forecast whose hypothesis moved "
                    f"after the event is not a forecast.")
        return None
    # A CONTRACT-V2 TWIN IS NOT FROZEN -- IT IS REGISTERED.
    #
    # The freeze below exists because a DERIVED ring changes when the
    # derivation improves. A v2 ring is not derived: it was typed, hashed and
    # committed before the answer date, exactly like a first-ring basket. So
    # it is held to the first ring's rule instead -- it must still be the
    # basket that was registered -- and drift is refused rather than kept.
    reg2 = (ring2 or {}).get(qid)
    if reg2 is not None:
        if (sorted(rec["win"]), sorted(rec["lose"])) != (sorted(reg2[0]),
                                                         sorted(reg2[1])):
            return (f"{fid}: second-ring baskets do not match the ones "
                    f"registered for {qid} in its contract. Registered "
                    f"win={list(reg2[0])} lose={list(reg2[1])}; received "
                    f"win={rec['win']} lose={rec['lose']}. The scored basket "
                    f"of a v2 question is hashed into its preregistration "
                    f"and cannot move after the event.")
        return None
    # ORDER 2 IS FROZEN ONCE IT IS IN THE FILE.
    #
    # It used to be re-derived here and compared exactly, which reads as the
    # same guarantee and is not: the direct basket is TYPED and can only
    # change if somebody edits it, while the second ring is DERIVED and
    # changes whenever the derivation improves. Under the old check, adding
    # the layer rule -- which stops the drawing claiming a sign the map
    # cannot support -- would have refused every twin already marked, and a
    # refused forecast leaves the ledger. A forecast that disappears because
    # the map got better is the opposite of a forward test.
    #
    # The legs are the claim, and they are in git with a commit date, exactly
    # like a direct basket. What is checked is that they are legal.
    return _second_ring_legs_are_legal(fid, qid, rec, baskets)


def _second_ring_legs_are_legal(fid: str, qid: str, rec: dict,
                                baskets: dict) -> str | None:
    """A stored twin's legs, checked for shape rather than for derivation.

    Three things a real second ring can never be, and a corrupted or
    hand-edited row easily is: nothing at all, the first ring again, or both
    directions at once.

    Deliberately map-free. Every check that reads the map is a check that can
    start failing because the map improved, which is the thing this function
    exists to stop. A leg the ledger cannot price simply scores nothing --
    chains/forecast.py already drops it -- so it needs no gate here.
    """
    legs = list(rec["win"]) + list(rec["lose"])
    if not legs:
        return (f"{fid}: an order-2 forecast with no legs is not a claim. "
                f"A question with no second ring gets no twin.")
    first = set(baskets.get(qid, ([], []))[0]) | set(
        baskets.get(qid, ([], []))[1])
    overlap = sorted(set(legs) & first)
    if overlap:
        return (f"{fid}: second-ring legs {overlap} are already in the "
                f"registered first-ring basket for {qid}. The second ring is "
                f"what the first ring depends on, not the first ring again.")
    both = sorted(set(rec["win"]) & set(rec["lose"]))
    if both:
        return (f"{fid}: second-ring legs {both} are on both sides at once, "
                f"which is no direction at all.")
    return None


def collect_forecasts(rows: object, ids: set[str] | None = None,
                      baskets: dict | None = None,
                      baskets2: dict | None = None,
                      ring2: dict | None = None
                      ) -> tuple[list[dict], list[str]]:
    """The usable forecasts and the reasons the rest were dropped."""
    if rows is None:
        return [], []
    if not isinstance(rows, list):
        return [], [f"forecasts must be a list, got {type(rows).__name__}"]
    ids = known_ids() if ids is None else ids
    baskets = registered_baskets() if baskets is None else baskets
    ring2 = registered_ring2() if ring2 is None else ring2
    good: list[dict] = []
    problems: list[str] = []
    seen: set[str] = set()
    for rec in rows:
        why = check_forecast(rec, ids, baskets, baskets2, ring2)
        if why:
            problems.append(why)
            continue
        if rec["id"] in seen:
            problems.append(f"{rec['id']}: duplicate forecast id")
            continue
        seen.add(rec["id"])
        order = rec.get("order", DEFAULT_ORDER)
        # Order 1: the REGISTERED basket, not the received one. They were
        # just proved equal; using the registered copy means the thing scored
        # is the thing in watch.json even if that check is ever loosened.
        #
        # Order 2: the RECEIVED basket, because for a twin the received copy
        # IS the registered one -- derived once at mint time and committed to
        # git with a date. See check_forecast.
        reg = (baskets[rec["qid"]] if order == 1
               else (rec["win"], rec["lose"]))
        good.append({
            "id": rec["id"], "qid": rec["qid"], "marked_at": rec["marked_at"],
            "status": rec["status"], "order": order,
            "direction": DIRECTIONS[rec["direction"]],
            "win": list(reg[0]),
            "lose": list(reg[1]),
            "benchmark": BENCHMARK, "horizons": list(ORDERS[order]),
        })
    good.sort(key=lambda r: (r["marked_at"], r["id"]))
    return good, problems


def with_twins(forecasts: list[dict],
               baskets2: dict | None = None) -> list[dict]:
    """Every direct forecast gets its indirect twin, and gets it once.

    The task that writes marks.json registers the direct row. It is not
    required to know about the second ring, and older files predate it, so the
    twin is created here from the same mark and the same date -- never from
    today, which would date a forecast to the day the code shipped rather than
    the day the claim was made.

    Idempotent by construction: the twin's id is derived from (qid, mark date),
    so a file that already carries it produces no second copy, and a file that
    carries a hand-written one keeps the hand-written one.
    """
    have = {f["id"] for f in forecasts}
    made = []
    registered = None
    for f in forecasts:
        if f.get("order", DEFAULT_ORDER) != 1:
            continue
        tid = twin_id(f["qid"], f["marked_at"])
        if tid in have:
            continue
        if baskets2 is None:
            baskets2 = derived_baskets()
        win2, lose2 = baskets2.get(f["qid"], ([], []))
        # THE V2 MINTING GUARD.
        #
        # A contract-v2 question is SCORED on the basket it registered. If the
        # baskets handed to this function do not carry that basket -- because
        # a caller built them from the edge derivation, or from a version of
        # this code that predates v2 -- then minting would quietly produce a
        # twin nobody signed and score the question on it. That is the one
        # failure mode a preregistration cannot survive, so it stops here
        # loudly instead of proceeding.
        if registered is None:
            registered = registered_ring2()
        want = registered.get(f["qid"])
        if want is not None and (sorted(win2), sorted(lose2)) != (
                sorted(want[0]), sorted(want[1])):
            raise MintError(
                f"{f['qid']} is a contract-v2 question: its scored basket is "
                f"win={list(want[0])} lose={list(want[1])}, registered and "
                f"hashed before its answer date. Minting was handed "
                f"win={list(win2)} lose={list(lose2)} instead, which is a "
                f"basket nobody signed. The v2 minting path is missing or "
                f"was bypassed; no forecast is registered until it is back.")
        # No second ring, no second forecast. An empty basket is not a claim.
        if not win2 and not lose2:
            continue
        have.add(tid)
        made.append({
            "id": tid, "qid": f["qid"], "marked_at": f["marked_at"],
            "status": f["status"], "order": 2, "direction": f["direction"],
            "win": list(win2), "lose": list(lose2),
            "benchmark": BENCHMARK, "horizons": list(HORIZONS_R2),
        })
    out = list(forecasts) + made
    out.sort(key=lambda r: (r["marked_at"], r["id"]))
    return out


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

    return answers, with_twins(forecasts), problems


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
