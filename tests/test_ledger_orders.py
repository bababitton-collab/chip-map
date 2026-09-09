"""Two orders in one ledger, scored apart.

Order 1 is the basket somebody registered by hand. Order 2 is its second ring,
derived from the map's supply edges. They are entered on the same date and
scored by the same arithmetic, and their numbers are never added together: a
hit rate over a mixed population of first- and second-order claims describes
neither of them.
"""
from __future__ import annotations

import datetime as dt

import pytest

from chains import answers, forecast, prices, rings

# Long enough for a 40-session horizon to lock, which a direct forecast never
# needs and an indirect one is defined by.
CAL = []
d = dt.date(2026, 3, 2)
while len(CAL) < 60:
    if d.weekday() < 5:
        CAL.append(d)
    d += dt.timedelta(days=1)

SYMS = ["UP.US", "DOWN.US", "FLAT.US", "S1.US", "S2.US"]
DOC = {"nodes": [{"id": i, "price_symbol": i.upper() + ".US",
                  "price_symbol_kind": "primary"}
                 for i in ("up", "down", "flat", "s1", "s2")],
       "subnodes": []}


@pytest.fixture
def book(monkeypatch, tmp_path):
    monkeypatch.setenv("CHIP_MAP_PRICES", str(tmp_path))
    for sym, step in (("UP.US", 1.0), ("DOWN.US", -1.0), ("FLAT.US", 0.0),
                      ("S1.US", 0.5), ("S2.US", -0.5)):
        prices.store(sym, [{"date": c.isoformat(),
                            "adjusted_close": 100.0 + step * i}
                           for i, c in enumerate(CAL)])
    return forecast.Book(SYMS)


def fc(fid, qid, win, lose, order=1, direction=1, marked="2026-03-02"):
    r = {"id": fid, "qid": qid, "marked_at": marked, "status": "yes",
         "direction": direction, "win": win, "lose": lose,
         "benchmark": "EW_MAP", "horizons": list(answers.ORDERS[order])}
    if order != 1:
        r["order"] = order
    return r


def led(book, forecasts, log=None):
    return forecast.build(forecasts, DOC, log if log is not None else [], CAL)


# -- the forty-session horizon -----------------------------------------------

def test_an_indirect_forecast_is_scored_at_forty_sessions(book):
    """A second-order effect arrives through somebody else's order book -- a
    quarter of wafer starts, not a press release. 20 sessions is short for
    that, so 40 is added; the first three stay so the orders can still be read
    against each other where they overlap."""
    r = led(book, [fc("r2", "mu_fq4", ["s1"], ["s2"], order=2)])["rows"][0]
    assert sorted(int(h) for h in r["horizons"]) == [5, 10, 20, 40]
    assert r["horizons"]["40"] is not None
    assert r["horizons"]["40"]["excess"] is not None


def test_forty_is_scored_the_same_way_as_the_others(book):
    r = led(book, [fc("r2", "mu_fq4", ["s1"], ["s2"], order=2)])["rows"][0]
    for h in ("5", "10", "20", "40"):
        got = r["horizons"][h]
        assert set(got) == {"excess", "win", "lose", "bench", "date", "hit"}
        # every field is stored rounded to 6 places
        assert got["excess"] == pytest.approx(got["win"] - got["lose"],
                                              abs=2e-6)


def test_a_direct_forecast_has_no_forty(book):
    r = led(book, [fc("f", "mu_fq4", ["up"], ["down"])])["rows"][0]
    assert sorted(int(h) for h in r["horizons"]) == [5, 10, 20]


def test_a_horizon_that_has_not_locked_yet_is_pending_not_zero(book):
    """40 sessions after a mark near the end of the calendar has not happened.
    It is pending -- it is not an excess of nothing."""
    r = led(book, [fc("r2", "mu_fq4", ["s1"], ["s2"], order=2,
                      marked=CAL[-5].isoformat())])["rows"][0]
    assert r["horizons"]["40"] is None
    s = led(book, [fc("r2", "mu_fq4", ["s1"], ["s2"], order=2,
                      marked=CAL[-5].isoformat())])["summary"]["indirect"]
    assert s["horizons"]["40"]["n"] == 0
    assert s["horizons"]["40"]["n_pending"] == 1


# -- the order field ---------------------------------------------------------

def test_the_order_defaults_to_one(book):
    """Every forecast written before the second ring existed is a direct one,
    and stays one without being rewritten."""
    old = fc("f", "mu_fq4", ["up"], ["down"])
    old.pop("order", None)
    assert led(book, [old])["rows"][0]["order"] == 1


def test_the_row_carries_its_order_through_to_the_page(book):
    rows = led(book, [fc("f", "mu_fq4", ["up"], ["down"]),
                      fc("r", "mu_fq4", ["s1"], ["s2"], order=2)])["rows"]
    assert {r["id"]: r["order"] for r in rows} == {"f": 1, "r": 2}


# -- two summaries, never one ------------------------------------------------

def test_the_two_orders_are_summarised_separately(book):
    s = led(book, [fc("f", "mu_fq4", ["up"], ["down"]),
                   fc("r", "mu_fq4", ["s1"], ["s2"], order=2)])["summary"]
    assert s["order"] == 1 and s["indirect"]["order"] == 2
    assert s["n_forecasts"] == 1, "the direct summary counts direct rows only"
    assert s["indirect"]["n_forecasts"] == 1


def test_nothing_pools_them(book):
    """Two direct rows and one indirect one. The direct N is 2, not 3."""
    s = led(book, [fc("f1", "mu_fq4", ["up"], ["down"]),
                   fc("f2", "nvda_q3", ["up"], ["down"]),
                   fc("r", "mu_fq4", ["s1"], ["s2"], order=2)])["summary"]
    assert s["horizons"]["5"]["n"] == 2
    assert s["indirect"]["horizons"]["5"]["n"] == 1


def test_pending_is_counted_per_order(book):
    """A row marked after the last session has entered nothing. It is pending
    in its OWN order's count and invisible in the other's."""
    late = CAL[-1] + dt.timedelta(days=1)
    s = led(book, [fc("f", "mu_fq4", ["up"], ["down"],
                      marked=late.isoformat()),
                   fc("r", "mu_fq4", ["s1"], ["s2"], order=2)])["summary"]
    assert s["n_pending"] == 1 and s["n_scored"] == 0
    assert s["indirect"]["n_pending"] == 0 and s["indirect"]["n_scored"] == 1


def test_the_capital_gate_reads_the_direct_row_only(book):
    """N=30 was set for the claim somebody registered. The derived ring does
    not lend it a count."""
    s = led(book, [fc("f", "mu_fq4", ["up"], ["down"])]
            + [fc(f"r{i}", "mu_fq4", ["s1"], ["s2"], order=2,
                  marked=CAL[i].isoformat()) for i in range(5)])["summary"]
    assert s["horizons"]["5"]["n"] == 1
    assert s["capital_rule"] == "no capital decision below N=30"


def test_both_summaries_carry_the_capital_rule(book):
    s = led(book, [fc("r", "mu_fq4", ["s1"], ["s2"], order=2)])["summary"]
    assert s["indirect"]["capital_rule"] == s["capital_rule"]
    assert s["indirect"]["min_n"] == 30


def test_an_empty_ledger_still_has_both_halves(monkeypatch, tmp_path):
    monkeypatch.setenv("CHIP_MAP_PRICES", str(tmp_path))
    s = forecast.build([], DOC)["summary"]
    assert s["indirect"]["horizons"]["40"]["n"] == 0
    assert s["hz"] == ["5", "10", "20"]
    assert s["indirect"]["hz"] == ["5", "10", "20", "40"]


# -- the twin ----------------------------------------------------------------

B2 = {"mu_fq4": (["s1"], ["s2"]), "nvda_q3": ([], [])}


def test_a_twin_is_registered_for_every_direct_mark():
    out = answers.with_twins([fc("f", "mu_fq4", ["up"], ["down"])], B2)
    twin = [r for r in out if r.get("order") == 2][0]
    assert twin["id"] == "mu_fq4-2026-03-02-r2"
    assert (twin["win"], twin["lose"]) == (["s1"], ["s2"])
    assert twin["horizons"] == [5, 10, 20, 40]


def test_the_twin_is_created_once(book):
    """Run the build twice, or three times, and there is still one r2 row. The
    id is derived from the mark, so a second copy has nowhere to go."""
    once = answers.with_twins([fc("f", "mu_fq4", ["up"], ["down"])], B2)
    twice = answers.with_twins(once, B2)
    thrice = answers.with_twins(twice, B2)
    assert [r["id"] for r in twice] == [r["id"] for r in once]
    assert [r["id"] for r in thrice] == [r["id"] for r in once]
    assert sum(1 for r in thrice if r.get("order") == 2) == 1


def test_the_twin_is_dated_to_the_mark_not_to_today():
    """Dating it to the day the code shipped would turn a forward test into a
    row that was registered after the fact."""
    out = answers.with_twins(
        [fc("f", "mu_fq4", ["up"], ["down"], marked="2026-03-02T21:05:00Z")],
        B2)
    twin = [r for r in out if r.get("order") == 2][0]
    assert twin["marked_at"] == "2026-03-02T21:05:00Z"
    assert twin["id"].endswith("2026-03-02-r2")


def test_no_twin_where_there_is_no_second_ring():
    """Most upstream questions have none. An empty basket is not a claim, and
    a forecast with nothing in it would score as a row of dashes."""
    out = answers.with_twins([fc("f", "nvda_q3", ["up"], ["down"])], B2)
    assert [r["id"] for r in out] == ["f"]


def test_a_hand_written_twin_is_left_alone():
    """If the marking task ever registers its own r2 row, that row is the
    registration. This does not overwrite it."""
    mine = fc("mu_fq4-2026-03-02-r2", "mu_fq4", ["s1"], ["s2"], order=2)
    mine["direction"] = -1
    out = answers.with_twins([fc("f", "mu_fq4", ["up"], ["down"]), mine], B2)
    twins = [r for r in out if r.get("order") == 2]
    assert len(twins) == 1 and twins[0]["direction"] == -1


def test_the_twin_inherits_the_direction_of_the_mark():
    out = answers.with_twins(
        [fc("f", "mu_fq4", ["up"], ["down"], direction=-1)], B2)
    assert [r for r in out if r.get("order") == 2][0]["direction"] == -1


# -- an r2 record is pre-registered too --------------------------------------

IDS = {"mu_fq4", "nvda_q3"}
B1 = {"mu_fq4": (["up"], ["down"]), "nvda_q3": (["up"], [])}


def test_an_r2_basket_that_drifted_from_the_map_is_refused():
    """The direct baskets are typed into watch.json by hand; these are a pure
    function of watch.json and map.json. Either way a row whose hypothesis
    moved after the event is not a forecast."""
    bad = fc("r", "mu_fq4", ["s1", "up"], ["s2"], order=2)
    good, log = answers.collect_forecasts([bad], IDS, B1, B2)
    assert good == []
    assert "do not match the ones registered" in log[0]
    assert "supply edges" in log[0]


def test_the_scored_r2_baskets_are_the_derived_ones_not_the_received_copy():
    good, _ = answers.collect_forecasts(
        [fc("r", "mu_fq4", ["s1"], ["s2"], order=2)], IDS, B1, B2)
    assert (good[0]["win"], good[0]["lose"]) == (["s1"], ["s2"])


def test_an_r2_record_must_carry_the_four_horizons():
    bad = fc("r", "mu_fq4", ["s1"], ["s2"], order=2)
    bad["horizons"] = [5, 10, 20]
    good, log = answers.collect_forecasts([bad], IDS, B1, B2)
    assert good == [] and "[5, 10, 20, 40]" in log[0]


def test_a_direct_record_may_not_claim_the_fourth_horizon():
    bad = fc("f", "mu_fq4", ["up"], ["down"])
    bad["horizons"] = [5, 10, 20, 40]
    good, log = answers.collect_forecasts([bad], IDS, B1, B2)
    assert good == [] and "[5, 10, 20]" in log[0]


@pytest.mark.parametrize("order", [0, 3, "1", None])
def test_an_order_that_is_not_one_or_two_is_refused(order):
    bad = fc("r", "mu_fq4", ["up"], ["down"])
    bad["order"] = order
    good, log = answers.collect_forecasts([bad], IDS, B1, B2)
    assert good == [] and "order" in log[0]


def test_the_derived_baskets_come_from_the_committed_map():
    """Not from anything this process computed on the fly: the same function
    the page draws with, over the same two files in git."""
    got = answers.derived_baskets()
    doc = __import__("chains.mapfile", fromlist=["load"]).load()
    import json

    from chains.paths import watch_path
    rows = json.loads(watch_path().read_text(encoding="utf-8"))
    by_tk = {str(n.get("ticker", "")).upper(): n["id"] for n in doc["nodes"]
             if n.get("ticker")}
    for r in rows:
        want = rings.second_ring(doc, r.get("win") or [], r.get("lose") or [],
                                 by_tk.get(str(r.get("tk") or "").upper()))
        assert got[r["id"]] == (want["win2"], want["lose2"])
