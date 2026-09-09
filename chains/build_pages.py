"""The three page builds, and the gate that keeps Hebrew off the public one.

    python -m chains.build_pages

    live-map.html  --(translate)-->  live-map-en.html
           |                                |
           +--------(fetch)--> public-map.html / public-map-en.html

ONE HEBREW SOURCE, THREE DERIVED PAGES
--------------------------------------
``chains/templates/live-map.html`` is the source of truth and the only file a
person edits. The English template is a translation of it, produced by
:func:`build_en_template` from an explicit list of before/after pairs, and the
two public pages are each built from one of those templates by swapping the
artifact-database read for a plain ``fetch``. Nothing else differs: the paywall
lives in the data, so both pages render the same cards and a locked one carries
no sentence in either.

The translation list is the fragile part, and it fails LOUDLY. Every pair must
match: if a string in the Hebrew template is reworded, its pair stops matching
and the build stops and names it. The alternative -- a silent no-op -- would
ship an English page with a Hebrew sentence in the middle of it, which is the
one thing that must never happen.

THE GATE
--------
:func:`build_public_en` refuses to write a file containing any character in
U+0590-U+05FF. It is a last line, not the first: the English page is built from
an English template and fed an English snapshot, so a Hebrew character reaching
this point means a translation pair was missed or the wrong data file was
handed in. Catching it here costs a failed build; not catching it puts Hebrew
in front of an English-speaking reader.

WHICH SNAPSHOT EACH PAGE FETCHES
--------------------------------
The Hebrew page fetches ``live.json``, the English page ``live_en.json``. The
sandbox scripts both fetched ``live.json``; that is a bug the static gate
cannot see, because the substitution happens in the browser. Both files are
written to the same directory, so an English page fetching ``live.json`` would
replace its own English watch rows with Hebrew ones the moment the fetch
succeeded -- a page that passes the gate at build time and violates the rule at
read time.

WHAT THE PUBLIC PAGE DOES NOT CARRY
-----------------------------------
Nothing that the private page does not also withhold. The product boundary
moved OUT of this module and into the data: a snapshot carries the question
text only for rows that are open -- every past date, plus the nearest upcoming
one -- and a locked row has no text field at all. Both pages render the same
rows the same way, so there is no longer a public variant that could be built
wrong and leak, and no private variant that has to be trusted not to.

What is still applied here is the shape of the page: five rows instead of the
whole table, a signup block instead of a status control, and a fetch instead of
a database read.
"""
from __future__ import annotations

import re

from chains.paths import out_dir, templates_dir

# ---------------------------------------------------------------- the config
# Every path this module touches. Templates are read from the repo, output goes
# to the derived-data root -- with the single exception of the English
# template, which is a reviewed artifact and belongs beside its Hebrew source.
TEMPLATE_HE = "live-map.html"
TEMPLATE_EN = "live-map-en.html"
LIVE_HE = "live.json"
LIVE_EN = "live_en.json"
PUBLIC_HE = "public-map.html"
PUBLIC_EN = "public-map-en.html"

HEBREW = re.compile(r"[֐-׿]")


# The board tooltip used to be stripped here, because the private page printed
# every question and the public one could print none. Both pages now obey the
# same rule -- text only where the row is open -- so there is nothing left to
# strip, and one rule is better than two that can disagree about the same row.
# See chains/questions.py.

DB_READ = """(async()=>{ try{ if(!window.claude||!claude.use) return; const db=await claude.use('db'); if(!db) return; const snap=await db.doc('live/latest').get(); const doc=snap&&(snap.data?snap.data():snap); if(doc&&doc.as_of&&doc.as_of>D.as_of&&doc.nodes){ doc.watch=doc.watch||LIVE.watch; D=doc; close(); boot(); } }catch(e){} })();"""

FETCH_READ = """(async()=>{ try{ const r=await fetch('%s',{cache:'no-store'}); if(!r.ok) return; const doc=await r.json(); if(doc&&doc.as_of&&doc.as_of>D.as_of&&doc.nodes){ doc.watch=doc.watch||LIVE.watch; D=doc; close(); boot(); } }catch(e){} })();"""

# The Hebrew footer sentence gains the full disclaimer on the public page. The
# English one does not need this step: its translated form below already
# carries the disclaimer, so there is nothing left to append.
# Ends at the backtick, not at the semicolon: the brand line now follows
# this sentence inside the same expression.
HE_FOOT_FROM = "זו מפה להבנת חשיפות, לא אות מסחר.`"
HE_FOOT_TO = ("זו מפה להבנת חשיפות, לא אות מסחר, לא ייעוץ השקעות ולא המלצה "
              "לאף אדם. כל מספר עם מקור; אומדן פירושו שלא נמצא מקור. מחירים "
              "באיחור של עד שבוע.`")

PUB = {
    "he": {
        "template": TEMPLATE_HE, "live": LIVE_HE,
        "out": PUBLIC_HE, "lang": "he", "dir": "rtl",
        "desc": ("מפה חיה של שרשרת האספקה של שבבי הבינה המלאכותית: 49 תחנות, "
                 "14 צווארי בקבוק שדופקים לפי השוק, ושאלות עם תאריך."),
    },
    "en": {
        "template": TEMPLATE_EN, "live": LIVE_EN,
        "out": PUBLIC_EN, "lang": "en", "dir": "ltr",
        "desc": ("A living map of the AI chip supply chain: 49 stations, 14 "
                 "chokepoints pulsing with the market, a forecast board and "
                 "questions with a date."),
    },
}


# ------------------------------------------------------- Hebrew -> English
# Every pair MUST match. A reworded Hebrew string silently stops matching, and
# a silent no-op here is a Hebrew sentence on the English page.
TRANSLATIONS = [
 ('html{direction:rtl}', 'html{direction:ltr}'),
 ('<span class="lbl">הבדיקות הקרובות</span>', '<span class="lbl">NEXT CHECKPOINTS</span>'),
 ("`מפה ${D.map_version} · מחירים עד <b>${stale}</b> · מתעדכן בשבוע`", "`map ${D.map_version} · prices through <b>${stale}</b> · refreshed weekly`"),
 ("`<b>${e.who}</b><i>${e.days<=0?'היום':(e.days===1?'מחר':'בעוד '+e.days+' ימים')} · ${e.d}</i>`", "`<b>${e.who}</b><i>${e.days<=0?'today':(e.days===1?'tomorrow':'in '+e.days+' days')} · ${e.d}</i>`"),
 ("`13 שבועות <span dir=\"ltr\">${pct(px.r13w)}</span> · שנה <span dir=\"ltr\">${pct(px.r52w)}</span>`:'אין קו מחיר'", "`13 weeks <span dir=\"ltr\">${pct(px.r13w)}</span> · 1 year <span dir=\"ltr\">${pct(px.r52w)}</span>`:'no price line'"),
 ("return '<p class=\"role\">אין קו מחיר.</p>'", "return '<p class=\"role\">No price line.</p>'"),
 ("const he={research:'מחקר',pilot:'פיילוט',qualified:'הסמכה',volume:'ייצור'}[st]||''", "const he={research:'research',pilot:'pilot',qualified:'qualified',volume:'volume'}[st]||''"),
 ("`<h3>מהדוחות (EDGAR)</h3>", "`<h3>From the filings (EDGAR)</h3>"),
 ('<button class="close" id="pclose">סגור</button>', '<button class="close" id="pclose">close</button>'),
 ("'<span class=\"badge sole\">ספק יחיד</span>'", "'<span class=\"badge sole\">sole source</span>'"),
 ("'<span class=\"badge priv\">פרטית</span>'", "'<span class=\"badge priv\">private</span>'"),
 ("'<span style=\"color:var(--ink3)\">אומדן</span>'", "'<span style=\"color:var(--ink3)\">estimate</span>'"),
 ("`<div class=\"nextcp\">הבדיקה הבאה: <b>${nx.who}</b> · ${nx.d} · בעוד ${nx.days} ימים</div>`", "`<div class=\"nextcp\">Next checkpoint: <b>${nx.who}</b> · ${nx.d} · in ${nx.days} days</div>`"),
 ("`<b>הדופק</b> הוא ההצבעה של השוק ב-13 השבועות האחרונים: תשואת המחזיק פחות תשואת המאתגרים הסחירים. חיובי — הנעילה מתהדקת, אדום ומהיר. שלילי — נשחקת, ירוק ואיטי. כרגע: ${nt} מתהדקים, ${ne} נשחקים, ${na} בלי מאתגר סחיר. גודל התחנה לפי שווי שוק. כל חברה במטבע שלה; מניות יפניות דרך תעודות פיקדון בארה\"ב. הנתונים: ${D.nodes.length} תחנות, ${D.cps.reduce((a,c)=>a+c.subs.length,0)} ספקים מתחתיהן, ${D.cps.reduce((a,c)=>a+c.sigs.length,0)} מאתגרים. זו מפה להבנת חשיפות, לא אות מסחר.`",
  "`<b>The pulse</b> is the market's vote over the last 13 weeks: the holder's return minus its listed challengers' return. Positive — the lock is tightening, red and fast. Negative — eroding, green and slow. Right now: ${nt} tightening, ${ne} eroding, ${na} with no listed challenger. Station size is market cap. Each company in its own currency; Japanese names via US depositary receipts. Data: ${D.nodes.length} stations, ${D.cps.reduce((a,c)=>a+c.subs.length,0)} suppliers beneath them, ${D.cps.reduce((a,c)=>a+c.sigs.length,0)} challengers. This is a map of exposures, not a trading signal, not investment advice and not a recommendation to anyone. Every number carries a source; \"estimate\" means none was found. Prices lag by up to a week.`"),
 # The private watch table. The public build replaces this whole section, but
 # the private English page needs it translated too.
 ("const STATUS = {open:'פתוח', yes:'אושר', no:'הופרך', mixed:'חלקי', none:'לא נמסר'};", "const STATUS = {open:'open', yes:'confirmed', no:'refuted', mixed:'partial', none:'not disclosed'};"),
 # Layout flip. RTL reads raw materials on the right; LTR reads them on the
 # left, so the column order and the panel's opening direction both reverse.
 ("const xOf={}; cols.forEach((l,i)=>xOf[l]=W-padR-i*colW);", "const xOf={}; cols.forEach((l,i)=>xOf[l]=padL+i*colW);"),
 ("const dirX = n.x < W-220 ? 1 : -1; // open toward the right (upstream) unless at the right edge", "const dirX = n.x > 220 ? -1 : 1; // open toward the left (upstream) unless at the left edge"),
 ("const padR=70, padL=110,", "const padR=110, padL=70,"),
 # The forecast board.
 ('<h2>לוח החיזוי</h2>', '<h2>The Forecast Board</h2>'),
 ('<p class="lede">ציר הזמן של השאלות. כל עיגול הוא יום שבו מתפרסמת תשובה. החיצים מראים מי מדליף קודם: שאלה שמתבררת מוקדם ונותנת תשובה חלקית לשאלה מאוחרת. רחף על עיגול לראות את שרשרת הרמזים שלו. כשתשובה מגיעה, סמן אותה בטבלה למטה — הלוח צובע אותה ומעדכן את הנטייה של כל מה שתלוי בה. הנטייה היא ספירה של רמזים שכבר נענו, לא תחזית ולא המלצה.</p>',
  '<p class="lede">The timeline of the questions. Each circle is a day an answer is published. The arrows show who leaks first: an early question that partly answers a later one. Hover a circle to see its chain of hints. When an answer lands, mark it in the table below — the board colors it and updates the lean of everything that depends on it. The lean is a count of hints already answered, not a forecast and not a recommendation.</p>'),
 ('<div class="bleg"><span><i class="f"></i>תאריך מאושר</span><span><i></i>תאריך צפוי</span><span><i class="y"></i>אושר</span><span><i class="n"></i>הופרך</span><span><i class="m"></i>חלקי</span><span><s></s>מדליף → שאלה</span></div>',
  '<div class="bleg"><span><i class="f"></i>confirmed date</span><span><i></i>expected date</span><span><i class="y"></i>confirmed</span><span><i class="n"></i>refuted</span><span><i class="m"></i>partial</span><span><s></s>leaker → question</span></div>'),
 # The tag on a row a machine marked. An auto mark and a checked mark colour
 # the board identically, so the page labels the difference rather than hiding
 # it -- a reader who cannot tell them apart is reading a stronger claim than
 # the page is making.
 (".btip{position:absolute;pointer-events:none;background:var(--panel);color:var(--ink);border:1px solid var(--rule);padding:10px 12px;font-size:.95rem;max-width:380px;line-height:1.35;z-index:5;display:none;direction:rtl;", ".btip{position:absolute;pointer-events:none;background:var(--panel);color:var(--ink);border:1px solid var(--rule);padding:10px 12px;font-size:.95rem;max-width:380px;line-height:1.35;z-index:5;display:none;direction:ltr;"),
 # The forecast ledger. Its own STATUS copy is caught by the STATUS pair
 # above, which replaces every occurrence.
 ('<h2>יומן התחזיות</h2>',
  '<h2>The Forecast Ledger</h2>'),
 ('<p class="lede">כל תשובה שסומנה הופכת לרישום: הסלים נקבעו מראש בקובץ שבגיט, לפני האירוע, והציון נמדד מהסגירה הראשונה שאחרי הסימון מול שאר המפה. אין כאן בדיקה לאחור ואי אפשר שתהיה — התחזית נכתבה לפני שהמחיר זז. המדגם קטן, וכל מספר כאן מוצג עם N שלו.</p>',
  '<p class="lede">Every marked answer becomes a record: the baskets were fixed in advance, in a file in git, before the event, and the score is measured from the first close after the mark against the rest of the map. There is no backtest here and there cannot be one — the forecast was written before the price moved. The sample is small, and every number here is shown with its N.</p>'),
 ("  const LT = {h2:'יומן התחזיות', none:'עוד לא סומנה אף תשובה. הרישום הראשון ייפתח כאן ברגע שתסומן.',\n    scored:'נרשמו', pending:'ממתינות', rate:'פגיעה', mean:'עודף ממוצע', sess:'מפגשים',\n    entry:'כניסה', close:'אחרון', gate:'N=30 לפני כל החלטת הון', of:'מתוך',\n    sym:'סימול', ent:'כניסה', last:'אחרון', ret:'תשואה', bench:'מפה', exc:'עודף',\n    pend:'ממתין', hit:'פגע', miss:'החטיא', dirUp:'סל המרוויחים ↑', dirDn:'סל המרוויחים ↓',\n    marked:'סומן', src:'מקור', noentry:'טרם נפתחה מסחר מאז הסימון',\n    direct:'ישיר — הסל הרשום', indirect:'עקיף — טבעת שנייה לפי המפה',\n    noind:'אין עדיין תחזית עקיפה'};",
  "  const LT = {h2:'The Forecast Ledger', none:'No answer has been marked yet. The first entry opens here the moment one is.',\n    scored:'recorded', pending:'pending', rate:'hit rate', mean:'mean excess', sess:'sessions',\n    entry:'entry', close:'last', gate:'N=30 before any capital decision', of:'of',\n    sym:'symbol', ent:'entry', last:'last', ret:'return', bench:'map', exc:'excess',\n    pend:'pending', hit:'hit', miss:'miss', dirUp:'win basket \\u2191', dirDn:'win basket \\u2193',\n    marked:'marked', src:'source', noentry:'no session has closed since the mark',\n    direct:'direct \\u2014 the registered basket', indirect:'indirect \\u2014 second ring, via the map',\n    noind:'no indirect forecast yet'};"),
 # The teaser layer. A locked row is fully visible and simply has no
 # sentence; the dummy below is fixed and is never the real text.
 ("const LOCK = {\n  dummy: 'שאלה נעולה — הטקסט המלא מגיע במייל השבועי יחד עם מה שצריך להקשיב לו בשיחת התוצאות',\n  line: 'הטקסט המלא', mail: 'במייל השבועי',\n  badge: 'השאלה הפתוחה השבוע',\n  marked: 'סומן', };",
  "const LOCK = {\n  dummy: 'Locked question — the full text arrives in the weekly mail, with what to listen for on the call',\n  line: 'The full question', mail: 'in the weekly mail',\n  badge: 'this week\\'s open question',\n  marked: 'marked', };"),
 ("  const T = {head:'כל שאלה, לפני שהיא נענית',\n    promise:'כל שאלה עם תאריך, מה להקשיב לו, מי מדליף קודם, והתשובה עם המקור שלה — לפני כל אירוע ואחריו.',\n    btn:'קבל את המייל השבועי', soon:'בקרוב',\n    disc:'חינם ובתשלום, בלי המלצות. זו מפה להבנת חשיפות, לא אות מסחר, לא ייעוץ השקעות ולא המלצה לאף אדם.',\n    q:'שאלות', open:'פתוחות', next:'התשובה הבאה', days:'ימים', today:'היום', tomorrow:'מחר'};",
  "  const T = {head:'Every question, before it is answered',\n    promise:'Every dated question, what to listen for, who leaks first, and the answer with its source — before and after each event.',\n    btn:'Get the weekly mail', soon:'coming soon',\n    disc:'Free and paid, no recommendations. This is a map of exposures, not a trading signal, not investment advice and not a recommendation to anyone.',\n    q:'questions', open:'open', next:'next answer', days:'days', today:'today', tomorrow:'tomorrow'};"),
 # One visual language: plain words for holder/challenger, a two-row
 # legend, and the peer panel's section titles.
 ("const WORDS = {holder:'שולט בצוואר הבקבוק', challenger:'מנסה להחליף אותו',\n  buys:'קונה מ', sells:'מוכרת ל', peers:'אחרים בשכבה הזאת',\n  via:'מתחרה דרך', against:'מול', sells1:'מוכרת', to:'ל־',\n  legendLine:'איזה קו?', legendRing:'האם השוק לוחץ על צוואר הבקבוק?'};",
  "const WORDS = {holder:'controls the chokepoint', challenger:'trying to replace them',\n  buys:'Buys from', sells:'Sells to', peers:'Others in this layer',\n  via:'Challenges through', against:'against', sells1:'sells', to:'to ',\n  legendLine:'Which line?', legendRing:'Is the market pressing on the chokepoint?'};"),
 ('    `<span class="hint">רחף על תחנה או על קו · לחץ לפתיחה · החץ מצביע על הקונה</span>`\n    + `<div class="row"><b>${WORDS.legendLine}</b>`\n    + Object.keys(LCOL).map(k=>`<span><i style="background:${LCOL[k]}"></i>${LHE[k]}</span>`).join(\'\')\n    + `</div><div class="row"><b>${WORDS.legendRing}</b>`\n    + `<span><i class="pl"></i>מתהדק</span><span><i class="pe"></i>נשחק</span>`\n    + `<span><i class="pa"></i>אי אפשר למדוד</span></div>`;',
  '    `<span class="hint">hover a station or a line · click to open · the arrow points at the buyer</span>`\n    + `<div class="row"><b>${WORDS.legendLine}</b>`\n    + Object.keys(LCOL).map(k=>`<span><i style="background:${LCOL[k]}"></i>${LHE[k]}</span>`).join(\'\')\n    + `</div><div class="row"><b>${WORDS.legendRing}</b>`\n    + `<span><i class="pl"></i>tightening</span><span><i class="pe"></i>eroding</span>`\n    + `<span><i class="pa"></i>cannot be measured</span></div>`;'),
 ('    h+=`<h3>מי מספק למי ש${WORDS.holder} · ${t1.length} ישירים, ${t2.length} מתחתיהם</h3>`;',
  '    h+=`<h3>Who supplies the company that ${WORDS.holder} · ${t1.length} direct, ${t2.length} beneath them</h3>`;'),
 ('    h+=`<h3>מי ${WORDS.challenger} · ${c.sigs.length}</h3>`;',
  '    h+=`<h3>Who is ${WORDS.challenger} · ${c.sigs.length}</h3>`;'),
 ("'למי ששולט אין קו מחיר.':'אין מי שמנסה להחליף אותו ונסחר. הטבעת כתומה: אי אפשר למדוד את הלחץ בשוק.'",
  "'The company that controls it has no price line.':'Nobody listed is trying to replace them. Amber ring: the market pressure cannot be measured.'"),
 ("'הנעילה מתהדקת: מי ששולט עוקף את מי שמנסה להחליף אותו.' : 'הנעילה נשחקת: מי שמנסה להחליף עוקף את מי ששולט.'",
  "'The lock is tightening: the company in control is outrunning the ones trying to replace it.' : 'The lock is eroding: the ones trying to replace it are outrunning the company in control.'"),
 # The board's own words. The lane NAMES come from the map now; the
 # rest of BT is still prose that has to be translated.
 ("const BT = {lanes:(D.labels||{}).lanes||{}, today:'היום', past:'עבר', in:'בעוד', days:'ימים', conf:'מאושר', exp:'צפוי', leaksIn:'רמזים שמגיעים לפני:', leaksOut:'מדליף אל:', noLeaks:'אין שאלה מוקדמת שמדליפה אליה.', later:'מעבר לטווח הלוח:', hintsH:'מה הרמזים אומרים עד עכשיו', hintsNone:'עדיין לא נענה אף רמז. הראשון שיצבע את הלוח:', of:'מתוך', answered:'נענו', leanY:'נוטה לכן', leanN:'נוטה ללא', leanM:'מעורב', leanO:'עוד אין נטייה', stillOpen:'עוד פתוחים:', pulse:'דופק', autoSuffix:' (אוטומטי)', locked:'🔒 הטקסט המלא — במייל השבועי'};",
  "const BT = {lanes:(D.labels||{}).lanes||{}, today:'today', past:'past', in:'in', days:'days', conf:'confirmed', exp:'expected', leaksIn:'Hints that arrive first:', leaksOut:'Leaks into:', noLeaks:'No earlier question leaks into this one.', later:'Beyond the board:', hintsH:'What the hints say so far', hintsNone:'No hint has been answered yet. The first to color the board:', of:'of', answered:'answered', leanY:'leans yes', leanN:'leans no', leanM:'mixed', leanO:'no lean yet', stillOpen:'still open:', pulse:'pulse', autoSuffix:' (auto)', locked:'🔒 The full question — in the weekly mail'};"),
 # The map's one-line instruction. It used to travel with the <h1> that
 # the brand header replaced; it is still here and still needs a pair.
 ('<div class="sub">מחומרי הגלם בימין אל מרכזי הנתונים בשמאל. תחנה שדופקת — צוואר בקבוק. לחץ עליה.</div>',
  '<div class="sub">Raw materials on the left, data centers on the right. A pulsing station is a chokepoint. Click it.</div>'),
 # The question cards. The placeholder below is fixed text in both
 # languages and is never the real sentence.
 ("  const T = {\n    yes:'תשובה חיובית נשמעת כך', no:'תשובה שלילית נשמעת כך', why:'למה זה משנה.',\n    lockA:'\\u{1F512} השאלה, ואיך נשמעת תשובה חיובית ושלילית — ',\n    lockB:'במייל השבועי',\n    conf:'מאושר', exp:'צפוי',\n    day:'יום', days:'ימים', today:'היום', tomorrow:'מחר', past:'לפני',\n    up:'עולה אם כן', down:'יורד אם כן', ring2:'טבעת שנייה · לפי המפה',\n    answered:'נענו', more:'נוספים', auto:'אוטומטי', evidence:'העדות:',\n    marks:{yes:'אושר', no:'הופרך', mixed:'לא ברור', none:'לא ברור',\n           open:'לא ברור'},\n  };",
  "  const T = {\n    yes:'Yes looks like', no:'No looks like', why:'Why it matters.',\n    lockA:'\\u{1F512} The question, and what yes and no sound like — ',\n    lockB:'in the weekly mail',\n    conf:'confirmed', exp:'expected',\n    day:'day', days:'days', today:'today', tomorrow:'tomorrow', past:'ago',\n    up:'up if yes', down:'down if yes', ring2:'second ring · via the map',\n    answered:'Answered', more:'more', auto:'auto', evidence:'Evidence:',\n    marks:{yes:'confirmed', no:'refuted', mixed:'unclear', none:'unclear',\n           open:'unclear'},\n  };"),
 ("  const PH = {q:'איזה מספר בשיחת התוצאות מכריע את השאלה שכולם כאן כבר מתווכחים עליה',\n    yes:'החברה נוקבת במספר מעל הטווח שעליו הנחתה ברבעון שעבר, ואומרת שהמגבלה זזה.',\n    no:'המספר נוחת בתוך הטווח הישן והשפה על הקיבולת לא משתנה מהפעם הקודמת.',\n    why:'זה קובע איזו משתי החברות מחזיקה את החלק הנדיר בעוד שנה.'};",
  "  const PH = {q:'Which number on the call settles the question that everyone in this room is already arguing about',\n    yes:'The company names a figure above the range it guided to last quarter, and says the constraint has moved.',\n    no:'The number lands inside the old range and the language about capacity is unchanged from last time.',\n    why:'It decides which of two companies is holding the scarce part twelve months from now.'};"),
 ('<div class="eyebrow">04 · שאלות עם תאריך</div>',
  '<div class="eyebrow">04 · Questions with a date</div>'),
 ('<h2>מה מתברר בהמשך — ואיך תיראה התשובה</h2>',
  '<h2>What gets answered next — and what the answer will look like</h2>'),
 ('<p class="lede">כל כרטיס הוא שאלה שמתבררת ביום ידוע. לא "מה לקנות": איך נשמעת תשובה חיובית ואיך נשמעת שלילית בשיחת התוצאות, ואילו תחנות על המפה זזות אם היא חיובית. השאלה הבאה פתוחה; השאר מגיעות במייל השבועי.</p>',
  '<p class="lede">Every card is a question that gets answered on a known day. Not "what to buy": what "yes" and "no" sound like on the call, and which stations on the map move if it is yes. The next question is open; the rest arrive in the weekly mail.</p>'),
]


# ---------------------------------------------------------------- the gates
SCRIPT_OR_STYLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.S | re.I)

# What a reader can actually see. The page's own source legitimately contains
# both of these words -- `typeof x !== 'undefined'`, and the English ternary
# that produces "in N days" -- so a check over the whole file would be a check
# that can only be satisfied by writing worse JavaScript.
def visible_text(html: str) -> str:
    return SCRIPT_OR_STYLE.sub(" ", html)


# Rendered-text defects that mean a field was missing or a plural was not
# thought about. Both have shipped before.
BAD_RENDER = (
    ("undefined", "a field reached the page as the word 'undefined'"),
    ("1 days", "'1 days' -- one day is a day"),
    ("NaN", "a number reached the page as NaN"),
)


def render_faults(html: str) -> list[str]:
    text = visible_text(html)
    return [f"{needle!r}: {why}" for needle, why in BAD_RENDER if needle in text]


def assert_renders_clean(html: str, where: str) -> None:
    faults = render_faults(html)
    if faults:
        raise ValueError(f"{where}: " + "; ".join(faults))


def hebrew_runs(text: str, context: int = 40) -> list[str]:
    """Every stretch of Hebrew in ``text``, with enough around it to find it."""
    out, seen = [], set()
    for m in re.finditer(r"[֐-׿][^<>\"`';{}]*", text):
        s = m.group(0).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        lo = max(0, m.start() - context)
        out.append(text[lo:m.end() + context].replace("\n", " "))
    return out


def assert_no_hebrew(text: str, where: str) -> None:
    runs = hebrew_runs(text)
    if runs:
        raise ValueError(
            f"{where}: {len(runs)} Hebrew string(s) in an English page. "
            f"A translation pair was missed, or the wrong snapshot was fed "
            f"in.\n  " + "\n  ".join(runs[:10]))


# ------------------------------------------------------------- the builds
def translate(he_html: str) -> tuple[str, list[str]]:
    """Apply every pair. Returns the English text and the pairs that missed."""
    missing, out = [], he_html
    for a, b in TRANSLATIONS:
        if a not in out:
            missing.append(a)
        out = out.replace(a, b)
    return out, missing


def build_en_template(src=None, dst=None) -> object:
    """The English template, from the Hebrew one.

    Writes into chains/templates/ -- the second and last place this package
    writes to the repository, alongside chains/watch.py. That is deliberate:
    the translation is a reviewed artifact and belongs in a diff beside the
    source it was made from. A run in which the Hebrew template did not change
    rewrites the file with identical bytes and produces no diff at all.
    """
    src = src or (templates_dir() / TEMPLATE_HE)
    dst = dst or (templates_dir() / TEMPLATE_EN)
    en, missing = translate(src.read_text(encoding="utf-8"))
    if missing:
        raise ValueError(
            f"{len(missing)} translation pair(s) matched nothing in "
            f"{src.name}. The Hebrew was reworded and the pair was not; "
            f"leaving it would put Hebrew on the English page.\n  "
            + "\n  ".join(m[:100] for m in missing))
    left = hebrew_runs(en)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(en, encoding="utf-8", newline="\n")
    return dst, len(en), left


def _must_replace(h: str, a: str, b: str, what: str) -> str:
    """Replace, or say which constant has drifted from the template.

    Every substitution in the public build is load-bearing, and a str.replace
    that matches nothing returns the string unchanged and says nothing. That
    already happened once: see the note on WROW_PRIVATE.
    """
    if a not in h:
        raise ValueError(
            f"{what}: the template does not contain the string this build "
            f"expects to replace. It was reworded, and the constant in "
            f"chains/build_pages.py was not.\n  looking for: {a[:120]}")
    return h.replace(a, b)


def public_page(template: str, live: str, cfg: dict) -> str:
    """A template plus a snapshot, wired for a page with no database.

    There used to be a five-row teaser spliced in here, because the private
    page printed every question and the public one could print none. Both pages
    now obey the data -- a locked row carries no sentence in either -- so there
    is nothing left to swap, and no public-only variant that could be built
    wrong and leak.
    """
    h = template

    # 1. the artifact database is not reachable from a public page
    h = _must_replace(h, DB_READ, FETCH_READ % cfg["live"], "database read")

    if cfg["lang"] == "he":
        h = _must_replace(h, HE_FOOT_FROM, HE_FOOT_TO, "footer disclaimer")

    head = (f'<!doctype html>\n<html lang="{cfg["lang"]}" '
            f'dir="{cfg["dir"]}">\n<head>\n<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width,'
            f'initial-scale=1">\n'
            f'<meta name="description" content="{cfg["desc"]}">\n')
    k = h.index("</style>") + len("</style>")
    doc = head + h[:k] + "\n</head>\n<body>\n" + h[k:] + "\n</body>\n</html>\n"
    return doc.replace("__LIVE__", live)


def _build_public(lang: str, template=None, live=None, out=None,
                  teaser=None):
    cfg = PUB[lang]
    template = template or (templates_dir() / cfg["template"])
    live = live or (out_dir() / cfg["live"])
    out = out or (out_dir() / cfg["out"])
    doc = public_page(template.read_text(encoding="utf-8"),
                      live.read_text(encoding="utf-8"), cfg)
    return doc, out


def build_public_he(template=None, live=None, out=None, teaser=None):
    doc, out = _build_public("he", template, live, out)
    assert_renders_clean(doc, out.name)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8", newline="\n")
    return out, len(doc.encode("utf-8"))


def build_public_en(template=None, live=None, out=None, teaser=None):
    """The English public page. Refuses to write a Hebrew character."""
    doc, out = _build_public("en", template, live, out)
    assert_no_hebrew(doc, out.name)
    assert_renders_clean(doc, out.name)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8", newline="\n")
    return out, len(doc.encode("utf-8"))


def main() -> int:
    dst, n, left = build_en_template()
    print(f"wrote {dst}  ({n:,} chars)")
    if left:
        print(f"  WARNING {len(left)} Hebrew string(s) survived translation:")
        for s in left[:10]:
            print(f"    {s[:100]}")
    for fn in (build_public_he, build_public_en):
        p, size = fn()
        print(f"wrote {p}  ({size:,} bytes, {size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
