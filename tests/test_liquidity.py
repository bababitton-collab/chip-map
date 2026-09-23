"""The liquidity gate, the nightly stale line, and the price lines they moved.

A basket leg is scored by its price, so its line has to trade. What is pinned
here: the two rules and their edges, that an unchecked leg is a refusal and
not a pass, that the nightly line reports and never fails the build, and that
the map and the baskets now say what the lines are.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from chains import build_all
from chains import build_pages as bp
from chains import liquidity as L
from chains.paths import map_path, out_dir, templates_dir, watch_en_path, watch_path

MAP = json.loads(map_path().read_text(encoding="utf-8"))
NODES = {n["id"]: n for n in MAP["nodes"]}
WATCH = json.loads(watch_path().read_text(encoding="utf-8"))
WATCH_EN = json.loads(watch_en_path().read_text(encoding="utf-8"))
TODAY = dt.date(2026, 9, 16)            # a Wednesday


def fake(adv=1_000_000.0, last="2026-09-15", error=None):
    def measure(symbol):
        if error:
            return {"symbol": symbol, "error": error}
        return {"symbol": symbol, "adv_usd": adv, "adv_shares": 1.0, "sessions": 60,
                "last_close": last, "currency": "USD"}
    return measure


# -- the rules -----------------------------------------------------------------

def test_sessions_count_completed_weekdays_only():
    assert L.sessions_since(dt.date(2026, 9, 15), TODAY) == 0
    assert L.sessions_since(dt.date(2026, 9, 11), TODAY) == 2, "Fri: Mon and Tue missing"
    assert L.sessions_since(dt.date(2026, 9, 10), TODAY) == 3


@pytest.mark.parametrize("adv,last,ok,words", [
    (250_000, "2026-09-11", True, ""),
    (249_999, "2026-09-15", False, "under US$250,000"),
    (5_000_000, "2026-09-10", False, "3 completed sessions old"),
])
def test_a_leg_needs_traded_value_and_a_recent_close(adv, last, ok, words):
    got = L.check_leg("x", "X.US", fake(adv, last), TODAY)
    assert got["ok"] is ok and words in got["why"]


def test_a_leg_with_no_line_or_no_bars_fails():
    assert L.check_leg("x", None, fake(), TODAY)["why"] == "no price line on the map"
    got = L.check_leg("x", "X.US", fake(error="EODHD has no daily bars with volume in three months"), TODAY)
    assert got["ok"] is False and "no daily bars" in got["why"]


def test_an_observe_only_row_has_no_legs_to_fail():
    got = L.check_row({"id": "m", "observe_only": True, "win": [], "lose": []}, MAP, fake(error="x"), TODAY)
    assert got == {"qid": "m", "ok": True, "legs": []}


def test_the_measure_converts_to_dollars_and_reads_the_last_close():
    class Client:
        def eod(self, symbol, from_=None, to=None):
            if symbol == "USDEUR.FOREX":
                return [{"date": "2026-09-15", "close": 0.8}]
            if symbol == "EURUSD.FOREX":
                return [{"date": "2026-09-15", "close": 1.2}]     # rounded; not used
            return [{"date": "2026-09-14", "close": 10.0, "volume": 1000},
                    {"date": "2026-09-15", "close": 20.0, "volume": 3000}]
    m = L.Measure(TODAY, client=Client())("WCH.XETRA")
    assert m["currency"] == "EUR" and m["last_close"] == "2026-09-15"
    assert m["adv_usd"] == pytest.approx(1.25 * (10_000 + 60_000) / 2), "1 / USDEUR"


def test_no_token_is_a_refusal_not_a_pass(monkeypatch):
    monkeypatch.delenv("EODHD_API_TOKEN", raising=False)
    with pytest.raises(L.LiquidityError, match="not committed"):
        L.Measure(TODAY)


def test_the_stored_record_is_what_the_gate_passed_on():
    res = L.check_row({"id": "q", "win": ["hoya"], "lose": []}, MAP, fake(400_000.4, "2026-09-15"), TODAY)
    rec = L.stored(res, "2026-09-16")
    assert rec == {"checked_at": "2026-09-16", "min_adv_usd": 250_000,
                   "legs": {"hoya": {"symbol": NODES["hoya"]["price_symbol"], "adv_usd": 400_000,
                                     "last_close": "2026-09-15"}}}
    assert L.record_problems(rec, "2026-09-16") == []


def test_a_blocking_message_names_the_leg_the_line_and_the_reason():
    res = L.check_row({"id": "q", "win": ["hoya", "tok"], "lose": []}, MAP,
                      lambda s: fake(8_522 if s == NODES["tok"]["price_symbol"] else 900_000)(s), TODAY)
    msg = L.blocking_message("q", res)
    assert "1 basket leg(s) fail the liquidity gate" in msg
    assert "tok (TOKCF.US): three-month average daily traded value US$8,522" in msg


# -- the nightly line ------------------------------------------------------------

def test_the_nightly_line_flags_only_legs_quiet_for_more_than_three_sessions():
    rows = [{"id": "a", "win": ["hoya", "tok"], "lose": []},
            {"id": "b", "win": ["tok"], "lose": ["agc"]},
            {"id": "m", "observe_only": True, "win": [], "lose": []}]
    n = {NODES["hoya"]["price_symbol"]: 3, NODES["tok"]["price_symbol"]: 14, NODES["agc"]["price_symbol"]: 0}
    flagged = L.stale_legs(rows, MAP, n.get)
    assert [(v["leg"], v["sessions"], v["questions"]) for v in flagged] == [("tok", 14, ["a", "b"])]
    lines = L.stale_lines(flagged)
    assert lines[0].startswith("legs: 1 basket leg(s)") and "report only" in lines[0]
    assert lines[1] == "  tok TOKCF.US: 14 sessions without a close -- a, b"
    assert L.stale_lines([])[0].startswith("legs: no basket leg")


def test_the_nightly_line_never_fails_the_build(monkeypatch, capsys, tmp_path):
    def boom(*a, **k):
        raise RuntimeError("no price store")
    monkeypatch.setattr(L, "stale_legs", boom)
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert L.main(["--stale"]) == 0
    assert "legs: check skipped (RuntimeError: no price store)" in capsys.readouterr().out
    assert "check skipped" in summary.read_text(encoding="utf-8")


def test_the_daily_build_runs_the_nightly_line_after_the_price_refresh():
    steps = build_all.steps(dt.date(2026, 9, 16))
    names = [n for n, _argv in steps]
    assert ("legs", ["-m", "chains.liquidity", "--stale"]) in steps
    assert names.index("repair") < names.index("legs") < names.index("preregister")


# -- the map and the baskets -----------------------------------------------------

def test_tok_and_agc_stay_on_the_map_marked_thin():
    thin = {i for i, n in NODES.items() if n.get("price_quality") == "thin"}
    assert thin == {"tok", "agc"}
    for i in thin:
        assert "Thin:" in NODES[i]["price_note"], i


@pytest.mark.parametrize("rows", [WATCH, WATCH_EN], ids=["watch", "watch_en"])
def test_no_basket_prices_a_leg_on_a_thin_line(rows):
    thin = {i for i, n in NODES.items() if n.get("price_quality") == "thin"}
    assert [(r["id"], i) for r in rows for i in L.legs_of(r) if i in thin] == []


def test_ibiden_is_priced_on_its_liquid_adr_wherever_the_map_names_it():
    assert NODES["ibiden"]["price_symbol"] == "IBIDY.US"
    subs = [s for s in MAP["subnodes"] if s["id"] in ("ibiden", "ibiden_cp8")]
    assert len(subs) == 2 and all(s["price_symbol"] == "IBIDY.US" for s in subs)
    assert "IBIDF" not in json.dumps(MAP)


# -- the badge -------------------------------------------------------------------

TPL = (templates_dir() / "live-map.html").read_text(encoding="utf-8")


def test_the_station_panel_badges_a_thin_or_stale_price_line():
    assert ".badge.thin{" in TPL
    assert "function priceBadge(n){" in TPL
    assert "</span>${priceBadge(n)}<p class=\"role\"" in TPL


def test_the_badge_is_in_english_on_the_english_map(tmp_path):
    dst = tmp_path / "en.html"
    bp.build_en_template(dst=dst)
    en = dst.read_text(encoding="utf-8")
    i = en.index("function priceBadge(n){")
    body = en[i:en.index("\n", i)]
    assert "thin price line" in body and "stale price" in body and "days" in body
    assert bp.hebrew_runs(body) == []


def test_the_snapshot_marks_only_the_thin_stations():
    p = out_dir() / "live_en.json"
    if not p.exists() or p.stat().st_mtime < map_path().stat().st_mtime:
        pytest.skip("live_en.json not built since the last map change")
    nodes = json.loads(p.read_text(encoding="utf-8"))["nodes"]
    assert sorted(n["id"] for n in nodes if "thin" in n) == ["agc", "tok"]
    assert all(n["thin"] is True for n in nodes if "thin" in n)


# -- a venue's own currency ----------------------------------------------------
# currency_of falls back to "USD" for a suffix it does not know, and the
# fallback is silent: the closes convert at 1.0 and the leg's traded value
# comes out in the exchange's own money wearing a dollar sign. That is not a
# gap, it is a wrong number large enough to carry a leg through the gate. HK
# was missing and 2269.HK read about 7.8x its true dollar value.

HKD_PER_USD = 7.8433            # USDHKD.FOREX, 2026-09-22


class _HKClient:
    """2269.HK as the vendor actually serves it: closes in Hong Kong dollars,
    and the peg on USDHKD.FOREX."""

    def eod(self, symbol, from_=None, to=None):
        if symbol == "USDHKD.FOREX":
            return [{"date": "2026-09-15", "close": HKD_PER_USD}]
        if symbol == "HKDUSD.FOREX":
            return [{"date": "2026-09-15", "close": 0.1275}]   # rounded; unused
        return [{"date": "2026-09-14", "close": 52.65, "volume": 18_626_715},
                {"date": "2026-09-15", "close": 52.80, "volume": 17_569_235}]


def test_a_hong_kong_line_is_measured_in_dollars_not_in_hong_kong_dollars():
    m = L.Measure(TODAY, client=_HKClient())("2269.HK")
    assert m["currency"] == "HKD", "the suffix has to resolve to the venue's money"

    hkd = (52.65 * 18_626_715 + 52.80 * 17_569_235) / 2
    assert m["adv_usd"] == pytest.approx(hkd / HKD_PER_USD, rel=1e-9)

    # The number this pins is the one the bug produced: unconverted, the same
    # bars read as about 7.8x more traded value than the line really has, and
    # the gate would have been cleared on money that was never dollars.
    assert m["adv_usd"] < hkd / 7, "still reading Hong Kong dollars as dollars"
    assert 1e8 < m["adv_usd"] < 3e8, "about US$200m, not about US$1.6bn"


def test_every_exchange_the_map_can_name_has_a_currency():
    """The two tables are added to together or not at all.

    A code in exchanges.py with no entry in CURRENCY_BY_EXCHANGE is the exact
    shape of the HK bug: the symbol resolves, the bars arrive, and the dollars
    are wrong with nothing raised.
    """
    from chains import exchanges as X

    known = set(X.BY_EXCHANGE.values()) | set(X.BY_SUFFIX.values())
    missing = sorted(code for code in known
                     if code not in L.CURRENCY_BY_EXCHANGE)
    assert not missing, (
        f"exchanges.py can produce {missing}, and liquidity.CURRENCY_BY_EXCHANGE "
        f"has no currency for it, so its closes would be read as US dollars")


def test_every_price_line_on_every_map_has_a_currency():
    """The maps are the other source of a suffix, and the one that bites.

    exchanges.py's tables are not where CO came from -- the energy map simply
    names NKT.CO -- so a test that reads only those tables would have passed
    over a live price line being measured in kroner and called dollars. This
    one walks what the maps actually say.
    """
    from chains import domains

    strays = []
    for dom in domains.discover():
        doc = json.loads((map_path(dom=dom)).read_text(encoding="utf-8"))
        for n in doc.get("nodes", []):
            sym = n.get("price_symbol")
            if not sym or n.get("price_symbol_kind") == "none":
                continue
            suffix = sym.rsplit(".", 1)[-1].upper()
            if suffix not in L.CURRENCY_BY_EXCHANGE:
                strays.append(f"{dom}:{n['id']}={sym}")
    assert not strays, (
        f"these price lines have no currency in CURRENCY_BY_EXCHANGE, so their "
        f"traded value would be measured in the venue's own money and reported "
        f"as US dollars: {strays}")


def test_hong_kong_is_no_longer_listed_as_unavailable():
    from chains import exchanges as X

    assert "HK" not in X.UNAVAILABLE and "HKEX" not in X.UNAVAILABLE
    assert X.BY_SUFFIX["HK"] == "HK" and X.BY_EXCHANGE["HKEX"] == "HK"
