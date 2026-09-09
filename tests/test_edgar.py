"""Reading companyfacts without trusting its labels.

The facts document tags every value with a fiscal year and period. Those tags
are the field that gets restated, so nothing here reads them to decide what a
period IS -- that comes from ``start`` and ``end``, which are the dates the
filing actually covers.
"""
from __future__ import annotations

import json

import httpx
import pytest
import respx

from chains import edgar


def fact(start, end, val, filed, fy=None, fp=None):
    return {"start": start, "end": end, "val": val, "filed": filed,
            "fy": fy, "fp": fp, "form": "10-K"}


def facts_doc(**tags):
    return {"cik": 1, "facts": {"us-gaap": {
        tag: {"units": {"USD": rows}} for tag, rows in tags.items()}}}


# -- a period is its length, not its label ----------------------------------

@pytest.mark.parametrize("start,end,expected", [
    ("2025-01-01", "2025-12-31", edgar.PERIOD_ANNUAL),
    ("2025-01-27", "2026-01-25", edgar.PERIOD_ANNUAL),      # 52/53-week year
    ("2025-01-01", "2025-03-31", edgar.PERIOD_QUARTER),
    ("2025-01-01", "2025-06-30", None),                     # a half year
    ("2025-01-01", "2025-01-31", None),                     # a month
    ("2023-01-01", "2025-12-31", None),                     # three years
])
def test_a_span_is_classified_by_its_length(start, end, expected):
    assert edgar._period_of(start, end) == expected


def test_an_instant_is_not_a_period():
    """A balance-sheet fact has no start. It is a level, not a flow, and
    treating it as a period would put a balance into a revenue series."""
    doc = facts_doc(Revenues=[{"end": "2025-12-31", "val": 5, "filed": "2026-01-01"}])
    out = edgar.rows_from_facts(doc)
    assert out[edgar.PERIOD_ANNUAL] == [] and out[edgar.PERIOD_QUARTER] == []


# -- which revenue tag ------------------------------------------------------

def test_exactly_one_revenue_tag_is_used():
    """A series that switches definition partway through has a year-on-year
    across the seam comparing two different things."""
    doc = facts_doc(
        RevenueFromContractWithCustomerExcludingAssessedTax=[
            fact("2025-01-01", "2025-12-31", 100, "2026-02-01")],
        Revenues=[fact("2025-01-01", "2025-12-31", 999, "2026-02-01")],
    )
    out = edgar.rows_from_facts(doc)
    assert len(out[edgar.PERIOD_ANNUAL]) == 1
    assert out[edgar.PERIOD_ANNUAL][0]["revenue"] in (100, 999)


def test_the_tag_a_company_still_files_under_beats_one_it_abandoned():
    """This is NVIDIA, and it is why priority order was the wrong rule. NVIDIA
    reports the narrow tag for 2017-2022 and nothing after; taking the first
    tag present gives it a revenue series that stops in 2022, on the most
    looked-at company on the map, with nothing to show that it had."""
    doc = facts_doc(
        RevenueFromContractWithCustomerExcludingAssessedTax=[
            fact("2021-01-01", "2021-12-31", 16_675, "2022-02-01"),
            fact("2022-01-01", "2022-12-31", 26_914, "2023-02-01")],
        Revenues=[fact("2021-01-01", "2021-12-31", 16_675, "2022-02-01"),
                  fact("2022-01-01", "2022-12-31", 26_914, "2023-02-01"),
                  fact("2025-01-01", "2025-12-31", 130_497, "2026-02-01")],
    )
    out = edgar.rows_from_facts(doc)[edgar.PERIOD_ANNUAL]
    assert out[-1]["period_end"].isoformat() == "2025-12-31"
    assert out[-1]["revenue"] == 130_497


def test_best_tag_prefers_the_newest_coverage_then_the_longest():
    doc = facts_doc(
        Revenues=[fact("2024-01-01", "2024-12-31", 1, "2025-01-01")],
        SalesRevenueNet=[fact("2025-01-01", "2025-12-31", 2, "2026-01-01")],
    )
    gaap = doc["facts"]["us-gaap"]
    assert edgar.best_tag(gaap, edgar.REVENUE_TAGS) == "SalesRevenueNet"


def test_best_tag_is_none_when_the_filer_reports_none_of_them():
    assert edgar.best_tag({}, edgar.REVENUE_TAGS) is None


def test_a_company_reporting_only_the_broad_tag_still_works():
    doc = facts_doc(Revenues=[fact("2025-01-01", "2025-12-31", 42, "2026-02-01")])
    out = edgar.rows_from_facts(doc)
    assert [r["revenue"] for r in out[edgar.PERIOD_ANNUAL]] == [42]


def test_measures_are_joined_on_the_same_span():
    doc = facts_doc(
        Revenues=[fact("2025-01-01", "2025-12-31", 100, "2026-02-01")],
        OperatingIncomeLoss=[fact("2025-01-01", "2025-12-31", 25, "2026-02-01")],
        PaymentsToAcquirePropertyPlantAndEquipment=[
            fact("2025-01-01", "2025-12-31", 7, "2026-02-01")],
    )
    r = edgar.rows_from_facts(doc)[edgar.PERIOD_ANNUAL][0]
    assert (r["revenue"], r["operating_income"], r["capital_expenditure"]) == (
        100, 25, 7)


def test_a_period_with_no_revenue_is_not_emitted():
    """Operating income with no revenue beside it cannot produce a margin and
    cannot produce a year-on-year. It is not a row."""
    doc = facts_doc(OperatingIncomeLoss=[
        fact("2025-01-01", "2025-12-31", 25, "2026-02-01")])
    assert edgar.rows_from_facts(doc)[edgar.PERIOD_ANNUAL] == []


def test_annual_and_quarterly_land_in_different_buckets():
    doc = facts_doc(Revenues=[
        fact("2025-01-01", "2025-12-31", 100, "2026-02-01"),
        fact("2025-10-01", "2025-12-31", 30, "2026-02-01"),
    ])
    out = edgar.rows_from_facts(doc)
    assert len(out[edgar.PERIOD_ANNUAL]) == 1
    assert len(out[edgar.PERIOD_QUARTER]) == 1


def test_rows_carry_the_filed_date_so_a_restatement_can_be_ordered():
    doc = facts_doc(Revenues=[
        fact("2025-01-01", "2025-12-31", 100, "2026-02-01"),
    ])
    assert edgar.rows_from_facts(doc)[edgar.PERIOD_ANNUAL][0]["pub"] == "2026-02-01"


def test_a_company_with_no_us_gaap_facts_yields_nothing():
    assert edgar.rows_from_facts({}) == {edgar.PERIOD_ANNUAL: [],
                                         edgar.PERIOD_QUARTER: []}


# -- the HTTP surface --------------------------------------------------------

def test_the_user_agent_identifies_the_caller():
    """SEC asks who is calling and how to reach them, and throttles traffic
    that does not say."""
    assert "chip-map" in edgar.USER_AGENT
    assert edgar.HEADERS["User-Agent"] == edgar.USER_AGENT


def test_the_user_agent_carries_no_url():
    """Confirmed against the live endpoint: a User-Agent containing a URL is
    refused by SEC's WAF with a 403 and an HTML error page. "name email" is
    the documented form and the only one that works."""
    assert "http" not in edgar.USER_AGENT.lower()
    assert "(" not in edgar.USER_AGENT


def test_the_contact_is_a_real_address_not_a_placeholder():
    """SEC refuses a request that does not identify its caller. A placeholder
    here fails every EDGAR call in CI, which is why it is checked rather than
    left to be noticed on a Saturday morning."""
    assert "@" in edgar.CONTACT and not edgar.CONTACT.startswith("CONTACT-")


@respx.mock
def test_a_403_on_a_placeholder_contact_says_what_to_do(monkeypatch):
    """If the address is ever removed, the 403 has to explain itself: a WAF
    rejection says nothing about which header it objected to."""
    monkeypatch.setattr(edgar, "CONTACT", "CONTACT-EMAIL-HERE")
    respx.get(edgar.TICKERS_URL).mock(return_value=httpx.Response(403, text="<html>"))
    with httpx.Client(headers=edgar.HEADERS) as c:
        with pytest.raises(edgar.EdgarError) as e:
            edgar.ticker_to_cik(c)
    assert "CONTACT" in str(e.value) and "real address" in str(e.value)


@respx.mock
def test_ticker_to_cik_upper_cases_and_keeps_the_first():
    respx.get(edgar.TICKERS_URL).mock(return_value=httpx.Response(200, json={
        "0": {"cik_str": 320193, "ticker": "aapl", "title": "Apple"},
        "1": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA"},
    }))
    with httpx.Client(headers=edgar.HEADERS) as c:
        m = edgar.ticker_to_cik(c)
    assert m["AAPL"] == 320193 and m["NVDA"] == 1045810


@respx.mock
def test_a_ticker_sec_does_not_know_is_empty_not_an_error():
    """The map names companies that do not file. That is data."""
    respx.get(edgar.TICKERS_URL).mock(return_value=httpx.Response(200, json={}))
    with httpx.Client(headers=edgar.HEADERS) as c:
        out = edgar.rows_for("NOSUCH", None, c)
    assert out == {edgar.PERIOD_ANNUAL: [], edgar.PERIOD_QUARTER: []}


@respx.mock
def test_a_404_on_companyfacts_is_empty_not_an_error():
    respx.get(edgar.FACTS_URL.format(cik=1045810)).mock(
        return_value=httpx.Response(404))
    with httpx.Client(headers=edgar.HEADERS) as c:
        out = edgar.rows_for("NVDA", {"NVDA": 1045810}, c)
    assert out[edgar.PERIOD_ANNUAL] == []


@respx.mock
def test_a_server_error_raises_rather_than_looking_like_no_filings():
    """A 500 is not "this company has no revenue". Silently returning empty
    would publish a blank panel and record no reason."""
    respx.get(edgar.FACTS_URL.format(cik=1045810)).mock(
        return_value=httpx.Response(503, text="busy"))
    with httpx.Client(headers=edgar.HEADERS) as c:
        with pytest.raises(edgar.EdgarError):
            edgar.rows_for("NVDA", {"NVDA": 1045810}, c)


@respx.mock
def test_the_source_fetches_the_cik_map_once_for_many_tickers():
    route = respx.get(edgar.TICKERS_URL).mock(return_value=httpx.Response(
        200, json={"0": {"cik_str": 1, "ticker": "AAA", "title": "A"}}))
    respx.get(edgar.FACTS_URL.format(cik=1)).mock(
        return_value=httpx.Response(200, json=facts_doc(Revenues=[
            fact("2025-01-01", "2025-12-31", 5, "2026-02-01")])))
    with httpx.Client(headers=edgar.HEADERS) as c:
        src = edgar.Source(client=c, sleep=0)
        src("AAA")
        src("AAA")
    assert route.call_count == 1
