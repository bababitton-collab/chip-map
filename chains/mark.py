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

# How far back a date can be and still be marked. Three days covers a Friday
# call reached on Monday; beyond that a silent row is a row somebody has to
# look at rather than one a machine should quietly close.
LOOKBACK = 3
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


def due(rows: list[dict], marks: dict, today: dt.date,
        only: str | None = None) -> list[dict]:
    """Rows whose day has come and whose answer is not settled by a person.

    A mark without ``auto: true`` was made by hand. It is never revisited --
    not to refine it, not to correct it. The machine's job stops where a
    person's judgement starts.
    """
    out = []
    lo = today - dt.timedelta(days=LOOKBACK)
    for r in rows:
        if only and r["id"] != only:
            continue
        d = r.get("d")
        if not d:
            continue
        try:
            day = dt.date.fromisoformat(d)
        except ValueError:
            continue
        if not (lo <= day <= today):
            continue
        got = marks.get("answers", {}).get(r["id"])
        if got is None:
            out.append(r)
        elif not got.get("auto"):
            continue                      # a person marked it; leave it alone
        elif got.get("status") == "open":
            out.append(r)
        else:
            continue
    return out


# ---------------------------------------------------------------- evidence
def headlines(ticker: str, day: dt.date, token: str | None) -> list[str]:
    """A few EODHD headlines around the date, if the plan serves them.

    Optional on purpose. The news endpoint is not on every plan, and a mark
    that depends on it would fail for a reason that has nothing to do with
    what the company said.
    """
    if not token or not ticker:
        return []
    try:
        import httpx
        frm = (day - dt.timedelta(days=1)).isoformat()
        to = (day + dt.timedelta(days=LOOKBACK)).isoformat()
        r = httpx.get(f"https://eodhd.com/api/news",
                      params={"s": ticker, "from": frm, "to": to,
                              "limit": 10, "api_token": token, "fmt": "json"},
                      timeout=20)
        if r.status_code != 200:
            return []
        out = []
        for item in r.json()[:10]:
            t = str(item.get("title") or "").strip()
            d = str(item.get("date") or "")[:10]
            if t:
                out.append(f"{d} {t}"[:180])
        return out
    except Exception:
        return []                          # quietly: this is a nice-to-have


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


def ask(row: dict, q: dict, news: list[str], key: str, model: str) -> str:
    """One call, with the web search tool. Returns the model's raw text."""
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
    r = httpx.post(f"{API}/messages", json=body, timeout=180,
                   headers={"x-api-key": key, "anthropic-version": VERSION,
                            "content-type": "application/json"})
    r.raise_for_status()
    parts = [b.get("text", "") for b in r.json().get("content", [])
             if b.get("type") == "text"]
    return "\n".join(parts).strip()


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


def unresolved(day: str, why: str) -> dict:
    return {"status": "open", "basis": "unclear", "evidence": "",
            "note": f"{NOTE_PREFIX}{why} on {day}"}


# ------------------------------------------------------------- the forecast
def forecast_for(row: dict, status: str, when: str, today: str) -> dict:
    """Assembled here, from the watch row. The model never sees this."""
    return {"id": f"{row['id']}-{today}", "qid": row["id"], "marked_at": when,
            "status": status, "direction": 1 if status == "yes" else -1,
            "win": list(row.get("win") or []),
            "lose": list(row.get("lose") or []),
            "benchmark": BENCHMARK, "horizons": list(HORIZONS)}


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
        say=print) -> int:
    from chains.paths import marks_path

    rows = load_watch(domain)
    marks = load_marks(domain)
    todo = due(rows, marks, today, only)
    day = today.isoformat()

    if not todo:
        say("אין שאלות לסימון היום.")
        say("commit: לא נדרש")
        return 0

    from chains import questions as Q
    text = Q.fetch()

    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        raise MarkError(
            f"{KEY_ENV} is not set. The marking job cannot read a source "
            f"without it; add it as a repository secret.")
    model = pick_model(key)
    say(f"model: {model}")

    eod = os.environ.get("EODHD_API_TOKEN", "").strip() or None
    when = dt.datetime.now(dt.timezone.utc).replace(
        microsecond=0).isoformat().replace("+00:00", "Z")

    changed = False
    marked, made = [], []
    for row in todo:
        q = text.get(row["id"]) or {}
        news = headlines(str(row.get("tk") or ""),
                         dt.date.fromisoformat(row["d"]), eod)
        rec = None
        for attempt in (1, 2):
            try:
                rec = parse(ask(row, q, news, key, model), row["d"])
            except Exception as e:
                say(f"  {row['id']}: קריאה נכשלה ({type(e).__name__})")
                rec = None
            if rec:
                break
        if not rec:
            rec = unresolved(day, "model output invalid")

        rec["auto"] = True
        rec["updated"] = when
        marks["answers"][row["id"]] = rec
        changed = True
        marked.append((row, rec))

        # A forecast is registered once, when a row first settles one way or
        # the other. Never rewritten, never removed: an entry that can be
        # edited after the fact is not a record of anything.
        if rec["status"] in ("yes", "no"):
            if not any(f.get("qid") == row["id"]
                       for f in marks.get("forecasts", [])):
                f = forecast_for(row, rec["status"], when, day)
                marks["forecasts"].append(f)
                made.append(f)

    blob = json.dumps(marks, ensure_ascii=False)
    leak = check_no_question_text(blob, text)
    if leak:
        raise MarkError(f"a question's own sentence reached marks.json: {leak}")

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
        marks_path(domain).write_text(
            json.dumps(marks, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        say("commit: נדרש")
    else:
        say("commit: לא נדרש")
    return 0


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
    args = ap.parse_args(argv)

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
        rc = run(args.domain, today, args.dry_run, args.only, say)
    except MarkError as e:
        print(f"mark: {e}", file=sys.stderr)
        return 1
    summarise(lines)
    return rc


if __name__ == "__main__":                                # pragma: no cover
    raise SystemExit(main())
