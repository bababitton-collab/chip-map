"""The dated-questions lists, and the one place their prose is written.

    python -m chains.watch

Writes the two curated inputs the page and the briefs read:
``watch.json`` (Hebrew, Michael's copy) and ``watch_en.json`` (English, the
product). Both carry the same 39 ids in the same order; only the prose differs.

THIS IS A GENERATOR FOR AN INPUT, NOT A STEP IN THE WEEKLY RUN
--------------------------------------------------------------
Everything else in this package turns data into output. This turns a table a
person wrote into two JSON files, and it is the single exception to the rule
that chains/ writes nothing into the repository. It is deliberately NOT in
chains/scripts/weekly.py: a scheduled job that rewrote a curated input would
make the diff that reviews it meaningless. Run it by hand when a row changes,
and read the diff before committing.

WHY THE ENGLISH ROWS LIVE IN chains/en_data.py
----------------------------------------------
They were already there, translated once, beside the English chokepoint names
and blurbs that the English snapshot needs. Copying them here would create a
second place to forget to update. This module holds the Hebrew table, imports
the English one, and is the only thing that knows both exist.

``confirmed`` is a real boolean and it means a PUBLISHED date. False means the
date came from last year's reporting rhythm and the company has not announced.
The flag travels all the way to the page for that reason: a provisional date
rendered as firm is the one error this list exists to prevent.
"""
from __future__ import annotations

import json

from chains import en_data, leaks
from chains.paths import watch_en_path, watch_path

FIELDS = ("id", "d", "confirmed", "who", "tk", "cps", "q", "listen", "win",
          "lose")

# id, date, confirmed, who, ticker, chokepoints, question, what to listen for,
# who gains if the answer is yes, who loses.
W = [
 ('orcl_q1',   '2026-09-10', True,  'Oracle Q1 FY27',           'ORCL',   [],            'כמה Oracle קונה: קצב ההשקעות ו־RPO. היא הלקוח הרעב ביותר של אנבידיה ו־AMD אחרי ארבע הגדולות.', 'הנחיית capex ל־FY27 ומספר ה־RPO', ['nvda','amd','vrt'], []),
 ('mu_fq4',    '2026-09-30', True,  'Micron FQ4',               'MU',     ['CP5'],       'האם מיקרון מגיעה ליעד הנתח ב־HBM ומהו קצב הקיבולת ל־HBM4.', 'יעד נתח HBM ל־2027 ו־capex', ['mu'], ['skhynix','samsung']),
 ('smsg_pre',  '2026-10-08', False, 'Samsung Q3 (מקדים)',       '005930', ['CP5','CP3'], 'האם רווחי הזיכרון מאשרים ש־HBM4 של סמסונג נכנס לאנבידיה בכמויות.', 'רווח תפעולי של חטיבת הזיכרון מול הרבעון הקודם', ['samsung'], ['skhynix']),
 ('asml_q3',   '2026-10-14', True,  'ASML Q3',                  'ASML',   ['CP1','CP2'], 'כמה מכונות EUV הוזמנו, כמה High-NA, ומה חלק סין. זו התקרה על כל מה שמתחת.', 'הזמנות EUV ברבעון, יחידות High-NA, ותחזית 2027', ['asml'], []),
 ('tsm_q3',    '2026-10-15', True,  'TSMC Q3',                  'TSM',    ['CP3','CP4'], 'קיבולת CoWoS בפועל, קצב 2 ננומטר, והאם תתחייב ל־High-NA ל־A14 או תדחה שוב.', 'מספר קיבולת CoWoS לסוף 2026 ו־capex 2027', ['tsmc','asml'], ['intc','samsung']),
 ('clf_q3',    '2026-10-19', True,  'Cleveland-Cliffs Q3',      'CLF',    ['CP11'],      'היצרן האמריקאי היחיד של פלדה חשמלית: האם השדרוג בבאטלר בזמן ומה הביקוש משנאים.', 'עדכון על השדרוג ($195M) ותמחור GOES', ['clf'], []),
 ('intc_q3',   '2026-10-22', True,  'Intel Q3',                 'INTC',   ['CP3'],       'האם יש לקוח חיצוני מחויב ל־14A. המנכ"ל אמר שההחלטות ייפלו במחצית השנייה. הבדיקה החדה ביותר ברשימה.', 'שם לקוח, או "החלטות נדחו"', ['intc'], ['tsmc']),
 ('shecy_h1',  '2026-10-23', True,  'Shin-Etsu H1',             'SHECY',  ['CP6','CP7'], 'ביקוש לפרוסות סיליקון ורזיסט EUV. ירדה 19% ברבעון — האם המספרים מסבירים למה.', 'משלוחי פרוסות 300mm ותחזית H2', ['shinetsu'], ['globalwafers']),
 ('skh_q3',    '2026-10-23', False, 'SK hynix Q3',              '000660', ['CP5'],       'נתח HBM, מחיר HBM4, והאם שבב הבסיס ב־TSMC פוגע במרווח.', 'נתח HBM ותמחור HBM4 מול HBM3E', ['skhynix'], ['mu','samsung']),
 ('amkr_q3',   '2026-10-26', True,  'Amkor Q3',                 'AMKR',   ['CP4'],       'האם יש לקוח עוגן למפעל בפיאוריה, אריזונה. זה מה שהופך אריזה מתקדמת מטייוואנית לאמריקאית.', 'שם לקוח לאריזונה', ['amkr'], ['tsmc']),
 ('cdns_q3',   '2026-10-26', True,  'Cadence Q3',               'CDNS',   ['CP14'],      'הכנסות מסין אחרי הסרת ההגבלות, וכמה מהצמיחה מגיע מכלי AI.', 'חלק סין מההכנסות', ['cdns'], []),
 ('ter_q3',    '2026-10-27', True,  'Teradyne Q3',              'TER',    ['CP13'],      'האם Teradyne נוגסת ב־Advantest בבדיקת HBM ו־GPU. הרמז: "merchant GPU" בלי שם לקוח.', 'הזמנות בדיקת HBM/GPU ושם לקוח', ['ter'], ['advantest']),
 ('gev_q3',    '2026-10-28', True,  'GE Vernova Q3',            'GEV',    ['CP11'],      'כמה משבצות טורבינה נשארו ל־2029–2030, ומה זמן האספקה של שנאים.', 'GW חתומים ושמורים, זמן אספקה LPT', ['gev'], ['msft','amzn','googl']),
 ('lrcx_q1',   '2026-10-28', True,  'Lam Research FQ1',         'LRCX',   ['CP3','CP5'], 'תמהיל לקוחות: סמסונג 16%, TSMC 15%, hynix 12%, מיקרון 12%. שינוי בסדר = שינוי במי בונה.', 'לקוחות מעל 10% ותחזית WFE', ['lrcx'], []),
 ('teck_q3',   '2026-10-28', True,  'Teck Q3',                  'TECK',   ['CP12'],      'הכפלת הגרמניום בטרייל — האם היא בזמן לפני פקיעת ההשעיה הסינית.', 'תפוקת גרמניום ולוח זמנים', ['teck'], []),
 ('googl_q3',  '2026-10-28', True,  'Alphabet Q3',              'GOOGL',  [],            'capex 2026 ו־2027. ארבע הגדולות הן 730 מיליארד — כל שינוי כאן מזיז את כל המפה.', 'הנחיית capex', ['nvda','avgo','tsmc'], []),
 ('adv_h1',    '2026-10-28', False, 'Advantest H1',             '6857',   ['CP13'],      'נתח בדיקת SoC (66%) ומה קורה עם הבודקים הקוריאניים אצל SK hynix.', 'נתח SoC ותחזית שנתית', ['advantest'], ['ter']),
 ('smsg_q3',   '2026-10-28', False, 'Samsung Q3 (מלא)',         '005930', ['CP5','CP3'], 'פירוט HBM4: כמה לאנבידיה, ומה קורה ב־2 ננומטר של הפאונדרי.', 'נתח HBM ותפוקת SF2', ['samsung'], ['skhynix','tsmc']),
 ('hanmi_q3',  '2026-10-29', False, 'Hanmi Semiconductor Q3',   '042700', ['CP4','CP5'], 'הספק שאיבד חצי מהזמנות מדביקי HBM4 ל־ASMPT. האם הדימום נעצר.', 'הזמנות TC bonder ושם לקוח', ['hanmi'], ['asmpt']),
 ('asx_q3',    '2026-10-29', True,  'ASE Q3',                   'ASX',    ['CP4'],       'האם ASE תנקוב בקיבולת CoWoS־שוות־ערך שלה. זה מה שמדלל את הריכוז ב־TSMC.', 'מספר קיבולת אריזה מתקדמת', ['ase'], ['tsmc']),
 ('axti_q3',   '2026-10-29', True,  'AXT Q3',                   'AXTI',   ['CP10'],      'מצעי InP — כולם מיוצרים בסין ברישיון. מחיר עלה 250%. האם הרישיונות ממשיכים.', 'הכנסות InP וסטטוס רישיונות MOFCOM', ['axti'], ['lite','cohr']),
 ('entg_q3',   '2026-10-29', True,  'Entegris Q3',              'ENTG',   ['CP3'],       'TSMC היא 16% מההכנסות. שינוי כאן הוא מד לקצב הבנייה ב־2 ננומטר.', 'חלק TSMC ותחזית', ['entegris'], []),
 ('amzn_q3',   '2026-10-29', True,  'Amazon Q3',                'AMZN',   [],            'capex ו־Trainium: כמה מהמחשוב עובר לשבבים עצמיים במקום אנבידיה.', 'הנחיית capex ואזכור Trainium', ['alab','crdo','mrvl'], ['nvda']),
 ('hwm_q3',    '2026-10-29', True,  'Howmet Q3',                'HWM',    ['CP11'],      'יציקות להבים לטורבינות — 60–90 שבועות לאצווה. האם הקיבולת גדלה.', 'הזמנות IGT', ['hwm'], []),
 ('mpwr_q3',   '2026-10-29', True,  'Monolithic Power Q3',      'MPWR',   ['CP3'],       'תכולת הכוח ב־Blackwell ו־Rubin. ספק שקט שכל שבב עובר דרכו.', 'הכנסות datacenter', ['mpwr'], []),
 ('hoya_h1',   '2026-10-30', False, 'HOYA H1',                  '7741',   ['CP9'],       'מסכות EUV: האם המפעל השלישי בסינגפור בזמן, ומה חלק AGC.', 'הכנסות מסכות ותחזית', ['hoya'], []),
 ('cohr_q1',   '2026-11-05', False, 'Coherent FQ1',             'COHR',   ['CP10'],      'ירדה 30% ברבעון. האם 1.6T ממריא והאם ה־FCC באמת מגביל את הסינים.', 'הזמנות 1.6T והתייחסות ל־FCC', ['cohr','fn'], []),
 ('ajin_h1',   '2026-11-05', False, 'Ajinomoto H1',             '2802',   ['CP8'],       'סרט ABF: כמויות ומחירים אחרי העלאה של 30%. מרווח תפעולי מעל 50%.', 'הכנסות חומרים אלקטרוניים ומרווח', ['ajinomoto'], []),
 ('sumco_q3',  '2026-11-06', False, 'SUMCO Q3',                 '3436',   ['CP6'],       'משלוחי פרוסות 300mm. NSIG הסינית מתקרבת ל־1.2 מיליון בחודש.', 'תחזית משלוחים', ['sumco'], []),
 ('mofcom_re', '2026-11-10', True,  'סין — פקיעת ההשעיה על מתכות נדירות', 'MOFCOM', ['CP12'], 'תאריך קשיח. אם ההשעיה לא מוארכת, הפיקוח על מגנטים חוזר.', 'הודעה רשמית: הארכה או פקיעה', ['mp'], []),
 ('tel_q2',    '2026-11-10', False, 'Tokyo Electron Q2',        '8035',   ['CP3'],       'ספק יחיד של מכונות ציפוי לרזיסט EUV. חלק סין מההכנסות.', 'חלק סין ותחזית', ['tel'], []),
 ('amat_q4',   '2026-11-12', False, 'Applied Materials FQ4',    'AMAT',   ['CP3'],       'סין, HBM, ו־2027. AMAT היא מד הבריאות של כל שכבת הציוד.', 'תחזית WFE 2027', ['amat','lrcx','klac'], []),
 ('sie_fy',    '2026-11-12', False, 'Siemens Energy FY26',      'ENR',    ['CP11'],      'זמני אספקה של שנאים. ירידה מתחת לשלוש שנים = המגבלה משתחררת.', 'lead time LPT ו־backlog', ['siemensenergy'], ['gev']),
 ('nvda_q3',   '2026-11-19', False, 'NVIDIA Q3 FY27',           'NVDA',   ['CP5','CP3','CP4'], 'הכול: תמהיל ספקי HBM, Rubin, ו־NVHBM שמזיז את שבב הבסיס פנימה.', 'אזכור ספקי זיכרון ותחזית Q4', ['tsmc','skhynix','mu'], []),
 ('mofcom_ga', '2026-11-27', True,  'סין — פקיעת ההשעיה על גליום וגרמניום', 'MOFCOM', ['CP12'], 'תאריך קשיח. 98% מהגליום. הארכה או חזרה לאיסור.', 'הודעה רשמית', ['aa','teck','mtln'], []),
 ('semi_smg',  '2026-12-10', False, 'SEMI — משלוחי סיליקון Q3', 'SEMI',   ['CP6'],       'הנתון הרבעוני של התעשייה. האם הסינים לוקחים נתח.', 'MSI משלוחים ושינוי שנתי', ['globalwafers'], ['shinetsu','sumco']),
 ('absolics',  '2026-12-31', False, 'Absolics — מצע זכוכית',    'SKC',    ['CP8','CP4'], 'תוצאות ברמת מארז או שם לקוח. הבדיקה הבינארית הנקייה ביותר בחומרים.', 'הודעה על לקוח או תוצאות אמינות', ['skc'], ['ajinomoto','ibiden']),
 ('lsrc_q2',   '2027-01-27', False, 'Lasertec Q2',              '6920',   ['CP9'],       'ספק יחיד לבדיקת מסכות EUV. הזמנות High-NA.', 'הזמנות ותחזית', ['lasertec'], []),
 ('spie',      '2027-02-22', False, 'SPIE Advanced Lithography','—',      ['CP7','CP1'], 'רזיסט מתכתי בייצור, וכל רמז לספק אופטיקה שני ל־ASML.', 'הרצאות של TSMC/Intel על רזיסט יבש', ['lrcx'], ['tok','shinetsu']),
]


def rows(table: list[tuple], lbl: dict[str, str]) -> list[dict]:
    """The table as records, with the board's leak/lane/label fields added."""
    out = [dict(zip(FIELDS, r)) for r in table]
    return leaks.apply(out, lbl)


def write(path, table: list[tuple], lbl: dict[str, str]) -> tuple[int, int]:
    out = rows(table, lbl)
    # LF, explicitly. .gitattributes pins these two files as binary precisely
    # so a checkout cannot rewrite their line endings; a generator that emitted
    # CRLF on Windows would defeat that from the other direction and rewrite
    # every line of the diff that is supposed to show what actually changed.
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                    encoding="utf-8", newline="\n")
    return len(out), sum(len(r["leaks"]) for r in out)


def main() -> int:
    for path, table, lbl in ((watch_path(), W, leaks.LBL_HE),
                             (watch_en_path(), en_data.W, leaks.LBL_EN)):
        n, links = write(path, table, lbl)
        print(f"{path.name:<16} {n} rows, {links} leak links")
    he = {r[0] for r in W}
    en = {r[0] for r in en_data.W}
    if he != en:
        print(f"MISMATCH he/en ids: {he ^ en}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
