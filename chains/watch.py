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

# No q, no listen. The question text is the product and it is not in this
# repository: it is fetched at build time from a private file (QUESTIONS_URL)
# and merged in by chains/questions.py. What stays here is the skeleton -- who,
# when, which chokepoints, which baskets -- which is what the free page shows
# for every row whether or not its text is unlocked.
FIELDS = ("id", "d", "confirmed", "who", "tk", "cps", "win", "lose")

# id, date, confirmed, who, ticker, chokepoints, who gains if the answer is
# yes, who loses.
W = [
 ('orcl_q1'  , '2026-09-10', True , 'Oracle Q1 FY27'                      , 'ORCL'  , []                   , ['nvda', 'amd', 'vrt'], []),
 ('mu_fq4'   , '2026-09-30', True , 'Micron FQ4'                          , 'MU'    , ['CP5']              , ['mu'], ['skhynix', 'samsung']),
 ('smsg_pre' , '2026-10-08', False, 'Samsung Q3 (מקדים)'                  , '005930', ['CP5', 'CP3']       , ['samsung'], ['skhynix']),
 ('asml_q3'  , '2026-10-14', True , 'ASML Q3'                             , 'ASML'  , ['CP1', 'CP2']       , ['asml'], []),
 ('tsm_q3'   , '2026-10-15', True , 'TSMC Q3'                             , 'TSM'   , ['CP3', 'CP4']       , ['tsmc', 'asml'], ['intc', 'samsung']),
 ('clf_q3'   , '2026-10-19', True , 'Cleveland-Cliffs Q3'                 , 'CLF'   , ['CP11']             , ['clf'], []),
 ('intc_q3'  , '2026-10-22', True , 'Intel Q3'                            , 'INTC'  , ['CP3']              , ['intc'], ['tsmc']),
 ('shecy_h1' , '2026-10-23', True , 'Shin-Etsu H1'                        , 'SHECY' , ['CP6', 'CP7']       , ['shinetsu'], ['globalwafers']),
 ('skh_q3'   , '2026-10-23', False, 'SK hynix Q3'                         , '000660', ['CP5']              , ['skhynix'], ['mu', 'samsung']),
 ('amkr_q3'  , '2026-10-26', True , 'Amkor Q3'                            , 'AMKR'  , ['CP4']              , ['amkr'], ['tsmc']),
 ('cdns_q3'  , '2026-10-26', True , 'Cadence Q3'                          , 'CDNS'  , ['CP14']             , ['cdns'], []),
 ('ter_q3'   , '2026-10-27', True , 'Teradyne Q3'                         , 'TER'   , ['CP13']             , ['ter'], ['advantest']),
 ('gev_q3'   , '2026-10-28', True , 'GE Vernova Q3'                       , 'GEV'   , ['CP11']             , ['gev'], ['msft', 'amzn', 'googl']),
 ('lrcx_q1'  , '2026-10-28', True , 'Lam Research FQ1'                    , 'LRCX'  , ['CP3', 'CP5']       , ['lrcx'], []),
 ('teck_q3'  , '2026-10-28', True , 'Teck Q3'                             , 'TECK'  , ['CP12']             , ['teck'], []),
 ('googl_q3' , '2026-10-28', True , 'Alphabet Q3'                         , 'GOOGL' , []                   , ['nvda', 'avgo', 'tsmc'], []),
 ('adv_h1'   , '2026-10-28', False, 'Advantest H1'                        , '6857'  , ['CP13']             , ['advantest'], ['ter']),
 ('smsg_q3'  , '2026-10-28', False, 'Samsung Q3 (מלא)'                    , '005930', ['CP5', 'CP3']       , ['samsung'], ['skhynix', 'tsmc']),
 ('hanmi_q3' , '2026-10-29', False, 'Hanmi Semiconductor Q3'              , '042700', ['CP4', 'CP5']       , ['hanmi'], ['asmpt']),
 ('asx_q3'   , '2026-10-29', True , 'ASE Q3'                              , 'ASX'   , ['CP4']              , ['ase'], ['tsmc']),
 ('axti_q3'  , '2026-10-29', True , 'AXT Q3'                              , 'AXTI'  , ['CP10']             , ['axti'], ['lite', 'cohr']),
 ('entg_q3'  , '2026-10-29', True , 'Entegris Q3'                         , 'ENTG'  , ['CP3']              , ['entegris'], []),
 ('amzn_q3'  , '2026-10-29', True , 'Amazon Q3'                           , 'AMZN'  , []                   , ['alab', 'crdo', 'mrvl'], ['nvda']),
 ('hwm_q3'   , '2026-10-29', True , 'Howmet Q3'                           , 'HWM'   , ['CP11']             , ['hwm'], []),
 ('mpwr_q3'  , '2026-10-29', True , 'Monolithic Power Q3'                 , 'MPWR'  , ['CP3']              , ['mpwr'], []),
 ('hoya_h1'  , '2026-10-30', False, 'HOYA H1'                             , '7741'  , ['CP9']              , ['hoya'], []),
 ('cohr_q1'  , '2026-11-05', False, 'Coherent FQ1'                        , 'COHR'  , ['CP10']             , ['cohr', 'fn'], []),
 ('ajin_h1'  , '2026-11-05', False, 'Ajinomoto H1'                        , '2802'  , ['CP8']              , ['ajinomoto'], []),
 ('sumco_q3' , '2026-11-06', False, 'SUMCO Q3'                            , '3436'  , ['CP6']              , ['sumco'], []),
 ('mofcom_re', '2026-11-10', True , 'סין — פקיעת ההשעיה על מתכות נדירות'  , 'MOFCOM', ['CP12']             , ['mp'], []),
 ('tel_q2'   , '2026-11-10', False, 'Tokyo Electron Q2'                   , '8035'  , ['CP3']              , ['tel'], []),
 ('amat_q4'  , '2026-11-12', False, 'Applied Materials FQ4'               , 'AMAT'  , ['CP3']              , ['amat', 'lrcx', 'klac'], []),
 ('sie_fy'   , '2026-11-12', False, 'Siemens Energy FY26'                 , 'ENR'   , ['CP11']             , ['siemensenergy'], ['gev']),
 ('nvda_q3'  , '2026-11-19', False, 'NVIDIA Q3 FY27'                      , 'NVDA'  , ['CP5', 'CP3', 'CP4'], ['tsmc', 'skhynix', 'mu'], []),
 ('mofcom_ga', '2026-11-27', True , 'סין — פקיעת ההשעיה על גליום וגרמניום', 'MOFCOM', ['CP12']             , ['aa', 'teck', 'mtln'], []),
 ('semi_smg' , '2026-12-10', False, 'SEMI — משלוחי סיליקון Q3'            , 'SEMI'  , ['CP6']              , ['globalwafers'], ['shinetsu', 'sumco']),
 ('absolics' , '2026-12-31', False, 'Absolics — מצע זכוכית'               , 'SKC'   , ['CP8', 'CP4']       , ['skc'], ['ajinomoto', 'ibiden']),
 ('lsrc_q2'  , '2027-01-27', False, 'Lasertec Q2'                         , '6920'  , ['CP9']              , ['lasertec'], []),
 ('spie'     , '2027-02-22', False, 'SPIE Advanced Lithography'           , '—'     , ['CP7', 'CP1']       , ['lrcx'], ['tok', 'shinetsu']),
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
