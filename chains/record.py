"""The track record of a question whose answer is in.

    from chains import record
    record.attach(data, doc, book, cal, today)   # adds "record" to resolved cards

WHAT THIS ADDS AND WHAT IT REFUSES TO ADD
-----------------------------------------
A resolved card already carries the question, the rule it was classified by,
the mark, the baskets and -- when a direction was registered -- the scored
horizons. What it did not carry is the thing a reader asks for first: what each
leg actually did, day by day, since the claim was signed.

So each leg gets a row with its ticker, its side, the price on the day the
question was signed, the entry price where there was an entry, the last close,
the move in the last session, and the move since the signature. Beside them the
same window is measured for the equal-weight map and for SOX, using
chains.forecast -- the scoring code this page has always used. No new
methodology is invented here: the official score stays exactly what
track.official() says it is, and for a question answered without a direction it
stays "not scored", not a number.

WHAT A MISSING SERIES LOOKS LIKE
--------------------------------
A leg the price store cannot serve cleanly over the window is a row that says
"no clean series" and carries no numbers. It is never dropped -- a dropped leg
is a basket that looks smaller than the one that was signed -- and it is never
filled in from a neighbouring day.

A leg priced through an ADR or an OTC line rather than its home listing says so
on the row, with the symbol that was actually used. Two of the map's stations
trade in Seoul and Tokyo; the number on the row is the one that was traded in
New York, and a reader is entitled to know which.
"""
from __future__ import annotations

import datetime as dt

from chains import forecast, prices

# The candle window is drawn from the signature, like every other number here.
# Big enough to read a session off. The page lays them two to a row on a
# desktop and one to a row on a phone, and the SVG scales to its box.
GROUPS = ("win", "lose")
# The second ring is measured and shown, never averaged into the basket: the
# ledger reports the two separately and so does this page. A ring-2 leg gets a
# row and a bar of its own move, and no weight and no contribution, because it
# contributed nothing to a basket it was never in.
RING2 = ("win2", "lose2")
ALL_GROUPS = GROUPS + RING2


def _round(v, n=4):
    """A price, rounded. Prices are prices; they are never multiplied."""
    return None if v is None else round(float(v), n)


def _pct(v, n=4):
    """A fraction as a percentage, converted once at this boundary.

    The same rule chains/track.py uses, and for the same reason: the page adds
    a per-cent sign and nothing else, so a number that arrives as 0.03 would be
    drawn as 0.03% instead of 3%.
    """
    return None if v is None else round(float(v) * 100, n)


def _day(v) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def kinds_for(doc: dict) -> dict[str, dict]:
    """{node id: {symbol, kind, ticker}} for every priced entry on the map."""
    out = {}
    for coll in ("nodes", "subnodes"):
        for n in doc.get(coll, []):
            if n.get("price_symbol"):
                out[n["id"]] = {"symbol": n["price_symbol"],
                                "kind": n.get("price_symbol_kind") or "primary",
                                "ticker": n.get("ticker") or n["id"].upper()}
    return out


def window_from(day: dt.date | None, cal: list[dt.date],
                today: dt.date) -> list[dt.date]:
    """Sessions from the signature's session through the last one that closed.

    The signature's own session is the baseline -- the last close on or before
    the day the contract was committed -- so the first point is zero and every
    number after it is measured against a price that existed when the claim
    was made.
    """
    if day is None or not cal:
        return []
    # A signature with no session at or after it has nothing to measure yet --
    # a contract signed after the last close, or dated ahead. Baselining it on
    # the last session would report a move of zero as if it were a measurement.
    if not any(d >= day for d in cal):
        return []
    base = max((d for d in cal if d <= day), default=None)
    if base is None:
        return []
    return [d for d in cal if base <= d <= today]


def leg_rows(legs: dict, doc: dict, book, kinds: dict,
             window: list[dt.date], entry: dt.date | None,
             cal: list[dt.date]) -> list[dict]:
    """One row per leg of the signed basket, in the order it was signed."""
    if not window:
        return []
    base_day, last_day = window[0], window[-1]
    prev_day = window[-2] if len(window) > 1 else None
    # A basket is the equal weight of the legs that actually have a series, so
    # a leg's share of it is 1/n of that side -- counted first, because a leg
    # with no series must not dilute the ones that have one.
    priced = {g: sum(1 for nid in (legs.get(g) or [])
                     if (kinds.get(nid) or {}).get("symbol")
                     and book.has(kinds[nid]["symbol"]))
              for g in GROUPS}
    rows = []
    for group in ALL_GROUPS:
        ring = 1 if group in GROUPS else 2
        for nid in legs.get(group) or []:
            info = kinds.get(nid) or {}
            sym = info.get("symbol")
            row = {"id": nid, "tk": info.get("ticker") or nid.upper(),
                   "group": group, "ring": ring, "symbol": sym,
                   "priced_via": info.get("kind") or "primary",
                   "currency": prices.currency_for(sym) if sym else None}
            if not sym or not book.has(sym):
                rows.append({**row, "no_series": "no clean series",
                             "commit_close": None, "entry_close": None,
                             "last": None, "day_pct": None,
                             "since_commit": None, "since_entry": None,
                             "entry_date": None, "weight": None,
                             "contribution": None})
                continue
            commit_close = book.at(sym, base_day)
            last = book.at(sym, last_day)
            prev = book.at(sym, prev_day) if prev_day else None
            entry_close = book.at(sym, entry) if entry else None
            since = (None if not commit_close or last is None
                     else last / commit_close - 1.0)
            n = priced.get(group) or 1
            rows.append({
                **row,
                "weight": round(1.0 / n, 4) if ring == 1 else None,
                # What this leg put into its side's number, in percentage
                # points: its own move over the window, divided by the number
                # of legs sharing that side.
                "contribution": (None if ring == 2 or since is None
                                 else _pct(since / n)),
                "commit_close": _round(commit_close),
                "entry_date": entry.isoformat() if entry else None,
                "entry_close": _round(entry_close),
                "last": _round(last),
                "day_pct": _pct(None if not prev or last is None
                                else last / prev - 1.0),
                "since_commit": _pct(None if not commit_close or last is None
                                     else last / commit_close - 1.0),
                "since_entry": _pct(None if not entry_close or last is None
                                    else last / entry_close - 1.0),
                "no_series": None,
            })
    return rows


def benchmarks(legs: dict, book, node_symbols: list[str], kinds: dict,
               window: list[dt.date], doc: dict | None = None) -> dict:
    """The basket, the equal-weight map and SOX over the same window.

    forecast.basket_returns and forecast.ew_map are the functions the ledger
    scores with; the only thing different here is where the window starts.
    """
    if not window:
        return {}
    base = window[0]

    def syms(ids):
        return [kinds[i]["symbol"] for i in ids
                if i in kinds and book.has(kinds[i]["symbol"])]

    out = {"from": base.isoformat(), "to": window[-1].isoformat(),
           "sessions": len(window) - 1}
    lines: dict[str, list] = {}
    for group in GROUPS:
        ids = legs.get(group) or []
        series = (forecast.basket_returns(book, syms(ids), base, window)
                  if syms(ids) else None)
        out[group] = _pct(series[-1]) if series else None
        if series:
            lines[group] = [_pct(v) for v in series]
    ew = forecast.ew_map(book, node_symbols, base, window)
    sox = forecast.basket_returns(
        book, [forecast.benchmark_in(doc)["symbol"]], base, window)
    out["ew"] = _pct(ew[-1]) if ew else None
    out["sox"] = _pct(sox[-1]) if sox else None
    if ew:
        lines["ew"] = [_pct(v) for v in ew]
    if sox:
        lines["sox"] = [_pct(v) for v in sox]
    # The same numbers as above, kept for every session instead of only the
    # last one, so the question's page can draw the three lines. Every measure
    # here returns one point per session in the window, so the dates and the
    # values are the same length and a crosshair cannot read a day out.
    out["series"] = {"dates": [d.isoformat() for d in window], **lines}
    # Both sides are already percentages here, so the difference is taken in
    # percentage points and not converted a second time.
    win = out.get("win")
    out["win_ew"] = (None if win is None or out["ew"] is None
                     else round(win - out["ew"], 4))
    out["win_sox"] = (None if win is None or out["sox"] is None
                      else round(win - out["sox"], 4))
    return out


def companies(rows: list[dict], book, window: list[dt.date]) -> list[dict]:
    """Every basket company as one line, rebased to 100 at the first session.

    Read from adjusted closes -- the same source the basket and both
    benchmarks are measured from -- and not from the raw OHLC bars. A bar
    needs all four prices to count, and over a window this short several
    companies have none: ARM had no drawable bar at all here while its closes
    were complete. Rebasing each line on whatever day it first had a bar would
    put them on different first days and make lines that are not comparable
    look as though they were.
    """
    if not window:
        return []
    out = []
    for r in rows:
        sym = r.get("symbol")
        if r.get("ring") != 1 or not sym or not book.has(sym):
            continue
        base = book.at(sym, window[0])
        if not base:
            continue
        out.append({"id": r["id"], "tk": r["tk"], "symbol": sym,
                    "group": r.get("group"),
                    "values": [None if (v := book.at(sym, d)) is None
                               else _round(100.0 * v / base) for d in window]})
    return out


def for_card(rec: dict, doc: dict, book, node_symbols: list[str],
             kinds: dict, cal: list[dt.date], today: dt.date) -> dict | None:
    """The record block for one resolved card, or None if it cannot be dated."""
    commitment = rec.get("commitment") or {}
    signed = _day(commitment.get("committed_at"))
    if signed is None:
        return None
    window = window_from(signed, cal, today)
    if not window:
        return None
    # Every ring is a row; only the first ring is the basket. The benchmarks
    # below are handed the first ring alone, so the number on the tile stays
    # the number the ledger scored.
    all_legs = {g: list(rec.get(g) or []) for g in ALL_GROUPS}
    legs = {g: all_legs[g] for g in GROUPS}
    entry = _day(rec.get("entry_date"))
    rows = leg_rows(all_legs, doc, book, kinds, window, entry, cal)
    missing = [r["tk"] for r in rows if r.get("no_series")]
    return {
        "committed_at": commitment.get("committed_at"),
        "answer_date": rec.get("d"),
        "sha256": commitment.get("sha256"),
        "verdict": rec.get("status"),
        "baseline": window[0].isoformat(),
        "last_session": window[-1].isoformat(),
        "legs": rows,
        "no_series": missing,
        "benchmarks": benchmarks(legs, book, node_symbols, kinds, window,
                                 doc),
        # One line per basket company, rebased to a common first session.
        # Empty is a fact about the data and says so rather than drawing an
        # empty frame.
        "companies": companies(rows, book, window),
        # Untouched: whether this question counts, and the horizons it was
        # scored at, are track.official() and the ledger. Repeated here only so
        # the block can be rendered on its own.
        "official": dict(rec.get("official") or {}),
        "horizons": dict(rec.get("horizons") or {}),
    }


def table_row(rec: dict) -> dict:
    """One line of the master table, from a card that already has a record."""
    r = rec.get("record") or {}
    b = r.get("benchmarks") or {}
    ph = (rec.get("horizons") or {}).get(str(rec.get("primary_horizon")))
    return {
        "qid": rec.get("qid"), "who": rec.get("who"), "tk": rec.get("tk"),
        "answer_date": rec.get("d"), "kind": rec.get("kind") or "",
        "verdict": rec.get("status"),
        "basket": b.get("win"), "ew": b.get("ew"), "sox": b.get("sox"),
        "excess_ew": b.get("win_ew"),
        "sessions": b.get("sessions"),
        "committed_at": r.get("committed_at"),
        "sha": (r.get("sha256") or "")[:12],
        "scored": bool((rec.get("official") or {}).get("counts")),
        "official_excess": (ph or {}).get("spread") if ph else None,
        "no_series": len(r.get("no_series") or []),
    }


def attach(data: dict, doc: dict, book, node_symbols: list[str],
           cal: list[dt.date], today: dt.date) -> dict:
    """Add a record block to every resolved card, and the master table."""
    from chains.track import is_resolved
    kinds = kinds_for(doc)
    rows = []
    for rec in data.get("forecasts", []):
        if not is_resolved(rec):
            continue
        block = for_card(rec, doc, book, node_symbols, kinds, cal, today)
        if block:
            rec["record"] = block
            rows.append(table_row(rec))
    rows.sort(key=lambda r: (r.get("answer_date") or "", r.get("qid") or ""))
    data["record_table"] = rows
    return data
