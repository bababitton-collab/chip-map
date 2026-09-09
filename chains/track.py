"""The forward test, as a page: what was said would move, and what moved.

WHAT THIS IS
------------
The ledger scores forecasts at fixed horizons. This is the same forecasts seen
day by day: the two baskets and the equal-weight map, indexed to zero at the
entry close, one point per session, plus the members that make them up.

It adds no measurement. The horizons come out of the ledger untouched -- the
numbers on this page and the numbers on the board are the same numbers, because
they are the same objects. What this module computes is the shape between the
checkpoints, and it computes it from closes and nothing else.

THE ONE PLACE THE SIGN IS DECIDED
---------------------------------
A forecast has a direction. "Yes, and the win basket outruns the lose basket"
is +1; a "no" mark that points the other way is -1. Every difference on the
page is sign-adjusted ONCE, in ``spread()``, by swapping the baskets before
subtracting. Nowhere else in this module or in the template is a sign applied,
because a second application would silently undo the first and the page would
report the opposite of what was claimed.

ORDERS ARE NOT POOLED
---------------------
Order 1 is the registered basket; order 2 is its second ring, derived from the
map's supply edges. One record carries both -- they are the same claim at two
removes -- but every number is kept apart, and the summary averages within an
order and never across.

WHAT IS SHOWN BUT NOT SCORED
----------------------------
A forecast marked after the last close has no entry yet. Its record is built,
listed and dated, with no series and no numbers: the entry rule is the close of
the first session AFTER the mark, and until that session prints there is
nothing to measure. Dropping it would hide a registered claim; scoring it would
invent one.
"""
from __future__ import annotations

import datetime as dt
import json
import statistics

from chains import forecast, mapfile
from chains.answers import DEFAULT_ORDER, HORIZONS_R2, R2_SUFFIX

# Every checkpoint either order can have. A direct forecast has no 40.
CHECKPOINTS = HORIZONS_R2

# A member whose last close is older than this is carried forward and said to
# be carried forward. Three sessions is a long weekend plus a holiday; beyond
# that the line is somebody's data problem and the reader should know.
STALE_AFTER = 3

# The chart runs from entry. Every horizon has locked by 40 sessions, so a
# series longer than this is history rather than the forward test, and it costs
# bytes in a file with a hard ceiling.
MAX_POINTS = 90

GROUPS = ("win", "lose", "win2", "lose2")


# ------------------------------------------------------------------ the sign
def flip(direction: int, a: list | None, b: list | None) -> tuple:
    """The two baskets in the order the claim puts them.

    Direction -1 means the claim is that ``b`` outruns ``a``. Swapping here,
    once, is what lets every subtraction downstream be a plain subtraction.
    """
    return (a, b) if direction >= 0 else (b, a)


def spread(direction: int, up: float | None, down: float | None) -> float | None:
    """Sign-adjusted difference. The only place a direction is applied."""
    if up is None:
        return None
    if down is None:
        return up if direction >= 0 else -up
    return (up - down) if direction >= 0 else (down - up)


# ------------------------------------------------------------------ helpers
def _round(v, n=6):
    return None if v is None else round(v, n)


def _pct(v, n=4):
    return None if v is None else round(v * 100, n)


def symbols_for(doc: dict) -> tuple[dict[str, str], list[str]]:
    """id -> price symbol, and the symbols EW_MAP is the mean of."""
    symbol_of = {r["id"]: r["price_symbol"]
                 for coll in ("nodes", "subnodes") for r in doc.get(coll, [])
                 if r.get("price_symbol")}
    node_symbols = [n["price_symbol"] for n in doc.get("nodes", [])
                    if n.get("price_symbol")
                    and n.get("price_symbol_kind") != "none"]
    return symbol_of, node_symbols


def label_of(doc: dict, nid: str) -> str:
    for coll in ("nodes", "subnodes"):
        for n in doc.get(coll, []):
            if n["id"] == nid:
                return (n.get("short")
                        or (n.get("ticker") or n["name"]).split(".")[0][:10])
    return nid.upper()


def ticker_of(doc: dict, nid: str) -> str:
    for coll in ("nodes", "subnodes"):
        for n in doc.get(coll, []):
            if n["id"] == nid:
                return n.get("ticker") or nid.upper()
    return nid.upper()


def _stale(book, sym: str, window: list[dt.date]) -> int:
    """Sessions between the member's last real close and the last session."""
    days = book.days.get(sym) or []
    if not days:
        return 0
    last = days[-1]
    return sum(1 for d in window if d > last)


# --------------------------------------------------------------- one record
def record(f: dict, twin: dict | None, row: dict | None, row2: dict | None,
           book, cal: list[dt.date], doc: dict, watch: dict,
           symbol_of: dict, node_symbols: list[str],
           marks: dict | None = None) -> dict:
    """One forecast, with its second ring folded in."""
    w = watch.get(f["qid"], {})
    direction = f["direction"]
    entry = forecast.entry_session(f["marked_at"], cal)

    out = {
        "id": f["id"], "qid": f["qid"],
        "who": w.get("who") or f["qid"],
        "tk": w.get("tk"),
        "status": f["status"], "direction": direction,
        "marked_at": f["marked_at"],
        "auto": bool((marks or {}).get(f["qid"], {}).get("auto", False)),
        "entry_date": entry.isoformat() if entry else None,
        "has_r2": twin is not None,
    }
    # The question text is the product boundary. It rides along only where the
    # row is already open; on a locked row the field is absent, not blank --
    # an empty string is still a field somebody can learn the shape of.
    if w.get("q"):
        out["q"] = w["q"]

    if entry is None:
        out.update({"day_index": None, "next_checkpoint": None,
                    "sessions_to": None, "series": None, "members": [],
                    "today": {}, "horizons": {}, "horizons2": {}})
        return out

    window = [d for d in cal if d >= entry][:MAX_POINTS + 1]
    out["day_index"] = len(window) - 1
    nxt = next((h for h in CHECKPOINTS if h > out["day_index"]), None)
    out["next_checkpoint"] = nxt
    out["sessions_to"] = None if nxt is None else nxt - out["day_index"]

    def syms(ids):
        return [symbol_of[i] for i in ids
                if i in symbol_of and book.has(symbol_of[i])]

    legs = {"win": list(f["win"]), "lose": list(f["lose"]),
            "win2": list(twin["win"]) if twin else [],
            "lose2": list(twin["lose"]) if twin else []}

    series = {g: forecast.basket_returns(book, syms(legs[g]), entry, window)
              if legs[g] else None for g in GROUPS}
    ew = forecast.ew_map(book, node_symbols, entry, window)

    out["series"] = {
        "dates": [d.isoformat() for d in window],
        "win": [_pct(v) for v in series["win"]] if series["win"] else None,
        "lose": [_pct(v) for v in series["lose"]] if series["lose"] else None,
        "ew": [_pct(v) for v in ew],
        "win2": [_pct(v) for v in series["win2"]] if series["win2"] else None,
        "lose2": [_pct(v) for v in series["lose2"]] if series["lose2"] else None,
    }

    members = []
    for g in GROUPS:
        for i in legs[g]:
            sym = symbol_of.get(i)
            if not sym or not book.has(sym):
                continue
            base = book.at(sym, entry)
            last = book.at(sym, window[-1])
            prev = book.at(sym, window[-2]) if len(window) > 1 else base
            old = _stale(book, sym, window)
            members.append({
                "id": i, "tk": ticker_of(doc, i), "label": label_of(doc, i),
                "group": g,
                "entry": _round(base, 4), "last": _round(last, 4),
                "day": _pct(None if not prev or last is None
                            else last / prev - 1.0),
                "since": _pct(None if not base or last is None
                              else last / base - 1.0),
                "stale": old if old > STALE_AFTER else 0,
            })
    out["members"] = members

    def last(name):
        s = out["series"][name]
        return s[-1] if s else None

    up, down = flip(direction, last("win"), last("lose"))
    up2, down2 = flip(direction, last("win2"), last("lose2"))
    ew_now = out["series"]["ew"][-1]
    # Four differences, every one of them through spread(). The map is passed
    # as the down side of the pair, because "win minus map" is the same claim
    # about direction that "win minus lose" is.
    out["today"] = {
        "win_lose": _round(spread(direction, last("win"), last("lose")), 4),
        "win_ew": _round(spread(direction, last("win"), ew_now), 4),
        "win2_lose2": _round(spread(direction, last("win2"), last("lose2")), 4),
        "win2_ew": _round(spread(direction, last("win2"), ew_now), 4),
        "up": _round(up, 4), "down": _round(down, 4),
        "up2": _round(up2, 4), "down2": _round(down2, 4),
        "ew": _round(ew_now, 4),
    }

    # The horizons are the ledger's. Not recomputed, not rounded again: the
    # board and this page must not be able to disagree.
    out["horizons"] = _from_ledger(row)
    out["horizons2"] = _from_ledger(row2)
    return out


def _from_ledger(row: dict | None) -> dict:
    """The ledger's horizons, in this page's units.

    The ledger stores fractions; everything here is a percentage, because a
    page that mixes the two is a page where a number is eventually read in the
    wrong one. The conversion is the only thing done to them -- the hit, the
    date and the ordering are the ledger's, so the board and this page cannot
    disagree about whether a checkpoint was met.
    """
    if not row:
        return {}
    out = {}
    for h, got in (row.get("horizons") or {}).items():
        out[h] = None if not got else {"spread": _pct(got["excess"]),
                                       "hit": got["hit"],
                                       "date": got["date"]}
    return out


# ---------------------------------------------------------------- the build
def summarise(records: list[dict]) -> dict:
    """Five numbers, each with the N behind it, pooled within an order only."""
    scored = [r for r in records if r.get("entry_date")]

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

    return {
        "n_forecasts": len(records),
        "n_open": sum(1 for r in records if not r.get("entry_date")),
        "n_scored": len(scored),
        "direct_hit_5": at("horizons", 5, "hit"),
        "direct_spread_5": at("horizons", 5, "mean"),
        "direct_spread_20": at("horizons", 20, "mean"),
        "ring2_hit_5": at("horizons2", 5, "hit"),
        "ring2_spread_5": at("horizons2", 5, "mean"),
    }


def build(forecasts: list[dict], ledger: dict | None = None,
          watch: list[dict] | None = None, doc: dict | None = None,
          marks: dict | None = None, book=None,
          cal: list[dt.date] | None = None) -> dict:
    """``{summary, forecasts}``. Empty and valid when nothing is marked."""
    doc = doc or mapfile.load()
    ledger = ledger or {"rows": []}
    rows = {r["id"]: r for r in ledger.get("rows", [])}
    by_watch = {w["id"]: w for w in (watch or [])}

    direct = [f for f in forecasts if f.get("order", DEFAULT_ORDER) == 1]
    twins = {f["id"]: f for f in forecasts
             if f.get("order", DEFAULT_ORDER) == 2}
    if not direct:
        return {"summary": summarise([]), "forecasts": []}

    symbol_of, node_symbols = symbols_for(doc)
    if book is None or cal is None:
        wanted = set(node_symbols)
        for f in forecasts:
            for i in list(f["win"]) + list(f["lose"]):
                if i in symbol_of:
                    wanted.add(symbol_of[i])
        book = book or forecast.Book(sorted(wanted))
        cal = cal or forecast.sessions(
            [s for s in node_symbols if s.endswith(".US")])

    out = []
    for f in direct:
        from chains.answers import twin_id
        tid = twin_id(f["qid"], f["marked_at"])
        twin = twins.get(tid)
        out.append(record(f, twin, rows.get(f["id"]),
                          rows.get(tid) if twin else None,
                          book, cal, doc, by_watch, symbol_of, node_symbols,
                          marks))
    out.sort(key=lambda r: (r["marked_at"], r["id"]), reverse=True)
    return {"summary": summarise(out), "forecasts": out}


# ------------------------------------------------------------------ the page
PLACEHOLDER = "__TRACK__"


def render(data: dict, template: str | None = None) -> str:
    """The page, with its data inlined.

    One substitution, and it is checked: a template whose placeholder has been
    renamed would otherwise publish a page that fetches nothing and renders an
    empty shell, which looks like "no forecasts yet" and is not.
    """
    from chains.paths import templates_dir
    t = template if template is not None else (
        (templates_dir() / "track.html").read_text(encoding="utf-8"))
    if PLACEHOLDER not in t:
        raise SystemExit(
            f"chains/templates/track.html has no {PLACEHOLDER} to fill. The "
            f"page would render an empty shell and read as 'no forecasts'.")
    return t.replace(PLACEHOLDER, json.dumps(data, ensure_ascii=False))


def main() -> int:
    """Write out/<domain>/track.json and out/<domain>/track.html."""
    from chains.paths import out_dir
    live = json.loads((out_dir() / "live_en.json").read_text(encoding="utf-8"))
    data = live.get("track") or {"summary": summarise([]), "forecasts": []}
    out_dir().mkdir(parents=True, exist_ok=True)
    j = out_dir() / "track.json"
    j.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                 encoding="utf-8", newline="\n")
    h = out_dir() / "track.html"
    h.write_text(render(data), encoding="utf-8", newline="\n")
    n = len(data["forecasts"])
    print(f"wrote {j}  ({j.stat().st_size:,} bytes)")
    print(f"wrote {h}  ({h.stat().st_size:,} bytes, {n} forecast"
          f"{'' if n == 1 else 's'})")
    return 0


__all__ = ["build", "record", "spread", "flip", "summarise", "render", "main",
           "CHECKPOINTS", "STALE_AFTER", "MAX_POINTS", "R2_SUFFIX"]


if __name__ == "__main__":                                # pragma: no cover
    raise SystemExit(main())
