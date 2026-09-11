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

import base64
import binascii
import datetime as dt
import json
import re
import os
import statistics

from chains import forecast, mapfile, rings
from chains.answers import DEFAULT_ORDER, HORIZONS_R2, R2_SUFFIX, twin_id

CHECKPOINTS = HORIZONS_R2
STALE_AFTER = 3
MAX_POINTS = 90

# The reason rides into track.json once per ring-1 station on thirty-nine
# cards. The first clause is the relationship; the rest is the evidence for it,
# which the map keeps in ``source``.
MAX_REASON = 90
CLOSED_AFTER = 40

GROUPS = ("win", "lose", "win2", "lose2")
STATES = ("tracking", "marked", "upcoming", "none", "closed")

# A mark that points nowhere: the question was answered and the answer supports
# no claim about which basket outruns which.
UNDIRECTED = frozenset({"none", "mixed", "open"})
# A question is ANSWERED once the report happened and the mark says what it
# said. "open" is not in here: open means the mark could not settle it, which
# is a question still waiting, not a question answered.
ANSWERED = frozenset({"yes", "no", "mixed", "none"})
# Answered, but nothing was pre-registered against it, so nothing is scored.
# The card exists and says what was reported; no number on this page moves.
UNSCORED = frozenset({"mixed", "none"})
# Words that turn an observation into advice. A "read" carrying one of these
# is dropped rather than published: the page measures, it does not counsel.
NOT_ADVICE = ("buy", "buys", "buying", "bought",
              "sell", "sells", "selling", "sold")


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
                # Since the day of the report rather than since an entry --
                # there was no entry. An observation, and the page says so.
                "since_report": _pct(
                    None if last is None
                    else (lambda rc: None if not rc else last / rc - 1.0)(
                        report_close(book, sym, d, today))),
                "stale": old if old > STALE_AFTER else 0,
            })
    return out


def _observed(legs: dict, doc: dict, book, symbol_of: dict,
              node_symbols: list[str], d: str,
              cal: list[dt.date]) -> dict | None:
    """The baskets since the day of the report. An observation, not a result.

    The same arithmetic a scored card uses, with the report's close as the
    baseline instead of an entry's. It is deliberately NOT called a spread and
    deliberately not in ``horizons``: nothing here reaches the hit rate, and
    the only number that could be mistaken for one is the up-minus-map line,
    which the page labels as an observation on the chart itself.
    """
    try:
        day = dt.date.fromisoformat(d)
    except (TypeError, ValueError):
        return None
    base = max((x for x in cal if x <= day), default=None)
    if base is None:
        return None
    window = [x for x in cal if x >= base][:MAX_POINTS + 1]
    # One point is allowed and says so on the page: a single dot on the zero
    # line, and a sentence that the first move prints after the next close.
    # The earlier version suppressed the whole block here, which left a card
    # with an empty middle column and no explanation of why -- worse than a
    # chart that admits it has one day in it.
    if not window:
        return None

    def syms(ids):
        return [symbol_of[i] for i in ids
                if i in symbol_of and book.has(symbol_of[i])]

    ser = {g: (forecast.basket_returns(book, syms(legs[g]), base, window)
               if legs[g] else None) for g in GROUPS}
    ew = forecast.ew_map(book, node_symbols, base, window)
    out = {
        "from": base.isoformat(),
        "sessions": len(window) - 1,
        "dates": [x.isoformat() for x in window],
        "ew": [_pct(v) for v in ew],
        **{g: ([_pct(v) for v in ser[g]] if ser[g] else None)
           for g in GROUPS},
    }
    tail = lambda k: (out[k][-1] if out.get(k) else None)   # noqa: E731
    up, ew_now = tail("win"), tail("ew")
    out["up"] = _round(up)
    out["ew_now"] = _round(ew_now)
    out["up_ew"] = _round(None if up is None or ew_now is None
                          else up - ew_now)
    out["down"] = _round(tail("lose"))
    return out


def reason_for(doc: dict, centre: str | None, nid: str) -> str:
    """What the edge between the reporting company and a ring-1 station carries.

    The same rule the map's cards use: the first clause of the edge's ``what``
    in either direction, and NOTHING where the map records no edge between the
    two. The layer name used to stand in there, which put the same three words
    beside every station on a card and read like three findings when it was one
    label. A blank line says what is true: the map does not record a link.

    The WHOLE clause. The page clips it for the drawing and keeps this in a
    <title>, so truncating here would make the hover give back the cut text.
    """
    if centre:
        for e in doc.get("edges", []):
            if ((e.get("from") == centre and e.get("to") == nid)
                    or (e.get("from") == nid and e.get("to") == centre)):
                w = (e.get("what") or "").split(";")[0].strip()
                if w:
                    return w[:MAX_REASON]
    return ""


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
    # Answered with nothing pre-registered against it. It used to fall back to
    # the upcoming layout with a grey pill, which said "no forecast" on a card
    # that still looked like a question waiting to happen -- so a mixed answer
    # read as though nothing had been reported at all. It is a report now, and
    # it keeps saying so.
    if status in ANSWERED:
        return "reported"
    return "none" if past else "upcoming"


def record(w: dict, f: dict | None, twin: dict | None, row: dict | None,
           row2: dict | None, mark: dict | None, book, cal: list[dt.date],
           doc: dict, symbol_of: dict, node_symbols: list[str],
           today: dt.date, ring2: dict, centre: str | None = None) -> dict:
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
        # What each ring-1 station's edge carries, for the grey line beside it.
        "ring1_edges": [{"id": i, "label": reason_for(doc, centre, i)}
                        for i in (list(w.get("win") or [])[:3]
                                  + list(w.get("lose") or [])[:3])],
    }
    out["has_r2"] = bool(out["win2"] or out["lose2"])

    # The findings, verbatim from the mark. The build never writes a word of
    # this: it is the sentence the marking task recorded with its source and
    # its date, and if the mark carries nothing the card shows nothing.
    for part in ("note", "evidence"):
        v = str((mark or {}).get(part) or "").strip()
        if v:
            out[part] = v
    if status in ANSWERED:
        out["report_date"] = d
    # An optional one-line read. Commentary, never a recommendation, and never
    # part of a number -- so it is checked before it can reach the page at all.
    read = str((mark or {}).get("read") or "").strip()
    if read:
        low = read.lower()
        if any(re.search(r"\b" + w + r"\b", low) for w in NOT_ADVICE):
            out["read_dropped"] = "reads as advice"
        else:
            out["read"] = read
    # The four sentences. In the SEALED payload every card carries them --
    # that file is the paid view and the whole point of paying for it. In any
    # plaintext output only an open row has them, because only an open row was
    # handed them: the tier is decided upstream, by what merge() attached, and
    # this copies whatever is there rather than deciding again.
    for part in ("q", "yes", "no", "why"):
        if w.get(part):
            out[part] = w[part]

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
        # A reported question was never entered, so it has no forecast series
        # and never will. What it does have is a price history since the day
        # of the report, and that is worth showing -- as long as it is shown
        # as an observation and not as a result. Baselined on the same close
        # the member table calls "report-day close", so the chart and the
        # table cannot tell different stories about the same day.
        if out["state"] == "reported" and d:
            out["observed"] = _observed(legs, doc, book, symbol_of,
                                        node_symbols, d, cal)
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
BANDS = {"tracking": 0, "reported": 1, "marked": 2, "upcoming": 3,
         "none": 4, "closed": 5}


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
    if r["state"] == "reported":
        # Newest report first: what was said yesterday matters more than what
        # was said a month ago.
        return (band, _desc(r.get("report_date") or r.get("d")), r["qid"])
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
        # The caption under the forecasts tile. Answered is every question the
        # report has happened for; scored is the subset a basket was
        # registered against; the rest are reports with no forecast and no
        # bearing on any number here.
        "n_answered": sum(1 for r in records
                          if r.get("status") in ANSWERED),
        "n_unscored": sum(1 for r in records if r["state"] == "reported"),
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
                          node_symbols, today, r2,
                          by_ticker.get(str(w.get("tk") or "").upper())))
    out.sort(key=sort_key)
    from chains import glossary as _gl
    return {"summary": summarise(out), "forecasts": out,
            "as_of": today.isoformat(),
            # Free tier, and it rides with the cards it explains so a
            # decrypted payload needs nothing else to render.
            "glossary": {t["id"]: {"label": t["label"], "def": t["en"],
                                   "match": list(t["match"])}
                         for t in _gl.load()}}


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


# ------------------------------------------------------------------- tiers
# What the public page may hold. chains/access.py decides; this shapes the
# payload to match, so the free file cannot leak by omission of a filter.
PUBLIC_CARD = ("qid", "who", "tk", "d", "confirmed", "state", "status",
               "marked_at", "entry_date", "day_index", "auto")


def _terms_on(gl: dict, texts: list[str]) -> dict:
    """The subset of ``gl`` the given text actually uses.

    A definition explains a word that is on the page, and a word that is not
    on the page needs no explaining. The free file carries the free text, so
    it carries the terms of the free text -- otherwise forty-seven definitions
    ride along for questions the free reader cannot see, and the teaser ends
    up larger than the thing it is teasing.
    """
    from chains import glossary as _gl
    terms = [{"id": k, "match": v.get("match") or []} for k, v in gl.items()]
    keep: list[str] = []
    for t in texts:
        for tid in _gl.find(t or "", terms, limit=_gl.MAX_PER_CARD):
            if tid not in keep:
                keep.append(tid)
    return {k: gl[k] for k in keep if k in gl}


def public(data: dict) -> dict:
    """The free half: finished forecasts in full, everything else as a count.

    A closed forecast is the record and the record is the evidence -- it goes
    out whole. Anything still running is the working position: it is counted,
    never described, and its members and prices are not in this object at all.
    """
    from chains import access
    rows, active, upcoming = [], 0, []
    for r in data.get("forecasts", []):
        if r["state"] == "closed":
            assert access.is_free("forecast_closed")
            row = {k: r[k] for k in PUBLIC_CARD if k in r}
            row["horizons"] = r.get("horizons") or {}
            # The second ring is a count, not a cast list.
            row["ring2_scored"] = sum(
                1 for v in (r.get("horizons2") or {}).values() if v)
            if r.get("q"):
                row["q"] = r["q"]
            rows.append(row)
            continue
        if r["state"] == "upcoming":
            upcoming.append({"d": r.get("d"), "who": r["who"],
                             "confirmed": r.get("confirmed")})
        else:
            active += 1
    s = dict(data.get("summary") or {})
    scored = [r for r in rows]
    return {
        "as_of": data.get("as_of"),
        # Narrowed to the free text: see _terms_on. The sealed payload keeps
        # the whole glossary, because behind the key every card is readable.
        "glossary": _terms_on(
            data.get("glossary") or {},
            [r.get("q") for r in rows] + [r.get("who") for r in rows]
            + [u.get("who") for u in upcoming]),
        "closed": rows,
        "n_active": active,
        "n_upcoming": len(upcoming),
        "next_up": min(upcoming, key=lambda x: x["d"] or "9999", default=None),
        "n_closed": len(scored),
        "capital_rule": s.get("capital_rule"),
    }


# ------------------------------------------------------------------- crypto
# The tracking detail is the paid half of the product, and a static host serves
# whatever is in the directory. So the plaintext never leaves the runner: the
# build writes it, encrypts it, and publishes only the ciphertext. A subscriber
# decrypts it in their own browser with a key from the mail; the key never
# reaches this repository, the site, or the server logs.
#
# AES-256-GCM: authenticated, so a tampered file fails to open rather than
# opening wrong, and available in WebCrypto without a library on the page.
KEY_ENV = "TRACK_KEY"
ALG = "A256GCM"
NONCE_BYTES = 12                      # what GCM is specified for
KEY_BYTES = 32


class TrackKeyError(RuntimeError):
    """The key is missing, malformed, or the wrong one."""


def load_key(env: str = KEY_ENV) -> bytes:
    """The 32-byte key, base64, out of the environment.

    Missing is a hard failure. The alternative -- writing the plaintext when
    the secret is not set -- is the one bug in this whole arrangement that
    nobody would notice, because the site would look exactly right.
    """
    raw = os.environ.get(env, "").strip()
    if not raw:
        raise TrackKeyError(
            f"{env} is not set. The tracking payload is published encrypted "
            f"and this build will not fall back to plaintext -- a site that "
            f"looks right and is unlocked is the failure nobody sees. Add the "
            f"repository secret, or run with --plain for a local build.")
    try:
        key = base64.b64decode(raw, validate=True)
    except (ValueError, binascii.Error) as e:
        raise TrackKeyError(f"{env} is not valid base64 ({e}).") from None
    if len(key) != KEY_BYTES:
        raise TrackKeyError(
            f"{env} decodes to {len(key)} bytes; AES-256 needs {KEY_BYTES}.")
    return key


def encrypt(payload: dict, key: bytes) -> dict:
    """``{v, alg, nonce, ct, tag, as_of}``, every binary field base64.

    ``as_of`` rides outside the ciphertext on purpose: the page has to be able
    to say how fresh the locked data is without holding the key.
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(NONCE_BYTES)
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    sealed = AESGCM(key).encrypt(nonce, blob.encode("utf-8"), None)
    # cryptography returns ciphertext||tag; WebCrypto wants them joined again,
    # and the file keeps them apart because the brief says so and because it
    # makes a truncated file obvious rather than merely broken.
    ct, tag = sealed[:-16], sealed[-16:]
    return {
        "v": 1, "alg": ALG,
        "nonce": base64.b64encode(nonce).decode(),
        "ct": base64.b64encode(ct).decode(),
        "tag": base64.b64encode(tag).decode(),
        "as_of": payload.get("as_of"),
    }


def decrypt(blob: dict, key: bytes) -> dict:
    """The payload back, or a clean error. Never a partial object."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if blob.get("alg") != ALG:
        raise TrackKeyError(f"unknown algorithm {blob.get('alg')!r}")
    try:
        nonce = base64.b64decode(blob["nonce"])
        sealed = base64.b64decode(blob["ct"]) + base64.b64decode(blob["tag"])
    except (KeyError, ValueError, binascii.Error) as e:
        raise TrackKeyError(f"malformed encrypted payload ({e})") from None
    try:
        out = AESGCM(key).decrypt(nonce, sealed, None)
    except InvalidTag:
        raise TrackKeyError(
            "that key does not open this file. GCM authenticates, so this is "
            "either the wrong key or a file that was changed after it was "
            "written -- it is not a partial read.") from None
    return json.loads(out.decode("utf-8"))


# ------------------------------------------------------------------ the page
PLACEHOLDER = "__TRACK__"
CARDS_PLACEHOLDER = "__CARDS_JS__"
GLOSSARY_PLACEHOLDER = "__GLOSSARY_JS__"


def glossary_js() -> str:
    """The shared term matcher and tooltip, read once."""
    from chains.paths import templates_dir
    return (templates_dir() / "glossary.js").read_text(encoding="utf-8")


def cards_js() -> str:
    """The shared card renderer, read once."""
    from chains.paths import templates_dir
    return (templates_dir() / "track-cards.js").read_text(
        encoding="utf-8")


def render(data: dict, template: str | None = None) -> str:
    """The page, with its data inlined.

    One substitution, and it is checked: a template whose placeholder has been
    renamed would publish a page that renders an empty shell, which reads as
    "nothing registered yet" and is the opposite of true.
    """
    from chains.paths import templates_dir
    t = template if template is not None else (
        (templates_dir() / "track.html").read_text(encoding="utf-8"))
    # The shared files, inlined into this page and into the private map so the
    # unlocked view and the private view cannot drift.
    if CARDS_PLACEHOLDER in t:
        t = t.replace(CARDS_PLACEHOLDER, cards_js())
    if GLOSSARY_PLACEHOLDER in t:
        t = t.replace(GLOSSARY_PLACEHOLDER, glossary_js())
    if PLACEHOLDER not in t:
        raise SystemExit(
            f"chains/templates/track.html has no {PLACEHOLDER} to fill. The "
            f"page would render an empty shell and read as 'nothing yet'.")
    return t.replace(PLACEHOLDER, json.dumps(data, ensure_ascii=False))


def _write(p, text: str) -> None:
    p.write_text(text, encoding="utf-8", newline="\n")


def build_files(plain: bool = False) -> dict:
    """Write the page and its data. Returns what was written, for the report.

    Three files, and only one of them is ever published:
      track.json      the full payload. Local only -- out/ is gitignored and
                      publish_site does not copy it.
      track.enc.json  the same thing sealed. This is what ships.
      track.html      the page, with the FREE half inlined and nothing else.
    """
    from chains import answers as answers_mod
    from chains.paths import out_dir, watch_en_path
    live = json.loads((out_dir() / "live_en.json").read_text(encoding="utf-8"))
    _a, forecasts, _p = answers_mod.read()
    # The baskets come from the tracked watch file, not from live_en.json:
    # that file now strips them off every locked row, which is the point. The
    # question TEXT still comes from live, where only an open row carries it.
    rows = json.loads(watch_en_path().read_text(encoding="utf-8"))
    # Every row gets its text. This file is encrypted before it is published
    # and the plaintext never leaves the runner, so the paywall here is the
    # key, not the absence of the sentence -- and a subscriber who cannot see
    # the question a forecast was made from cannot check the forecast.
    from chains import questions
    rows = questions.merge(rows, questions.fetch(), "en",
                           dt.date.fromisoformat(live["as_of"]),
                           unlock_all=True)
    data = build(forecasts, live.get("ledger"), rows,
                 marks=live.get("answers"),
                 today=dt.date.fromisoformat(live["as_of"]))
    out_dir().mkdir(parents=True, exist_ok=True)
    wrote = {}

    j = out_dir() / "track.json"
    _write(j, json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    wrote["track.json"] = j

    enc = out_dir() / "track.enc.json"
    if plain:
        # A local build with no secret. The file is REMOVED rather than left
        # stale, so a publish cannot pick up last run's ciphertext and serve
        # it beside this run's page.
        enc.unlink(missing_ok=True)
    else:
        _write(enc, json.dumps(encrypt(data, load_key()),
                               ensure_ascii=False, indent=1) + "\n")
        wrote["track.enc.json"] = enc

    h = out_dir() / "track.html"
    _write(h, render(public(data)))
    wrote["track.html"] = h
    return {"wrote": wrote, "data": data}


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m chains.track")
    sub = ap.add_subparsers(dest="cmd")
    ap.add_argument("--plain", action="store_true",
                    help="local build: skip encryption and write no sealed "
                         "file. Never used in CI -- publishing refuses to run "
                         "without one.")
    d = sub.add_parser("decrypt", help="open a sealed payload")
    d.add_argument("--in", dest="src", required=True)
    d.add_argument("--key-env", dest="key_env", default=KEY_ENV)
    d.add_argument("--out", dest="dst", required=True)
    a = ap.parse_args(argv)

    if a.cmd == "decrypt":
        from pathlib import Path
        blob = json.loads(Path(a.src).read_text(encoding="utf-8"))
        try:
            got = decrypt(blob, load_key(a.key_env))
        except TrackKeyError as e:
            print(f"track: {e}")
            return 1
        _write(Path(a.dst), json.dumps(got, ensure_ascii=False, indent=1)
               + "\n")
        n = len(got.get("forecasts", []))
        print(f"wrote {a.dst}  ({n} card{'' if n == 1 else 's'})")
        return 0

    try:
        got = build_files(plain=a.plain)
    except TrackKeyError as e:
        print(f"track: {e}")
        return 1
    by: dict[str, int] = {}
    for r in got["data"]["forecasts"]:
        by[r["state"]] = by.get(r["state"], 0) + 1
    for name, p in got["wrote"].items():
        note = "  (local only, never published)" if name == "track.json" else ""
        print(f"wrote {p}  ({p.stat().st_size:,} bytes){note}")
    if a.plain:
        print("  --plain: no track.enc.json written; publishing will refuse")
    print("  " + (" · ".join(f"{k} {v}" for k, v in sorted(by.items()))
                  or "no dated questions"))
    return 0


__all__ = ["build", "record", "spread", "flip", "expected_dir", "summarise",
           "public", "PUBLIC_CARD", "build_files", "cards_js",
           "CARDS_PLACEHOLDER", "GLOSSARY_PLACEHOLDER", "glossary_js",
           "encrypt", "decrypt", "load_key", "TrackKeyError", "KEY_ENV",
           "render", "main", "slim", "sort_key", "state_of", "members_for",
           "reason_for", "MAX_REASON",
           "report_close", "CHECKPOINTS", "STALE_AFTER", "MAX_POINTS",
           "CLOSED_AFTER", "STATES", "UNDIRECTED", "ANSWERED", "UNSCORED",
           "NOT_ADVICE", "R2_SUFFIX"]


if __name__ == "__main__":                                # pragma: no cover
    raise SystemExit(main())
