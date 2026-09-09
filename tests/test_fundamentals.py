"""The two things companyfacts gets wrong, and the shaping that survives them.

These tests used to build a DuckDB file and query it. They now hand rows
straight to the shaping functions, which is what the change of source made
possible: the maths was never about where the rows came from, and a test that
had to stand up a database to check a year-on-year calculation was testing the
database too.

What is checked is exactly what the old store's own notes warned about --
restated duplicates, and a fiscal-year tag that cannot be trusted to find the
prior period -- because both are still true when the facts are read directly.
"""
from __future__ import annotations

import datetime as dt

import pytest

from chains import fundamentals
from chains.edgar import PERIOD_ANNUAL, PERIOD_QUARTER


def row(end: str, rev, oi=None, pub: str = "2026-01-01",
        fy: int | None = None, fp: str | None = None, capex=None) -> dict:
    return {"period_end": dt.date.fromisoformat(end), "revenue": rev,
            "operating_income": oi, "capital_expenditure": capex,
            "pub": pub, "fiscal_year": fy, "fiscal_period": fp}


# -- the duplicate that fabricates a 0.0% year -------------------------------

def test_a_restated_period_is_deduplicated_on_period_end():
    """companyfacts restates the same fact in later filings under a different
    fiscal-year tag. Left alone the row compares against itself and produces a
    year-on-year of exactly 0.0, which is not a slightly wrong number -- it is
    a fabricated one."""
    rows = [row("2025-12-31", 100.0, pub="2026-01-01", fy=2025),
            row("2025-12-31", 100.0, pub="2026-06-01", fy=2026),
            row("2025-12-31", 100.0, pub="2026-09-01", fy=2027)]
    out = fundamentals.series_from_rows(rows)
    assert len(out) == 1
    assert out[0]["revenue_yoy"] is None, "compared against its own restatement"


def test_the_most_recently_published_restatement_wins():
    rows = [row("2025-12-31", 100.0, pub="2026-01-01"),
            row("2025-12-31", 111.0, pub="2026-06-01")]
    out = fundamentals.series_from_rows(rows)
    assert [r["revenue"] for r in out] == [111.0]


# -- year-on-year is measured on the calendar, not on the tag ----------------

def test_annual_yoy_is_year_over_year():
    out = fundamentals.series_from_rows(
        [row("2024-12-31", 100.0), row("2025-12-31", 125.0)])
    assert out[1]["revenue_yoy"] == pytest.approx(0.25)


def test_quarterly_yoy_is_against_the_same_quarter_a_year_earlier():
    """Not against the previous quarter. A chip company's Q4 against its Q3 is
    a seasonality reading dressed up as growth."""
    rows = [row("2025-03-31", 10.0), row("2025-06-30", 20.0),
            row("2025-09-30", 30.0), row("2025-12-31", 40.0),
            row("2026-03-31", 15.0)]
    out = fundamentals.series_from_rows(rows)
    assert out[-1]["period_end"] == "2026-03-31"
    assert out[-1]["revenue_yoy"] == pytest.approx(0.5)


def test_the_first_period_has_no_yoy():
    out = fundamentals.series_from_rows([row("2025-03-31", 10.0)])
    assert out[0]["revenue_yoy"] is None


def test_a_fiscal_calendar_shift_inside_six_weeks_still_matches():
    """A 52/53-week calendar moves the period end by up to a week, and
    companies do change their year end. A period_end within six weeks of a
    year earlier is still "the same period a year earlier"."""
    out = fundamentals.series_from_rows(
        [row("2025-01-26", 100.0), row("2026-02-01", 120.0)])
    assert out[1]["revenue_yoy"] == pytest.approx(0.2)


def test_a_gap_of_two_years_is_not_a_yoy():
    out = fundamentals.series_from_rows(
        [row("2023-12-31", 100.0), row("2025-12-31", 120.0)])
    assert out[1]["revenue_yoy"] is None


def test_the_fiscal_year_tag_is_not_used_to_find_the_prior_period():
    """The tag is the field that was duplicated. Two rows tagged the same year
    but a year apart must still compare correctly."""
    out = fundamentals.series_from_rows(
        [row("2024-12-31", 100.0, fy=2025), row("2025-12-31", 150.0, fy=2025)])
    assert out[1]["revenue_yoy"] == pytest.approx(0.5)


# -- operating margin --------------------------------------------------------

def test_operating_margin_is_operating_income_over_revenue():
    out = fundamentals.series_from_rows([row("2025-12-31", 200.0, oi=50.0)])
    assert out[0]["operating_margin"] == pytest.approx(0.25)


def test_margin_is_null_when_revenue_is_zero():
    out = fundamentals.series_from_rows([row("2025-12-31", 0.0, oi=5.0)])
    assert out == [] or out[0]["operating_margin"] is None


def test_margin_is_null_when_operating_income_is_missing():
    out = fundamentals.series_from_rows([row("2025-12-31", 100.0, oi=None)])
    assert out[0]["operating_margin"] is None


def test_a_negative_operating_income_gives_a_negative_margin_not_a_null():
    """A loss is a number. Reporting it as missing would hide exactly the
    quarters a reader most wants to see."""
    out = fundamentals.series_from_rows([row("2025-12-31", 100.0, oi=-20.0)])
    assert out[0]["operating_margin"] == pytest.approx(-0.2)


def test_a_row_with_no_revenue_is_dropped():
    rows = [row("2025-12-31", 100.0), row("2024-12-31", None)]
    out = fundamentals.series_from_rows(rows)
    assert [r["period_end"] for r in out] == ["2025-12-31"]


# -- who is a filer ----------------------------------------------------------

DOC = {
    "nodes": [
        {"id": "nvda", "price_symbol": "NVDA.US",
         "price_symbol_kind": "primary"},
        {"id": "shinetsu", "price_symbol": "SHECY.US",
         "price_symbol_kind": "adr"},
        {"id": "zeiss", "price_symbol": None},
    ],
    "subnodes": [
        {"id": "amat", "price_symbol": "AMAT.US",
         "price_symbol_kind": "primary"},
    ],
}


def test_a_us_primary_listing_is_a_filer():
    assert fundamentals.us_filer_symbols(DOC)["nvda"] == "NVDA"


def test_an_adr_is_a_listing_not_a_filing():
    """SHECY prices Shin-Etsu; Shin-Etsu files with the Japanese FSA. EDGAR
    has nothing for it, and asking would return an empty panel that looks like
    a loading failure."""
    assert "shinetsu" not in fundamentals.us_filer_symbols(DOC)


def test_a_private_company_is_not_a_filer():
    assert "zeiss" not in fundamentals.us_filer_symbols(DOC)


def test_subnodes_are_searched_too():
    assert fundamentals.us_filer_symbols(DOC)["amat"] == "AMAT"


# -- build over a fake source ------------------------------------------------

def fake_source(ticker: str) -> dict:
    if ticker == "NVDA":
        return {PERIOD_ANNUAL: [row("2024-12-31", 100.0, oi=30.0),
                                row("2025-12-31", 130.0, oi=45.0)],
                PERIOD_QUARTER: [row("2025-12-31", 40.0, oi=12.0)]}
    return {PERIOD_ANNUAL: [], PERIOD_QUARTER: []}


def test_every_entry_gets_a_key_never_an_absent_one():
    out = fundamentals.build(DOC, fake_source)
    assert set(out) == {"nvda", "shinetsu", "zeiss", "amat"}
    assert all("fundamentals" in v and "reason" in v for v in out.values())


def test_a_non_filer_gets_the_null_block_and_a_reason():
    out = fundamentals.build(DOC, fake_source)
    assert out["shinetsu"]["fundamentals"] is None
    assert out["shinetsu"]["reason"] == "no EDGAR filing"
    assert out["shinetsu"]["display"] == fundamentals.NO_FILING_DISPLAY


def test_a_filer_edgar_has_nothing_for_says_so_rather_than_looking_empty():
    out = fundamentals.build(DOC, fake_source)
    assert out["amat"]["fundamentals"] is None
    assert "no EDGAR facts" in out["amat"]["reason"]


def test_a_filer_gets_its_series():
    out = fundamentals.build(DOC, fake_source)["nvda"]["fundamentals"]
    assert out["ticker"] == "NVDA"
    assert [r["period_end"] for r in out["annual"]] == ["2024-12-31",
                                                        "2025-12-31"]
    assert out["annual"][1]["revenue_yoy"] == pytest.approx(0.3)


def test_one_company_failing_does_not_fail_the_build():
    """Sixty other panels still render. The one that did not is recorded with
    its reason rather than taking the whole map down."""
    def angry(ticker: str) -> dict:
        if ticker == "NVDA":
            raise RuntimeError("connection reset")
        return fake_source(ticker)

    out = fundamentals.build(DOC, angry)
    assert out["nvda"]["fundamentals"] is None
    assert "EDGAR lookup failed" in out["nvda"]["reason"]
    assert set(out) == {"nvda", "shinetsu", "zeiss", "amat"}


def test_rnd_is_reported_missing_rather_than_guessed():
    """A guessed XBRL tag produces a number nobody can trace to a filing."""
    assert "research_and_development" in fundamentals.MISSING
    assert "research_and_development" not in fundamentals.AVAILABLE
    out = fundamentals.build(DOC, fake_source)["nvda"]["fundamentals"]
    assert "research_and_development" in out["fields_missing"]
