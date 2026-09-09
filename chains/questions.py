"""The question text: fetched at build time, never stored in this repository.

    python -m chains.questions        # fetch, validate, and say what unlocks

WHY IT IS NOT IN GIT
--------------------
The skeleton of a question -- who reports, on what day, which chokepoints it
touches, which basket gains if the answer is yes -- is the map, and the map is
public. The question itself, and what to listen for on the call, is the thing
somebody would pay for. So the repository carries the skeleton and the text
lives in one private file that the build reads and never writes down.

Everything that follows from that is deliberate: data/watch.json has no q and
no listen, chains/watch.py's table has no text columns, and a snapshot carries
text only for the rows that are unlocked. A locked row is FULLY VISIBLE -- date,
countdown, exposures, how many hints have already landed -- and simply has no
sentence attached. That is the offer: the shape is free, the sentence is not.

A BUILD WITHOUT QUESTIONS MUST NOT PUBLISH
------------------------------------------
There is no soft failure here. If the fetch returns HTML, or 404s, or the URL
is unset, the build stops. The alternative is a page that looks finished and
has an empty sentence under every headline, published over a good one, with
nothing to say what happened. Google Drive in particular answers with an HTML
interstitial rather than a status code when it feels like it, so the content is
checked and not just the status.

WHAT IS FREE, AND WHY THAT SHAPE
--------------------------------
Every question whose date has passed: free, permanently. The event happened,
the answer is public, and a paywall over yesterday's news buys nothing and
costs the one thing that makes the list worth trusting -- being able to check
what it said before the fact.

Plus exactly one upcoming question: the nearest by date. That is the sample.
It is a real question with a real date, not a redacted one, and it rotates on
its own as the calendar moves.
"""
from __future__ import annotations

import datetime as dt
import json
import os

from chains.paths import watch_path

QUESTIONS_URL_ENV = "QUESTIONS_URL"
HTTP_TIMEOUT = 10.0

# TWO SHAPES, ONE MEANING
# -----------------------
# v2 says what each answer will sound like:
#     q, yes, no, why      -- per language
# v1 said only what to listen for:
#     q, listen
# A v1 file is read as v2 with ``listen`` standing in for ``yes`` and the other
# two empty. Empty, not filled in: "what no sounds like" is a claim about the
# world, and inventing one to make a card look finished would be inventing the
# product.
PARTS = ("q", "yes", "no", "why")
LANGS = ("he", "en")

# Every field a question can carry, in every language.
FIELDS = tuple(f"{part}_{lang}" for lang in LANGS for part in PARTS)

# Only the question itself has to be there. The rest are a v1 file's gaps.
REQUIRED = tuple(f"q_{lang}" for lang in LANGS)

# What a row carries in each language once merged.
LANG_FIELDS = {lang: {part: f"{part}_{lang}" for part in PARTS}
               for lang in LANGS}


class QuestionsError(RuntimeError):
    """The text could not be fetched or is not usable. Always fatal."""


def questions_url() -> str | None:
    return os.environ.get(QUESTIONS_URL_ENV, "").strip() or None


def fetch(url: str | None = None) -> dict[str, dict]:
    """The question text, or raise. Never returns a partial answer.

    A value with no scheme that names an existing file is read as one. That is
    for a local build: the text is private, and requiring the laptop to hold
    the share link just to rebuild a page would put the link in a shell history
    instead of a secret. CI always passes a URL.
    """
    url = url or questions_url()
    if url and "://" not in url:
        from pathlib import Path
        p = Path(url)
        if not p.exists():
            raise QuestionsError(f"{QUESTIONS_URL_ENV} is {url!r}, which is "
                                 f"neither a URL nor a file that exists")
        try:
            return validate(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError as e:
            raise QuestionsError(f"{p} is not valid JSON ({e})") from None
    if not url:
        raise QuestionsError(
            f"{QUESTIONS_URL_ENV} is not set. The question text lives outside "
            f"this repository and the build cannot make a page without it; a "
            f"page with an empty sentence under every headline would publish "
            f"over a good one and say nothing about why.")
    try:
        import httpx
    except ImportError:                                   # pragma: no cover
        raise QuestionsError("httpx is not installed") from None
    try:
        r = httpx.get(url, timeout=HTTP_TIMEOUT, follow_redirects=True)
    except Exception as e:                                # noqa: BLE001
        raise QuestionsError(
            f"{QUESTIONS_URL_ENV} unreachable ({type(e).__name__}: "
            f"{str(e)[:120]})") from None
    if r.status_code != 200:
        raise QuestionsError(f"{QUESTIONS_URL_ENV} returned HTTP "
                             f"{r.status_code}")
    head = r.text.lstrip()[:200]
    if head[:1] not in "{[":
        # Drive serves a "can't scan this file for viruses" interstitial, or a
        # sign-in page, with a 200. Both are HTML and neither is an error the
        # status code will tell you about.
        raise QuestionsError(
            f"{QUESTIONS_URL_ENV} did not return JSON. The first bytes were "
            f"{head[:80]!r} -- a Google Drive share link that is not public, "
            f"or is being served through the large-file interstitial, answers "
            f"with HTML and a 200.")
    try:
        payload = r.json()
    except ValueError:
        raise QuestionsError(f"{QUESTIONS_URL_ENV} returned unparseable "
                             f"JSON") from None
    return validate(payload)


def normalise(rec: dict) -> dict:
    """One question's text, in the canonical four-part shape.

    A v1 record has ``listen`` and no ``yes``; its sentence moves to ``yes``
    because that is what it always meant -- what you would hear if the answer
    were yes. ``no`` and ``why`` stay empty rather than being invented.
    """
    out = {}
    for lang in LANGS:
        legacy = rec.get(f"listen_{lang}")
        for part in PARTS:
            v = rec.get(f"{part}_{lang}")
            if v is None and part == "yes" and legacy is not None:
                v = legacy
            out[f"{part}_{lang}"] = (v or "").strip()
    return out


def validate(payload: object, ids: set[str] | None = None) -> dict[str, dict]:
    """Every watch id present, every question a non-empty string. Or raise.

    Strict, unlike the answers file, and for the opposite reason: an answer
    that is missing colours nothing and the page renders the row open. A
    question that is missing renders a card with no sentence in it, which looks
    like a bug in the page rather than a gap in the data.

    ``yes``, ``no`` and ``why`` may be empty -- a v1 file has no way to supply
    them -- and the card simply omits the part it has nothing for.
    """
    if isinstance(payload, dict) and "questions" in payload:
        payload = payload["questions"]
    if not isinstance(payload, dict):
        raise QuestionsError(
            f"expected an object keyed by question id, got "
            f"{type(payload).__name__}")
    ids = known_ids() if ids is None else ids
    missing = sorted(ids - set(payload))
    if missing:
        raise QuestionsError(f"no text for {len(missing)} question(s): "
                             f"{missing[:8]}")
    out: dict[str, dict] = {}
    for qid in ids:
        rec = payload[qid]
        if not isinstance(rec, dict):
            raise QuestionsError(f"{qid}: expected an object")
        for f in FIELDS + ("listen_he", "listen_en"):
            v = rec.get(f)
            if v is not None and not isinstance(v, str):
                raise QuestionsError(f"{qid}: {f} must be a string")
        norm = normalise(rec)
        for f in REQUIRED:
            if not norm[f]:
                raise QuestionsError(f"{qid}: {f} is missing or empty")
        out[qid] = norm
    return out


def known_ids() -> set[str]:
    return {r["id"] for r in
            json.loads(watch_path().read_text(encoding="utf-8"))}


# ------------------------------------------------------------------ the rule
def open_ids(rows: list[dict], today: dt.date | None = None) -> set[str]:
    """Which rows show their text: everything past, plus the next one.

    "Past" is strictly before today, so a question being answered TODAY is
    still the upcoming one -- the sentence is worth most in the hours before
    the call, and giving it away that morning would give away the only sample
    that is worth anything.
    """
    today = today or dt.date.today()
    past = {r["id"] for r in rows if dt.date.fromisoformat(r["d"]) < today}
    upcoming = sorted((r for r in rows
                       if dt.date.fromisoformat(r["d"]) >= today),
                      key=lambda r: (r["d"], r["id"]))
    return past | ({upcoming[0]["id"]} if upcoming else set())


def merge(rows: list[dict], text: dict[str, dict], lang: str,
          today: dt.date | None = None,
          unlock_all: bool = False) -> list[dict]:
    """Watch rows with the text attached where the row is open.

    A locked row gets ``locked: true`` and none of the four text fields. Not an
    empty string, not a placeholder: the fields are absent, so a page that
    forgot to check the flag renders nothing rather than something, and a
    snapshot that leaked would have to leak a field that is not there.

    An OPEN row omits a part it has nothing for, so the card can tell "this
    question has no 'no' sentence yet" from "this row is locked".
    """
    fields = LANG_FIELDS[lang]
    unlocked = open_ids(rows, today)
    # The paid mail is the one place every row carries its text. The flag is
    # explicit and it is never set by anything that writes a published file:
    # grep for unlock_all and every hit is a brief.
    open_flags = {r["id"]: r["id"] in unlocked for r in rows}
    if unlock_all:
        unlocked = {r["id"] for r in rows}
    out = []
    for r in rows:
        row = dict(r)
        is_open = r["id"] in unlocked
        # ``open`` keeps meaning "free on the site" even in the paid mail, so a
        # brief can mark which rows its reader is paying for.
        row["open"] = open_flags[r["id"]]
        row["locked"] = not open_flags[r["id"]]
        if is_open:
            t = text.get(r["id"])
            if t:
                for part in PARTS:
                    v = t.get(fields[part], "")
                    if v:
                        row[part] = v
        out.append(row)
    return out


def next_open(rows: list[dict], today: dt.date | None = None) -> dict | None:
    """The single upcoming row that is unlocked -- "this week's question"."""
    today = today or dt.date.today()
    up = sorted((r for r in rows if dt.date.fromisoformat(r["d"]) >= today),
                key=lambda r: (r["d"], r["id"]))
    return up[0] if up else None


def main() -> int:
    import datetime
    try:
        text = fetch()
    except QuestionsError as e:
        print(f"QUESTIONS: {e}")
        return 1
    rows = json.loads(watch_path().read_text(encoding="utf-8"))
    unlocked = open_ids(rows)
    nxt = next_open(rows)
    print(f"{len(text)} questions fetched, {len(unlocked)} open, "
          f"{len(rows) - len(unlocked)} locked")
    if nxt:
        days = (datetime.date.fromisoformat(nxt["d"])
                - datetime.date.today()).days
        print(f"  this week's open question: {nxt['who']} ({nxt['d']}, "
              f"in {days} days)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
