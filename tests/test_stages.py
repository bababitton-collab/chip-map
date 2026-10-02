"""The stage rule (docs/stage-rules.md), one test per branch."""
from __future__ import annotations

import pytest

from chains import stages

SRC = "https://example.com/src"


def rec(signals=(), trigger="fired", resolving=None):
    sig = {k: {"value": None, "date": None, "source_url": None} for k in stages.SIGNALS}
    for k in signals:
        sig[k] = {"value": True, "date": "2026-09-01", "source_url": SRC}
    out = {"top_signals": sig, "trigger": {"status": trigger, "date": "2026-09-01", "source_url": SRC}}
    if resolving:
        out["resolving"] = {"kind": resolving, "date": "2026-09-02", "source_url": SRC}
    return out


@pytest.mark.parametrize("kind", ["price_decline", "gap_closing"])
def test_resolving_needs_a_sourced_decline_or_gap_closing(kind):
    assert stages.stage(rec(resolving=kind))[0] == "resolving"


def test_resolving_without_a_source_does_not_count():
    r = rec()
    r["resolving"] = {"kind": "price_decline", "date": "2026-09-02", "source_url": None}
    assert stages.stage(r)[0] == "tightening"


def test_resolving_wins_over_peaking():
    r = rec(("hike_decel_or_no_more_hikes", "all_suppliers_hiking"), resolving="price_decline")
    assert stages.stage(r)[0] == "resolving"


@pytest.mark.parametrize("turn", stages.TURN)
def test_peaking_needs_top_risk_two_and_a_sourced_turn_signal(turn):
    assert stages.stage(rec((turn, "ltas_prepay_noncancellable")))[0] == "peaking"


def test_two_signals_without_a_turn_signal_is_not_peaking():
    assert stages.stage(rec(("all_suppliers_hiking", "ltas_prepay_noncancellable")))[0] == "tightening"


def test_one_turn_signal_alone_is_not_peaking():
    assert stages.stage(rec(("hike_decel_or_no_more_hikes",)))[0] == "tightening"


def test_an_unsourced_signal_never_counts():
    r = rec(("hike_decel_or_no_more_hikes",))
    r["top_signals"]["customer_affordability_or_spec_downgrade"] = {"value": True, "date": "2026-09-01",
                                                                    "source_url": None}
    assert stages.top_risk(r) == 1 and stages.stage(r)[0] == "tightening"


def test_tightening_needs_a_fired_trigger():
    assert stages.stage(rec())[0] == "tightening"


@pytest.mark.parametrize("trigger", ["not_yet", "unclear"])
def test_otherwise_unclear(trigger):
    assert stages.stage(rec(trigger=trigger)) == ("unclear", [])
    # a turn signal without top_risk 2 and without a fired trigger is still unclear
    assert stages.stage(rec(("hike_decel_or_no_more_hikes",), trigger=trigger))[0] == "unclear"


def test_annotate_fills_stage_basis_and_top_risk_without_touching_the_record():
    r = rec(("hike_decel_or_no_more_hikes", "all_suppliers_hiking"))
    got = stages.annotate([r])[0]
    assert (got["stage"], got["top_risk"]) == ("peaking", 2) and got["stage_basis"]
    assert "stage" not in r and "top_risk" not in r
