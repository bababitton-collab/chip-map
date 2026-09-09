"""Who leaks first: the earlier question that partly answers a later one.

The forecast board is a TRACKING view, not a signal. There is no hypothesis
behind these edges and no backtest under them -- recorded decision, 2026-09-08:
no customer->supplier study, no third hypothesis. What an edge asserts is much
smaller than a prediction: *this* question is answered on an earlier day, and
its answer constrains what *that* one can say. Micron's HBM share target lands
on 2026-09-30; by the time NVIDIA reports on 2026-11-19 that number is already
public, so NVIDIA's memory-supplier mix is no longer a blank page.

TWO INVARIANTS, BOTH CHECKED IN chains/tests/test_leaks.py
----------------------------------------------------------
A leak must be EARLIER. An edge from a later question to an earlier one would
draw an arrow on the board that runs backwards through time, and the reader
would take it for a claim of causation rather than a claim of chronology. The
dates live in the watch list, not here, so ``apply`` filters against them at
build time rather than trusting the table below: when a company announces a
date and a row moves, an edge that has stopped being earlier disappears on its
own instead of quietly reversing.

Every question sits in exactly one LANE. The lane is the board's vertical axis;
a question with no lane would be drawn at whatever row the fallback picks and
would look deliberate. The test asserts the mapping is total.

The ``lbl`` is the short name on the circle. It is cosmetic and it is the only
field here with a Hebrew and an English variant.
"""
from __future__ import annotations

import re

# Ordered by the date the answer arrives; only strictly earlier ids survive.
LEAKS = {
    "smsg_pre": ["mu_fq4"],
    "skh_q3": ["mu_fq4", "smsg_pre"],
    "smsg_q3": ["mu_fq4", "smsg_pre", "skh_q3"],
    "hanmi_q3": ["smsg_pre", "skh_q3", "smsg_q3"],
    "lrcx_q1": ["mu_fq4", "asml_q3", "tsm_q3", "smsg_pre"],
    "nvda_q3": ["mu_fq4", "smsg_pre", "tsm_q3", "skh_q3", "smsg_q3",
                "amkr_q3", "asx_q3", "mpwr_q3", "hanmi_q3"],
    "tsm_q3": ["asml_q3"],
    "entg_q3": ["tsm_q3", "lrcx_q1"],
    "tel_q2": ["asml_q3", "tsm_q3", "lrcx_q1"],
    "amat_q4": ["asml_q3", "tsm_q3", "lrcx_q1", "tel_q2"],
    "shecy_h1": ["asml_q3", "tsm_q3"],
    "sumco_q3": ["tsm_q3", "shecy_h1"],
    "semi_smg": ["shecy_h1", "sumco_q3"],
    "hoya_h1": ["asml_q3", "tsm_q3"],
    "lsrc_q2": ["asml_q3", "hoya_h1"],
    "spie": ["asml_q3", "shecy_h1", "lsrc_q2"],
    "amkr_q3": ["tsm_q3", "intc_q3"],
    "asx_q3": ["tsm_q3", "amkr_q3"],
    "mpwr_q3": ["tsm_q3"],
    "ter_q3": ["mu_fq4", "tsm_q3"],
    "adv_h1": ["skh_q3", "ter_q3"],
    "ajin_h1": ["tsm_q3", "asx_q3"],
    "absolics": ["intc_q3", "ajin_h1"],
    "gev_q3": ["clf_q3"],
    "hwm_q3": ["gev_q3"],
    "sie_fy": ["clf_q3", "gev_q3", "hwm_q3"],
    "cohr_q1": ["axti_q3", "amzn_q3", "googl_q3"],
    "googl_q3": ["orcl_q1"],
    "amzn_q3": ["orcl_q1", "googl_q3"],
    "mofcom_ga": ["mofcom_re"],
}

# The board's rows. Every question belongs to exactly one.
LANE = {
    "hbm": ["mu_fq4", "smsg_pre", "skh_q3", "smsg_q3", "hanmi_q3", "lrcx_q1",
            "nvda_q3"],
    "litho": ["asml_q3", "hoya_h1", "shecy_h1", "tel_q2", "lsrc_q2", "spie"],
    "fab": ["tsm_q3", "intc_q3", "amkr_q3", "asx_q3", "entg_q3", "mpwr_q3",
            "amat_q4", "ter_q3", "adv_h1", "ajin_h1", "absolics"],
    "mat": ["sumco_q3", "semi_smg", "axti_q3", "teck_q3", "mofcom_re",
            "mofcom_ga", "cohr_q1"],
    "power": ["clf_q3", "gev_q3", "hwm_q3", "sie_fy"],
    "cloud": ["orcl_q1", "googl_q3", "amzn_q3", "cdns_q3"],
}

LANE_OF = {i: k for k, v in LANE.items() for i in v}

# Only the rows whose auto-derived label would be wrong or unreadable.
LBL_HE = {
    "mofcom_re": "סין: מתכות נדירות", "mofcom_ga": "סין: גליום",
    "hanmi_q3": "Hanmi", "smsg_pre": "Samsung (מקדים)",
    "smsg_q3": "Samsung (מלא)", "semi_smg": "SEMI", "absolics": "Absolics",
    "spie": "SPIE",
}
LBL_EN = {
    "mofcom_re": "China: rare earths", "mofcom_ga": "China: gallium",
    "hanmi_q3": "Hanmi", "smsg_pre": "Samsung (prelim)",
    "smsg_q3": "Samsung (full)", "semi_smg": "SEMI", "absolics": "Absolics",
    "spie": "SPIE",
}

# "Micron FQ4" -> "Micron"; "Samsung Q3 (full)" -> "Samsung". The period suffix
# is already shown as a date on the board, so repeating it on a 18-character
# circle label costs the company name.
_PERIOD_SUFFIX = re.compile(r"\s*(Q\d.*|FQ\d.*|H\d.*|FY\d+.*|—.*)$")

FALLBACK_LANE = "fab"


def apply(rows: list[dict], lbl: dict[str, str] | None = None) -> list[dict]:
    """Add ``leaks``, ``lane`` and ``lbl`` to each watch row, in place.

    An edge survives only if its target is in this list AND its date is
    strictly earlier. Both filters matter: the first drops an edge to a
    question that has been retired, the second drops one that has stopped
    being earlier because a company announced a date and the row moved.
    """
    lbl = lbl if lbl is not None else LBL_HE
    byid = {r["id"]: r for r in rows}
    for r in rows:
        r["leaks"] = [l for l in LEAKS.get(r["id"], [])
                      if l in byid and byid[l]["d"] < r["d"]]
        r["lane"] = LANE_OF.get(r["id"], FALLBACK_LANE)
        r["lbl"] = lbl.get(r["id"]) or _PERIOD_SUFFIX.sub("", r["who"])[:18]
    return rows
