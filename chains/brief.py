"""The weekly brief, in English. This one is the product.

    python -m chains.brief <live.json> <watch.json> [answers.json] [out.md] [--free]

Prints to stdout when no output path is given, so it still works in a pipe.

EVERY NUMBER COMES FROM live.json
---------------------------------
Not from a memory of last week's figure, not from a second source, and never
from an estimate this file invented. The brief is a reading of one snapshot,
and a number that is not in that snapshot does not appear in it. Where the map
has no source for a figure it is marked an estimate there, and the brief
carries that mark through rather than quietly dropping it.

QUESTIONS ARE QUESTIONS
-----------------------
There is no pick in this document and no recommendation. "The forecast board"
counts hints that have already been answered; the lean is arithmetic over
answers that exist, not a prediction about the ones that do not. That is also
why there is no backtest under it -- recorded decision, 2026-09-08: the board
is a tracking view, not a signal.

The Hebrew twin is chains/brief_he.py. Two files rather than one with a
translation table, because every line of prose differs and only the shape of
the reading is shared.


WHO GETS WHICH
--------------
``--free`` is the public letter: only the questions whose text is already
unlocked on the site -- everything past, plus the nearest upcoming one. Without
it this is the paid mail and every row carries its question and what to listen
for. The flag is the whole difference; there is no second template and no
second set of numbers.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

from chains import answers, questions, rings


USAGE = "usage: python -m chains.brief <live.json> <watch.json> [answers.json] [out.md] [--free]"


def when(n: int) -> str:
    """One day is a day. "in 1 days" shipped once."""
    if n == 0:
        return "today"
    if n == 1:
        return "tomorrow"
    return f"in {n} days" if n > 0 else f"{-n} days ago"


def render(live: dict, watch: list, statuses: dict, free: bool = False) -> str:
    T = dt.date.fromisoformat(live['as_of'])
    byid = {n['id']: n for n in live['nodes']}
    name = lambda i: (byid.get(i) or {}).get('short') or i.upper()
    pct = lambda v: '—' if v is None else f"{v*100:+.1f}%"
    days = lambda d: (dt.date.fromisoformat(d) - T).days

    out = []
    out.append(f"# This week's questions · {T.strftime('%B %d, %Y')}")
    out.append("")
    out.append("The chip-chain map: who holds what, who is trying to break it, and what gets answered this week. No picks. Every number has a source; anything without one is marked estimate.")
    out.append("")

    # pulse
    cps = live['cps']
    tight = sorted([c for c in cps if c['pressure'] is not None and c['pressure'] > 0], key=lambda c: -c['pressure'])
    erode = sorted([c for c in cps if c['pressure'] is not None and c['pressure'] < 0], key=lambda c: c['pressure'])
    none_ = [c for c in cps if c['pressure'] is None]
    out.append("## The pulse")
    out.append("")
    out.append(f"Over the last 13 weeks, holder return minus listed-challenger return: {len(tight)} chokepoints tightening, {len(erode)} eroding, {len(none_)} with no listed challenger.")
    out.append("")
    if tight:
        c = tight[0]; out.append(f"**Tightening most — {c['he']}:** holder {pct(c['hr13'])} vs challengers {pct(c['cr13'])}. {c['blurb']}")
        out.append("")
    if erode:
        c = erode[0]; out.append(f"**Eroding most — {c['he']}:** holder {pct(c['hr13'])} vs challengers {pct(c['cr13'])}. {c['blurb']}")
        out.append("")

    # --- forecast board: leaks (earlier questions that partly answer this one) ---
    byq = {w['id']: w for w in watch}
    def leak_line(w):
        ls = [l for l in w.get('leaks', []) if l in byq]
        if not ls: return None
        parts = []
        for l in ls:
            st = statuses.get(l, {}).get('status')
            parts.append(byq[l]['who'] + (' (' + {'yes': 'confirmed', 'no': 'refuted', 'mixed': 'partial', 'none': 'not disclosed'}[st] + ')' if st in {'yes': 'confirmed', 'no': 'refuted', 'mixed': 'partial', 'none': 'not disclosed'} else ' (still open)'))
        return "Who leaks first: " + ' · '.join(parts) + '.'
    def lean(w):
        c = {'yes':0,'no':0,'mixed':0}
        for l in w.get('leaks', []):
            st = statuses.get(l, {}).get('status')
            if st in c: c[st] += 1
        n = sum(c.values())
        if not n: return 'o', 0, len(w.get('leaks', []))
        k = 'y' if c['yes']>c['no'] and c['yes']>=c['mixed'] else ('n' if c['no']>c['yes'] and c['no']>=c['mixed'] else 'm')
        return k, n, len(w.get('leaks', []))

    # last week's answers
    past = [w for w in watch if -7 <= days(w['d']) < 0]
    if past:
        out.append("## What was answered last week")
        out.append("")
        for w in past:
            st = statuses.get(w['id'], {})
            s = {'yes': 'confirmed', 'no': 'refuted', 'mixed': 'partial', 'none': 'not disclosed'}.get(st.get('status'), 'not yet marked')
            out.append(f"- **{w['who']}** ({w['d']}): {w['q']} — {s}." + (f" {st['note']}" if st.get('note') else ''))
        out.append("")

    # next 14 days
    nxt = [w for w in sorted(watch, key=lambda w: w['d']) if 0 <= days(w['d']) <= 14]
    out.append("## The next two weeks")
    out.append("")
    if not nxt:
        out.append("No dated question in the next two weeks.")
    for w in nxt:
        tag = 'confirmed' if w['confirmed'] else 'expected'
        who = ', '.join(name(i) for i in w['win'])
        lose = ', '.join(name(i) for i in w['lose'])
        out.append(f"### {w['who']} · {w['d']} · {when(days(w['d']))} · {tag}")
        out.append("")
        # A locked row reaches the free letter with no text
        # at all; it gets the lock line instead of a blank.
        out.append(w["q"] if w.get("q") else "_The question, and what yes and no sound like, are in the weekly mail._")
        out.append("")
        # The four parts, in the order the card shows them. A part the
        # question has nothing for is omitted rather than printed
        # empty: a v1 file has no "no" sentence, and inventing one
        # would be inventing the product.
        if w.get("yes"):
            out.append(f"**Yes looks like:** {w['yes']}")
        if w.get("no"):
            out.append(f"**No looks like:** {w['no']}")
        if w.get("why"):
            out.append(f"**Why it matters:** {w['why']}")
        if leak_line(w): out.append(leak_line(w))
        if who or lose:
            out.append(f"Affected if yes: {who}" + (f" · loses: {lose}" if lose else '') + '.')
        # The second ring: not a second claim, but the first one's
        # mechanical consequence, read off supply edges that were in the
        # map before the question was asked. Omitted where the map has
        # no depth behind the basket -- which is most of the upstream
        # questions, and saying nothing is the honest result there.
        up2 = ', '.join(name(i) for i in (w.get("win2") or []))
        dn2 = ', '.join(name(i) for i in (w.get("lose2") or []))
        if up2 or dn2:
            bits = ([f"{up2} up"] if up2 else []) + ([f"{dn2} down"] if dn2 else [])
            out.append("Second ring (via the map): " + " · ".join(bits) + ".")
        out.append("")


    # -- the forward test ----------------------------------------------------
    # The same records the tracking page draws, in five numbers and one line
    # per open forecast. Read from live.json rather than recomputed: the letter
    # and the page must not be able to disagree.
    tr = live.get("track") or {}
    ts, tf = tr.get("summary") or {}, tr.get("forecasts") or []
    # The free letter carries the RECORD -- forecasts whose forty sessions are
    # complete -- and nothing about a position still open. chains/access.py
    # draws that line; this is the same line, applied to the letter.
    tf = [r for r in tf
          if r.get("entry_date") or r.get("state") == "marked"]
    if free:
        tf = [r for r in tf if r.get("state") == "closed"]
    if ts.get("n_scored") or tf:
        out.append("## Forward test")
        out.append("")
        hit5, r2hit = ts.get("direct_hit_5"), ts.get("ring2_hit_5")
        rate = lambda d: "—" if not d or d.get("value") is None             else f"{d['value']*100:.0f}%"
        avg = lambda d: "—" if not d or d.get("value") is None             else f"{d['value']:+.2f}%"
        cnt = lambda d: f" (n={d.get('n', 0)})" if d else " (n=0)"
        out.append(
            f"{ts['n_scored']} of {ts['n_forecasts']} scored"
            f" · direct hit 5d {rate(hit5)}{cnt(hit5)}"
            f" · direct avg spread 5d {avg(ts.get('direct_spread_5'))}"
            f"{cnt(ts.get('direct_spread_5'))}"
            f" · direct vs map 20d {avg(ts.get('direct_spread_20'))}"
            f"{cnt(ts.get('direct_spread_20'))}"
            f" · second ring hit 5d {rate(r2hit)}{cnt(r2hit)}.")
        out.append("")
        for r in tf:
            if not r.get("entry_date"):
                out.append(f"- {r['who']} · marked {r['marked_at'][:10]}"
                           f" · entry at the next close")
                continue
            t = r.get("today") or {}
            bit = ""
            if r.get("has_r2") and t.get("win2_lose2") is not None:
                bit = f" · second ring {t['win2_lose2']:+.2f}%"
            out.append(
                f"- {r['who']} · day {r['day_index']}"
                f" · up − down {t.get('win_lose', 0):+.2f}%"
                f" · up − map {t.get('win_ew', 0):+.2f}%{bit}")
        out.append("")

    # forecast board: upcoming questions with at least one answered hint
    LEAN={'y':'leans yes','n':'leans no','m':'mixed','o':'no lean yet'}
    brd = [w for w in sorted(watch, key=lambda w: w['d']) if days(w['d']) >= 0 and lean(w)[1] > 0]
    out.append("## The forecast board — what the hints say")
    out.append("")
    if not brd: out.append("No hint has been answered yet.")
    for w in brd:
        k, n, tot = lean(w)
        out.append(f"- **{w['who']}** ({w['d']}): {LEAN[k]} — {n} of {tot} answered. " + leak_line(w))
    out.append("")
    # further out, one line each
    later = [w for w in sorted(watch, key=lambda w: w['d']) if 14 < days(w['d']) <= 60]
    if later:
        out.append("## Further out")
        out.append("")
        for w in later:
            out.append(f"- {w['d']} · **{w['who']}** — {w.get('q') or '_in the weekly mail_'}" + ('' if w['confirmed'] else ' (expected)'))
        out.append("")

    # movers among map nodes, 1 week
    mv = [n for n in live['nodes'] if n.get('px') and n['px'].get('r1w') is not None]
    mv.sort(key=lambda n: n['px']['r1w'])
    if mv:
        out.append("## Who moved this week")
        out.append("")
        up = mv[-3:][::-1]; dn = mv[:3]
        out.append("Up: " + ' · '.join(f"{n['short']} {pct(n['px']['r1w'])}" for n in up) + ".")
        out.append("Down: " + ' · '.join(f"{n['short']} {pct(n['px']['r1w'])}" for n in dn) + ".")
        out.append("")

    out.append("---")
    out.append(f"Prices through {live['last_price_date']}. Map version {live['map_version']}. Japanese names via US depositary receipts. Not investment advice and not a recommendation to anyone.")
    brand = ((live.get("labels") or {}).get("brand") or {})
    if brand.get("footer"):
        out.append("")
        out.append(brand["footer"])
    return '\n'.join(out)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    free = "--free" in argv
    argv = [a for a in argv if a != "--free"]
    if not 2 <= len(argv) <= 4:
        print(USAGE, file=sys.stderr)
        return 2
    live = json.load(open(argv[0], encoding="utf-8"))
    watch = json.load(open(argv[1], encoding="utf-8"))
    # The same second ring the page draws, derived from the same map.
    # Derived here rather than copied out of live.json so the letter
    # and the page cannot drift: both read map.json and watch.json.
    rings.for_rows(watch)
    # The text is not in the watch file any more. The paid mail unlocks every
    # row; the free letter keeps every row too -- the dates are the free half
    # of the offer -- and a locked one prints its header and the lock line
    # instead of a sentence.
    watch = questions.merge(watch, questions.fetch(), "en",
                            unlock_all=not free)
    statuses = {}
    if len(argv) > 2 and argv[2]:
        # Through the validator, not json.load. A bad status is not a crash --
        # it is a wrong word in a document that goes out to a reader.
        statuses = answers.load(Path(argv[2]), ids={w["id"] for w in watch})
    text = render(live, watch, statuses, free=free)
    if len(argv) > 3:
        out = Path(argv[3])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {out}  ({len(text.encode('utf-8')):,} bytes)")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
