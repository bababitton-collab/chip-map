"""What is free and what is not, decided in one place.

WHY ONE FUNCTION
----------------
The paywall used to be a property each builder maintained for itself: the page
knew that a locked row carries no text, the brief knew which sections to skip,
publish_site scanned the bytes afterwards to catch what the other two got
wrong. That last one exists because the first two disagreed at least once.

``tier(item, ctx)`` is the single answer. Every builder asks it and none of
them decides. The byte-level scan in publish_site stays -- a negative property
should be checked on what is actually served, not inferred from the function
that was supposed to produce it -- but it now guards one rule instead of three.

DOMAIN-NEUTRAL
--------------
Nothing here names a chip, a company or a domain. It takes a kind and a
context and returns a word. A second map gets the same paywall without a line
of code, which is the only kind of paywall worth having in an engine that is
meant to carry more than one map.

THE RULE: THE PAST IS PUBLIC PROOF, THE FUTURE IS THE PRODUCT
-------------------------------------------------------------
FREE is what makes the argument checkable by a stranger:

  * the map itself -- stations, edges, layers, the pulse. It is sourced
    research and it is the reason to trust the rest.
  * the calendar -- who reports, which ticker, what date, confirmed or
    expected, the countdown, which chokepoint it touches. A date is not a
    finding; it is a public fact with a countdown on it.
  * the NEAREST upcoming question's text and its first ring. One worked
    example, so the offer is legible rather than described.
  * every question that has been ANSWERED, in full: its text and the yes/no
    rule it was classified by, the mark and its evidence, both rings, the
    stations and their prices, the chart, every horizon against every
    benchmark, whether it counted toward the score and why, and the revealed
    pre-registration contract a stranger recomputes the hash of. A claim stops
    being an edge the moment its answer is public, and a skeptic who has to pay
    to check the record is being asked to take it on trust.
  * the scoreboard of finished forecasts, and brand and method copy.

LOCKED is what has not happened yet:

  * every unanswered question's text and sentences, but the nearest one's,
  * their constellations, and the second ring of any unanswered question --
    derived work about a claim still ahead,
  * the mark, members, prices and results of a question not yet answered,
  * the contract bytes of an unanswered question (its hash is public; the bytes
    carry the paid wording),
  * the paid halves of the letter.

The line is between "here is the record, check it" and "here is what we think
happens next".
"""
from __future__ import annotations

FREE = "free"
LOCKED = "locked"

# Every kind the engine asks about. A builder passing anything else is a
# builder that grew a new surface without deciding which side it is on, and it
# gets an exception rather than a guess.
KINDS = frozenset({
    "map", "edge", "layer", "pulse", "chokepoint",     # the map itself
    "calendar_row",                                    # who / ticker / date
    "question_text",                                   # q, yes, no, why
    "constellation",                                   # rings 1 and 2
    "ring2",                                           # the second ring alone
    "mark",                                            # an answer, once given
    "forecast_closed",                                 # a finished 40 sessions
    "forecast_active",                                 # anything still running
    "member_prices",                                   # entry/last/spread rows
    "contract",                                        # the hashed contract bytes
    "brand", "method",                                 # copy
})

# The kinds that are free whatever the context.
ALWAYS_FREE = frozenset({
    "map", "edge", "layer", "pulse", "chokepoint",
    "calendar_row", "forecast_closed", "brand", "method",
})

# The kinds that are free once the question is answered and locked before --
# not even the one worked example opens them early.
LOCKED_UNTIL_ANSWERED = frozenset({
    "ring2", "forecast_active", "member_prices", "contract", "mark",
})


class AccessError(ValueError):
    """A kind nobody decided about."""


def tier(item: str, ctx: dict | None = None) -> str:
    """``"free"`` or ``"locked"``, for one thing in one context.

    ``ctx`` carries only what the rule needs:
      ``nearest``  this is the next question on the calendar
      ``answered`` this question already has a settled answer
    """
    if item not in KINDS:
        raise AccessError(
            f"{item!r} is not a kind chains/access.py knows. Add it to KINDS "
            f"and decide which side of the line it is on -- a new surface "
            f"defaulting to free is how a paywall leaks.")
    ctx = ctx or {}
    if item in ALWAYS_FREE:
        return FREE
    # Resolved is public, whatever it is.
    if ctx.get("answered"):
        return FREE
    if item in LOCKED_UNTIL_ANSWERED:
        return LOCKED
    # question_text, constellation: free for the one worked example only.
    return FREE if ctx.get("nearest") else LOCKED


def is_free(item: str, ctx: dict | None = None) -> bool:
    return tier(item, ctx) == FREE


def open_question(row: dict, nearest_id: str | None = None) -> bool:
    """Whether one watch row's text is free.

    The row's own shape decides it: a row that has been answered, or the row
    that is next on the calendar.
    """
    ctx = {"nearest": row.get("id") == nearest_id,
           "answered": bool(row.get("answered"))}
    return is_free("question_text", ctx)


__all__ = ["tier", "is_free", "open_question", "FREE", "LOCKED", "KINDS",
           "ALWAYS_FREE", "LOCKED_UNTIL_ANSWERED", "AccessError"]
