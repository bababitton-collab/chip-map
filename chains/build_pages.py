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
from chains.questions import languages_for

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
# What focus mode draws around a station, written by chains/live_snapshot.py
# and inlined into every page at build time.
FOCUS_HE = "focus.json"
FOCUS_EN = "focus_en.json"

HEBREW = re.compile(r"[֐-׿]")


# The board tooltip used to be stripped here, because the private page printed
# every question and the public one could print none. Both pages now obey the
# same rule -- text only where the row is open -- so there is nothing left to
# strip, and one rule is better than two that can disagree about the same row.
# See chains/questions.py.

DB_READ = """(async()=>{ try{ if(!window.claude||!claude.use) return; const db=await claude.use('db'); if(!db) return; const snap=await db.doc('live/latest').get(); let doc=snap&&(snap.data?snap.data():snap); if(doc&&doc.enc==='gzip+b64'&&doc.z){ const b=Uint8Array.from(atob(doc.z),c=>c.charCodeAt(0)); const s=new Blob([b]).stream().pipeThrough(new DecompressionStream('gzip')); doc=JSON.parse(await new Response(s).text()); } if(doc&&doc.as_of&&doc.as_of>D.as_of&&doc.nodes){ doc.watch=doc.watch||LIVE.watch; D=doc; close(); boot(); } }catch(e){} })();"""

# The private page reads the decrypted tracking payload out of the artifact
# database. The public build removes that block outright rather than pointing
# it somewhere else: there is no public URL for it, and a public page must not
# reach for a private database at all.
TRACK_DB_READ = """// The forward test, in full, from the copy the 07:00 task decrypts into the
// database. Absent on the public build and on any browser without it -- the
// section stays hidden rather than showing an empty shell.
(async()=>{ try{
  if(!window.claude||!claude.use||!window.renderTrack) return;
  const db=await claude.use('db'); if(!db) return;
  const snap=await db.doc('track/latest').get();
  const doc=snap&&(snap.data?snap.data():snap);
  if(!doc||!doc.forecasts||!doc.forecasts.length) return;
  const sect=document.getElementById('fwdsect');
  const n=window.renderTrack(document.getElementById('fwdcards'), doc);
  document.getElementById('fwdlede').textContent =
    n+' '+FWD.tracked+' · '+FWD.through+' '+(doc.as_of||'');
  sect.hidden=false;
}catch(e){} })();"""

TRACK_GONE = ("// the forward test is not on the public page: the payload is "
              "published encrypted and opened in the reader's own browser")

FETCH_READ = """(async()=>{ try{ const r=await fetch('%s',{cache:'no-store'}); if(!r.ok) return; const doc=await r.json(); if(doc&&doc.as_of&&doc.as_of>D.as_of&&doc.nodes){ doc.watch=doc.watch||LIVE.watch; D=doc; close(); boot(); } }catch(e){} })();"""

# The Hebrew footer used to be short on the private page and gain the full
# disclaimer on the public one, by substitution here. The pressure-method
# footer now carries the disclaimer in the source, in both languages, so there
# is nothing left to append -- and a substitution that adds nothing is a step
# that can silently stop running. What is still worth enforcing is that the
# sentence is THERE, so the step became an assertion.
HE_FOOT_MUST = "לא אות מסחר ולא ייעוץ השקעות."

PUB = {
    "he": {
        "template": TEMPLATE_HE, "live": LIVE_HE, "focus": FOCUS_HE,
        "out": PUBLIC_HE, "lang": "he", "dir": "rtl",
        "desc": ("מפה חיה של שרשרת האספקה של שבבי הבינה המלאכותית: {nodes} תחנות, "
                 "{cps} צווארי בקבוק שדופקים לפי השוק, ושאלות עם תאריך."),
    },
    "en": {
        "template": TEMPLATE_EN, "live": LIVE_EN, "focus": FOCUS_EN,
        "out": PUBLIC_EN, "lang": "en", "dir": "ltr",
        # The counts are read from the snapshot at build time: a number
        # typed here was true on the day it was typed, and this one said 49
        # for a map that had grown to 58.
        "desc": ("A living map of the AI chip supply chain: {nodes} stations, "
                 "{cps} chokepoints pulsing with the market, a forecast board "
                 "and questions with a date."),
    },
}


# ------------------------------------------------------- Hebrew -> English
# Every pair MUST match. A reworded Hebrew string silently stops matching, and
# a silent no-op here is a Hebrew sentence on the English page.
TRANSLATIONS = [
 ("const FWD = {tracked:'שאלות במעקב', through:'מחירים עד'};",
  "const FWD = {tracked:'questions tracked', through:'prices through'};"),
 ('<h2>לוח התוצאות</h2>',
  '<h2>Track record</h2>'),
 ('    `<div class="row"><b>${WORDS.legendLine}</b>`\n    + Object.keys(LCOL).map(k=>`<span><i style="background:${LCOL[k]}"></i>${LHE[k]}</span>`).join(\'\')\n    + `</div><div class="row"><b>${WORDS.legendRing}</b>`\n    + `<span><i class="pl"></i>מתהדק</span><span><i class="pe"></i>מתרופף</span>`\n    + `<span><i class="pa"></i>אין מתחרה נסחר</span></div>`;',
  '    `<div class="row"><b>${WORDS.legendLine}</b>`\n    + Object.keys(LCOL).map(k=>`<span><i style="background:${LCOL[k]}"></i>${LHE[k]}</span>`).join(\'\')\n    + `</div><div class="row"><b>${WORDS.legendRing}</b>`\n    + `<span><i class="pl"></i>Tightening</span><span><i class="pe"></i>Easing</span>`\n    + `<span><i class="pa"></i>No listed challenger</span></div>`;'),
    ("רחף לבדיקה · בחר תחנה לפרטים · \"עיון בתחנות\" לחיפוש וסינון", "Hover to inspect · select to open details · use Browse stations to search and filter"),
    # What the same hint says where there is no hover to give.
    ("const TOUCH_HINT = 'החלק הצידה כדי לנוע בין השכבות. הקש על תחנה לפרטים.';",
     "const TOUCH_HINT = 'Swipe sideways to explore layers. Tap a station for details.';"),
    ("לוח התוצאות →", "Track record →"),
 ('html{direction:rtl}', 'html{direction:ltr}'),
 ('<span class="lbl">האירועים הקרובים</span>', '<span class="lbl">UPCOMING EVENTS</span>'),
 # The cadence, from .github/workflows/build.yml: `30 5 * * 2-6` is once
 # after each US trading session, not weekly.
 ("`מפה ${D.map_version} · נתוני שוק עד <b>${stale}</b> · נבנה מחדש אחרי כל יום מסחר`",
  "`map ${D.map_version} · market data through <b>${stale}</b> · rebuilt after each trading session`"),
 ("`<b>${e.who}</b><i>${e.days<=0?'היום':(e.days===1?'מחר':'בעוד '+e.days+' ימים')} · ${e.d}</i>`", "`<b>${e.who}</b><i>${e.days<=0?'today':(e.days===1?'tomorrow':'in '+e.days+' days')} · ${e.d}</i>`"),
 ("`13 שבועות <span dir=\"ltr\">${pct(px.r13w)}</span> · שנה <span dir=\"ltr\">${pct(px.r52w)}</span>`:'אין קו מחיר'", "`13 weeks <span dir=\"ltr\">${pct(px.r13w)}</span> · 1 year <span dir=\"ltr\">${pct(px.r52w)}</span>`:'no price line'"),
 ("return '<p class=\"role\">אין קו מחיר.</p>'", "return '<p class=\"role\">No price line.</p>'"),
 ("const he={research:'מחקר',pilot:'פיילוט',qualified:'הסמכה',volume:'ייצור'}[st]||''", "const he={research:'research',pilot:'pilot',qualified:'qualified',volume:'volume'}[st]||''"),
 ("`<h3>מהדוחות (EDGAR)</h3>", "`<h3>From the filings (EDGAR)</h3>"),
 ('<button class="close" id="pclose">סגור</button>', '<button class="close" id="pclose">close</button>'),
 ("'<span class=\"badge sole\">ספק יחיד</span>'", "'<span class=\"badge sole\">sole source</span>'"),
 ("'<span class=\"badge priv\">פרטית</span>'", "'<span class=\"badge priv\">private</span>'"),
 ("const EXPOSED='חשופה ל־';", "const EXPOSED='Exposed to';"),
 ("'קו מחיר דליל: מעט מסחר':'אין סגירה עדכנית'", "'thin price line: little trading':'no recent close'"),
 ("n.thin?'קו מחיר דליל':'מחיר ישן'", "n.thin?'thin price line':'stale price'"),
 ("' · '+d+' ימים'", "' · '+d+' days'"),
 ("'<span style=\"color:var(--ink3)\">אומדן</span>'", "'<span style=\"color:var(--ink3)\">estimate</span>'"),
 ("`<div class=\"nextcp\">הבדיקה הבאה: <b>${nx.who}</b> · ${nx.d} · בעוד ${nx.days} ימים</div>`", "`<div class=\"nextcp\">Next checkpoint: <b>${nx.who}</b> · ${nx.d} · in ${nx.days} days</div>`"),
 # The pressure method, as the brief words it, minus two claims the data does
 # not carry. "Station size reflects market capitalization" holds for 34 of
 # 178 stations -- four of the five maps record no market value at all and
 # draw every station at one fixed radius -- so the sentence now says where it
 # applies. "Every published figure carries a source" is not true of the
 # market caps or the price-derived returns, which carry none; what IS true is
 # the supplier shares, 88 sourced and 42 published blank rather than
 # unsourced, so the claim is narrowed to them.
 ("`<span class=\"eyebrow\">שיטת מדידת הלחץ</span><b>הלחץ</b> משווה את תשואת המחזיק ב-13 השבועות האחרונים לתשואת המתחרים הנסחרים. ערך חיובי מציין התהדקות; ערך שלילי מציין התרופפות. כשאין מתחרה נסחר לא מוצג ערך. תחנה שרשום לה שווי שוק מצוירת לפיו; לכל השאר גודל אחיד. כל חברה במטבע המסחר שלה; מניות יפניות דרך תעודות פיקדון בארה\"ב. נתחי ספקים מוצגים עם המקור שלהם, ונשארים ריקים כשאין מקור רשום; אומדנים מסומנים. נתוני שוק עשויים לפגר עד שבוע. זו מפה להבנת חשיפות, לא אות מסחר ולא ייעוץ השקעות.`",
  "`<span class=\"eyebrow\">PRESSURE METHOD</span><b>Pressure</b> compares the chokepoint holder's 13-week return with its listed challengers. Positive values indicate tightening; negative values indicate easing. No value is shown when there is no listed challenger. A station with a recorded market value is drawn to it; the rest are drawn at one fixed size. Prices remain in each company's trading currency; Japanese names via US depositary receipts. Supplier shares are shown with their source and left blank where none is recorded; estimates are labelled. Market data may lag by up to one week. This is a map of exposures, not a trading signal and not investment advice.`"),
 # The private watch table. The public build replaces this whole section, but
 # the private English page needs it translated too.
 ("const STATUS = {open:'פתוח', yes:'אושר', no:'הופרך', mixed:'חלקי', none:'לא נמסר'};", "const STATUS = {open:'open', yes:'confirmed', no:'refuted', mixed:'partial', none:'not disclosed'};"),
 # Layout flip. RTL reads raw materials on the right; LTR reads them on the
 # left, so the column order and the panel's opening direction both reverse.
 ("const xOf={}; cols.forEach((l,i)=>xOf[l]=W-padR-i*colW);", "const xOf={}; cols.forEach((l,i)=>xOf[l]=padL+i*colW);"),
 ("const padR=70, padL=110,", "const padR=110, padL=70,"),
 # The relationship diagram's phone view.
 ("  const REL = {view:'הצג קשרים', close:'סגור', title:'קשרים',\n    up:'עולה אם כן', down:'יורד אם כן', none:'אין סל רשום לשאלה הזו.'};",
  "  const REL = {view:'View relationships', close:'Close', title:'Relationships',\n    up:'up if yes', down:'down if yes', none:'No basket is registered for this question.'};"),
 # The stations rail: the map's contents as HTML, beside the canvas.
 ("const RAIL = {stations:'תחנות', search:'חיפוש לפי חברה או סימול', sortName:'שם',\n  sortLayer:'שכבה', sortPulse:'לחץ', back:'חזרה לתחנות',\n  none:'אין תחנה שמתאימה לסינון הזה.', cp:'צוואר בקבוק', pulseT:'מתהדק',\n  pulseE:'מתרופף', pulseA:'אין מתחרה נסחר', pulseNo:'לא צוואר בקבוק',\n  lLayer:'שכבה', lCp:'צוואר בקבוק', lPulse:'לחץ', lSort:'מיון',\n  anyLayer:'כל השכבות', cpAll:'כל התחנות',\n  cpYes:'רק צווארי בקבוק', cpNo:'לא צווארי בקבוק', anyPulse:'כל מצבי הלחץ',\n  count:'{n} מתוך {N} תחנות', clear:'נקה סינון', copy:'העתק קישור לתצוגה',\n  copied:'הקישור הועתק'};",
  "const RAIL = {stations:'Stations', search:'Search by company or ticker', sortName:'Name',\n  sortLayer:'Layer', sortPulse:'Pressure', back:'Back to stations',\n  none:'No stations match these filters.', cp:'chokepoint', pulseT:'Tightening',\n  pulseE:'Easing', pulseA:'No listed challenger', pulseNo:'Not a chokepoint',\n  lLayer:'Layer', lCp:'Chokepoint', lPulse:'Pressure', lSort:'Sort',\n  anyLayer:'All layers', cpAll:'All stations',\n  cpYes:'Chokepoints only', cpNo:'Non-chokepoints', anyPulse:'All pressure states',\n  count:'{n} of {N} stations', clear:'Clear filters', copy:'Copy view link',\n  copied:'View link copied'};"),
 ('<aside class="srail" id="srail" aria-label="תחנות"></aside>',
  '<aside class="srail" id="srail" aria-label="Stations"></aside>'),
 ('<button type="button" class="railbtn" id="railbtn" aria-expanded="false" aria-controls="srail">עיון בתחנות</button>',
  '<button type="button" class="railbtn" id="railbtn" aria-expanded="false" aria-controls="srail">Browse stations</button>'),
 # The forecast board.
 ('<h2>לוח התאריכים</h2>', '<h2>Forecast calendar</h2>'),
 # The board lead says what the section IS. The mechanics it used to carry --
 # contracts, benchmarks, timing, scoring -- are stated once, in the
 # "How scoring works" disclosure beside the ledger, and linked from here.
 # Repeating them above every list was how the page got long enough that the
 # lists below them stopped being read.
 ('<p class="lede">שאלות מתוארכות לאורך השרשרת. סימון מלא — תאריך תשובה מאושר; סימון חלול — תאריך צפוי. <a class="howlink" href="#howscoring">שיטת המדידה</a></p>',
  '<p class="lede">Dated questions across the chain. Solid markers have confirmed answer dates; outlined markers have expected dates. <a class="howlink" href="#howscoring">Measurement method</a></p>'),
 ('<div class="bleg"><span><i class="f"></i>תאריך מאושר</span><span><i></i>תאריך צפוי</span><span><i class="y"></i>אושר</span><span><i class="n"></i>הופרך</span><span><i class="m"></i>חלקי</span><span><s></s>תשובה מוקדמת → שאלה מאוחרת</span></div>',
  '<div class="bleg"><span><i class="f"></i>date confirmed</span><span><i></i>date expected</span><span><i class="y"></i>confirmed</span><span><i class="n"></i>refuted</span><span><i class="m"></i>partial</span><span><s></s>earlier answer → later question</span></div>'),
 # The tag on a row a machine marked. An auto mark and a checked mark colour
 # the board identically, so the page labels the difference rather than hiding
 # it -- a reader who cannot tell them apart is reading a stronger claim than
 # the page is making.
 (".btip{position:absolute;pointer-events:none;background:var(--panel);color:var(--ink);border:1px solid var(--rule);padding:10px 12px;font-size:.95rem;max-width:380px;line-height:1.35;z-index:5;display:none;direction:rtl;", ".btip{position:absolute;pointer-events:none;background:var(--panel);color:var(--ink);border:1px solid var(--rule);padding:10px 12px;font-size:.95rem;max-width:380px;line-height:1.35;z-index:5;display:none;direction:ltr;"),
 # The forecast ledger. Its own STATUS copy is caught by the STATUS pair
 # above, which replaces every occurrence.
 ('<h2>תוצאות שנמדדו</h2>',
  '<h2>Measured outcomes</h2>'),
 ('<p class="lede">שאלות שנענו והתוצאות שנמדדו אחריהן בשוק. תשובות חלקיות נשארות ברישום הציבורי ואינן נכנסות לציון.</p>',
  '<p class="lede">Resolved questions and their forward market results. Partial answers remain in the public record but do not enter the score.</p>'),
 # The mechanics, once, where the ledger can be read beside them.
 ('<summary>שיטת המדידה</summary>', '<summary>Measurement method</summary>'),
 ('<p>כל שאלה נושאת חוזה ניקוד שנכתב מראש: הסלים, כלל הכן/לא, האופקים ומדדי ההשוואה, מגובבים ומפורסמים עם היום שבו נקבעו. רק חוזים שנקבעו לפני התשובה נחשבים רישום מוקדם.</p>',
  '<p>Every question carries a scoring contract written in advance: the baskets, the yes/no rule, the horizons and the benchmarks, hashed and published with the day they were set. Only contracts committed before the answer count as preregistered.</p>'),
 ('<p>הציון נמדד מהסגירה הראשונה שאחרי הסימון, מול המפה בשקלול שווה ומול מדד ההשוואה השני, ונקרא באופק הראשי. אין כאן בדיקה לאחור ואי אפשר שתהיה — התחזית נכתבה לפני שהמחיר זז. המדגם קטן, וכל מספר כאן מוצג עם N שלו.</p>',
  '<p>The score is measured from the first close after the mark, against the equal-weight map and against the second benchmark, and read at the primary horizon. There is no backtest here and there cannot be one — the forecast was written before the price moved. The sample is small, and every number here is shown with its N.</p>'),
 ("  const LT = {h2:'תוצאות שנמדדו', none:'עדיין לא נרשמו תשובות.',\n    nextAnswer:'התשובה הבאה הצפויה', answerRec:'תשובה נרשמה', answersRec:'תשובות נרשמו',\n    obsLabel:'חלקי · לתיעוד בלבד', obsNote:'התשובה נשארת ברישום הציבורי ואינה נכנסת לציון.',\n    pendingLabel:'נענתה · הציון ממתין',\n    scored:'נרשמו', pending:'ממתינות', rate:'שיעור פגיעה', mean:'עודף ממוצע', sess:'מפגשים',\n    entry:'כניסה', close:'אחרון', gate:'תוצאות מקבלות משמעות ב-n=__MIN_N__', of:'מתוך', scoredLow:'נרשמו',\n    sym:'סימול', ent:'כניסה', last:'אחרון', ret:'תשואה', bench:'מפה', exc:'עודף',\n    pend:'ממתין', hit:'פגע', miss:'החטיא', dirUp:'סל המרוויחים ↑', dirDn:'סל המרוויחים ↓',\n    marked:'סומן', src:'מקור', noentry:'טרם נפתחה מסחר מאז הסימון',\n    direct:'סל ישיר', indirect:'טבעת שנייה',\n    noind:'אין עדיין תחזית לטבעת השנייה'};",
  "  const LT = {h2:'Measured outcomes', none:'No answers recorded yet.',\n    nextAnswer:'next expected answer', answerRec:'answer recorded', answersRec:'answers recorded',\n    obsLabel:'Partial \\u00b7 observation only', obsNote:'This answer remains in the public record but does not enter the score.',\n    pendingLabel:'Answered \\u00b7 scoring pending',\n    scored:'Scored', pending:'Pending', rate:'Hit rate', mean:'Mean excess', sess:'sessions',\n    entry:'entry', close:'last', gate:'Results become meaningful at n=__MIN_N__', of:'of', scoredLow:'scored',\n    sym:'symbol', ent:'entry', last:'last', ret:'return', bench:'map', exc:'excess',\n    pend:'pending', hit:'hit', miss:'miss', dirUp:'win basket \\u2191', dirDn:'win basket \\u2193',\n    marked:'marked', src:'source', noentry:'no session has closed since the mark',\n    direct:'Direct basket', indirect:'Second ring',\n    noind:'No second-ring forecast yet'};"),
 # The teaser layer. A locked row is fully visible and simply has no
 # sentence; the dummy below is fixed and is never the real text.
 ("const LOCK = {\n  line: 'שאלה קרובה', mail: 'זמינה עם המפתח השבועי',\n  badge: 'השאלה הפתוחה השבוע',\n  marked: 'סומן', };",
  "const LOCK = {\n  line: 'Upcoming question', mail: 'available with the weekly key',\n  badge: 'this week\\'s open question',\n  marked: 'marked', };"),
 # The map's counts line. Its heading, promise, button and disclaimer
 # went to sitenav.subscribe_html(), which is not translated because it
 # is English-only copy spliced into both builds.
 ("  const T = {q:'\u05e9\u05d0\u05dc\u05d5\u05ea', open:'\u05e4\u05ea\u05d5\u05d7\u05d5\u05ea', next:'\u05d4\u05ea\u05e9\u05d5\u05d1\u05d4 \u05d4\u05d1\u05d0\u05d4', days:'\u05d9\u05de\u05d9\u05dd', today:'\u05d4\u05d9\u05d5\u05dd', tomorrow:'\u05de\u05d7\u05e8'};",
  "  const T = {q:'questions', open:'open', next:'next answer', days:'days', today:'today', tomorrow:'tomorrow'};"),
 # One visual language: plain words for holder/challenger, a two-row
 # legend, and the peer panel's section titles.
 ("const WORDS = {holder:'שולט בצוואר הבקבוק', challenger:'מתחרים נסחרים',\n  buys:'ספקים ישירים', sells:'לקוחות', peers:'אחרים בשכבה הזאת',\n  via:'מתחרה דרך', against:'מול', sells1:'מוכרת', to:'ל־',\n  legendLine:'קשר', legendRing:'לחץ על צוואר הבקבוק',\n  legendZone:'אזור'};",
  "const WORDS = {holder:'Controls this chokepoint', challenger:'Listed challengers',\n  buys:'Direct suppliers', sells:'Customers', peers:'Peers in this layer',\n  via:'Challenges through', against:'against', sells1:'sells', to:'to ',\n  legendLine:'Relationship', legendRing:'Chokepoint pressure',\n  legendZone:'Zone'};"),
 ('    h+=`<h3>${WORDS.buys} · ${t1.length} ישירים, ${t2.length} מתחתיהם</h3>`;',
  '    h+=`<h3>${WORDS.buys} · ${t1.length} direct, ${t2.length} beneath them</h3>`;'),
 ('    h+=`<h3>${WORDS.challenger} · ${c.sigs.length}</h3>`;',
  '    h+=`<h3>${WORDS.challenger} · ${c.sigs.length}</h3>`;'),
 ("'למי ששולט אין קו מחיר.':'אין מתחרה נסחר. הטבעת כתומה: אין מול מי למדוד את הלחץ.'",
  "'The company that controls it has no price line.':'No listed challenger. Amber ring: there is nothing to measure the holder against.'"),
 ("'הנעילה מתהדקת: המחזיק מקדים את המתחרים הנסחרים.' : 'הנעילה מתרופפת: המתחרים הנסחרים מקדימים את המחזיק.'",
  "'Tightening: the holder is outrunning its listed challengers.' : 'Easing: the listed challengers are outrunning the holder.'"),
 # The board's own words. The lane NAMES come from the map now; the
 # rest of BT is still prose that has to be translated.
 ("const BT = {lanes:(D.labels||{}).lanes||{}, today:'היום', past:'עבר', in:'בעוד', days:'ימים', conf:'תאריך מאושר', exp:'תאריך צפוי', leaksIn:'תשובות מוקדמות שמגיעות לפני:', leaksOut:'משפיעה על:', noLeaks:'אין שאלה מוקדמת שמשפיעה עליה.', later:'מעבר לטווח הלוח:', hintsH:'מה תשובות קודמות מרמזות', hintsNone:'אף תשובה מוקדמת עוד לא שינתה את הלוח. הראשונה בתור:', of:'מתוך', answered:'נענו', leanY:'תשובות קודמות נוטות לכן', leanN:'תשובות קודמות נוטות ללא', leanM:'תשובות קודמות מעורבות', leanO:'עוד אין עדות כיוונית', stillOpen:'עוד פתוחים:', pulse:'לחץ', autoSuffix:' (אוטומטי)', locked:'שאלה קרובה · זמינה עם המפתח השבועי'};",
  "const BT = {lanes:(D.labels||{}).lanes||{}, today:'today', past:'past', in:'in', days:'days', conf:'date confirmed', exp:'date expected', leaksIn:'Earlier answers that arrive first:', leaksOut:'Feeds into:', noLeaks:'No earlier question feeds into this one.', later:'Beyond the board:', hintsH:'What earlier answers imply', hintsNone:'No earlier answer has changed the board yet. First in line:', of:'of', answered:'answered', leanY:'Earlier answers lean YES', leanN:'Earlier answers lean NO', leanM:'Earlier answers are mixed', leanO:'No directional evidence yet', stillOpen:'still open:', pulse:'pressure', autoSuffix:' (auto)', locked:'Upcoming question · available with the weekly key'};"),
 # The map's one-line instruction. It used to travel with the <h1> that
 # the brand header replaced; it is still here and still needs a pair.
 ('<div class="sub">עקוב אחרי השרשרת מחומרי הגלם ועד המערכות בקצה. בחר תחנה לפרטים.</div>',
  '<div class="sub">Follow the chain from upstream inputs to downstream systems. Select a station for details.</div>'),
 # The question cards. The placeholder below is fixed text in both
 # languages and is never the real sentence.
 ("  const T = {\n    yes:'כן אם', no:'לא אם', why:'למה זה משנה.',\n    lockEyebrow:'שאלה קרובה',\n    lockBody:'השאלה המלאה, כלל ההכרעה והחברות המושפעות זמינים עם המפתח השבועי.',\n    lockCta:'קבל את המפתח החינמי',\n    conf:'תאריך מאושר', exp:'תאריך צפוי',\n    day:'יום', days:'ימים', today:'היום', tomorrow:'מחר', past:'לפני',\n    up:'עולה אם כן', down:'יורד אם כן', ring2:'טבעת שנייה · לפי המפה',\n    answered:'נענו', more:'נוספים', auto:'אוטומטי', evidence:'העדות:',\n    terms:'מונחים',\n    upMore:'תאריכים נוספים', doneMore:'תשובות קודמות',\n    moreDates:'הצג עוד {n} תאריכים', fewer:'הצג פחות', noStatus:'—',\n    marks:{yes:'אושר', no:'הופרך', mixed:'חלקי', none:'לא נמסר',\n           open:'לא ברור'},\n  };",
  "  const T = {\n    yes:'Yes if', no:'No if', why:'Why it matters.',\n    lockEyebrow:'Upcoming question',\n    lockBody:'The full question, decision rule and affected companies are available with the weekly key.',\n    lockCta:'Get the free key',\n    conf:'date confirmed', exp:'date expected',\n    day:'day', days:'days', today:'today', tomorrow:'tomorrow', past:'ago',\n    up:'up if yes', down:'down if yes', ring2:'second ring · via the map',\n    answered:'Answered', more:'more', auto:'auto', evidence:'Evidence:',\n    terms:'Terms',\n    upMore:'More dates', doneMore:'Earlier answers',\n    moreDates:'Show {n} more dates', fewer:'Show fewer', noStatus:'—',\n    marks:{yes:'confirmed', no:'refuted', mixed:'partial', none:'not disclosed',\n           open:'unclear'},\n  };"),
 ('<div class="eyebrow">04 · שאלות מתוארכות</div>',
  '<div class="eyebrow">04 · Dated questions</div>'),
 ('<h2>שאלות שנוסחו לפני האירוע</h2>',
  '<h2>Questions defined before the event</h2>'),
 ('<p class="lede">כל כרטיס אומר מה ייחשב כן, מה ייחשב לא, למה התשובה משנה, ואילו חברות צפויות לזוז.</p>',
  '<p class="lede">Each card states what would count as YES, what would count as NO, why the answer matters and which companies are expected to move.</p>'),
 # Focus mode's two buttons.
 ("const FOCUSW = {details:'פרטים', more:'נוספים'};",
  "const FOCUSW = {details:'Details', more:'more'};"),
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


def _bench_js(dom: str | None = None) -> str:
    """The second benchmark's label, declared for the cards inlined after it.

    The card renderer prints ``window.BENCH_LABEL||'SOX'`` in half a dozen
    places. The track page sets that variable from its own template; the map
    inlines the same renderer and never did, so every card on it fell through
    to the literal -- and a power map that labels its benchmark with the
    semiconductor index is not a styling slip, it is the wrong fact. The
    first domain's label IS 'SOX', which is why nothing looked wrong until
    there was a second map.
    """
    import json as _json

    from chains import forecast
    label = forecast.benchmark_for(dom)["label"]
    return f"window.BENCH_LABEL={_json.dumps(label)};\n"


MIN_N_PLACEHOLDER = "__MIN_N__"


def _fill_min_n(text: str) -> str:
    """The capital gate's N, from the one place it is defined.

    The templates carry the sentence -- in each language, where copy
    belongs -- and a placeholder where the number goes. The number itself is
    forecast.MIN_N_FOR_CAPITAL, which is also what record_stats publishes
    beside every record it computes. Typed into the templates it was the
    same figure written in three files and provable in none of them: a
    threshold raised in the scoring code would have left two pages promising
    the old one, and the page is where a reader is told the rule.
    """
    from chains.forecast import MIN_N_FOR_CAPITAL
    return text.replace(MIN_N_PLACEHOLDER, str(MIN_N_FOR_CAPITAL))


# The subscription call, from the one place it is written
# (chains/sitenav.subscribe_html). The track page fills the same placeholder
# through chains/track.py; the map fills it here, so the public map, the
# private map, the landing and the track page draw one component and cannot
# say four different things about the same key.
SUBSCRIBE_PLACEHOLDER = "__SUBSCRIBE__"


def _fill_subscribe(text: str, public: bool = True) -> str:
    """With no mail service configured this is the empty string, which is the
    point: a page built before the service exists makes no claim about a
    signup, and never a "coming soon".

    ``public`` is False for the private map. The component carries the mail
    service's one analytics event, and the private page carries no analytics
    at all -- see tests/test_analytics.py -- so there it becomes nothing.
    A reader of the private page is already the person who writes the mail.
    """
    if SUBSCRIBE_PLACEHOLDER not in text:
        return text
    if not public:
        return text.replace(SUBSCRIBE_PLACEHOLDER, "")
    from chains import sitenav
    from chains.paths import subscribe_embed_url
    return text.replace(SUBSCRIBE_PLACEHOLDER,
                        sitenav.subscribe_html(subscribe_embed_url()))


def _inline_cards(text: str) -> str:
    """Fill the shared card renderer into a page that asks for it.

    One file, two pages: the private map's Forward test section and the public
    tracking page's unlocked view. Inlined rather than fetched so the private
    page keeps working from a database with no network of its own.
    """
    from chains.track import (CARDS_PLACEHOLDER, GLOSSARY_PLACEHOLDER,
                              cards_js, glossary_js)
    if CARDS_PLACEHOLDER in text:
        text = text.replace(CARDS_PLACEHOLDER, _bench_js() + cards_js())
    if GLOSSARY_PLACEHOLDER in text:
        text = text.replace(GLOSSARY_PLACEHOLDER, glossary_js())
    return text


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


# The English map's first screen. It leads with what the site is and where to go
# next -- the value line and the two calls -- and the how-to-read line moves
# beneath them. Spliced at build time, so the templates are not rewritten.
EN_TOP_FROM = (
    '<div class="top">\n'
    '  <div><h1 id="brand"></h1><div class="maptitle" id="maptitle"></div>'
    '<div class="story" id="story"></div><div class="sub">Follow the chain '
    'from upstream inputs to downstream systems. Select a station for '
    'details.</div></div>\n'
    '  <div class="asof" id="asof"></div>\n'
    '  <a class="fwd" href="track/">Track record →</a>\n'
    '</div>')
EN_FWD_LINK_FROM = '<a class="fwd inline" href="track/">Track record →</a>'
EN_FWD_H2_FROM = '<h2>Track record</h2>'
EN_VALUE = ("The physical supply chain behind AI — who supplies whom, where the "
            "chokepoints are, and which dated questions come next.")


def desc_line(lang: str, dom: str | None = None) -> str:
    """The ``<meta name="description">`` sentence, from the domain's own map.

    The wording in PUB above is the first domain's and stays its exact
    wording, so a map that declares nothing reads today as it read yesterday.
    A second industry has to say what IT is: "the AI chip supply chain" on a
    power map is the single sentence search engines and link previews quote,
    and it described the wrong industry entirely. ``{nodes}`` and ``{cps}``
    are filled from the snapshot either way -- a count typed into a map would
    be true only on the day somebody typed it.
    """
    from chains import mapfile
    try:
        brand = ((mapfile.load(dom=dom).get("labels") or {}).get("brand") or {})
    except (FileNotFoundError, ValueError):
        return PUB[lang]["desc"]
    d = brand.get("desc")
    if isinstance(d, dict):
        d = d.get(lang)
    return (str(d).strip() if d else "") or PUB[lang]["desc"]


def value_line(dom: str | None = None) -> str:
    """The sentence under the brand, from the domain's own map when it names
    one. The line above is the first domain's and stays its exact wording, so
    a map that declares nothing reads today exactly as it read yesterday.

    ``line`` is the map's own one-line description of the chain it draws and
    ``value`` is the blurb the landing card carries. The map page wants the
    first; where a map declares only the second, the second still reads
    correctly here. Never ``desc``: that is the <meta> description TEMPLATE,
    with {nodes} and {cps} in it, and it belongs to desc_line above.
    """
    from chains import mapfile
    try:
        brand = ((mapfile.load(dom=dom).get("labels") or {}).get("brand") or {})
    except (FileNotFoundError, ValueError):
        return EN_VALUE
    for key in ("line", "value"):
        v = brand.get(key)
        if isinstance(v, dict):
            v = v.get("en")
        if v and str(v).strip():
            return str(v).strip()
    return EN_VALUE
EN_TOP_CSS = (
    # The nav is inserted above .top, not inside it, so it inherits no
    # gutter. Without one the brand sat against the viewport edge at
    # 390 and the track-record button's border ran off the right.
    ".sitenav{padding-inline:22px}"
    "@media (max-width:760px){.sitenav{padding-inline:20px}}"
    ".top .value{font-family:'Source Serif 4',serif;font-size:1.25rem;"
    "line-height:1.35;color:var(--ink);max-width:62ch;margin:6px 0 8px}"
    # The map-specific description carries the first screen; the instruction
    # under it is the only other sentence. The global story line says the same
    # thing as the instruction ("select a company/station for details") and is
    # already the blurb on the landing map cards, so the map page does not
    # repeat it.
    ".top .story{display:none}"
    ".top .sub{color:var(--ink3);font-size:.92rem;max-width:62ch;margin:0 0 8px}"
    ".top .valuecta{display:flex;flex-wrap:wrap;gap:10px;margin:0 0 6px}"
    ".top .valuecta a{font-family:'IBM Plex Mono',monospace;font-size:.72rem;"
    "letter-spacing:.1em;text-transform:uppercase;text-decoration:none;"
    "border-radius:6px;padding:8px 14px}"
    ".top .valuecta .cta1{background:var(--amber);color:#0b0e14;"
    "border:1px solid var(--amber)}"
    ".top .valuecta .cta2{color:var(--amber);border:1px solid #3a3320;"
    "background:var(--panel)}")


def en_top(dom: str) -> str:
    from chains import sitenav
    return (sitenav.html(dom, "map", several=sitenav.several_maps()) + "\n"
            '<div class="top">\n'
            '  <div><h1 id="brand"></h1><div class="maptitle" id="maptitle"></div>\n'
            f'  <p class="value">{value_line(dom)}</p>\n'
            '  <div class="valuecta"><a class="cta1" href="#stage">Explore the map</a>'
            f'<a class="cta2" href="/{dom}/track/">View track record</a></div>\n'
            '  <div class="story" id="story"></div><div class="sub">Follow the chain '
            'from upstream inputs to downstream systems. Select a station for '
            'details.</div></div>\n'
            '  <div class="asof" id="asof"></div>\n'
            '</div>')


def public_page(template: str, live: str, cfg: dict,
                focus: str = "null") -> str:
    """A template plus a snapshot, wired for a page with no database.

    There used to be a five-row teaser spliced in here, because the private
    page printed every question and the public one could print none. Both pages
    now obey the data -- a locked row carries no sentence in either -- so there
    is nothing left to swap, and no public-only variant that could be built
    wrong and leak.
    """
    import json as _json

    from chains import sitenav
    try:
        snap = _json.loads(live)
    except ValueError:
        snap = {}
    desc = desc_line(cfg["lang"]).format(
        nodes=len(snap.get("nodes") or []),
        cps=len(snap.get("cps") or []))
    h = template

    # 1. the artifact database is not reachable from a public page
    h = _must_replace(h, DB_READ, FETCH_READ % cfg["live"], "database read")
    h = _must_replace(h, TRACK_DB_READ, TRACK_GONE,
                      "forward-test database read")

    if cfg["lang"] == "he" and HE_FOOT_MUST not in h:
        raise ValueError(
            "footer disclaimer: the Hebrew page no longer carries "
            f"{HE_FOOT_MUST!r}. It was reworded; say it again or say why not.")

    extra_head = ""
    if cfg["lang"] == "en":
        from chains import sitenav
        from chains.paths import domain
        h = _must_replace(h, EN_TOP_FROM, en_top(domain()),
                          "map first screen")
        # One name for the track record on the public map: the nav, the
        # in-section link and the (hidden) section heading all read the
        # same. The track page keeps its own <title>.
        h = _must_replace(h, EN_FWD_LINK_FROM,
                          f'<a class="fwd inline" href="track/">'
                          f"{sitenav.TRACK_RECORD} →</a>",
                          "in-section track record link")
        h = _must_replace(h, EN_FWD_H2_FROM,
                          f"<h2>{sitenav.TRACK_RECORD}</h2>",
                          "track record section heading")
        extra_head = f"<style>{sitenav.CSS}{EN_TOP_CSS}</style>\n"

    head = (f'<!doctype html>\n<html lang="{cfg["lang"]}" '
            f'dir="{cfg["dir"]}">\n<head>\n<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width,'
            f'initial-scale=1">\n'
            f'<meta name="description" content="{desc}">\n'
            # Public pages only: private_page() below builds its own head.
            + sitenav.ANALYTICS + "\n")
    k = h.index("</style>") + len("</style>")
    doc = (head + h[:k] + "\n" + extra_head + "</head>\n<body>\n" + h[k:]
           + "\n</body>\n</html>\n")
    return _fill_subscribe(_fill_min_n(
        doc.replace("__FOCUS__", focus).replace("__LIVE__", live)))


def private_page(template: str, live: str, focus: str = "null") -> str:
    """The Hebrew page for the artifact, with its database reads intact.

    The mirror of public_page(): everything that function takes OUT is what
    makes this one what it is. Both database reads stay -- live/latest for a
    fresher snapshot than the one baked in, and track/latest for the forward
    test the 07:00 task decrypts -- and the footer keeps its private wording.

    It is built here rather than by hand so that the private page and the
    public one cannot drift: the same template, the same snapshot, the same
    card renderer, and one function each deciding what to remove.
    """
    h = _inline_cards(template)
    assert DB_READ in h, "the live/latest read is missing from the template"
    assert TRACK_DB_READ in h, "the track/latest read is missing"
    head = ('<!doctype html>\n<html lang="he" dir="rtl">\n<head>\n'
            '<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width,'
            'initial-scale=1">\n')
    k = h.index("</style>") + len("</style>")
    doc = (head + h[:k] + "\n</head>\n<body>\n" + h[k:]
           + "\n</body>\n</html>\n")
    return _fill_subscribe(_fill_min_n(
        doc.replace("__FOCUS__", focus).replace("__LIVE__", live)),
                           public=False)


def build_private(template=None, live=None, out=None):
    """Write out/<domain>/live-map.built.html -- the file Michael attaches."""
    from chains.paths import out_dir
    template = template or (templates_dir() / TEMPLATE_HE)
    live = live or (out_dir() / LIVE_HE)
    out = out or (out_dir() / "live-map.built.html")
    focus = out_dir() / FOCUS_HE
    doc = private_page(template.read_text(encoding="utf-8"),
                       live.read_text(encoding="utf-8"),
                       focus.read_text(encoding="utf-8") if focus.exists()
                       else "null")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8", newline="\n")
    return out, len(doc.encode("utf-8"))


def _build_public(lang: str, template=None, live=None, out=None,
                  teaser=None, focus=None):
    cfg = PUB[lang]
    template = template or (templates_dir() / cfg["template"])
    live = live or (out_dir() / cfg["live"])
    out = out or (out_dir() / cfg["out"])
    # Focus mode's rows. Without them the page still draws; a click then
    # focuses a station with no suppliers around it.
    focus = focus or (out_dir() / cfg["focus"])
    doc = public_page(template.read_text(encoding="utf-8"),
                      live.read_text(encoding="utf-8"), cfg,
                      focus.read_text(encoding="utf-8") if focus.exists()
                      else "null")
    return _inline_cards(doc), out


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
    # The Hebrew page is built only for a map that declares Hebrew. A domain
    # whose labels say languages: ["en"] has no Hebrew reader to serve, and a
    # page built for nobody is a page nothing keeps in step: its own template
    # would drift, and chains/publish_site.py would copy it to /he.html with
    # no link anywhere pointing at it. The map's own declaration decides,
    # because that is where every other per-domain vocabulary choice already
    # lives -- semi declares both and is untouched.
    langs = languages_for()
    builders = [build_public_he] if "he" in langs else []
    builders.append(build_public_en)
    if "he" not in langs:
        print(f"  no Hebrew page: this map declares languages {list(langs)}")
        # A map that used to be bilingual leaves one behind otherwise, and a
        # stale Hebrew page in out/ is a page publish_site would still copy.
        stale = out_dir() / PUBLIC_HE
        if stale.exists():
            stale.unlink()
            print(f"  removed {stale}  (stale Hebrew page)")
    for fn in builders:
        p, size = fn()
        print(f"wrote {p}  ({size:,} bytes, {size / 1024:.0f} KB)")
    # The artifact copy: same template, database reads intact.
    p, size = build_private()
    print(f"wrote {p}  ({size:,} bytes, {size / 1024:.0f} KB)  private")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
