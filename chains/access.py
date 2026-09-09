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

THE RULE
--------
FREE is what makes the argument checkable by a stranger:

  * the map itself -- stations, edges, layers, the pulse. It is sourced
    research and it is the reason to trust the rest.
  * the calendar -- who reports, which ticker, what date, confirmed or
    expected, the countdown, which chokepoint it touches. A date is not a
    finding; it is a public fact with a countdown on it.
  * the NEAREST upcoming question, in full: its text, what yes and no sound
    like, why it matters, and both constellation rings. One worked example,
    complete, so the offer is legible rather than described.
  * every question that has already been ANSWERED -- its text and its mark.
    A claim stops being an edge the moment its answer is public, and keeping
    it behind glass afterwards would only hide the record.
  * the scoreboard of FINISHED forecasts: what was claimed, and what happened
    over the full forty sessions. The track record is the product's evidence
    and evidence nobody can see is not evidence.
  * brand and method copy.

LOCKED is the working position:

  * every other question's text and its three sentences,
  * their constellations, both rings,
  * the second ring anywhere -- it is derived work, not a public fact,
  * everything about a forecast still in flight: the members, their prices,
    the spreads, the chart,
  * the paid halves of the letter.

The line is between "here is the argument and here is the record" and "here is
the position I am in right now".
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
    "brand", "method",                                 # copy
})

# The kinds that are free whatever the context.
ALWAYS_FREE = frozenset({
    "map", "edge", "layer", "pulse", "chokepoint",
    "calendar_row", "forecast_closed", "brand", "method",
})

# The kinds that are never free, whatever the context.
ALWAYS_LOCKED = frozenset({
    "ring2", "forecast_active", "member_prices",
})


class AccessError(ValueError):
    """A kind nobody decided about."""


def tier(item: str, ctx: dict | None = None) -> str:
    """``"free"`` or ``"locked"``, for one thing in one context.

    ``ctx`` carries only what the rule needs:
      ``nearest``  this is the next question on the calendar
      ``answered`` this question already has a mark
    """
    if item not in KINDS:
        raise AccessError(
            f"{item!r} is not a kind chains/access.py knows. Add it to KINDS "
            f"and decide which side of the line it is on -- a new surface "
            f"defaulting to free is how a paywall leaks.")
    ctx = ctx or {}
    if item in ALWAYS_FREE:
        return FREE
    if item in ALWAYS_LOCKED:
        return LOCKED
    # question_text, constellation, mark: free for the one worked example and
    # for anything the answer has already made public.
    if ctx.get("answered"):
        return FREE
    if item == "mark":
        return FREE if ctx.get("answered") else LOCKED
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
           "ALWAYS_FREE", "ALWAYS_LOCKED", "AccessError"]
