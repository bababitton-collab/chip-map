"""The gate a price series passes before it is allowed into the store.

    from chains import price_guard
    price_guard.check("RHM.XETRA", rows, prior_close=988.50)   # or raises

WHY THIS IS NOT IN THE PROVIDER
-------------------------------
It is not a property of a vendor, it is a property of a number. The EODHD
client was replaced by a Yahoo client and the next one will be replaced by
something else; the rule that a missing price stops the build has to outlive
all of them, so it sits between whatever is fetching and prices.store, and
every provider is held to it.

WHAT IT REFUSES, AND WHY EACH ONE
---------------------------------
An EMPTY SERIES. The failure this repository keeps re-learning is the silent
one: liquidity.currency_of answered "USD" for a suffix it did not know and
2269.HK read 7.8x high for as long as nobody looked. An empty series is worse,
because the page still renders -- a station with no line simply looks calm.

A SERIES WITH NO USABLE CLOSE. Yahoo pads non-trading days with nulls inside
the window rather than omitting them, so "rows came back" is not the same as
"prices came back".

A MOVE NO MARKET MADE. A day-over-day jump past MAX_DAILY_MOVE is either a
corporate action nobody adjusted for, a decimal point, or a symbol that now
points at a different company -- the failure mode of a suffix table, where
``BA`` is Boeing in New York and BAE Systems in London and both answer with a
perfectly healthy series.

The move is measured on the ADJUSTED close, which is the point: a real split
is already adjusted away there, so a 2-for-1 does not trip the gate, while a
symbol that silently changed companies still does. The raw close is left
alone -- prices.py keeps it unadjusted on purpose, because a candle is one
day's own trading.

A threshold cannot separate a crash from a corruption and this one does not
try. It is set wide enough that a real market day never reaches it, and
anything that does is worth a human looking. Refusing is the cheap half of
that trade: a stopped build costs a morning, a published wrong number costs
the thing the whole record is for.
"""
from __future__ import annotations

# Wide on purpose. Circuit breakers on most of the venues here halt trading
# well before this, so a single session that clears it is a corporate action,
# a data error, or a different company.
MAX_DAILY_MOVE = 0.50
# The same rule across a gap in the stored series, where a weekend or a
# holiday means the two closes are further apart in time.
MAX_GAP_MOVE = 0.60


class PriceSanityError(RuntimeError):
    """A series that will not be stored. Always fatal, never downgraded.

    Carries the symbol in the message because the caller is looping over
    hundreds of them and "a price looked wrong" is not an actionable line in
    a build log.
    """


def _adj(row: dict) -> float | None:
    v = row.get("adjusted_close", row.get("adjClose", row.get("close")))
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _move(a: float, b: float) -> float:
    return abs(b - a) / a


def check(symbol: str, rows: list[dict] | None,
          prior_close: float | None = None,
          *, max_daily: float = MAX_DAILY_MOVE,
          max_gap: float = MAX_GAP_MOVE,
          allow_empty: bool = False) -> list[dict]:
    """The rows, or raise. Returns them so a caller can wrap a fetch inline.

    ``prior_close`` is the last adjusted close already in the store, when
    there is one; the first fetch of a new symbol has none and the gap test
    is skipped rather than guessed at.

    ``allow_empty`` exists for the one honest empty: a window that genuinely
    contains no session, asked for deliberately. It is not a default.
    """
    if rows is None:
        raise PriceSanityError(
            f"{symbol}: the provider returned None, which is not a price "
            f"series. Nothing is stored and the build stops here.")
    if not rows:
        if allow_empty:
            return rows
        raise PriceSanityError(
            f"{symbol}: the provider returned no bars at all. A symbol with "
            f"no series is a missing number, not a quiet one -- the station "
            f"would render calm and empty. Check the symbol spelling and the "
            f"exchange suffix before anything is published.")

    closes = [(r.get("date"), _adj(r)) for r in rows]
    usable = [(d, c) for d, c in closes if c is not None]
    if not usable:
        raise PriceSanityError(
            f"{symbol}: {len(rows)} bar(s) came back and not one carries a "
            f"usable close. Padding rows are not prices.")

    if prior_close is not None and prior_close > 0:
        first_date, first_close = usable[0]
        m = _move(prior_close, first_close)
        if m > max_gap:
            raise PriceSanityError(
                f"{symbol}: the first new close {first_close:g} on {first_date} "
                f"is {m:.0%} away from the stored close {prior_close:g}, past "
                f"the {max_gap:.0%} gap limit. Either a corporate action has "
                f"not been adjusted, or this symbol no longer points at the "
                f"same company. Nothing is stored.")

    for (d0, c0), (d1, c1) in zip(usable, usable[1:]):
        m = _move(c0, c1)
        if m > max_daily:
            raise PriceSanityError(
                f"{symbol}: the adjusted close moves {m:.0%} between {d0} "
                f"({c0:g}) and {d1} ({c1:g}), past the {max_daily:.0%} limit. "
                f"A split is already adjusted away in this series, so this is "
                f"a data error or a changed symbol. Nothing is stored.")
    return rows


def last_stored_close(symbol: str) -> float | None:
    """The store's last adjusted close, or None if it holds nothing yet."""
    from chains import prices
    df = prices.load(symbol)
    if df.is_empty():
        return None
    v = df.sort("date")["adj_close"][-1]
    return float(v) if v is not None else None


__all__ = ["MAX_DAILY_MOVE", "MAX_GAP_MOVE", "PriceSanityError", "check",
           "last_stored_close"]
