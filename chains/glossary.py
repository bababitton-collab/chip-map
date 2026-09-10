"""Plain-language definitions for the terms a card uses.

WHY
---
The questions are written for somebody who already knows what HBM is. Most
readers do not, and a reader who stops at the third acronym never reaches the
claim. The glossary puts the definition where the word is, and nowhere else:
no separate page to navigate to, no jargon list to read first.

WHAT IT IS NOT
--------------
It is not content. A definition explains a word that is already on the page; it
never adds a fact, a number or an opinion the map does not already carry. That
is enforced rather than trusted: :func:`numbers_without_a_source` walks every
definition, pulls out every figure in it, and fails the build naming any that
does not appear in the map or in a question. A glossary that can smuggle in a
new number is a second, unsourced dataset wearing a helpful hat.

DOMAIN-NEUTRAL
--------------
``data/<domain>/glossary.json``, read through the same path helper as the map
and the watch list. A domain with no glossary file has no glossary and no
error: the file is an addition to a map, not a requirement of one.

MATCHING
--------
Whole words only, longest first, and each stretch of text is claimed once. That
is three rules doing one job:

  * whole words, so "test" inside "latest" is not a term;
  * longest first, so "HBM4" takes the HBM entry rather than leaving a bare
    "HBM" and a dangling 4;
  * claimed once, so "High-NA" is one term and not also the "NA" inside it.

Case matters for a match string that has any capital in it -- HBM, RPO, EUV,
FY27, InP are the words themselves -- and does not for a plain lowercase one,
because "Capex" at the start of a sentence is still capex.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# What a card shows. Four is what fits under "Why it matters" without the line
# becoming its own paragraph, and a card that needs more than four definitions
# is a card whose question needs rewriting.
MAX_PER_CARD = 4

FILENAME = "glossary.json"

# Figures a definition is allowed to contain only if the map or a question
# already contains them. The spelled-out ones are here because "three years" is
# as much a claim as "3 years".
WORD_NUMBERS = ("one", "two", "three", "four", "five", "six", "seven",
                "eight", "nine", "ten", "eleven", "twelve", "twenty",
                "thirty", "forty", "fifty", "hundred", "thousand", "million",
                "billion", "trillion")
NUMBER_TOKEN = re.compile(
    r"(?:[$€£¥]\s?\d[\d,.]*\s?(?:[KMBT]|bn|m|k)?%?"      # $380M, €1.2bn
    r"|\d[\d,.]*\s?%"                                    # 98%
    r"|\d[\d,.]*\s?(?:nm|mm|GB|TB|kW|MW|GW|x)"           # 3nm, 300mm, 800x
    r"|\d[\d,.]*)",                                      # 2027, 1.4
    re.I)


class GlossaryError(ValueError):
    """A glossary that cannot be used as written."""


# ------------------------------------------------------------------ loading
def path_for(domain: str | None = None) -> Path:
    from chains.paths import data_dir
    return data_dir(domain) / FILENAME


def load(domain: str | None = None, path: Path | None = None) -> list[dict]:
    """The terms, validated. An absent file is an empty glossary, not a fault.

    Everything else IS a fault: a duplicate id would make a tooltip ambiguous,
    an empty definition would render a blank box, and an empty match string
    would match everywhere.
    """
    p = path or path_for(domain)
    if not p.exists():
        return []
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise GlossaryError(f"{p} is not valid JSON ({e})") from None
    terms = doc.get("terms")
    if not isinstance(terms, list):
        raise GlossaryError(f"{p}: 'terms' must be a list")
    validate(terms, str(p))
    return terms


def validate(terms: list[dict], where: str = "glossary") -> list[dict]:
    seen: set[str] = set()
    for i, t in enumerate(terms):
        if not isinstance(t, dict):
            raise GlossaryError(f"{where}: term {i} is not an object")
        tid = t.get("id")
        if not isinstance(tid, str) or not tid.strip():
            raise GlossaryError(f"{where}: term {i} has no id")
        if tid in seen:
            raise GlossaryError(
                f"{where}: two terms share the id {tid!r}. A card names a "
                f"definition by id, so a duplicate makes the tooltip a "
                f"coin toss.")
        seen.add(tid)
        if not str(t.get("label") or "").strip():
            raise GlossaryError(f"{where}: {tid} has no label")
        for lang in ("en", "he"):
            if not str(t.get(lang) or "").strip():
                raise GlossaryError(
                    f"{where}: {tid} has no {lang} definition. Both pages "
                    f"show the same terms; one language missing is one page "
                    f"with an empty tooltip.")
        m = t.get("match")
        if not isinstance(m, list) or not m:
            raise GlossaryError(f"{where}: {tid} has no match list")
        for s in m:
            if not isinstance(s, str) or not s.strip():
                raise GlossaryError(
                    f"{where}: {tid} has an empty match string, which would "
                    f"match at every position in every sentence.")
    return terms


# ----------------------------------------------------------------- matching
def _cased(match: str) -> bool:
    """Whether this match string is case-sensitive.

    A string with a capital in it IS the word -- HBM, InP, FY27. A plain
    lowercase one is a normal word and "Capex" at the start of a sentence is
    still capex.
    """
    return match != match.lower()


def _boundary(text: str, start: int, end: int) -> bool:
    before = text[start - 1] if start else ""
    after = text[end] if end < len(text) else ""
    return not (before.isalnum() or after.isalnum())


def pairs(terms: list[dict]) -> list[tuple[str, str]]:
    """(match string, term id), longest first."""
    out = [(m, t["id"]) for t in terms for m in t.get("match") or []]
    out.sort(key=lambda p: (-len(p[0]), p[0]))
    return out


def find(text: str, terms: list[dict],
         limit: int = MAX_PER_CARD) -> list[str]:
    """Term ids present in ``text``, in the order they first appear."""
    if not text or not terms:
        return []
    claimed: list[tuple[int, int]] = []
    hits: list[tuple[int, str]] = []
    for match, tid in pairs(terms):
        flags = 0 if _cased(match) else re.I
        for m in re.finditer(re.escape(match), text, flags):
            s, e = m.span()
            if not _boundary(text, s, e):
                continue
            # Longest first, so an overlap means a longer term already owns
            # this stretch -- "NA" inside a claimed "High-NA".
            if any(s < ce and cs < e for cs, ce in claimed):
                continue
            claimed.append((s, e))
            hits.append((s, tid))
    hits.sort()
    out: list[str] = []
    for _pos, tid in hits:
        if tid not in out:
            out.append(tid)
        if len(out) >= limit:
            break
    return out


def mark(text: str, terms: list[dict], limit: int = MAX_PER_CARD) -> str:
    """``text`` with each matched term wrapped for the tooltip.

    Returns HTML. The caller must not escape the result again; it escapes the
    text itself, because the wrapping has to survive and the sentence must
    not.
    """
    from html import escape
    if not text or not terms:
        return escape(text or "")
    keep = set(find(text, terms, limit))
    spans: list[tuple[int, int, str]] = []
    claimed: list[tuple[int, int]] = []
    for match, tid in pairs(terms):
        if tid not in keep:
            continue
        flags = 0 if _cased(match) else re.I
        for m in re.finditer(re.escape(match), text, flags):
            s, e = m.span()
            if not _boundary(text, s, e):
                continue
            if any(s < ce and cs < e for cs, ce in claimed):
                continue
            claimed.append((s, e))
            spans.append((s, e, tid))
    spans.sort()
    out, at = [], 0
    for s, e, tid in spans:
        out.append(escape(text[at:s]))
        out.append(f'<abbr class="gl" data-gl="{escape(tid)}">'
                   f'{escape(text[s:e])}</abbr>')
        at = e
    out.append(escape(text[at:]))
    return "".join(out)


def for_page(terms: list[dict], lang: str) -> dict[str, dict]:
    """``{id: {label, def}}`` -- what a page needs and nothing else."""
    return {t["id"]: {"label": t["label"], "def": t[lang]} for t in terms}


# ------------------------------------------------- a definition invents nothing
def numbers_in(text: str) -> list[str]:
    """Every figure a definition contains, spelled or written."""
    out = [m.group(0).strip() for m in NUMBER_TOKEN.finditer(text or "")]
    low = (text or "").lower()
    for w in WORD_NUMBERS:
        if re.search(r"\b" + w + r"\b", low):
            out.append(w)
    return out


def _haystack(doc: dict | None, questions: dict | None) -> str:
    """Everything a definition is allowed to draw a number from."""
    parts = [json.dumps(doc or {}, ensure_ascii=False)]
    parts.append(json.dumps(questions or {}, ensure_ascii=False))
    return " ".join(parts).lower()


def numbers_without_a_source(terms: list[dict], doc: dict | None = None,
                             questions: dict | None = None
                             ) -> list[tuple[str, str, str]]:
    """``(term id, language, figure)`` for every number nobody else states.

    A definition explains a word that is already on the page. The moment one
    carries a figure the map does not, the glossary has become a second
    dataset -- unsourced, unversioned, and read as if it were the first.
    """
    hay = _haystack(doc, questions)
    bad: list[tuple[str, str, str]] = []
    for t in terms:
        for lang in ("en", "he"):
            for n in numbers_in(t.get(lang) or ""):
                probe = n.lower().replace(" ", "").replace(",", "")
                flat = hay.replace(" ", "").replace(",", "")
                if probe and probe not in flat:
                    bad.append((t["id"], lang, n))
    return bad


# ------------------------------------------------------------- by hand
def main() -> int:
    """Say what the loader sees, and run the number gate over it.

        python -m chains.glossary

    An absent file is not an error anywhere in the build, which is right --
    a glossary is an addition to a map, not a requirement of one -- but it
    does mean a file saved to the wrong place looks exactly like no file at
    all. This is the one command that tells them apart.
    """
    from chains import mapfile
    p = path_for()
    print(f"looking for : {p}")
    print(f"exists      : {p.exists()}")
    if not p.exists():
        print("\nNo glossary in this domain. Cards will show no terms, which "
              "is not an error -- but if you meant to add one, it belongs at "
              "the path above.")
        return 0
    try:
        terms = load()
    except GlossaryError as e:
        print(f"\nREFUSED: {e}")
        return 1
    print(f"terms       : {len(terms)}")
    try:
        from chains import questions
        qs = questions.fetch()
    except Exception:
        qs = {}
        print("questions   : not fetched (QUESTIONS_URL unset) -- a figure "
              "sourced only from a question will be reported below")
    bad = numbers_without_a_source(terms, mapfile.load(), qs)
    if bad:
        print(f"\n{len(bad)} figure(s) appear in a definition and nowhere "
              f"else:")
        for tid, lang, n in bad:
            print(f"   {tid} ({lang}): {n}")
        return 1
    print("numbers     : every figure has a source")
    return 0


__all__ = ["load", "validate", "find", "mark", "pairs", "for_page", "main",
           "numbers_in", "numbers_without_a_source", "path_for",
           "GlossaryError", "MAX_PER_CARD", "FILENAME"]


if __name__ == "__main__":                                # pragma: no cover
    raise SystemExit(main())
