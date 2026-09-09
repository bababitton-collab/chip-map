"""Fundamentals for the map's US filers, shaped for the page.

US FILERS ONLY, AND THE BOUNDARY IS THE FILING NOT THE LISTING
--------------------------------------------------------------
A company is included if it files with the SEC. A depositary receipt is not a
filing: SHECY prices Shin-Etsu but Shin-Etsu files with the Japanese FSA, and
EDGAR has nothing for it. So the ADR lines recovered for the price layer buy
nothing here, and every one of them gets

    {"fundamentals": null, "reason": "no EDGAR filing"}

explicitly, so the page renders "no filing data" rather than an empty panel
that looks like a loading failure.

WHERE THE ROWS COME FROM
------------------------
A ``source``: any callable taking a ticker and returning
``{"annual": [...], "quarter": [...]}``. The build passes chains/edgar.Source,
which fetches companyfacts over HTTP with no key. It used to be a read of a
DuckDB store at an absolute path in a sibling project -- that read is what tied
this build to one laptop, and replacing it with an argument is what untied it.

The maths below did not change with the source, because it was never about the
source. It is about two things companyfacts gets wrong, and both are still
wrong when read directly.

NO NEW XBRL TAGS
----------------
R&D expense is reported as missing rather than derived from a tag guessed at
here -- a guessed tag produces a number, and a number nobody can trace is worse
than a gap.
"""
from __future__ import annotations

import datetime as dt
from typing import Callable

from chains.edgar import PERIOD_ANNUAL, PERIOD_QUARTER

# what the store carries, against what was asked for
WANTED = ("revenue", "operating_income", "research_and_development",
          "capital_expenditure")
AVAILABLE = ("revenue", "operating_income", "capital_expenditure")
MISSING = {
    "research_and_development": (
        "not read. Adding it means choosing an XBRL tag "
        "(us-gaap:ResearchAndDevelopmentExpense and its several variants) and "
        "deciding which one each filer means; a tag guessed at here would "
        "produce numbers nobody could trace back to a filing."
    ),
}


def us_filer_symbols(doc: dict) -> dict[str, str]:
    """map id -> SEC ticker, for entries that plausibly file with the SEC.

    A primary US listing only. An ADR is a listing, not a filing.
    """
    out: dict[str, str] = {}
    for coll in ("nodes", "subnodes"):
        for r in doc.get(coll, []):
            sym = r.get("price_symbol") or ""
            if r.get("price_symbol_kind") != "primary" or not sym.endswith(".US"):
                continue
            out[r["id"]] = sym[:-3]
    return out


# a fiscal year is a year of days, give or take a 52/53-week calendar
YEAR_DAYS = 365
YEAR_SLACK_DAYS = 45


def series_from_rows(rows: list[dict]) -> list[dict]:
    """One row per PERIOD, with year-on-year measured against the calendar.

    Two things the raw facts cannot be trusted on:

    DUPLICATE period_end. companyfacts restates the same fact in later filings
    under a different fiscal_year tag, so NVDA's year ending 2011-01-30 appears
    three times -- tagged 2010, 2011 and 2012, all with the same revenue. There
    were 67,732 such symbol/period_end pairs in the store built from this same
    API. Left alone they give a year-on-year of exactly 0.0 against themselves,
    which is not a slightly wrong number, it is a fabricated one. Deduped on
    period_end, keeping the most recently published row.

    THE fiscal_year TAG. Having seen it duplicated, it is not used to find the
    prior period either. The comparison is made on period_end: the row ending
    closest to a year earlier, within six weeks. That is what "the same quarter
    a year earlier" means, and it survives a company changing its fiscal
    calendar, which the tag does not.
    """
    by_end: dict = {}
    for r in sorted(rows, key=lambda r: (r["period_end"], r.get("pub") or "")):
        if r.get("revenue") is None:
            continue
        oi, rev = r.get("operating_income"), r["revenue"]
        by_end[r["period_end"]] = {          # sorted by pub means the last wins
            "period_end": r["period_end"],
            "fiscal_year": r.get("fiscal_year"),
            "fiscal_period": r.get("fiscal_period"),
            "revenue": rev,
            "operating_income": oi,
            "capital_expenditure": r.get("capital_expenditure"),
            "operating_margin": (oi / rev) if (oi is not None and rev) else None,
        }
    out = [by_end[k] for k in sorted(by_end)]

    ends = [r["period_end"] for r in out]
    for r in out:
        target = r["period_end"] - dt.timedelta(days=YEAR_DAYS)
        prev = None
        best = YEAR_SLACK_DAYS + 1
        for i, e in enumerate(ends):
            gap = abs((e - target).days)
            if gap <= YEAR_SLACK_DAYS and gap < best:
                best, prev = gap, out[i]
        r["revenue_yoy"] = (
            (r["revenue"] / prev["revenue"] - 1.0)
            if prev and prev.get("revenue") else None
        )
    for r in out:
        r["period_end"] = str(r["period_end"])
    return out


def for_entry(source: Callable[[str], dict], ticker: str) -> dict:
    got = source(ticker)
    annual = series_from_rows(got.get(PERIOD_ANNUAL) or [])
    quarterly = series_from_rows(got.get(PERIOD_QUARTER) or [])
    if not annual and not quarterly:
        return {"fundamentals": None,
                "reason": f"no EDGAR facts for {ticker}"}
    return {
        "fundamentals": {
            "ticker": ticker,
            "annual": annual,
            "quarterly": quarterly[-12:],
            "fields_present": list(AVAILABLE),
            "fields_missing": MISSING,
        },
        "reason": None,
    }


NO_FILING_DISPLAY = "no filing data"


def build(doc: dict, source: Callable[[str], dict],
          verbose: bool = False) -> dict:
    """Every node and subnode, with a null block and a reason where there is
    no filing. Never an absent key.

    One company that EDGAR has nothing for is data, not a failure: the map
    names private companies and foreign filers on purpose. One that raises is
    also not a failure of the whole build -- it is one missing panel, recorded
    with the reason, and the other sixty still render.
    """
    filers = us_filer_symbols(doc)
    out: dict[str, dict] = {}
    for coll in ("nodes", "subnodes"):
        for r in doc.get(coll, []):
            eid = r["id"]
            if eid not in filers:
                out[eid] = {"fundamentals": None,
                            "reason": "no EDGAR filing",
                            "display": NO_FILING_DISPLAY}
                continue
            try:
                res = for_entry(source, filers[eid])
            except Exception as exc:                        # noqa: BLE001
                res = {"fundamentals": None,
                       "reason": f"EDGAR lookup failed for {filers[eid]}: "
                                 f"{type(exc).__name__}"}
                if verbose:
                    print(f"  {filers[eid]:<8} {res['reason']}")
            if res["fundamentals"] is None:
                res["display"] = NO_FILING_DISPLAY
            out[eid] = res
    return out
