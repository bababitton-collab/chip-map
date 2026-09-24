"""The gate between a provider and the store, and the Yahoo client's shape.

What is pinned here: that a missing price stops the build instead of being
published as a calm empty station, that a move no market made stops it too,
that a real split does NOT, and that the symbol table refuses an exchange it
cannot spell rather than sending the request to the US market.
"""
from __future__ import annotations

import pytest

from chains import price_guard as G
from chains.providers import yahoo as Y


def bars(*pairs) -> list[dict]:
    """(date, adjusted_close) -> rows in the shape prices.frame reads."""
    return [{"date": d, "open": c, "high": c, "low": c, "close": c,
             "adjusted_close": c, "volume": 1_000} for d, c in pairs]


# -- the empty cases, which are the ones that render as a calm page -----------
def test_none_is_refused():
    with pytest.raises(G.PriceSanityError, match="returned None"):
        G.check("RHM.XETRA", None)


def test_an_empty_series_stops_the_build():
    with pytest.raises(G.PriceSanityError) as e:
        G.check("RHM.XETRA", [])
    assert "RHM.XETRA" in str(e.value), "the log is a loop; name the symbol"
    assert "no bars" in str(e.value)


def test_an_empty_series_is_allowed_only_when_asked_for():
    assert G.check("RHM.XETRA", [], allow_empty=True) == []


def test_rows_that_carry_no_usable_close_are_not_prices():
    padding = [{"date": "2026-09-21", "close": None, "adjusted_close": None},
               {"date": "2026-09-22", "close": None, "adjusted_close": None}]
    with pytest.raises(G.PriceSanityError, match="not one carries a usable"):
        G.check("2269.HK", padding)


def test_a_zero_or_negative_close_does_not_count_as_usable():
    with pytest.raises(G.PriceSanityError, match="not one carries a usable"):
        G.check("X.US", bars(("2026-09-21", 0.0)))


# -- the moves ----------------------------------------------------------------
def test_an_ordinary_series_passes():
    rows = bars(("2026-09-21", 100.0), ("2026-09-22", 103.0),
                ("2026-09-23", 99.5))
    assert G.check("LMT.US", rows, prior_close=101.0) is rows


def test_a_move_no_market_made_stops_the_build():
    rows = bars(("2026-09-21", 100.0), ("2026-09-22", 8.0))
    with pytest.raises(G.PriceSanityError) as e:
        G.check("BA.LSE", rows)
    msg = str(e.value)
    assert "BA.LSE" in msg and "92%" in msg
    assert "Nothing is stored" in msg


def test_a_split_is_already_adjusted_away_and_does_not_trip_the_gate():
    """The whole reason the gate reads the ADJUSTED close.

    A 2-for-1 halves the raw close overnight. In the adjusted series it is
    not an event at all, so a real corporate action passes while a symbol
    that quietly changed company still fails.
    """
    raw_halving = [
        {"date": "2026-09-21", "close": 200.0, "adjusted_close": 100.0},
        {"date": "2026-09-22", "close": 101.0, "adjusted_close": 101.0},
    ]
    assert G.check("NVDA.US", raw_halving) is raw_halving


def test_a_gap_against_the_stored_close_is_caught():
    rows = bars(("2026-09-22", 300.0))
    with pytest.raises(G.PriceSanityError, match="away from the stored close"):
        G.check("WST.US", rows, prior_close=100.0)


def test_no_stored_close_means_the_gap_test_is_skipped_not_guessed():
    rows = bars(("2026-09-22", 300.0))
    assert G.check("NEW.US", rows, prior_close=None) is rows


# -- the symbol table ---------------------------------------------------------
@pytest.mark.parametrize("eodhd,yahoo", [
    ("AAPL.US", "AAPL"),          # US tickers are bare at Yahoo
    ("005930.KO", "005930.KS"),   # KRX: EODHD says KO, Yahoo says KS
    ("ENR.XETRA", "ENR.DE"),
    ("600111.SHG", "600111.SS"),
    ("002155.SHE", "002155.SZ"),
    ("BA.LSE", "BA.L"),
    ("2269.HK", "2269.HK"),
    ("NKT.CO", "NKT.CO"),
    ("6488.TWO", "6488.TWO"),
])
def test_the_symbol_table_spells_each_exchange_the_way_yahoo_does(eodhd, yahoo):
    assert Y.to_yahoo(eodhd) == yahoo


@pytest.mark.parametrize("eodhd,yahoo", [
    ("USDTWD.FOREX", "TWD=X"),     # a USD pair is the quote currency alone
    ("USDKRW.FOREX", "KRW=X"),
    ("USDGBP.FOREX", "GBP=X"),
    ("USDDKK.FOREX", "DKK=X"),
    ("TWDUSD.FOREX", "TWDUSD=X"),  # anything else is the two codes joined
    ("EURUSD.FOREX", "EURUSD=X"),
])
def test_the_liquidity_gates_fx_pairs_translate(eodhd, yahoo):
    """liquidity.Measure.fx asks in the old vendor's spelling.

    This is not cosmetic. A rate that does not resolve is a leg measured in
    the wrong money, which is the failure this repository has already shipped
    once with the missing HK entry.
    """
    assert Y.to_yahoo(eodhd) == yahoo


def test_an_unknown_suffix_raises_rather_than_falling_through_to_the_us():
    """Guessing here returns a healthy series for the wrong company.

    BA is Boeing in New York and BAE Systems in London. A suffix this client
    cannot spell must stop, not strip.
    """
    with pytest.raises(Y.UnknownSuffix) as e:
        Y.to_yahoo("BA.NOSUCH")
    assert "BA.NOSUCH" in str(e.value)


def test_every_suffix_the_maps_use_has_a_yahoo_spelling():
    """The maps are the source of a suffix, and the one that bites."""
    import json
    from chains import domains
    from chains.paths import map_path

    strays = []
    for dom in domains.discover():
        doc = json.loads(map_path(dom=dom).read_text(encoding="utf-8"))
        for n in doc.get("nodes", []) + doc.get("subnodes", []):
            sym = n.get("price_symbol")
            if not sym or n.get("price_symbol_kind") == "none":
                continue
            try:
                Y.to_yahoo(sym)
            except Y.UnknownSuffix:
                strays.append(f"{dom}:{n['id']}={sym}")
    assert not strays, f"no Yahoo spelling for: {strays}"


# -- the provider's own refusals ---------------------------------------------
def test_a_yahoo_error_block_is_not_an_empty_result():
    payload = {"chart": {"error": {"code": "Not Found"}, "result": None}}
    with pytest.raises(Y.NoData, match="Not Found"):
        Y.YahooClient._rows("NOPE.US", "NOPE", payload)


def test_a_missing_result_block_is_refused():
    with pytest.raises(Y.NoData, match="no result block"):
        Y.YahooClient._rows("NOPE.US", "NOPE", {"chart": {"result": []}})


def test_yahoos_null_padding_is_dropped_not_stored():
    payload = {"chart": {"result": [{
        "timestamp": [1758412800, 1758499200],
        "indicators": {"quote": [{"close": [None, 101.0], "open": [None, 100.0],
                                  "high": [None, 102.0], "low": [None, 99.0],
                                  "volume": [None, 5]}],
                       "adjclose": [{"adjclose": [None, 101.0]}]},
    }], "error": None}}
    rows = Y.YahooClient._rows("X.US", "X", payload)
    assert len(rows) == 1 and rows[0]["adjusted_close"] == 101.0


def test_adjusted_close_falls_back_to_close_when_yahoo_omits_it():
    payload = {"chart": {"result": [{
        "timestamp": [1758499200],
        "indicators": {"quote": [{"close": [50.0], "open": [49.0],
                                  "high": [51.0], "low": [48.0],
                                  "volume": [7]}]},
    }], "error": None}}
    rows = Y.YahooClient._rows("X.US", "X", payload)
    assert rows[0]["adjusted_close"] == 50.0


def test_the_broken_response_stops_a_store_shaped_call_end_to_end():
    """The actual requirement: feed a deliberately broken response through
    the gate the build would use, and confirm it stops."""
    broken = Y.YahooClient._rows("X.US", "X", {"chart": {"result": [{
        "timestamp": [], "indicators": {"quote": [{}]}}], "error": None}})
    assert broken == [], "an empty window is empty at the provider"
    with pytest.raises(G.PriceSanityError):
        G.check("X.US", broken)          # and fatal at the gate
