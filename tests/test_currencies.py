"""One currency table, and the walk over every real price line that proves it.

The bug this pins is not "London was wrong". It is that the same fact was
written down twice -- once in prices.py to label a stored series, once in
liquidity.py to convert traded value -- and the two copies drifted with
nothing able to notice. By the time anyone looked they disagreed about
London, and the map published Rolls-Royce at "GBP 1485.20" for a share worth
about fourteen pounds eighty.
"""
from __future__ import annotations

import json

import pytest

from chains import currencies, domains, liquidity, prices
from chains.paths import map_path


def priced_lines() -> list[tuple[str, str, str]]:
    """(domain, node id, price symbol) for every line a map really carries."""
    out = []
    for dom in domains.discover():
        doc = json.loads(map_path(dom=dom).read_text(encoding="utf-8"))
        for coll in ("nodes", "subnodes"):
            for n in doc.get(coll, []):
                sym = n.get("price_symbol")
                if sym and n.get("price_symbol_kind") != "none":
                    out.append((dom, n["id"], sym))
        bench = (doc.get("benchmark") or {}).get("symbol")
        if bench:
            out.append((dom, "BENCHMARK", bench))
    return out


# -- the one table -------------------------------------------------------------
def test_there_is_one_table_and_both_modules_read_it():
    """Not "they agree" -- they are the same object. Agreement can lapse."""
    assert prices.CURRENCY is currencies.BY_SUFFIX
    assert liquidity.CURRENCY_BY_EXCHANGE is currencies.BY_SUFFIX


@pytest.mark.parametrize("symbol", [
    "RR.LSE", "BA.LSE", "0522.HK", "NKT.CO", "AAPL.US", "005930.KO",
    "600111.SHG", "SAF.PA", "FOO.ZZZ", "NOSUFFIX",
])
def test_the_two_callers_cannot_answer_differently(symbol):
    assert prices.currency_for(symbol) == liquidity.currency_of(symbol)


# -- the walk, which is what would have caught it ------------------------------
def test_every_price_line_on_every_map_has_a_known_currency():
    """The maps are the source of a suffix, and the one that bites.

    NKT.CO reached the energy map without anything in liquidity's table, and
    RR.LSE and BA.LSE reached the defence map with the two tables disagreeing.
    Neither was found by reading a table; both were found by walking the maps.
    """
    stray = [f"{dom}:{nid}={sym}" for dom, nid, sym in priced_lines()
             if currencies.of(sym) == currencies.UNKNOWN]
    assert not stray, (
        f"these price lines have no currency, so their traded value would be "
        f"unmeasurable and their stored label would read UNKNOWN: {stray}")


def test_no_price_line_resolves_differently_in_the_two_modules():
    bad = [f"{dom}:{nid}={sym} prices={prices.currency_for(sym)} "
           f"liquidity={liquidity.currency_of(sym)}"
           for dom, nid, sym in priced_lines()
           if prices.currency_for(sym) != liquidity.currency_of(sym)]
    assert not bad, bad


def test_every_stored_series_has_a_known_currency():
    """The store is the other place a suffix arrives -- challengers are
    fetched and stored without being nodes, which is how 0522.HK and 0981.HK
    came to sit in out/prices labelled UNKNOWN."""
    from chains.paths import prices_dir

    d = prices_dir()
    if not d.is_dir():
        pytest.skip("no price store in this checkout")
    stray = sorted({p.stem.replace("_", ".") for p in d.glob("*.parquet")
                    if currencies.of(p.stem.replace("_", ".")) == currencies.UNKNOWN})
    assert not stray, f"stored series with no currency: {stray}"


# -- the specifics that were wrong ---------------------------------------------
def test_london_is_pence():
    """A number labelled GBP that is really pence is wrong by a hundred."""
    assert currencies.of("RR.LSE") == "GBX"
    assert currencies.of("BA.LSE") == "GBX"


def test_hong_kong_is_hkd():
    assert currencies.of("2269.HK") == "HKD"
    assert currencies.of("0522.HK") == "HKD"


def test_an_unknown_suffix_is_unknown_and_never_quietly_usd():
    """Guessing dollars reads a foreign line as already converted: richer
    than it is, by exactly the exchange rate, with nothing raised."""
    for sym in ("FOO.ZZZ", "FOO", ""):
        assert currencies.of(sym) == "UNKNOWN"
        assert liquidity.currency_of(sym) == "UNKNOWN"


# -- the stale-label path ------------------------------------------------------
def test_the_stored_label_is_re_derived_on_load(tmp_path, monkeypatch):
    """A parquet written when the table said GBP must read back as GBX.

    The column is a pure function of the symbol, so storing it denormalised a
    fact, and a denormalised fact goes stale. It did: two London series were
    written as GBP and nothing rewrites a column that is only appended to.
    """
    import polars as pl
    monkeypatch.setattr("chains.prices.prices_dir", lambda: tmp_path)
    rows = [{"date": "2026-09-23", "open": 1, "high": 1, "low": 1,
             "close": 1480.0, "adjusted_close": 1480.0, "volume": 10}]
    df = prices.frame("RR.LSE", rows).with_columns(
        pl.lit("GBP", dtype=pl.Utf8).alias("currency"))      # the old label
    prices.path_for("RR.LSE").parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(prices.path_for("RR.LSE"))

    got = prices.load("RR.LSE")
    assert got["currency"][0] == "GBX", "a stale stored label must not survive a read"
    assert got["adj_close"][0] == 1480.0, "the price itself must not be touched"
