"""Mark the questions whose date has passed, and register the forecasts.

WHAT THIS IS
------------
A question has a date. On that date a company says something, and the mark
records what it said against what the question asked -- nothing more. It is not
a view, not a recommendation, and not a number anybody should trade on: it is
"the call happened, and here is the sentence that settles it, with its source
and its date".

WHY IT MOVED HERE
-----------------
It ran as a scheduled cloud task that could reason but could not commit --
GitHub is unreachable from those sessions and there is no connector with write
access. A mark that cannot be committed is a claim with no hash, no diff and no
author, which is exactly what the forecast ledger exists to avoid. So the job
runs where the write is: in Actions, on a checkout, and the commit is the
record. The 07:00 refresh goes on reading data/<domain>/marks.json over raw.

WHAT THE MODEL DECIDES AND WHAT IT DOES NOT
-------------------------------------------
The model reads sources and picks one of five words. That is all it does. The
forecast -- the baskets, the direction, the horizons, the timestamp -- is
assembled in code from the watch row, because the ledger's entire argument is
that the baskets were fixed before the event and were not chosen by anything
that had seen the outcome. A model that could write a forecast could choose
one, and the ledger would be worth nothing.

THE TEXT NEVER LANDS HERE
-------------------------
The question text is the product. It goes to the model and it comes back in
nothing: marks.json carries a status, a basis, an evidence line and a note, and
the summary carries who/when/what. :func:`check_no_question_text` holds that,
and publish_site's locked-text gate covers marks.json as well.

    python -m chains.mark --dry-run --today 2026-09-11 --only orcl_q1
    python -m chains.mark --dry-run --force mu_fq4

``--force`` asks one question whatever its date and whatever is already
marked, to prove the whole path -- fetch, key, sources, decision -- end to end.
It exists only as a dry run: a mark made before the call happened is exactly
the claim the ledger cannot carry.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

MODEL_ENV = "ANTHROPIC_MODEL"
KEY_ENV = "ANTHROPIC_API_KEY"
API = "https://api.anthropic.com/v1"
VERSION = "2023-06-01"

# How long a question stays on the list after its date: five sessions. A call
# after the close is read that evening or the next morning, a Friday call on
# Monday, and a company that has said nothing clean by the fifth session is
# closed as "none" rather than left open for good. Sessions are weekdays: the
# price store that knows the holidays is not on the marking runner, and a
# holiday can only make the window a day shorter, never longer.
WINDOW_SESSIONS = 5
EXPIRED_NOTE = f"no clean answer within {WINDOW_SESSIONS} sessions"
# Calendar days of headlines asked for after the date: the window, and a weekend.
NEWS_DAYS = 7
MAX_SEARCHES = 5
MAX_EVIDENCE = 200
MAX_NOTE = 300
STATUSES = ("yes", "no", "mixed", "none", "open")
BASES = ("yes", "no", "unclear")
HORIZONS = [5, 10, 20]
BENCHMARK = "EW_MAP"
NOTE_PREFIX = "auto: "

# A date in some readable form, so "evidence" cannot be a claim with no day on
# it. 2026-09-10, 10 Sep 2026, Sep 10 2026, 10/09/2026 all count.
DATE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}[/.]\d{1,2}[/.]\d{2,4}"
    r"|\d{1,2}\s+[A-Z][a-z]{2,8}\s+\d{4}"
    r"|[A-Z][a-z]{2,8}\.?\s+\d{1,2},?\s+\d{4})")

RULES = """You record what a company said. You do not give investment advice,
you do not recommend anything, and you do not predict anything.

Decide strictly against the two sentences you are given:
- "yes looks like" describes what a yes sounds like.
- "no looks like" describes what a no sounds like.

Return exactly one status:
  yes    what was said matches the yes sentence
  no     what was said matches the no sentence
  mixed  parts of both are true
  none   the company did not address the topic at all
  open   you could not settle it from sources you could verify

Hard rules:
- Only use sources dated on or after the question's date. An earlier article
  cannot report an event that had not happened.
- If you find nothing, return open with note "auto: no source found on <date>".
- If it was reported but you cannot tell which way, return open with
  basis "unclear" and note "auto: reported but unclear - <source>".
- Never invent a number. If you did not read a figure in a source, it does not
  go in your answer.
- Quote at most 15 words from any source.
- evidence must name the source and carry a date.

Reply with JSON only, no prose around it, with exactly these keys:
{"status": "...", "basis": "yes|no|unclear", "evidence": "...", "note": "auto: ..."}
evidence at most 200 characters. note at most 300 characters and it must start
with "auto: "."""


class AskFailed(RuntimeError):
    """The model call did not return an answer, and why.

    Carries the HTTP status when there was one. The old handler printed the
    exception CLASS and nothing else -- "HTTPStatusError" for a week, which
    is every 4xx and every 5xx at once and tells nobody which. The status is
    the one fact that separates "the key is wrong" from "this account cannot
    use the search tool" from "slow down".
    """

    def __init__(self, why: str, status: int | None = None,
                 detail: str = ""):
        self.status = status
        self.detail = detail
        super().__init__(why)


class MarkError(RuntimeError):
    """Something the run cannot proceed without."""


# ------------------------------------------------------------------ inputs
def load_watch(domain: str | None = None) -> list[dict]:
    """The watch rows the build itself uses -- id, date, who, ticker, baskets.

    The same file, not a copy: a forecast registered here is scored later
    against the baskets in this row, and two sources for one basket is a bug
    waiting for the day they disagree.
    """
    from chains.paths import WATCH_FILENAME, data_dir
    rows = json.loads((data_dir(domain) / WATCH_FILENAME)
                      .read_text(encoding="utf-8"))
    return [r for r in rows if isinstance(r, dict) and r.get("id")]


def load_marks(domain: str | None = None) -> dict:
    """What has been marked so far. A missing file is the normal first state."""
    from chains.paths import marks_path
    p = marks_path(domain)
    if not p.exists():
        return {"answers": {}, "forecasts": []}
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc.setdefault("answers", {})
    doc.setdefault("forecasts", [])
    return doc


def sessions_after(day: dt.date, today: dt.date) -> int:
    """Weekday sessions after ``day``, up to and including ``today``."""
    n, d = 0, day + dt.timedelta(days=1)
    while d <= today:
        if d.weekday() < 5:
            n += 1
        d += dt.timedelta(days=1)
    return n


def _unsettled(rows: list[dict], marks: dict, today: dt.date,
               only: str | None):
    """(row, sessions since its date) for every row dated on or before today
    whose answer is missing or an automatic "open".

    A mark without ``auto: true`` was made by hand. It is never revisited --
    not to refine it, not to correct it, not to close it. The machine's job
    stops where a person's judgement starts.
    """
    for r in rows:
        if only and r["id"] != only:
            continue
        try:
            day = dt.date.fromisoformat(r.get("d") or "")
        except ValueError:
            continue
        if day > today:
            continue
        got = marks.get("answers", {}).get(r["id"])
        if got is None or (got.get("auto") and got.get("status") == "open"):
            yield r, sessions_after(day, today)


def due(rows: list[dict], marks: dict, today: dt.date,
        only: str | None = None) -> list[dict]:
    """Rows to ask about: dated on or before today, answer missing or "open",
    and no more than WINDOW_SESSIONS sessions past their date.

    An "open" is re-asked on every run until it settles or the window ends.
    """
    return [r for r, n in _unsettled(rows, marks, today, only)
            if n <= WINDOW_SESSIONS]


def expired(rows: list[dict], marks: dict, today: dt.date,
            only: str | None = None) -> list[dict]:
    """Rows still unsettled after the window: closed as "none", not asked."""
    return [r for r, n in _unsettled(rows, marks, today, only)
            if n > WINDOW_SESSIONS]


# ---------------------------------------------------------------- evidence
# Why the last news lookup returned what it did. Status and error CLASS
# only: this endpoint takes its token as a query parameter, so neither the
# URL nor the response body may be logged.
LAST_NEWS: dict = {"status": None, "error": None, "n": 0}


def headlines(ticker: str, day: dt.date, token: str | None = None) -> list[str]:
    """No headline source. Returns nothing, and says so.

    This used to call EODHD's news endpoint. That subscription is gone, and
    the endpoint was already answering with nothing useful before it went --
    "0 headlines" for a week, which is what sent somebody looking.

    The function stays rather than its callers losing a parameter, because
    headlines were always optional here: a mark that depended on them would
    fail for a reason that has nothing to do with what the company said. The
    marking job reads the filing and the release; the headlines were colour.

    ``token`` is accepted and ignored so no caller has to change on the way
    past. A replacement source, if one is ever wanted, plugs in here.
    """
    LAST_NEWS.update(status=None, error="no headline source configured", n=0)
    return []


# ------------------------------------------------------------------- model
def pick_model(key: str) -> str:
    """The model to use: the repo variable, or the newest sonnet on offer."""
    named = os.environ.get(MODEL_ENV, "").strip()
    if named:
        return named
    import httpx
    r = httpx.get(f"{API}/models",
                  headers={"x-api-key": key, "anthropic-version": VERSION},
                  timeout=30)
    r.raise_for_status()
    rows = r.json().get("data") or []
    sonnets = [m for m in rows if "sonnet" in str(m.get("id", "")).lower()]
    if not sonnets:
        raise MarkError("no sonnet model available and ANTHROPIC_MODEL unset")
    sonnets.sort(key=lambda m: str(m.get("created_at") or m.get("id")),
                 reverse=True)
    return str(sonnets[0]["id"])


def ask(row: dict, q: dict, news: list[str], key: str, model: str,
        tools: bool = True) -> str:
    """One call, with the web search tool. Returns the model's raw text.

    ``tools`` False drops the search tool: see the fallback below.
    """
    import httpx
    lines = [
        f"id: {row['id']}",
        f"company: {row.get('who') or ''}",
        f"ticker: {row.get('tk') or ''}",
        f"date: {row.get('d')}",
        f"question: {q.get('q_en') or ''}",
        f"yes looks like: {q.get('yes_en') or ''}",
        f"no looks like: {q.get('no_en') or ''}",
    ]
    if news:
        lines.append("headlines already found:")
        lines += [f"  - {h}" for h in news]
    body = {
        "model": model,
        "max_tokens": 1500,
        "system": RULES,
        "tools": [{"type": "web_search_20250305", "name": "web_search",
                   "max_uses": MAX_SEARCHES}],
        "messages": [{"role": "user", "content": "\n".join(lines)}],
    }
    if not tools:
        # The documented fallback. The search tool is a server tool the
        # account has to be entitled to; without it the model still answers
        # from the headlines it was handed, and a mark with a headline behind
        # it is worth more than no mark at all. Recorded in the note either
        # way, so a card never claims a search that did not happen.
        body.pop("tools", None)
    r = httpx.post(f"{API}/messages", json=body, timeout=180,
                   headers={"x-api-key": key, "anthropic-version": VERSION,
                            "content-type": "application/json"})
    if r.status_code != 200:
        # The body, trimmed, never the headers: the key is in the headers.
        raise AskFailed(f"the model call returned HTTP {r.status_code}",
                        status=r.status_code,
                        detail=str(r.text or "")[:300])
    content = r.json().get("content", [])
    LAST_CALL["searches"] = sum(1 for b in content
                                if b.get("type") == "server_tool_use")
    LAST_CALL["sources"] = [
        str(s.get("url")) for b in content
        if b.get("type") == "web_search_tool_result"
        and isinstance(b.get("content"), list)
        for s in b["content"] if isinstance(s, dict) and s.get("url")]
    parts = [b.get("text", "") for b in content if b.get("type") == "text"]
    return "\n".join(parts).strip()


# What the last model call searched and read: counts and URLs, never text.
LAST_CALL: dict = {"searches": 0, "sources": []}
MAX_SOURCES_SHOWN = 8


# -------------------------------------------------------------- validation
def parse(text: str, day: str) -> dict | None:
    """The model's JSON, or None if it is not usable as written.

    Checked rather than trusted. Every field is one the file will carry for
    good, and a mark with an evidence line that names no date is not evidence.
    """
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict):
        return None
    status, basis = d.get("status"), d.get("basis")
    ev, note = str(d.get("evidence") or ""), str(d.get("note") or "")
    if status not in STATUSES or basis not in BASES:
        return None
    if len(ev) > MAX_EVIDENCE or len(note) > MAX_NOTE:
        return None
    if not note.startswith(NOTE_PREFIX):
        return None
    # "open" is allowed to have nothing to point at; anything else has to.
    if status != "open":
        if not ev or not DATE_RE.search(ev):
            return None
    return {"status": status, "basis": basis, "evidence": ev, "note": note}


def no_source(failed: "AskFailed") -> str:
    """Why nothing was read, for the note on the card.

    Never "model output invalid": the model returned no output at all. A
    card that blames the model for a network it never reached sends the next
    reader looking in the wrong place.
    """
    if failed.status:
        return f"no source found (model call HTTP {failed.status})"
    return f"no source found ({failed})"


def sourced(mark: dict | None) -> bool:
    """Does this mark point at anything?

    Evidence, or a basis that names one. An auto mark with neither is the
    engine saying "I could not look"; it is not a finding, and it must never
    stand in front of one.
    """
    if not isinstance(mark, dict):
        return False
    if str(mark.get("evidence") or "").strip():
        return True
    return str(mark.get("basis") or "").strip() not in ("", "unclear")


def unresolved(day: str, why: str) -> dict:
    return {"status": "open", "basis": "unclear", "evidence": "",
            "note": f"{NOTE_PREFIX}{why} on {day}"}


def closed() -> dict:
    """The mark a question gets when its window ends with nothing clean."""
    return {"status": "none", "basis": "unclear", "evidence": "",
            "note": f"{NOTE_PREFIX}{EXPIRED_NOTE}"}


# ------------------------------------------------------------- the forecast
def forecast_for(row: dict, status: str, when: str, today: str) -> dict:
    """Assembled here, from the watch row. The model never sees this."""
    return {"id": f"{row['id']}-{today}", "qid": row["id"], "marked_at": when,
            "status": status, "direction": 1 if status == "yes" else -1,
            "win": list(row.get("win") or []),
            "lose": list(row.get("lose") or []),
            "benchmark": BENCHMARK, "horizons": list(HORIZONS)}


def registers_forecast(row: dict) -> bool:
    """Whether a settled answer on this row registers a forecast at all.

    A row marked ``observe_only`` is asked so its answer is on the record, not
    to bet a basket on it; a row with nothing in win or lose says the same
    thing without the flag. Either way a forecast would score nothing against
    the benchmark and still count as a call.
    """
    if row.get("observe_only"):
        return False
    return bool(list(row.get("win") or []) + list(row.get("lose") or []))


# ------------------------------------------------------------------- guard
def check_no_question_text(blob: str, questions: dict) -> list[str]:
    """Any question's own sentence appearing where it must not.

    The sentences are the paid half of the product. They go to the model and
    they come back in nothing: this is checked against what is about to be
    written and against what is about to be printed.
    """
    hits = []
    for qid, q in (questions or {}).items():
        for field in ("q_en", "yes_en", "no_en", "why_en",
                      "q_he", "yes_he", "no_he", "why_he"):
            s = str(q.get(field) or "").strip()
            if len(s) >= 25 and s in blob:
                hits.append(f"{qid}.{field}")
    return hits


# -------------------------------------------------------------------- run
def run(domain: str | None, today: dt.date, dry: bool, only: str | None,
        say=print, force: str | None = None,
        no_model: bool = False) -> int:
    from chains.paths import marks_path

    if force and not dry:
        raise MarkError("--force is a dry run only: a question asked before "
                        "its date cannot be marked for real")
    rows = load_watch(domain)
    marks = load_marks(domain)
    if force:
        todo = [r for r in rows if r["id"] == force]
        if not todo:
            raise MarkError(f"--force {force}: no such question in watch.json")
        say(f"force: {force} (date {todo[0].get('d')}, dry-run)")
        gone: list[dict] = []
    else:
        todo = due(rows, marks, today, only)
        gone = expired(rows, marks, today, only)
    day = today.isoformat()

    if not todo and not gone:
        say("אין שאלות לסימון היום.")
        say("commit: לא נדרש")
        return 0

    # Closing an expired row asks nobody, so it needs neither the text nor
    # the key; only a row that is actually asked does.
    text: dict = {}
    key = model = ""
    # Every mark this run decided, by qid. Written onto a FRESH read of the
    # file at the end rather than onto the copy loaded at the top, so a
    # writer that touched the file while this run was thinking is not
    # silently discarded -- see the merge below.
    changes: dict[str, dict] = {}
    if todo and no_model:
        # The marker of record is elsewhere. A due question is reported and
        # left alone: no text is fetched, no key is read, no model is asked,
        # and nothing is decided for it. Saying so per question matters --
        # a job that skipped its work in silence is indistinguishable from a
        # job that found nothing to do.
        for row in todo:
            say(f"  {row['id']}: due — left to the Cowork marker")
        todo = []
    if todo:
        from chains import questions as Q
        # The corpus is keyed by domain, and this one's section is the only
        # one that can answer for its rows. Left to default, the fetch falls
        # back to CHIP_MAP_DOMAIN and then to the first map -- which is right
        # only for as long as nothing else is ever marked. Two maps may name
        # a question alike (semi and energy both own gev_q3), so the wrong
        # section does not fail loudly, it answers with another industry's
        # sentence for the same id.
        text = Q.fetch(dom=domain)
        say(f"questions: {len(text)} fetched; text for "
            f"{sum(1 for r in todo if text.get(r['id']))}/{len(todo)} due")

        key = os.environ.get(KEY_ENV, "").strip()
        if not key:
            raise MarkError(
                f"{KEY_ENV} is not set. The marking job cannot read a source "
                f"without it; add it as a repository secret.")
        model = pick_model(key)
        say(f"model: {model}")

    when = dt.datetime.now(dt.timezone.utc).replace(
        microsecond=0).isoformat().replace("+00:00", "Z")

    changed = False
    marked, made, trail = [], [], []
    for row in todo:
        q = text.get(row["id"]) or {}
        news = headlines(str(row.get("tk") or ""),
                         dt.date.fromisoformat(row["d"]))
        why_news = LAST_NEWS.get("error")
        trail.append(f"  {row['id']}: {len(news)} headline(s)"
                     + (f" ({why_news})" if why_news else ""))
        rec = None
        failed: AskFailed | None = None
        # Attempt 1 and 2 use the search tool. Attempt 3 drops it: if the
        # account cannot use a server tool, every call with one attached
        # fails identically, and retrying the same shape twice more only
        # spends time to reach the same nothing.
        for attempt, tools in ((1, True), (2, True), (3, False)):
            if attempt == 3 and failed is None:
                break                      # the tool worked; nothing to fall
            LAST_CALL.update(searches=0, sources=[])
            try:
                rec = parse(ask(row, q, news, key, model, tools=tools),
                            row["d"])
                failed = None
            except AskFailed as e:
                failed = e
                say(f"  {row['id']}: model call failed — HTTP {e.status}")
                if e.detail:
                    say(f"    {e.detail[:200]}")
                rec = None
            except Exception as e:                 # network, timeout, JSON
                failed = AskFailed(type(e).__name__)
                say(f"  {row['id']}: model call failed — {type(e).__name__}")
                rec = None
            srcs = LAST_CALL["sources"]

            trail.append(f"  {row['id']}: call {attempt}"
                         f"{'' if tools else ' (no search tool)'}: "
                         f"{LAST_CALL['searches']} web search(es), "
                         f"{len(srcs)} source(s) read, "
                         f"{'valid' if rec else 'no valid'} decision")
            trail += [f"    {u}" for u in srcs[:MAX_SOURCES_SHOWN]]
            if rec:
                break
        if not rec:
            # Two different failures, and they must not read alike. The call
            # that never returned is not the model answering badly: a mark
            # saying "model output invalid" when nothing was ever reached
            # blames the model for the network, and the next reader looks in
            # the wrong place. "Invalid" is reserved for a reply that came
            # back and could not be used.
            rec = unresolved(day, no_source(failed) if failed is not None
                             else "model output invalid")
        trail.append(f"  {row['id']}: decision "
                     f"{json.dumps(rec, ensure_ascii=False)}")

        rec["auto"] = True
        rec["updated"] = when
        old = marks["answers"].get(row["id"])
        if sourced(old) and not sourced(rec):
            # THE RULE: an unsourced automatic mark never replaces a mark
            # that points at something. The job runs twice a day against the
            # same file, and a bad afternoon -- a dead endpoint, a rate
            # limit, an entitlement that lapsed -- would otherwise quietly
            # erase the morning's finding and leave a card reading "open,
            # no source found" over evidence somebody had already checked.
            # Losing a day's attempt is cheap; losing the evidence is not.
            say(f"  {row['id']}: kept the existing mark — "
                f"{old.get('status')} with a source; this run found none")
            trail.append(f"  {row['id']}: not overwritten "
                         f"(existing mark is sourced, this one is not)")
            marked.append((row, old))
            continue
        marks["answers"][row["id"]] = rec
        changes[row["id"]] = rec
        changed = True
        marked.append((row, rec))

        # A forecast is registered once, when a row first settles one way or
        # the other. Never rewritten, never removed: an entry that can be
        # edited after the fact is not a record of anything.
        if rec["status"] in ("yes", "no") and registers_forecast(row):
            if not any(f.get("qid") == row["id"]
                       for f in marks.get("forecasts", [])):
                f = forecast_for(row, rec["status"], when, day)
                marks["forecasts"].append(f)
                made.append(f)

    for row in gone:
        rec = closed()
        rec["auto"] = True
        rec["updated"] = when
        marks["answers"][row["id"]] = rec
        changes[row["id"]] = rec
        changed = True
        marked.append((row, rec))
        trail.append(f"  {row['id']}: "
                     f"{sessions_after(dt.date.fromisoformat(row['d']), today)}"
                     f" sessions since {row['d']}, closed as none")

    blob = json.dumps(marks, ensure_ascii=False)
    leak = check_no_question_text(blob, text)
    if leak:
        raise MarkError(f"a question's own sentence reached marks.json: {leak}")
    leak = check_no_question_text("\n".join(trail), text)
    if leak:
        raise MarkError(f"a question's own sentence reached the log: {leak}")

    for line in trail:
        say(line)
    for row, rec in marked:
        say(f"  {row.get('who')} · {row.get('d')} · {rec['status']} · "
            f"{rec['note']}")
    for f in made:
        say(f"  תחזית {f['qid']} · כיוון {f['direction']:+d} · "
            f"עולה {','.join(f['win']) or '-'} · "
            f"יורד {','.join(f['lose']) or '-'}")

    if dry:
        say("commit: לא נדרש (dry-run)")
        return 0
    if changed:
        kept = merge_and_write(marks_path(domain), changes,
                               marks.get("forecasts") or [])
        for qid in kept:
            say(f"  {qid}: kept the copy on disk — it has a source, "
                f"this run's does not")
        say("commit: נדרש")
    else:
        say("commit: לא נדרש")
    return 0


def merge_and_write(path: Path, changes: dict[str, dict],
                    forecasts: list[dict]) -> list[str]:
    """Apply this run's marks onto a FRESH read of the file, atomically.

    Two reasons, and the second is the one that bites.

    The file is re-read here rather than written from the copy loaded at the
    start of the run. In between, this process fetched a corpus and made a
    number of network calls -- seconds to minutes -- and the daily marker
    writes to the same file. Writing the whole document from the older copy
    silently discards whatever landed in the meantime, and no git conflict
    catches it: by the time the commit step rebases, the content is already
    decided.

    And the sourced rule is applied again here, against what is actually on
    disk. Checking it only against the copy read at the top answers a
    question about the past. Returns the qids kept from disk, so the run can
    say so out loud.
    """
    import tempfile

    on_disk: dict = {"answers": {}, "forecasts": []}
    if path.exists():
        try:
            on_disk = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            # Unreadable is not empty. Overwriting it would turn a corrupt
            # file into a lost one.
            raise MarkError(f"{path} is not readable JSON; refusing to "
                            f"overwrite it") from None
    on_disk.setdefault("answers", {})
    on_disk.setdefault("forecasts", [])

    kept = []
    for qid, rec in changes.items():
        if sourced(on_disk["answers"].get(qid)) and not sourced(rec):
            kept.append(qid)
            continue
        on_disk["answers"][qid] = rec

    # A forecast is registered once and never rewritten, so only the ones the
    # file does not already carry are added.
    have = {f.get("qid") for f in on_disk["forecasts"]}
    for f in forecasts:
        if f.get("qid") not in have:
            on_disk["forecasts"].append(f)
            have.add(f.get("qid"))

    path.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(on_disk, indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name,
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(blob)
        os.replace(tmp, path)          # atomic: a reader sees one or the other
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return kept


def summarise(lines: list[str]) -> None:
    """The same summary, into the run page, when there is one."""
    path = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("### סימון שאלות\n\n```\n" + "\n".join(lines) + "\n```\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--domain", default=None)
    ap.add_argument("--today", default=None, metavar="YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default=None, metavar="QID")
    ap.add_argument("--force", default=None, metavar="QID",
                    help="ask this question whatever its date; needs --dry-run")
    ap.add_argument("--no-model", action="store_true",
                    help="never call the model: report a due question and "
                         "leave it to the marker of record")
    args = ap.parse_args(argv)
    if args.force and not args.dry_run:
        ap.error("--force needs --dry-run")

    if args.domain:
        # The same plumbing build_all uses: one env var, and every path helper
        # in the process answers for the same map.
        os.environ["CHIP_MAP_DOMAIN"] = args.domain
    today = (dt.date.fromisoformat(args.today) if args.today
             else dt.datetime.now(dt.timezone.utc).date())
    lines: list[str] = []

    def say(msg: str) -> None:
        print(msg)
        lines.append(msg)

    try:
        rc = run(args.domain, today, args.dry_run, args.only, say,
                 force=args.force, no_model=args.no_model)
    except MarkError as e:
        print(f"mark: {e}", file=sys.stderr)
        return 1
    summarise(lines)
    return rc


if __name__ == "__main__":                                # pragma: no cover
    raise SystemExit(main())
