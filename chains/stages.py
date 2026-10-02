"""A bottleneck's lifecycle stage, computed from its sourced fields. Never typed.

The rule (docs/stage-rules.md), applied to every bottleneck the same way:

  resolving   a sourced price decline, or a sourced closing of the capacity
              gap (the record's "resolving" field)
  peaking     top_risk >= 2, AND one of the two turn signals is sourced:
              hike_decel_or_no_more_hikes or
              customer_affordability_or_spec_downgrade
  tightening  the trigger fired, and neither of the above holds
  unclear     anything else

Resolving is checked first: a sourced price decline is a later phase than a
peak, and a bottleneck showing both is past its peak. top_risk is the count of
the seven top signals that carry a source, so it is computed here too.
"""
from __future__ import annotations

SIGNALS = ("hike_decel_or_no_more_hikes", "all_suppliers_hiking", "capacity_x2_or_equity_raise",
           "ltas_prepay_noncancellable", "low_pe_peak_eps_or_not_a_bubble",
           "customer_affordability_or_spec_downgrade",
           "supplier_inventory_rebuild_or_reservations_in_backlog")
TURN = ("hike_decel_or_no_more_hikes", "customer_affordability_or_spec_downgrade")
RESOLVING_KINDS = ("price_decline", "gap_closing")
PEAK_AT = 2


def _on(sig: dict | None) -> bool:
    return bool(sig and sig.get("value") is True and sig.get("source_url"))


def top_risk(b: dict) -> int:
    return sum(1 for k in SIGNALS if _on((b.get("top_signals") or {}).get(k)))


def stage(b: dict) -> tuple[str, list[dict]]:
    """(stage, basis): the stage and the sourced fields it rests on."""
    sig = b.get("top_signals") or {}
    res = b.get("resolving") or {}
    if res.get("kind") in RESOLVING_KINDS and res.get("source_url"):
        return "resolving", [{"field": f"resolving.{res['kind']}", "date": res.get("date"),
                              "source_url": res["source_url"]}]
    turns = [k for k in TURN if _on(sig.get(k))]
    if top_risk(b) >= PEAK_AT and turns:
        return "peaking", [{"field": k, "date": sig[k].get("date"),
                            "source_url": sig[k]["source_url"]}
                           for k in SIGNALS if _on(sig.get(k))]
    t = b.get("trigger") or {}
    if t.get("status") == "fired":
        return "tightening", [{"field": "trigger", "date": t.get("date"),
                               "source_url": t.get("source_url")}]
    return "unclear", []


def annotate(bottlenecks: list[dict]) -> list[dict]:
    """Copies of the records with stage, stage_basis and top_risk filled in."""
    out = []
    for b in bottlenecks or []:
        st, basis = stage(b)
        out.append({**b, "stage": st, "stage_basis": basis, "top_risk": top_risk(b)})
    return out
