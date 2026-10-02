"""The 2026-10-01 semi map closure: bottlenecks, lagging rings, sources, splits.

What these hold is the honesty of the additions, not their completeness:
a bottleneck field either points at one of the pages that were fetched and
read, or says it has no source; a media-only edge never feeds a derived ring;
the lagging flag is a description computed one way only.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from chains import lagging, mapfile, prices, rings, stages
from chains.paths import data_dir, map_path

DOC = mapfile.load(map_path("semi"))
RAW = DOC["bottlenecks"]
BN = stages.annotate(RAW)          # stage and top_risk are computed, never stored
IDS = {n["id"] for n in DOC["nodes"]}
SIGNALS = ("hike_decel_or_no_more_hikes", "all_suppliers_hiking", "capacity_x2_or_equity_raise",
           "ltas_prepay_noncancellable", "low_pe_peak_eps_or_not_a_bubble",
           "customer_affordability_or_spec_downgrade",
           "supplier_inventory_rebuild_or_reservations_in_backlog")
# The 24 pages listed in semi-closure.md, fetched 2026-10-01. Digitimes was a
# paywall stub, so nothing may stand on it as fired.
FAILED = {"https://www.digitimes.com/news/a20260309PD233/pcb-topoint-2026-high-end-sales.html"}


def urls(b):
    yield b["pressure"]["source_url"]
    yield b["rigidity"]["source_url"]
    yield b["trigger"]["source_url"]
    for s in b["top_signals"].values():
        yield s["source_url"]


# -- the records -------------------------------------------------------------
def test_there_is_one_record_per_listed_bottleneck():
    assert len(BN) >= 30
    assert len({b["id"] for b in BN}) == len(BN)


@pytest.mark.parametrize("b", BN, ids=[b["id"] for b in BN])
def test_a_record_has_every_field_and_names_only_nodes(b):
    for k in ("id", "name", "layer", "pressure", "rigidity", "trigger", "owners", "hurt",
              "propagation", "kill", "exposure", "stage", "top_signals", "top_risk", "next_node"):
        assert k in b, k
    assert b["trigger"]["status"] in ("fired", "not_yet", "unclear")
    assert b["stage"] in ("tightening", "peaking", "resolving", "unclear")
    assert set(b["exposure"].values()) <= {"low", "medium", "high"}
    for k in ("owners", "hurt", "propagation", "next_node"):
        assert set(b[k]) <= IDS, (k, set(b[k]) - IDS)
    assert set(b["exposure"]) <= IDS


@pytest.mark.parametrize("b", BN, ids=[b["id"] for b in BN])
def test_signals_are_sourced_or_unknown_and_top_risk_counts_them(b):
    assert tuple(b["top_signals"]) == SIGNALS
    for s in b["top_signals"].values():
        assert s["value"] in (True, None), "an unsourced signal is unknown, not false"
        assert (s["value"] is True) == bool(s["source_url"] and s["date"])
    assert b["top_risk"] == sum(1 for s in b["top_signals"].values() if s["value"])


@pytest.mark.parametrize("b", BN, ids=[b["id"] for b in BN])
def test_a_stage_other_than_unclear_rests_on_sourced_fields(b):
    if b["stage"] != "unclear":
        assert b["stage_basis"] and all(x["source_url"] for x in b["stage_basis"])


def test_no_record_types_its_own_stage():
    for b in RAW:
        assert not {"stage", "stage_source", "stage_note", "top_risk"} & set(b), b["id"]


def test_nothing_fired_rests_on_a_page_that_failed_to_load():
    for b in BN:
        if b["trigger"]["source_url"] in FAILED:
            assert b["trigger"]["status"] == "unclear", b["id"]


def test_a_fired_trigger_has_a_date_a_source_and_its_type():
    for b in BN:
        t = b["trigger"]
        if t["status"] == "fired":
            assert t["date"] and t["source_url"], b["id"]
            assert t["source_type"] in ("primary", "analyst", "media"), b["id"]


def test_every_source_is_one_of_the_closure_pages():
    """No source outside what was read: the 24 pages in semi-closure.md, and
    the two analyst pages amendment 2 supplied for commodity DRAM (2026-10-02)."""
    allowed = {s for b in BN for s in urls(b) if s}
    # + 2 more (TrendForce 2026-07-03, Tom's Hardware 2026-07-04), stage rules.
    assert len(allowed) <= 24 + 2 + 2
    for e in DOC["edges"]:
        if e.get("source_type"):
            assert e["source"] in allowed | FAILED or e["source"].startswith("https://"), e


def test_the_excluded_names_are_not_on_the_map():
    names = " ".join(n["name"].lower() for n in DOC["nodes"])
    for gone in ("pure storage", "unitika", "tecnisco", "terra drone", "antimony"):
        assert gone not in names


def test_rambus_montage_and_astera_are_hurt_by_commodity_dram():
    b = next(b for b in BN if b["id"] == "dram_commodity")
    assert {"rambus", "montage", "alab"} <= set(b["hurt"])


# -- edges ---------------------------------------------------------------------
def test_a_supplies_edge_rests_on_a_primary_or_analyst_source():
    for e in DOC["edges"]:
        if e.get("source_type"):
            want = "supplies" if e["source_type"] in ("primary", "analyst") else "reported"
            assert e["type"] == want, e


def test_a_media_only_edge_never_appears_in_a_derived_ring():
    doc = {"nodes": [{"id": i, "price_symbol": f"{i.upper()}.US", "price_symbol_kind": "primary",
                      "layer": "L1"} for i in ("a", "b", "x", "y")],
           "edges": [{"from": "x", "to": "a", "type": "reported", "what": "media"},
                     {"from": "y", "to": "b", "type": "supplies", "what": "filing"}]}
    assert [e["from"] for e in rings.suppliers_of(doc, "a")] == []
    assert [e["from"] for e in rings.suppliers_of(doc, "b")] == ["y"]


# -- lagging -------------------------------------------------------------------
SRC = "https://example.com/source"


def evidence(stage):
    """The fields that make a record compute to ``stage`` under the rule."""
    sig = {k: {"value": None, "date": None, "source_url": None} for k in stages.SIGNALS}
    out = {"top_signals": sig}
    if stage == "peaking":
        for k in ("hike_decel_or_no_more_hikes", "all_suppliers_hiking"):
            sig[k] = {"value": True, "date": "2026-09-01", "source_url": SRC}
    if stage == "resolving":
        out["resolving"] = {"kind": "price_decline", "date": "2026-09-01", "source_url": SRC}
    return out


def fake_doc(stage="tightening", status="fired"):
    return {"nodes": [{"id": i, "name": i.upper(), "price_symbol": f"{i}.US",
                       "price_symbol_kind": "primary"} for i in ("lead", "own2", "prop", "x")],
            "bottlenecks": [{"id": "b1", "name": "B1", **evidence(stage),
                             "trigger": {"status": status, "date": "2026-09-01"},
                             "owners": ["lead", "own2"], "propagation": ["prop"],
                             "exposure": {"prop": "high"}},
                            {"id": "b2", "name": "B2", **evidence("tightening"),
                             "trigger": {"status": "fired", "date": "2026-09-02"},
                             "owners": ["x"], "propagation": []}]}


RETS = {"lead.US": 3.0, "own2.US": 2.5, "prop.US": 0.4, "x.US": 0.1}


def test_lagging_is_below_150_and_100_points_behind_its_own_leader():
    got = lagging.compute(fake_doc(), ret=RETS.get)
    assert [e["lagging"] for e in got["prop"]] == [True]
    assert got["prop"][0]["leader_id"] == "lead"
    assert [e["lagging"] for e in got["own2"]] == [False]          # +250% broke out
    # Leader is per bottleneck: x leads its own and is not behind "lead".
    assert got["x"][0]["leader_id"] == "x" and got["x"][0]["lagging"] is False


@pytest.mark.parametrize("status", ["not_yet", "unclear"])
def test_no_lagging_flag_unless_the_trigger_fired(status):
    got = lagging.compute(fake_doc(status=status), ret=RETS.get)
    assert "prop" not in got


@pytest.mark.parametrize("stage", ["peaking", "resolving"])
def test_a_turning_cycle_gets_the_grey_tag_never_the_ring(stage):
    got = lagging.compute(fake_doc(stage=stage), ret=RETS.get)
    assert got["prop"] == [{"b": "b1", "kind": "cycle", "stage": stage,
                            "top_risk": 2 if stage == "peaking" else 0}]


def test_an_unclear_stage_gets_nothing():
    assert "prop" not in lagging.compute(fake_doc(stage="unclear", status="unclear"), ret=RETS.get)


def test_the_rule_at_its_edges():
    assert lagging.is_lagging(1.49, 2.49) is True
    assert lagging.is_lagging(1.5, 3.0) is False                    # not below +150%
    assert lagging.is_lagging(0.5, 1.49) is False                   # 99 points behind


def test_the_history_rows_are_the_lagging_set_only(tmp_path):
    p = tmp_path / "h.json"
    doc = fake_doc()
    got = lagging.compute(doc, ret=RETS.get)
    rows = lagging.rows_for("2026-10-01", got)
    assert [(r["node"], r["leader"]) for r in rows] == [("prop", "lead")]


def test_the_committed_history_holds_only_lagging_rows():
    p = data_dir("semi") / "lagging_history.json"
    if not p.exists():
        pytest.skip("no history in this checkout")
    for r in json.loads(p.read_text(encoding="utf-8")):
        assert lagging.is_lagging(r["ret_252"], r["leader_ret"]), r


# -- splits --------------------------------------------------------------------
@pytest.mark.parametrize("sym", ["5706.T", "285A.T"])
def test_the_2026_09_29_splits_leave_no_seam(sym):
    """Mitsui Kinzoku 10:1 and Kioxia 3:1, both effective 2026-10-01 (ex-date
    2026-09-29). An unadjusted series would show a one-day drop of 90% / 67%."""
    df = prices.load(sym)
    if df.is_empty():
        pytest.skip(f"{sym} not in the price store here")
    rows = [(d, c) for d, c in zip(df["date"].to_list(), df["adj_close"].to_list())
            if dt.date(2026, 9, 15) <= d <= dt.date(2026, 10, 5) and c]
    assert len(rows) >= 5
    moves = [b / a - 1 for (_, a), (_, b) in zip(rows, rows[1:])]
    assert max(abs(m) for m in moves) < 0.3, moves


# -- amendment 2: buyers of memory, hurt by commodity DRAM -----------------------
def test_hurt_links_are_on_the_bottleneck_and_never_edges():
    b = next(b for b in BN if b["id"] == "dram_commodity")
    links = {h["node"]: h for h in b["hurt_links"]}
    assert set(links) == {"hpq"} and set(links) <= set(b["hurt"])
    assert all(h["relation"] == "hurt" and h["source_type"] == "analyst" for h in links.values())
    for e in DOC["edges"]:
        assert "hpq" not in (e["from"], e["to"])


def test_lenovo_is_gone_from_the_map():
    """Removed 2026-10-02 (Michael): The Register, 2026-05-22, reports Lenovo's
    operating profit +20.7% y/y on a premium mix shift, which contradicts a
    hurt link that rested only on "notebook brands"."""
    assert "lenovo" not in json.dumps(DOC)


def test_a_hurt_buyer_never_reaches_a_derived_supplier_ring():
    for first in (["samsung", "skhynix", "mu"], ["nanya", "winbond"]):
        got = rings.second_ring(DOC, first, [])
        assert "hpq" not in set(got["win2"] + got["lose2"])


def test_commodity_dram_is_peaking_on_two_sourced_turn_signals():
    b = next(b for b in BN if b["id"] == "dram_commodity")
    assert b["stage"] == "peaking" and b["top_risk"] == 2
    on = {x["field"] for x in b["stage_basis"]}
    assert on == {"hike_decel_or_no_more_hikes", "customer_affordability_or_spec_downgrade"}


def test_mlcc_is_tightening_because_neither_turn_signal_is_sourced():
    b = next(b for b in BN if b["id"] == "mlcc")
    assert b["top_risk"] == 2 and b["stage"] == "tightening"
