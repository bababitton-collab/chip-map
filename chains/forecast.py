"""Scoring the forecasts. Forward only, and the arithmetic is deliberately dull.

    python -m chains.forecast          # print the ledger as it stands

WHAT IS BEING CLAIMED
---------------------
A question is answered on a known day. The answer points one way or the other,
and the baskets that gain and lose if it does were written down BEFORE the
event, in data/watch.json, in git. The claim is then narrow: from the first
close after the mark, the win basket outruns the lose basket, and the market as
a whole is netted out. Nothing here says by how much, or for how long, or that
anybody should act on it.

THERE IS NO BACKTEST HERE AND THERE CANNOT BE ONE
--------------------------------------------------
Every row is scored from a mark that already existed, against baskets that
already existed. chains/answers.py refuses a forecast whose baskets differ from
the registered ones, so the hypothesis cannot move after the fact. That is the
whole design: a forward test is not a backtest with better manners, it is a
different object, and the only thing that makes it one is that the claim was
written down first and cannot be edited.

The consequence is that the sample grows one question at a time and is small
for a long while. ``capital_rule`` says so in the output, on every horizon, at
every N. See the note on N below.

THE CALENDAR COMES FROM THE PRICES
----------------------------------
"The first NYSE session strictly after the mark" needs a session list, and this
package has no holiday table. Rather than write one -- a hand-typed calendar is
a silent, annual source of off-by-one-day errors -- the sessions are read out of
the price store: a date on which at least half the US-listed symbols printed a
bar is a session. Checked against the real store this reproduces the exchange
calendar exactly, weekends and holidays included, and it cannot drift from the
data it is used to index, which a separate table can.

ONLY CLOSES EXIST
-----------------
The store has adjusted closes and nothing else. So entry is a CLOSE -- the
close of the first session after the mark -- and every horizon is measured
close to close. There is no open in this data and none is invented. What that
costs is honest and worth stating: a mark made mid-session is scored from that
day's close, so part of any reaction is already in the entry price. That makes
the test harder, not easier, which is the right direction for the error to run.

A NON-US LINE MOVES ON ITS OWN CALENDAR
---------------------------------------
Six map symbols trade in Taipei, Seoul or Frankfurt. Their bars do not land on
NYSE sessions. Each is read as its last close on or before the session date, so
on a day its own market was shut it contributes a flat return. That is a real
staleness effect, it is not corrected, and it is recorded here rather than
hidden behind an interpolation nobody would see.
"""
from __future__ import annotations

import datetime as dt
import json
import statistics
from bisect import bisect_right

from chains import mapfile, prices
from chains.answers import (BENCHMARK, DEFAULT_ORDER, HORIZONS,
                            HORIZONS_R2, ORDERS)

# A date on which at least this share of US-listed symbols printed is a
# session. Half is far above any plausible outage and far below the fraction
# that prints on a real trading day.
SESSION_QUORUM = 0.5

# What travels to the page per symbol. The chart is a 60-point sparkline; more
# points would be invisible and the snapshot has a hard ceiling.
MAX_SERIES = 60

# Below this the hit rate is noise dressed as evidence. It is emitted with the
# summary at every N so the number is never read without it.
MIN_N_FOR_CAPITAL = 30
CAPITAL_RULE = f"no capital decision below N={MIN_N_FOR_CAPITAL}"


# ----------------------------------------------------------------- calendar
def sessions(symbols: list[str] | None = None,
             quorum: float = SESSION_QUORUM) -> list[dt.date]:
    """The exchange calendar, as the price store actually witnessed it."""
    symbols = symbols or [s for s in prices.symbols_in_map(mapfile.load())
                          if s.endswith(".US")]
    counts: dict[dt.date, int] = {}
    n_seen = 0
    for sym in symbols:
        df = prices.load(sym)
        if df.is_empty():
            continue
        n_seen += 1
        for d in df["date"].to_list():
            counts[d] = counts.get(d, 0) + 1
    if not n_seen:
        return []
    need = max(1, int(n_seen * quorum))
    return sorted(d for d, c in counts.items() if c >= need)


def entry_session(marked_at: str, cal: list[dt.date]) -> dt.date | None:
    """The first session STRICTLY after the mark, or None if it has not come.

    Strictly after, so a mark made during a session is entered at the NEXT
    close and not the one that was printing while it was written.
    """
    if not cal:
        return None
    day = dt.date.fromisoformat(str(marked_at)[:10])
    i = bisect_right(cal, day)
    return cal[i] if i < len(cal) else None


# ------------------------------------------------------------------ prices
def closes(symbol: str) -> dict[dt.date, float]:
    df = prices.load(symbol)
    if df.is_empty():
        return {}
    return dict(zip(df["date"].to_list(), df["adj_close"].to_list()))


def as_of(series: dict[dt.date, float], day: dt.date,
          days_sorted: list[dt.date]) -> float | None:
    """Last close on or before ``day``. See the note on non-US lines."""
    i = bisect_right(days_sorted, day)
    return series[days_sorted[i - 1]] if i else None


class Book:
    """Every symbol's closes, loaded once for a whole ledger build."""

    def __init__(self, symbols: list[str]):
        self.series: dict[str, dict[dt.date, float]] = {}
        self.days: dict[str, list[dt.date]] = {}
        for s in symbols:
            c = closes(s)
            if c:
                self.series[s] = c
                self.days[s] = sorted(c)

    def has(self, symbol: str) -> bool:
        return symbol in self.series

    def at(self, symbol: str, day: dt.date) -> float | None:
        if symbol not in self.series:
            return None
        return as_of(self.series[symbol], day, self.days[symbol])


# ------------------------------------------------------------- the measures
def symbol_returns(book: Book, symbol: str, entry: dt.date,
                   window: list[dt.date]) -> list[float | None]:
    """Cumulative return since the entry close, one point per session."""
    base = book.at(symbol, entry)
    if not base:
        return [None] * len(window)
    return [(None if (v := book.at(symbol, d)) is None else v / base - 1.0)
            for d in window]


def basket_returns(book: Book, symbols: list[str], entry: dt.date,
                   window: list[dt.date]) -> list[float | None]:
    """Equal weight of the members' cumulative returns since entry.

    Equal weight of CUMULATIVE returns, not a daily-rebalanced index: the
    basket is a position taken once, at entry, and held. EW_MAP below is the
    other thing on purpose -- it is a benchmark, and a benchmark is rebalanced.
    """
    have = [s for s in symbols if book.has(s)]
    if not have:
        return [None] * len(window)
    per = [symbol_returns(book, s, entry, window) for s in have]
    out: list[float | None] = []
    for i in range(len(window)):
        vals = [p[i] for p in per if p[i] is not None]
        out.append(sum(vals) / len(vals) if vals else None)
    return out


def ew_map(book: Book, symbols: list[str], entry: dt.date,
           window: list[dt.date]) -> list[float | None]:
    """Equal-weight daily return of the priced map, rebalanced daily.

    Each session, the mean of that session's simple returns across every symbol
    that printed on both it and the session before; compounded from entry. A
    symbol missing on a day drops out of that day's mean and rejoins the next,
    which is what "uses the rest" has to mean for an index that is rebalanced
    every day.
    """
    have = [s for s in symbols if book.has(s)]
    out: list[float | None] = []
    level = 1.0
    prev = entry
    for d in window:
        rets = []
        for s in have:
            a, b = book.at(s, prev), book.at(s, d)
            if a and b:
                rets.append(b / a - 1.0)
        if rets:
            level *= 1.0 + sum(rets) / len(rets)
        out.append(level - 1.0)
        prev = d
    return out


def excess(win: list[float | None], lose: list[float | None],
           bench: list[float | None]) -> list[float | None]:
    """(win - EW_MAP) - (lose - EW_MAP), or win - EW_MAP with no lose side.

    Written the long way because that is what the claim says. With both sides
    present the benchmark cancels algebraically and the result is win - lose;
    that is not a simplification worth making in the code, because the day the
    two sides are weighted differently the cancellation stops being true and
    the formula has to already be the honest one.
    """
    out: list[float | None] = []
    for i in range(len(win)):
        w, b = win[i], bench[i]
        if w is None or b is None:
            out.append(None)
            continue
        l = lose[i] if lose else None
        out.append((w - b) - (l - b) if l is not None else w - b)
    return out


# -------------------------------------------------------------- the ledger
def score_one(f: dict, book: Book, cal: list[dt.date],
              node_symbols: list[str], symbol_of: dict[str, str],
              log: list[str]) -> dict | None:
    entry = entry_session(f["marked_at"], cal)
    order = f.get("order", DEFAULT_ORDER)
    if entry is None:
        return {"id": f["id"], "qid": f["qid"], "status": f["status"],
                "order": order,
                "direction": f["direction"], "marked_at": f["marked_at"],
                "entry_session": None, "pending_entry": True,
                "symbols": [], "series": [], "horizons": {},
                "note": "no session has closed since the mark yet"}

    window = [d for d in cal if d >= entry]
    win_syms, lose_syms = [], []
    for side, ids in (("win", f["win"]), ("lose", f["lose"])):
        for i in ids:
            s = symbol_of.get(i)
            if not s:
                log.append(f"{f['id']}: {side} leg {i!r} has no price symbol "
                           f"in the map -- skipped")
                continue
            if not book.has(s):
                log.append(f"{f['id']}: {side} leg {i} ({s}) has no price "
                           f"line -- skipped")
                continue
            (win_syms if side == "win" else lose_syms).append((i, s))

    if not win_syms:
        log.append(f"{f['id']}: no win leg has a price line -- not scored")
        return None

    w = basket_returns(book, [s for _, s in win_syms], entry, window)
    l = basket_returns(book, [s for _, s in lose_syms], entry, window) \
        if lose_syms else []
    b = ew_map(book, node_symbols, entry, window)
    exc = excess(w, l, b)

    rows = []
    for side, legs in (("win", win_syms), ("lose", lose_syms)):
      for i, s in legs:
        r = symbol_returns(book, s, entry, window)
        rows.append({
            "id": i, "sym": s, "side": side,
            "entry": round(book.at(s, entry), 4),
            "last": round(v, 4) if (v := book.at(s, window[-1])) else None,
            "ret": None if r[-1] is None else round(r[-1], 6),
            "exc": None if (r[-1] is None or b[-1] is None)
                   else round(r[-1] - b[-1], 6),
            "series": [None if x is None else round(x, 5)
                       for x in r[-MAX_SERIES:]],
        })

    hz: dict[str, dict] = {}
    # The row's own horizons, not the module's: an indirect forecast is scored
    # at 40 sessions as well, and 40 is not a horizon a direct row has.
    for h in (f.get("horizons") or ORDERS[order]):
        # h sessions AFTER entry: window[0] is entry itself.
        if len(window) > h and exc[h] is not None:
            e = exc[h]
            hz[str(h)] = {"excess": round(e, 6),
                          "win": None if w[h] is None else round(w[h], 6),
                          "lose": None if not l or l[h] is None
                                  else round(l[h], 6),
                          "bench": None if b[h] is None else round(b[h], 6),
                          "date": window[h].isoformat(),
                          "hit": bool(e) and (e > 0) == (f["direction"] > 0)}
        else:
            hz[str(h)] = None

    return {
        "id": f["id"], "qid": f["qid"], "status": f["status"], "order": order,
        "direction": f["direction"], "marked_at": f["marked_at"],
        "entry_session": entry.isoformat(),
        "entry_close": window[-1].isoformat(),
        "sessions": len(window) - 1,
        "benchmark": BENCHMARK,
        "symbols": rows,
        "series": [None if x is None else round(x, 5)
                   for x in exc[-MAX_SERIES:]],
        "bench_series": [None if x is None else round(x, 5)
                         for x in b[-MAX_SERIES:]],
        "excess": None if exc[-1] is None else round(exc[-1], 6),
        "horizons": hz,
        "pending_entry": False,
    }


def summarise(rows: list[dict], horizons: tuple[int, ...] = HORIZONS) -> dict:
    """One order's numbers. Never two orders' -- see ORDERS in answers.py."""
    out: dict[str, dict] = {}
    for h in horizons:
        vals = [r["horizons"][str(h)]["excess"] for r in rows
                if r.get("horizons", {}).get(str(h))]
        hits = [r["horizons"][str(h)]["hit"] for r in rows
                if r.get("horizons", {}).get(str(h))]
        n = len(vals)
        out[str(h)] = {
            "n": n,
            "hits": sum(1 for x in hits if x),
            "hit_rate": round(sum(1 for x in hits if x) / n, 4) if n else None,
            "mean_excess": round(statistics.fmean(vals), 6) if n else None,
            "median_excess": round(statistics.median(vals), 6) if n else None,
            "n_pending": sum(1 for r in rows
                             if not r.get("horizons", {}).get(str(h))),
        }
    # "Scored" means at least one horizon has locked. A forecast entered
    # yesterday is a real row with a real position and nothing to say yet; it
    # belongs in pending, not in the denominator of a hit rate.
    scored = [r for r in rows if any((r.get("horizons") or {}).values())]
    return {
        "horizons": out,
        "hz": [str(h) for h in horizons],
        "n_forecasts": len(rows),
        "n_scored": len(scored),
        "n_pending": len(rows) - len(scored),
        "min_n": MIN_N_FOR_CAPITAL,
        "capital_rule": CAPITAL_RULE,
        "benchmark": BENCHMARK,
    }


def build(forecasts: list[dict], doc: dict | None = None,
          log: list[str] | None = None,
          cal: list[dt.date] | None = None) -> dict:
    """The ledger: {summary, rows}. Empty and valid when nothing is marked."""
    log = [] if log is None else log
    doc = doc or mapfile.load()
    symbol_of = {r["id"]: r["price_symbol"]
                 for coll in ("nodes", "subnodes") for r in doc.get(coll, [])
                 if r.get("price_symbol")}
    node_symbols = [n["price_symbol"] for n in doc.get("nodes", [])
                    if n.get("price_symbol")
                    and n.get("price_symbol_kind") != "none"]
    if not forecasts:
        return {"summary": _summaries([]), "rows": []}

    wanted = set(node_symbols)
    for f in forecasts:
        for i in list(f["win"]) + list(f["lose"]):
            if i in symbol_of:
                wanted.add(symbol_of[i])
    book = Book(sorted(wanted))
    cal = sessions([s for s in node_symbols if s.endswith(".US")])         if cal is None else cal

    rows = []
    for f in forecasts:
        r = score_one(f, book, cal, node_symbols, symbol_of, log)
        if r:
            rows.append(r)
    rows.sort(key=lambda r: (r["marked_at"], r["id"]), reverse=True)
    return {"summary": _summaries(rows), "rows": rows}


def _summaries(rows: list[dict]) -> dict:
    """The direct summary, with the indirect one hanging beneath it.

    The shape is deliberate. The top level is order 1 and nothing else, so
    every existing reader -- the board's headline tiles, the N=30 gate, the
    brief -- keeps reading the direct number it has always read. The indirect
    numbers are a sibling, at the same size, under their own name. Nothing adds
    the two together, because a hit rate over a mixed population of first- and
    second-order claims is not a hit rate for either.
    """
    direct = [r for r in rows if r.get("order", DEFAULT_ORDER) == 1]
    indirect = [r for r in rows if r.get("order", DEFAULT_ORDER) == 2]
    out = summarise(direct, HORIZONS)
    out["order"] = 1
    ind = summarise(indirect, HORIZONS_R2)
    ind["order"] = 2
    out["indirect"] = ind
    return out


def drop_symbol_series(ledger: dict) -> None:
    """Shed the per-symbol sparklines, keep the basket one.

    The first thing given up when the snapshot is over its ceiling: the basket
    line is the claim, the per-symbol lines are the detail behind it.
    """
    for r in ledger.get("rows", []):
        for s in r.get("symbols", []):
            s.pop("series", None)


def main() -> int:
    from chains import answers
    _a, forecasts, problems = answers.read()
    for why in problems:
        print(f"  DROPPED {why}")
    log: list[str] = []
    led = build(forecasts, log=log)
    for line in log:
        print(f"  {line}")
    s = led["summary"]
    print(f"\nforecasts scored {len(led['rows'])}  pending {s['n_pending']}")
    print(f"{s['capital_rule']}\n")
    print("   h    N  hits   rate   mean excess  median excess  pending")
    for h in HORIZONS:
        d = s["horizons"][str(h)]
        pct = lambda v: "     --" if v is None else f"{v * 100:+6.2f}%"  # noqa: E731
        rate = "  --" if d["hit_rate"] is None else f"{d['hit_rate']:.0%}"
        print(f"  {h:>2} {d['n']:>4} {d['hits']:>5}  {rate:>5}"
              f"  {pct(d['mean_excess'])}      {pct(d['median_excess'])}"
              f"    {d['n_pending']:>4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
