"""The ticker field is prose. Extraction must fail loudly, never guess."""
from __future__ import annotations

import pytest

from chains import exchanges, mapfile


# -- what is and is not a ticker ------------------------------------------

@pytest.mark.parametrize("raw", [
    "private",
    "state-backed",
    "n/a",
    "",
    None,
    "various",
])
def test_non_tickers_yield_nothing(raw):
    assert mapfile.candidate_tickers(raw) == []


def test_a_plain_ticker_comes_through():
    assert mapfile.candidate_tickers("4063.T") == ["4063.T"]
    assert mapfile.candidate_tickers("AMAT") == ["AMAT"]


def test_a_dual_listing_yields_both_in_order():
    """'2330 / TSM' is one company on two venues. Order matters: the probe
    falls back to the second only if the first is unavailable."""
    assert mapfile.candidate_tickers("2330 / TSM") == ["2330", "TSM"]


def test_commentary_after_a_semicolon_is_not_an_alternative():
    got = mapfile.candidate_tickers("6146.T (TSE) / sub in CN; Coorstek = private")
    assert got == ["6146.T"]


def test_a_dotted_ticker_buried_in_prose_is_found():
    assert mapfile.candidate_tickers("601600.SS (Chalco) et al.") == ["601600.SS"]


def test_an_undotted_word_in_prose_is_NOT_treated_as_a_ticker():
    """'et', 'al', 'TPE' and 'sub' all match the bare ticker shape. Pricing the
    wrong company is worse than a gap, so only the dotted form is lifted out of
    free text."""
    assert mapfile.candidate_tickers("PVA TePla = TPE Xetra") == []
    assert "et" not in mapfile.candidate_tickers("601600.SS et al.")


# -- venue resolution ------------------------------------------------------

def test_korea_is_KO_not_the_yahoo_KS():
    """The habit is .KS. EODHD calls the Korea Stock Exchange KO, confirmed
    against /exchanges-list/ on 2026-09-08."""
    assert exchanges.resolve("005930.KS", "KRX") == ("005930.KO", None)


def test_tokyo_is_reported_as_a_subscription_gap_not_a_bad_ticker():
    tick, why = exchanges.resolve("4063.T", "TSE")
    assert tick is None and "not in the EODHD exchange list" in why


@pytest.mark.parametrize("sym,exch,want", [
    ("AMAT", "NASDAQ", "AMAT.US"),
    ("ASML", "NASDAQ/Euronext", "ASML.US"),
    ("6488.TWO", "TPEx", "6488.TWO"),
    ("300316.SZ", "SZSE", "300316.SHE"),
    ("601600.SS", "SSE", "601600.SHG"),
])
def test_known_venues_resolve(sym, exch, want):
    assert exchanges.resolve(sym, exch)[0] == want


def test_a_numeric_ticker_never_resolves_to_a_us_venue():
    """'2330 / TSM' on 'TWSE / NYSE' is two listings paired positionally. An
    earlier version matched NYSE first and produced 2330.US, which is a real
    NASDAQ symbol belonging to a different company -- the silent-wrong-company
    failure this whole module is written to avoid."""
    assert exchanges.resolve("2330", "TWSE / NYSE") == ("2330.TW", None)
    assert exchanges.resolve("2330", "NYSE (ADR) / TWSE 2330")[0] == "2330.TW"


def test_an_unreadable_label_on_a_numeric_ticker_asks_for_a_person():
    tick, why = exchanges.resolve("1234", "some exchange we do not know")
    assert tick is None and "needs a person" in why


def test_an_alphabetic_ticker_with_no_label_defaults_to_us():
    assert exchanges.resolve("NVDA", None) == ("NVDA.US", None)


# -- entries ---------------------------------------------------------------

def test_a_private_subnode_is_private_even_when_it_names_a_listed_parent():
    """'private (Cosmo Energy 5021.T)' is not Cosmo Energy. The subnode is the
    private one; the parenthetical names its owner."""
    e = mapfile._entry("subnode", {
        "id": "maruzen", "name": "Maruzen Petrochemical",
        "ticker": "private (Cosmo Energy 5021.T)", "exchange": None,
    })
    assert e.ticker is None
    assert "private" in e.reason


def test_unparseable_prose_is_flagged_for_a_person_not_silently_dropped():
    e = mapfile._entry("subnode", {
        "id": "x", "name": "X", "exchange": None,
        "ticker": "PVA TePla = TPE (Xetra); Ferrotec = 6890.T",
    })
    assert e.ticker is None and "needs a person" in e.reason
