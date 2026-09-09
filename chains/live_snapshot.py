"""The living map's data snapshot: the files the pages read.

    python -m chains.live_snapshot

Reads the tracked map, chain_page.json, chain_fundamentals.json and the price
parquets. Writes <root>/chains/out/live.json (Hebrew) and live_en.json
(English).

TWO FILES, NOT ONE FILE WITH TWO LANGUAGES
------------------------------------------
The public page is English and must not carry a Hebrew character anywhere --
chains/build_pages.py fails the build over a single one. The cheapest way to
guarantee that is for the English page never to be handed a Hebrew string in
the first place, so the language is chosen here, once, and the two snapshots
share nothing but the numbers. What differs is the chokepoint names, the
blurbs, the stage labels and which watch list is read; every price, return and
pressure figure is computed once per symbol and is identical in both.

THE TEXT IS NOT IN THIS REPOSITORY AND NOT IN EVERY ROW
--------------------------------------------------------
``watch`` carries the skeleton of all 39 questions -- who, when, which
chokepoints, which baskets, how many hints have landed -- and the question
itself only where the row is OPEN: every date that has passed, plus the single
nearest upcoming one. A locked row has no ``q`` and no ``listen`` key at all,
so a page that forgot to check ``locked`` renders nothing rather than
something, and a leaked snapshot has nothing to leak. See chains/questions.py.

``signup`` is where the page's call to action points, or null while the
newsletter platform is not wired up; the page says "coming soon" rather than
offering a button that goes nowhere.

THE WATCH LIST NOW TRAVELS IN THE FILE
--------------------------------------
It used to not. The page carried all 39 rows inline and live.json held only
``cal`` -- the join keys and dates -- so the prose would not be shipped twice
into a file with a hard ceiling. That changed when the page became something
the weekly job republishes: a row whose date a company has since announced was
corrected in watch.json and the page kept rendering last month's copy, because
the only way to update the inline list was to rebuild the HTML. Now ``watch``
is the source and the inline copy is the fallback the page uses when the fetch
fails. ``cal`` stays lean and stays separate: it is the marker layer, and it is
filtered by date in a way the full list is not.

``ledger`` rides along too: the forecast ledger from chains/forecast.py,
{summary, rows}. It is language-neutral -- ids, symbols and numbers, no prose --
so one build serves both files. It is the first thing trimmed when the snapshot
is over its ceiling, and the per-symbol sparklines go before the basket ones:
the basket line is the claim, the per-symbol lines are the detail behind it.

``answers`` rides along with it: {question_id: {status, note, updated}}, read
from data/<domain>/marks.json in git, or {} when nothing has been marked
yet. The page reads it as the fallback status for each question, which is what
lets the PUBLIC board colour itself -- the private board's own answers live in
an artifact database no public reader can see. Nothing here invents an answer;
see chains/answers.py.

THE 256 KB CEILING IS A HARD CONSTRAINT, NOT A TARGET
------------------------------------------------------
The artifact database rejects anything larger, so a file that grows past it
does not degrade -- it stops arriving. The build therefore shortens STRINGS
under pressure and never drops a node, a chokepoint or a subnode: a missing
sentence is a smaller loss than a missing company, and a map with a hole in it
is worse than a map with terse prose. If the ladder runs out of things to
shorten the build FAILS rather than writing a file that will be refused
silently on the other end.

TODAY COMES FROM THE CLOCK
--------------------------
Not a constant. The snapshot is regenerated weekly and a frozen date would make
every "days until" count drift a week further from the truth each run, while
still looking like a live number. Calendar events past their date drop out on
their own for the same reason.

ISOLATION
---------
Same rule as the rest of chains/: no import of the project this came from, and
no path that leaves this repository. Pinned by tests/test_isolation.py.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from chains import answers as answers_mod
from chains import forecast, mapfile, prices, questions, rings, track
from chains import paths
from chains.paths import out_dir, signup_url, watch_en_path, watch_path

# DECIMAL, not binary. "250 KB" could mean 250,000 or 256,000 and the two
# readings differ by 6 KB -- which is more than the headroom at the current
# size. Taking the stricter reading means being wrong in the safe direction: a
# file that is smaller than it had to be still arrives, and one that is 4 KB
# too big does not arrive at all.
MAX_BYTES = 250_000             # the page's own limit
TRIM_AT = 244_000               # start shortening here
HARD_LIMIT = 256_000            # what the artifact database refuses

SPARK_WEEKS = 52

# What differs between the two snapshots is which language is read out of the
# map, and which watch list. Every price, return and pressure number is
# computed once and shared.
#
# The vocabulary itself used to live here: the metro lines, the layer names,
# every chokepoint's title and blurb, and a table of display names. It is all
# in the map now, under "labels" and on the node and chokepoint records, so
# this module can draw an industry it has never heard of. Pinned by
# tests/test_isolation.py, which fails if any of that vocabulary comes back.
LANG = {
    "he": {"watch": watch_path, "file": "live.json"},
    "en": {"watch": watch_en_path, "file": "live_en.json"},
}


def labels_for(m: dict, lang: str) -> dict:
    """The map's own words, resolved to one language.

    Shipped whole to the page, which renders whatever is here: a domain with
    four layers and two lines draws four columns and two colours without a
    line of code changing.
    """
    lb = m.get("labels") or {}
    br = lb.get("brand") or {}
    return {
        # The brand travels with the labels because it is the same kind of
        # thing: words the page shows, chosen per map rather than per engine.
        "brand": {"name": br.get("name", ""),
                  "title": (br.get("title") or {}).get(lang, ""),
                  "story": (br.get("story") or {}).get(lang, ""),
                  "footer": (br.get("footer") or {}).get(lang, "")},
        "layers": {k: v.get(lang, k) for k, v in (lb.get("layers") or {}).items()},
        "lines": {k: {"name": v.get(lang, k), "color": v.get("color")}
                  for k, v in (lb.get("lines") or {}).items()},
        "lanes": {k: v.get(lang, k) for k, v in (lb.get("lanes") or {}).items()},
        "stages": {k: v.get(lang, k) for k, v in (lb.get("stages") or {}).items()},
    }


def load_watch(lang: str = "he") -> list[dict]:
    """The dated-questions list, from the repo beside the map.

    39 rows: what is being asked, when it will be answered, and who wins or
    loses either way. A row whose ``confirmed`` is false carries an EXPECTED
    date, taken from the company's usual reporting rhythm rather than an
    announcement. When the company announces, the row's date is corrected and
    confirmed is set true. Nothing here guesses: an unannounced date stays
    provisional and is flagged as such all the way to the page.

    The two language files are generated together by chains/watch.py and carry
    the same ids in the same order; only the prose differs.
    """
    return json.loads(LANG[lang]["watch"]().read_text(encoding="utf-8"))


def calendar_from(watch: list[dict], today: dt.date) -> list[dict]:
    """The rows that belong on the chart, as markers.

    Only rows carrying a ``cps`` entry: a question with no chokepoint has
    nothing to attach to on the map. It is still in the watch list, which the
    page holds inline -- it simply is not a marker.

    A row whose date has passed falls out here rather than being filtered by
    the page, so a stale question cannot be rendered as upcoming.

    What is emitted is the JOIN KEY and the timing, not the prose. The page
    carries the whole list inline, so shipping q/listen/win/lose again would be
    sending the same text twice into a file with a hard size ceiling.
    """
    out = [{
        "id": r["id"], "d": r["d"], "who": r.get("who"),
        "cps": r.get("cps") or [], "confirmed": bool(r.get("confirmed")),
        "days": (dt.date.fromisoformat(r["d"]) - today).days,
    } for r in watch
        if r.get("cps") and dt.date.fromisoformat(r["d"]) >= today]
    return sorted(out, key=lambda r: r["d"])


# ---------------------------------------------------------------- price maths
def _rows(symbol: str):
    """(date, adj_close) pairs, oldest first, nulls already dropped."""
    df = prices.load(symbol)
    if df.is_empty():
        return None, None
    d = df.drop_nulls("adj_close").sort("date")
    if d.is_empty():
        return None, None
    return list(zip(d["date"].to_list(), d["adj_close"].to_list())), d["currency"][0]


def weekly(rows):
    """Last close of each ISO week."""
    out = {}
    for d, v in rows:
        out[d.isocalendar()[:2]] = (d, v)
    return [out[k] for k in sorted(out)]


def ret(rows, days: int):
    """Total return over the last ``days``, against the last bar on or before."""
    if not rows:
        return None
    last_d, last_v = rows[-1]
    target = last_d - dt.timedelta(days=days)
    prev = None
    for d, v in rows:
        if d <= target:
            prev = v
        else:
            break
    if prev is None or prev == 0:
        return None
    return last_v / prev - 1


def r13_only(px: dict | None) -> dict | None:
    """The one number a subnode or a challenger actually shows.

    Both render a single "13w -4.2%" badge and nothing else -- no sparkline,
    no 1w/4w/52w row, no currency, no last date. Holders have always been
    emitted this way; subnodes and challengers were not, and shipping them a
    full block put 234 unread 52-point sparklines into a file with a hard size
    ceiling. That was 47 KB, which is more than the entire trim ladder can
    recover by shortening prose.

    Nothing is lost that anything reads. If a sparkline is ever wanted on a
    subnode, widen this -- do not go back to shipping the whole block.
    """
    return None if not px else {"r13w": px["r13w"]}


def price_block(symbol: str, today: dt.date, cache: dict):
    if not symbol:
        return None
    if symbol in cache:
        return cache[symbol]
    rows, cur = _rows(symbol)
    if not rows:
        cache[symbol] = None
        return None
    wk = weekly(rows)[-SPARK_WEEKS:]
    cache[symbol] = {
        "cur": cur, "last": rows[-1][0].isoformat(), "px": rows[-1][1],
        "spark": [round(v / wk[0][1] * 100) for _, v in wk] if wk and wk[0][1] else [],
        "r1w": ret(rows, 7), "r4w": ret(rows, 28),
        "r13w": ret(rows, 91), "r52w": ret(rows, 365),
        "stale_days": (today - rows[-1][0]).days,
    }
    return cache[symbol]


# ---------------------------------------------------------------- the snapshot
def build(today: dt.date | None = None, lang: str = "he",
          answers: dict | None = None, ledger: dict | None = None,
          text: dict | None = None, forecasts: list | None = None) -> dict:
    """One snapshot, in one language.

    ``answers``, ``ledger`` and ``text`` are read/built here when not supplied,
    so a direct call works. main() does all three once and passes them to both
    builds: reading twice would print every dropped row twice and say nothing
    new the second time, and scoring twice would load the whole price store
    twice.
    """
    today = today or dt.date.today()
    L = LANG[lang]
    m = mapfile.load()
    labels = labels_for(m, lang)
    stages = labels["stages"]
    page = json.loads((out_dir() / "chain_page.json").read_text(encoding="utf-8"))
    fnd = json.loads((out_dir() / "chain_fundamentals.json").read_text(
        encoding="utf-8"))
    cache: dict = {}

    def get(sym):
        return price_block(sym, today, cache)

    nodes = []
    for n in m["nodes"]:
        px = get(n.get("price_symbol"))
        nodes.append({
            "id": n["id"], "name": n["name"], "ticker": n.get("ticker"),
            "short": n.get("short")
                     or (n.get("ticker") or n["name"]).split(".")[0][:8],
            "layer": n["layer"], "line": n.get("line"),
            "cap": n.get("market_cap_usd_b"), "role": n.get("role", ""),
            "country": n.get("exchange", ""),
            "sym": n.get("price_symbol"), "kind": n.get("price_symbol_kind"),
            "px": px,
            "cps": [c["id"] for c in m["chokepoints"] if n["id"] in c["node_ids"]],
        })
    node_by = {n["id"]: n for n in nodes}

    edges = [{"from": e["from"], "to": e["to"], "what": e.get("what", ""),
              "crit": e.get("criticality", "medium")}
             for e in m.get("edges", [])
             if e["from"] in node_by and e["to"] in node_by]
    flows = [{"from": f["from_layer"], "to": f["to_layer"],
              "usd_b": f.get("annual_usd_b"), "what": ""}
             for f in m.get("flows", [])]

    pg_cp = {c["id"]: c for c in page["chokepoints"]}
    cps = []
    for c in m["chokepoints"]:
        cid = c["id"]
        pc = pg_cp.get(cid, {})
        holders, hsyms = [], set()
        for h in c["node_ids"]:
            nn = node_by.get(h)
            if not nn:
                continue
            holders.append({
                "id": h, "name": nn["name"], "sym": nn["sym"],
                "px": {"r13w": nn["px"]["r13w"]} if nn["px"] else None,
            })
            if nn["sym"]:
                hsyms.add(nn["sym"])
        chal = []
        for ch in pc.get("challengers", []):
            sym = ch.get("symbol")
            same = bool(sym) and sym in hsyms
            chal.append({
                "name": ch["name"], "sym": None if same else sym,
                "same_as_holder": same, "stage": ch.get("stage"),
                "stage_he": stages.get(ch.get("stage"), ""),
                "px": r13_only(get(sym)) if sym and not same else None,
            })
        sigs = [{
            "name": ch["name"], "stage": ch.get("stage"),
            "stage_he": stages.get(ch.get("stage"), ""),
            "signal": (ch.get("signal") or "")[:170], "as_of": ch.get("as_of"),
            "src": ch.get("signal_source"),
            # The map station funding this attack, where the map records one.
            # It is what lets a company that holds no chokepoint still show
            # what it is doing to somebody else's.
            "sponsor": ch.get("sponsor"),
            "approach": (ch.get("approach") or "")[:120],
        } for ch in (m.get("challengers") or {}).get(cid, [])]

        hr = [h["px"]["r13w"] for h in holders
              if h["px"] and h["px"]["r13w"] is not None]
        cr = [x["px"]["r13w"] for x in chal
              if x["px"] and x["px"]["r13w"] is not None]
        pressure = (sum(hr) / len(hr) - sum(cr) / len(cr)) if hr and cr else None

        subs = []
        for s in m["subnodes"]:
            if cid not in (s.get("chokepoint_ids") or []):
                continue
            sh = s.get("share") or {}
            v = str(sh.get("value", ""))
            unsourced = "unsourced" in v.lower()
            subs.append({
                "id": s["id"], "name": s["name"], "tier": s.get("tier"),
                "to": s.get("supplies_to"), "what": (s.get("what") or "")[:110],
                "share": "" if unsourced else v[:90],
                "src": None if unsourced else sh.get("source"),
                "sole": bool(s.get("sole_source")), "ticker": s.get("ticker"),
                "country": s.get("country_factory") or s.get("country_hq") or "",
                "sym": s.get("price_symbol"),
                "px": r13_only(get(s.get("price_symbol")))
                      if s.get("price_symbol") else None,
            })
        cps.append({
            "id": cid, "he": (c.get("label") or {}).get(lang, c["name"]),
            "blurb": (c.get("blurb") or {}).get(lang, ""),
            "name": c["name"],
            "holders": holders, "chal": chal, "sigs": sigs,
            "pressure": pressure,
            "hr13": (sum(hr) / len(hr)) if hr else None,
            "cr13": (sum(cr) / len(cr)) if cr else None,
            "n_chal_priced": len(cr), "subs": subs,
        })

    fund = {}
    for nid, rec in fnd.items():
        fu = rec.get("fundamentals")
        if not fu:
            continue
        seen, rows = set(), []
        for a in sorted(fu["annual"], key=lambda r: r["period_end"]):
            if a["period_end"] in seen or not a.get("revenue"):
                continue
            seen.add(a["period_end"])
            rows.append(a)
        q = sorted(fu.get("quarterly", []), key=lambda r: r["period_end"])[-4:]
        fund[nid] = {
            "annual": [{
                "fy": r["period_end"][:4],
                "rev": round(r["revenue"] / 1e9, 1),
                "yoy": None if r["revenue_yoy"] is None
                       else round(r["revenue_yoy"] * 100),
                "om": None if r["operating_margin"] is None
                      else round(r["operating_margin"] * 100),
            } for r in rows[-4:]],
            "q": [{
                "pe": r["period_end"],
                "rev": round(r["revenue"] / 1e9, 1) if r.get("revenue") else None,
                "yoy": None if r.get("revenue_yoy") is None
                       else round(r["revenue_yoy"] * 100),
            } for r in q],
        }

    # Two views of the same list. ``watch`` is the whole thing, in this
    # language, because the page now reads its rows from here rather than from
    # an inline copy that goes stale the moment a date is announced. ``cal`` is
    # the marker layer: join keys only, and only for rows that have a
    # chokepoint and a date that has not passed.
    watch = load_watch(lang)
    # The text, attached only where the row is open. Everything downstream --
    # cal, the page, the briefs -- reads the merged rows, so there is one
    # place that decides what is unlocked and no second opinion about it.
    watch = questions.merge(
        watch, questions.fetch() if text is None else text, lang, today)
    # The second ring, attached to every row. Both rings are then STRIPPED
    # from every locked row: a constellation is one of the things the paywall
    # holds, and a basket sitting in the JSON is the answer to "who moves"
    # whether or not any pixel draws it. The locked card draws a placeholder.
    rings.for_rows(watch, m)
    for r in watch:
        if r.get("locked"):
            for k in ("win", "lose", "win2", "lose2", "ring2_edges"):
                r.pop(k, None)
    cal = calendar_from(watch, today)
    if answers is None:
        answers = answers_mod.load(ids={r["id"] for r in watch})
    if forecasts is None:
        _a, forecasts, _p = answers_mod.read(ids={r["id"] for r in watch})
    if ledger is None:
        ledger = forecast.build(forecasts, m)

    return {
        "as_of": today.isoformat(), "map_version": m.get("version"),
        "nodes": nodes, "edges": edges, "flows": flows, "cps": cps,
        "fund": fund, "cal": cal, "watch": watch,
        "answers": answers, "ledger": ledger, "labels": labels,
        # The same forecasts, day by day. The horizons inside it are the
        # ledger's own objects, so the board and the tracking page cannot
        # disagree about a checkpoint.
        # Slimmed: the full record set is 42 KB and this file has a hard
        # ceiling. chains/track.py builds the full copy for its own page.
        "track": track.slim(track.build(forecasts, ledger, watch, m, answers,
                                        today=today)),
        "domain": paths.domain(),
        "signup": signup_url(),
        "n_open": sum(1 for r in watch if r["open"]),
        "last_price_date": max((p["last"] for p in cache.values() if p),
                               default=None),
    }


# ---------------------------------------------------------------- the ceiling
def _dump(live: dict) -> bytes:
    return json.dumps(live, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


# Cheapest cut first, and "cheapest" is measured in what a reader loses.
#
# The ledger's per-symbol sparklines go first: they are the detail behind a
# claim whose own line is kept, so losing them costs a reader the breakdown and
# not the finding. Then ``flows``, because the page does not read it: it is layer-to-layer
# dollar totals kept for a chart that was never built, so dropping it costs the
# reader nothing at all. The blurbs go second -- they are the one piece of prose
# on the page that repeats what the panel below already says, and a truncated
# blurb still names the companies. Only then do the rungs that were here before
# start cutting into text that is the only place its fact appears.
TRIM_LADDER = [
    ("ledger per-symbol series", lambda L: forecast.drop_symbol_series(
        L.get("ledger") or {})),
    ("drop flows", lambda L: L.pop("flows", None)),
    ("blurb ->150", lambda L: _cap_cp(L, "blurb", 150)),
    ("blurb ->90", lambda L: _cap_cp(L, "blurb", 90)),
    ("signal text 170->110", lambda L: _cap(L, "sigs", "signal", 110)),
    ("approach 120->70", lambda L: _cap(L, "sigs", "approach", 70)),
    ("subnode what 110->70", lambda L: _cap(L, "subs", "what", 70)),
    ("subnode share 90->60", lambda L: _cap(L, "subs", "share", 60)),
    ("node role 1st clause", lambda L: _roles(L, 60)),
    ("signal text ->70", lambda L: _cap(L, "sigs", "signal", 70)),
]


def _cap(live: dict, coll: str, field: str, n: int) -> None:
    for c in live["cps"]:
        for row in c.get(coll, []):
            if row.get(field):
                row[field] = row[field][:n]


def _cap_cp(live: dict, field: str, n: int) -> None:
    """Shorten a field on the chokepoint itself, not on its child rows."""
    for c in live["cps"]:
        if c.get(field):
            c[field] = c[field][:n]


def _roles(live: dict, n: int) -> None:
    for node in live["nodes"]:
        if node.get("role"):
            node["role"] = node["role"][:n]


def shrink_to_fit(live: dict, limit: int = TRIM_AT) -> list[str]:
    """Shorten strings until it fits. Never drops a node or a chokepoint."""
    applied: list[str] = []
    for name, fn in TRIM_LADDER:
        if len(_dump(live)) <= limit:
            break
        fn(live)
        applied.append(name)
    return applied


def write(live: dict, path: Path | None = None) -> tuple[Path, int, list[str]]:
    applied = shrink_to_fit(live)
    blob = _dump(live)
    if len(blob) > MAX_BYTES:
        raise SystemExit(
            f"live.json is {len(blob):,} bytes, over the {MAX_BYTES:,} limit "
            f"even after {applied}. The artifact database refuses anything "
            f"above {HARD_LIMIT:,}, so writing it would fail silently at the "
            f"other end. Shorten something rather than dropping a node."
        )
    p = path or (out_dir() / "live.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(blob)
    return p, len(blob), applied


def main() -> int:
    # Read once, log once, embed in both. A dropped row is printed here and
    # the run continues on the rows that survived -- see chains/answers.py for
    # why a bad row must not cost the whole Saturday chain.
    # Fetched once, before anything is written. A failure here stops the run
    # rather than publishing a page with an empty sentence under every
    # headline; see chains/questions.py.
    try:
        text = questions.fetch()
    except questions.QuestionsError as e:
        # One line, not a traceback: the cause is always a URL or a permission,
        # and a stack through httpx says nothing useful about either.
        raise SystemExit(f"QUESTIONS: {e}") from None
    print(f"  questions: {len(text)} fetched")

    good, forecasts, problems = answers_mod.read()
    for why in problems:
        print(f"  answers: DROPPED {why}")
    if problems:
        print(f"  answers: {len(good)} answers, {len(forecasts)} forecasts, "
              f"{len(problems)} dropped")

    # Scored once. The ledger carries no prose, so both languages share it.
    log: list[str] = []
    ledger = forecast.build(forecasts, log=log)
    for line in log:
        print(f"  ledger: {line}")

    first = None
    for lang in LANG:
        live = build(lang=lang, answers=good, ledger=ledger, text=text,
                     forecasts=forecasts)
        p, size, applied = write(live, out_dir() / LANG[lang]["file"])
        # Belt and braces. write() already refuses to produce an oversized
        # file; this says out loud, at the call site, what the invariant is.
        assert size < MAX_BYTES, f"{p.name} is {size:,} bytes"
        print(f"wrote {p}  ({size:,} bytes, {size / 1024:.1f} KB "
              f"of {MAX_BYTES / 1024:.0f} KB)")
        if applied:
            print(f"  trimmed: {', '.join(applied)}")
        print(f"  watch {len(live['watch'])} rows  "
              f"answers {len(live['answers'])}  calendar {len(live['cal'])}  "
              f"ledger {len(live['ledger']['rows'])} scored, "
              f"{live['ledger']['summary']['n_pending']} pending")
        print(f"  track {len(live['track']['forecasts'])} forecasts, "
              f"{live['track']['summary']['n_open']} awaiting entry")
        print(f"  questions open {live['n_open']} of {len(live['watch'])}"
              f"  signup {'set' if live['signup'] else 'coming soon'}")
        first = first or live

    live = first
    print()
    print(f"  as_of            : {live['as_of']}")
    print(f"  last_price_date  : {live['last_price_date']}")
    print(f"  nodes {len(live['nodes'])}  priced "
          f"{sum(1 for n in live['nodes'] if n['px'])}  "
          f"subs priced {sum(1 for c in live['cps'] for s in c['subs'] if s['px'])}")
    print()
    print("  CP    pressure    holders 13w  challengers 13w  n")
    for c in live["cps"]:
        f = lambda v: "    --" if v is None else f"{v * 100:+6.1f}"  # noqa: E731
        print(f"  {c['id']:<5} {f(c['pressure'])}      {f(c['hr13'])}"
              f"           {f(c['cr13'])}    {c['n_chal_priced']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
