"""The weekly brief, in Hebrew. Michael's copy.

    python -m chains.brief_he <live.json> <watch.json> [answers.json] [out.md] [--free]

The English twin, chains/brief.py, is the one that ships. This is the same
reading of the same snapshot, in Hebrew, for one reader.

Same two rules: every number comes from live.json, and nothing here is a
recommendation. See chains/brief.py for why.


``--free`` selects the public letter, the same rule as the English one: only
the rows whose text is already unlocked on the site.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

from chains import answers, questions


USAGE = "usage: python -m chains.brief_he <live.json> <watch.json> [answers.json] [out.md] [--free]"


def render(live: dict, watch: list, statuses: dict) -> str:
    T = dt.date.fromisoformat(live['as_of'])
    byid = {n['id']: n for n in live['nodes']}
    name = lambda i: (byid.get(i) or {}).get('short') or i.upper()
    pct = lambda v: '—' if v is None else f"{v*100:+.1f}%"
    days = lambda d: (dt.date.fromisoformat(d) - T).days

    out = []
    out.append(f"# השאלות של השבוע · {T.strftime('%d.%m.%Y')}")
    out.append("")
    out.append("מפת שרשרת השבבים: מי מחזיק במה, מי מנסה לפרוץ, ומה מתברר השבוע. לא המלצות. כל מספר עם מקור, ומה שאין לו מקור מסומן אומדן.")
    out.append("")

    # pulse
    cps = live['cps']
    tight = sorted([c for c in cps if c['pressure'] is not None and c['pressure'] > 0], key=lambda c: -c['pressure'])
    erode = sorted([c for c in cps if c['pressure'] is not None and c['pressure'] < 0], key=lambda c: c['pressure'])
    none_ = [c for c in cps if c['pressure'] is None]
    out.append("## הדופק")
    out.append("")
    out.append(f"ב־13 השבועות האחרונים, לפי תשואת המחזיק פחות תשואת המאתגרים הסחירים: {len(tight)} צווארי בקבוק מתהדקים, {len(erode)} נשחקים, {len(none_)} בלי מאתגר סחיר.")
    out.append("")
    if tight:
        c = tight[0]; out.append(f"**הכי מתהדק — {c['he']}:** המחזיק {pct(c['hr13'])} מול המאתגרים {pct(c['cr13'])}. {c['blurb']}")
        out.append("")
    if erode:
        c = erode[0]; out.append(f"**הכי נשחק — {c['he']}:** המחזיק {pct(c['hr13'])} מול המאתגרים {pct(c['cr13'])}. {c['blurb']}")
        out.append("")

    # --- forecast board: leaks (earlier questions that partly answer this one) ---
    byq = {w['id']: w for w in watch}
    def leak_line(w):
        ls = [l for l in w.get('leaks', []) if l in byq]
        if not ls: return None
        parts = []
        for l in ls:
            st = statuses.get(l, {}).get('status')
            parts.append(byq[l]['who'] + (' (' + {'yes': 'אושר', 'no': 'הופרך', 'mixed': 'חלקי', 'none': 'לא נמסר'}[st] + ')' if st in {'yes': 'אושר', 'no': 'הופרך', 'mixed': 'חלקי', 'none': 'לא נמסר'} else ' (עוד פתוח)'))
        return "מי מדליף קודם: " + ' · '.join(parts) + '.'
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
        out.append("## מה התברר בשבוע שעבר")
        out.append("")
        for w in past:
            st = statuses.get(w['id'], {})
            s = {'yes': 'אושר', 'no': 'הופרך', 'mixed': 'חלקי', 'none': 'לא נמסר'}.get(st.get('status'), 'עדיין לא סומן')
            out.append(f"- **{w['who']}** ({w['d']}): {w['q']} — {s}." + (f" {st['note']}" if st.get('note') else ''))
        out.append("")

    # next 14 days
    nxt = [w for w in sorted(watch, key=lambda w: w['d']) if 0 <= days(w['d']) <= 14]
    out.append("## השבועיים הקרובים")
    out.append("")
    if not nxt:
        out.append("אין שאלה עם תאריך בשבועיים הקרובים.")
    for w in nxt:
        tag = 'מאושר' if w['confirmed'] else 'צפוי'
        who = ', '.join(name(i) for i in w['win'])
        lose = ', '.join(name(i) for i in w['lose'])
        out.append(f"### {w['who']} · {w['d']} · בעוד {days(w['d'])} ימים · {tag}")
        out.append("")
        out.append(w['q'])
        out.append("")
        out.append(f"להקשיב ל: {w['listen']}.")
        if leak_line(w): out.append(leak_line(w))
        if who or lose:
            out.append(f"מושפעים אם כן: {who}" + (f" · מפסידים: {lose}" if lose else '') + '.')
        out.append("")


    # forecast board: upcoming questions with at least one answered hint
    LEAN={'y': 'נוטה לכן', 'n': 'נוטה ללא', 'm': 'מעורב', 'o': 'עוד אין נטייה'}
    brd = [w for w in sorted(watch, key=lambda w: w['d']) if days(w['d']) >= 0 and lean(w)[1] > 0]
    out.append("## לוח החיזוי — מה הרמזים אומרים")
    out.append("")
    if not brd: out.append("עדיין לא נענה אף רמז.")
    for w in brd:
        k, n, tot = lean(w)
        out.append(f"- **{w['who']}** ({w['d']}): {LEAN[k]} — {n} מתוך {tot} נענו. " + leak_line(w))
    out.append("")
    # further out, one line each
    later = [w for w in sorted(watch, key=lambda w: w['d']) if 14 < days(w['d']) <= 60]
    if later:
        out.append("## בהמשך")
        out.append("")
        for w in later:
            out.append(f"- {w['d']} · **{w['who']}** — {w['listen']}" + ('' if w['confirmed'] else ' (צפוי)'))
        out.append("")

    # movers among map nodes, 1 week
    mv = [n for n in live['nodes'] if n.get('px') and n['px'].get('r1w') is not None]
    mv.sort(key=lambda n: n['px']['r1w'])
    if mv:
        out.append("## מי זז השבוע")
        out.append("")
        up = mv[-3:][::-1]; dn = mv[:3]
        out.append("עלו: " + ' · '.join(f"{n['short']} {pct(n['px']['r1w'])}" for n in up) + ".")
        out.append("ירדו: " + ' · '.join(f"{n['short']} {pct(n['px']['r1w'])}" for n in dn) + ".")
        out.append("")

    out.append("---")
    out.append(f"מחירים עד {live['last_price_date']}. מפה גרסה {live['map_version']}. מניות יפניות דרך תעודות פיקדון בארה\"ב. לא ייעוץ השקעות ולא המלצה לאף אדם.")
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
    # The text is not in the watch file any more. The paid mail unlocks every
    # row; the free one carries only what the site already shows.
    watch = questions.merge(watch, questions.fetch(), "he",
                            unlock_all=not free)
    if free:
        watch = [w for w in watch if w["open"]]
    statuses = {}
    if len(argv) > 2 and argv[2]:
        # Through the validator, not json.load. A bad status is not a crash --
        # it is a wrong word in a document that goes out to a reader.
        statuses = answers.load(Path(argv[2]), ids={w["id"] for w in watch})
    text = render(live, watch, statuses)
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
