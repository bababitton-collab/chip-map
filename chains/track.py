"""The forward test, as a page: every dated question, before and after it moves.

WHAT CHANGED IN v2
------------------
The first cut of this page listed forecasts. With nothing marked yet that was
an empty page under five dashes, which said the opposite of what the page is
for: the claims are registered NOW, in git, before the event. So the unit is
the dated question, not the forecast, and every one of the thirty-nine gets a
card the day it enters the watch list.

A card moves through states without moving on the page:

  upcoming  the date has not come and nothing is marked. The baskets are
            already fixed, so they are already listed -- that is the whole
            claim, made in public before the answer exists.
  none      the date passed and the answer was ambiguous, undisclosed or still
            open. No direction, so no forecast and no spreads, and the card
            says so rather than quietly vanishing.
  marked    an answer was marked but no session has closed since. Entry is the
            close AFTER the mark, so there is nothing to measure yet.
  tracking  entered, inside forty sessions.
  closed    every checkpoint scored.

REPORT-DAY CLOSE
----------------
The close on the session the question was answered on, or the last one before
it. It is the number a reader wants when asking "where was this when the news
landed". It stays absent until that day has arrived -- a report-day close for a
future date would be today's price wearing a future date.

THE SIGN IS DECIDED IN ONE PLACE
--------------------------------
A "no" mark says the win basket falls. Every difference goes through
``spread()``, which swaps the baskets before subtracting; nothing downstream
applies a direction again, because a second application would silently undo the
first and the page would report a correct forecast as a wrong one.
``expected_dir`` on a member row is the same rule applied to one station.

ORDERS ARE NOT POOLED
---------------------
Order 1 is the registered basket; order 2 is its second ring, read off the
map's supply edges. One card carries both, and every number is kept apart.
"""
from __future__ import annotations

import datetime as dt
import json
import statistics

from chains import forecast, mapfile, rings
from chains.answers import DEFAULT_ORDER, HORIZONS_R2, R2_SUFFIX, twin_id

CHECKPOINTS = HORIZONS_R2
STALE_AFTER = 3
MAX_POINTS = 90
CLOSED_AFTER = 40

GROUPS = ("win", "lose", "win2", "lose2")
STATES = ("tracking", "marked", "upcoming", "none", "closed")

# A mark that points nowhere: the question was answered and the answer supports
# no claim about which basket outruns which.
UNDIRECTED = frozenset({"none", "mixed", "open"})


# ------------------------------------------------------------------ the sign
def flip(direction: int, a, b) -> tuple:
    """The two baskets in the order the claim puts them."""
    return (a, b) if direction >= 0 else (b, a)


def spread(direction: int, up: float | None, down: float | None) -> float | None:
    """Sign-adjusted difference. The only place a direction is applied."""
    if up is None:
        return None
    if down is None:
        return up if direction >= 0 else -up
    return (up - down) if direction >= 0 else (down - up)


def expected_dir(group: str, direction: int) -> int:
    """+1 if the row is expected to rise under the claim, -1 if to fall."""
    base = 1 if group in ("win", "win2") else -1
    return base if direction >= 0 else -base


# ------------------------------------------------------------------ helpers
def _round(v, n=4):
    return None if v is None else round(v, n)


def _pct(v, n=4):
    return None if v is None else round(v * 100, n)


def symbols_for(doc: dict) -> tuple[dict[str, str], list[str]]:
    symbol_of = {r["id"]: r["price_symbol"]
                 for coll in ("nodes", "subnodes") for r in doc.get(coll, [])
                 if r.get("price_symbol")}
    node_symbols = [n["price_symbol"] for n in doc.get("nodes", [])
                    if n.get("price_symbol")
                    and n.get("price_symbol_kind") != "none"]
    return symbol_of, node_symbols


def _node(doc: dict, nid: str) -> dict:
    for coll in ("nodes", "subnodes"):
        for n in doc.get(coll, []):
            if n["id"] == nid:
                return n
    return {}


def label_of(doc: dict, nid: str) -> str:
    n = _node(doc, nid)
    if not n:
        return nid.upper()
    return n.get("short") or (n.get("ticker") or n["name"]).split(".")[0][:10]


def ticker_of(doc: dict, nid: str) -> str:
    return _node(doc, nid).get("ticker") or nid.upper()


def _stale(book, sym: str, upto: dt.date, cal: list[dt.date]) -> int:
    """Sessions between the member's last real close and ``upto``."""
    days = book.days.get(sym) or []
    if not days:
        return 0
    return sum(1 for d in cal if days[-1] < d <= upto)


def report_close(book, sym: str, d: str | None,
                 today: dt.date) -> float | None:
    """The close on the day the question is answered, or the last before it."""
    if not d:
        return None
    try:
        day = dt.date.fromisoformat(d)
    except ValueError:
        return None
    if day > today:
        return None
    return book.at(sym, day)


# ------------------------------------------------------------------ members
def members_for(legs: dict, direction: int, doc: dict, book, symbol_of: dict,
                d: str | None, today: dt.date, entry: dt.date | None,
                window: list[dt.date], cal: list[dt.date]) -> list[dict]:
    """One row per basket leg, the same columns in every state.

    A number that does not exist yet is absent. None becomes an em dash in the
    page and never a zero: a zero is a measurement.
    """
    out = []
    last_day = window[-1] if window else (cal[-1] if cal else today)
    prev_day = (window[-2] if len(window) > 1
                else (cal[-2] if len(cal) > 1 else None))
    for g in GROUPS:
        for i in legs.get(g) or []:
            sym = symbol_of.get(i)
            if not sym or not book.has(sym):
                continue
            base = book.at(sym, entry) if entry else None
            last = book.at(sym, last_day)
            prev = book.at(sym, prev_day) if prev_day else None
            old = _stale(book, sym, last_day, cal)
            out.append({
                "id": i, "tk": ticker_of(doc, i), "label": label_of(doc, i),
                "group": g, "expected_dir": expected_dir(g, direction),
                "report_close": _round(report_close(book, sym, d, today)),
                "entry_close": _round(base),
                "last": _round(last),
                "day_pct": _pct(None if not prev or last is None
                                else last / prev - 1.0),
                "since_pct": _pct(None if not base or last is None
                                  else last / base - 1.0),
                "stale": old if old > STALE_AFTER else 0,
            })
    return out


def _from_ledger(row: dict | None) -> dict:
    """The ledger's horizons, in this page's units and otherwise untouched."""
    if not row:
        return {}
    return {h: (None if not got else {"spread": _pct(got["excess"]),
                                      "hit": got["hit"], "date": got["date"]})
            for h, got in (row.get("horizons") or {}).items()}


# --------------------------------------------------------------- one record
def state_of(f: dict | None, entry: dt.date | None, day_index: int | None,
             status: str | None, past: bool) -> str:
    """Which of the five a card is in. One function, so the page cannot
    disagree with the tests about what it is looking at."""
    if entry is not None:
        return "closed" if day_index >= CLOSED_AFTER else "tracking"
    if f is not None:
        return "marked"
    if status in UNDIRECTED:
        return "none"
    return "none" if past else "upcoming"


def record(w: dict, f: dict | None, twin: dict | None, row: dict | None,
           row2: dict | None, mark: dict | None, book, cal: list[dt.date],
           doc: dict, symbol_of: dict, node_symbols: list[str],
           today: dt.date, ring2: dict) -> dict:
    """One dated question, in whatever state it is in."""
    status = (mark or {}).get("status")
    direction = f["direction"] if f else 1
    entry = forecast.entry_session(f["marked_at"], cal) if f else None
    d = w.get("d")
    past = bool(d and dt.date.fromisoformat(d) < today)

    out = {
        "qid": w["id"], "id": (f or {}).get("id") or w["id"],
        "who": w.get("who") or w["id"], "tk": w.get("tk"), "d": d,
        "confirmed": bool(w.get("confirmed")),
        "status": status, "direction": direction,
        "auto": bool((mark or {}).get("auto", False)),
        "marked_at": (f or {}).get("marked_at") or (mark or {}).get("updated"),
        "entry_date": entry.isoformat() if entry else None,
        "win": list(w.get("win") or []), "lose": list(w.get("lose") or []),
        "win2": list(ring2.get("win2") or []),
        "lose2": list(ring2.get("lose2") or []),
        "ring2_edges": list(ring2.get("ring2_edges") or []),
    }
    out["has_r2"] = bool(out["win2"] or out["lose2"])
    # The question text is the product boundary: present only where the row is
    # already open, and absent rather than empty on a locked one.
    if w.get("q"):
        out["q"] = w["q"]

    legs = {g: out[g] for g in GROUPS}
    window = ([x for x in cal if x >= entry][:MAX_POINTS + 1]
              if entry else [])

    if entry is not None:
        out["day_index"] = len(window) - 1
        nxt = next((h for h in CHECKPOINTS if h > out["day_index"]), None)
        out["next_checkpoint"] = nxt
        out["sessions_to"] = None if nxt is None else nxt - out["day_index"]
    else:
        out["day_index"] = None
        out["next_checkpoint"] = None
        out["sessions_to"] = None
    out["state"] = state_of(f, entry, out["day_index"], status, past)

    out["members"] = members_for(legs, direction, doc, book, symbol_of,
                                 d, today, entry, window, cal)

    if entry is None:
        out.update({"series": None, "today": {}, "horizons": {},
                    "horizons2": {}})
        return out

    def syms(ids):
        return [symbol_of[i] for i in ids
                if i in symbol_of and book.has(symbol_of[i])]

    ser = {g: (forecast.basket_returns(book, syms(legs[g]), entry, window)
               if legs[g] else None) for g in GROUPS}
    ew = forecast.ew_map(book, node_symbols, entry, window)
    out["series"] = {
        "dates": [x.isoformat() for x in window],
        "ew": [_pct(v) for v in ew],
        **{g: ([_pct(v) for v in ser[g]] if ser[g] else None) for g in GROUPS},
    }

    def last(name):
        s = out["series"][name]
        return s[-1] if s else None

    ew_now = out["series"]["ew"][-1]
    up, down = flip(direction, last("win"), last("lose"))
    up2, down2 = flip(direction, last("win2"), last("lose2"))
    out["today"] = {
        "win_lose": _round(spread(direction, last("win"), last("lose"))),
        "win_ew": _round(spread(direction, last("win"), ew_now)),
        "win2_lose2": _round(spread(direction, last("win2"), last("lose2"))),
        "win2_ew": _round(spread(direction, last("win2"), ew_now)),
        "up": _round(up), "down": _round(down),
        "up2": _round(up2), "down2": _round(down2), "ew": _round(ew_now),
    }
    out["horizons"] = _from_ledger(row)
    out["horizons2"] = _from_ledger(row2)
    return out


# ---------------------------------------------------------------- the build
BANDS = {"tracking": 0, "marked": 1, "upcoming": 2, "none": 3, "closed": 4}


def _desc(v: str | None) -> str:
    """A key that sorts descending under an ascending sort."""
    return "".join(chr(0x10FFFC - ord(c)) for c in (v or ""))


def sort_key(r: dict):
    """Tracking first, newest entry first; then marked, newest first; then
    upcoming by date; then answered-but-undirected; then closed, at the
    bottom. A card never moves band without its state changing."""
    band = BANDS.get(r["state"], 9)
    if r["state"] == "tracking":
        return (band, _desc(r.get("entry_date")), r["qid"])
    if r["state"] in ("upcoming", "none"):
        return (band, r.get("d") or "9999-12-31", r["qid"])
    return (band, _desc(r.get("marked_at") or r.get("d")), r["qid"])


def summarise(records: list[dict]) -> dict:
    scored = [r for r in records if r.get("entry_date")]
    upcoming = [r for r in records if r["state"] == "upcoming"]

    def at(key, h, want):
        vals = [r[key].get(str(h)) for r in scored if r.get(key, {}).get(str(h))]
        vals = [v for v in vals if v]
        if not vals:
            return {"n": 0, "value": None}
        if want == "hit":
            return {"n": len(vals),
                    "value": round(sum(1 for v in vals if v["hit"])
                                   / len(vals), 4)}
        return {"n": len(vals),
                "value": round(statistics.fmean(v["spread"] for v in vals), 4)}

    nxt = min(upcoming, key=lambda r: r.get("d") or "9999", default=None)
    return {
        "n_cards": len(records),
        "n_forecasts": sum(1 for r in records if r.get("entry_date")
                           or r["state"] == "marked"),
        "n_open": sum(1 for r in records if r["state"] == "marked"),
        "n_scored": len(scored),
        "n_upcoming": len(upcoming),
        "next_up": None if not nxt else {"d": nxt.get("d"), "who": nxt["who"]},
        "direct_hit_5": at("horizons", 5, "hit"),
        "direct_spread_5": at("horizons", 5, "mean"),
        "direct_spread_20": at("horizons", 20, "mean"),
        "ring2_hit_5": at("horizons2", 5, "hit"),
        "ring2_spread_5": at("horizons2", 5, "mean"),
    }


def build(forecasts: list[dict] | None = None, ledger: dict | None = None,
          watch: list[dict] | None = None, doc: dict | None = None,
          marks: dict | None = None, book=None,
          cal: list[dt.date] | None = None,
          today: dt.date | None = None) -> dict:
    """``{summary, forecasts}`` -- one record per dated question."""
    doc = doc or mapfile.load()
    forecasts = forecasts or []
    ledger = ledger or {"rows": []}
    watch = watch or []
    marks = marks or {}
    today = today or dt.date.today()
    rows = {r["id"]: r for r in ledger.get("rows", [])}

    direct = {f["qid"]: f for f in forecasts
              if f.get("order", DEFAULT_ORDER) == 1}
    twins = {f["id"]: f for f in forecasts
             if f.get("order", DEFAULT_ORDER) == 2}

    symbol_of, node_symbols = symbols_for(doc)
    by_ticker = {str(n.get("ticker", "")).upper(): n["id"]
                 for n in doc.get("nodes", []) if n.get("ticker")}

    if book is None or cal is None:
        wanted = set(node_symbols)
        for w in watch:
            for i in list(w.get("win") or []) + list(w.get("lose") or []):
                if i in symbol_of:
                    wanted.add(symbol_of[i])
        book = book or forecast.Book(sorted(wanted))
        cal = cal or forecast.sessions(
            [s for s in node_symbols if s.endswith(".US")])

    out = []
    for w in watch:
        if not w.get("d"):
            continue
        r2 = rings.second_ring(doc, w.get("win") or [], w.get("lose") or [],
                               by_ticker.get(str(w.get("tk") or "").upper()))
        f = direct.get(w["id"])
        tid = twin_id(w["id"], f["marked_at"]) if f else None
        twin = twins.get(tid) if tid else None
        out.append(record(w, f, twin, rows.get(f["id"]) if f else None,
                          rows.get(tid) if twin else None,
                          marks.get(w["id"]), book, cal, doc, symbol_of,
                          node_symbols, today, r2))
    out.sort(key=sort_key)
    return {"summary": summarise(out), "forecasts": out,
            "as_of": today.isoformat()}


# ------------------------------------------------------------------- slimming
# What live.json carries. The full record set is 42 KB of members and series
# for thirty-nine questions, and live.json has a hard 250 KB ceiling it was
# already close to. The page builds its own full copy; live.json carries only
# what the brief and the map read, which is the summary and one line per card.
SLIM_FIELDS = ("qid", "who", "tk", "d", "state", "status", "auto",
               "marked_at", "entry_date", "day_index", "next_checkpoint",
               "sessions_to", "has_r2", "today", "confirmed")


def slim(data: dict) -> dict:
    """The same object with the heavy halves dropped."""
    return {"summary": data["summary"], "as_of": data.get("as_of"),
            "forecasts": [{k: r[k] for k in SLIM_FIELDS if k in r}
                          for r in data["forecasts"]]}


# ------------------------------------------------------------------ the page
PLACEHOLDER = "__TRACK__"


def render(data: dict, template: str | None = None) -> str:
    """The page, with its data inlined.

    One substitution, and it is checked: a template whose placeholder has been
    renamed would publish a page that renders an empty shell, which reads as
    "nothing registered yet" and is the opposite of true.
    """
    from chains.paths import templates_dir
    t = template if template is not None else (
        (templates_dir() / "track.html").read_text(encoding="utf-8"))
    if PLACEHOLDER not in t:
        raise SystemExit(
            f"chains/templates/track.html has no {PLACEHOLDER} to fill. The "
            f"page would render an empty shell and read as 'nothing yet'.")
    return t.replace(PLACEHOLDER, json.dumps(data, ensure_ascii=False))


def main() -> int:
    """Build the FULL record set and write the page beside its data.

    live.json carries a slimmed copy, so this rebuilds rather than reads: the
    watch rows, the answers and the ledger come out of live_en.json -- already
    merged, already in English, already scored -- and only the members and the
    series are computed again here.
    """
    from chains import answers as answers_mod
    from chains.paths import out_dir
    live = json.loads((out_dir() / "live_en.json").read_text(encoding="utf-8"))
    _a, forecasts, _p = answers_mod.read()
    data = build(forecasts, live.get("ledger"), live.get("watch"),
                 marks=live.get("answers"),
                 today=dt.date.fromisoformat(live["as_of"]))
    out_dir().mkdir(parents=True, exist_ok=True)
    j = out_dir() / "track.json"
    j.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                 encoding="utf-8", newline="\n")
    h = out_dir() / "track.html"
    h.write_text(render(data), encoding="utf-8", newline="\n")
    by: dict[str, int] = {}
    for r in data["forecasts"]:
        by[r["state"]] = by.get(r["state"], 0) + 1
    print(f"wrote {j}  ({j.stat().st_size:,} bytes)")
    print(f"wrote {h}  ({h.stat().st_size:,} bytes)")
    print("  " + (" · ".join(f"{k} {v}" for k, v in sorted(by.items()))
                  or "no dated questions"))
    return 0


__all__ = ["build", "record", "spread", "flip", "expected_dir", "summarise",
           "render", "main", "slim", "sort_key", "state_of", "members_for",
           "report_close", "CHECKPOINTS", "STALE_AFTER", "MAX_POINTS",
           "CLOSED_AFTER", "STATES", "UNDIRECTED", "R2_SUFFIX"]


if __name__ == "__main__":                                # pragma: no cover
    raise SystemExit(main())
