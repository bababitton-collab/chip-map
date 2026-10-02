# Bottleneck stage rules

A bottleneck's stage is **computed from its sourced fields, never typed by hand.**
The code is `chains/stages.py`. Every reader calls it: the lagging ring
(`chains/lagging.py`), the bottleneck card (through the focus data in
`chains/live_snapshot.py`), and the ring candidates (`tools/ring2_candidates.py`).
`data/<domain>/map.json` carries the evidence; it holds no `stage` or `top_risk`
field of its own.

Adopted 2026-10-02 (Michael), applied to every bottleneck the same way.

## The rule, in order

| Stage | Holds when |
|---|---|
| **resolving** | The record's `resolving` field carries a sourced price decline (`kind: price_decline`) or a sourced closing of the capacity gap (`kind: gap_closing`), with a `source_url`. |
| **peaking** | `top_risk` ≥ 2 **and** at least one turn signal is true with a fetched source: `hike_decel_or_no_more_hikes` or `customer_affordability_or_spec_downgrade`. |
| **tightening** | The trigger has `status: fired`, and neither of the above holds. |
| **unclear** | Anything else. |

Resolving is checked first: a sourced price decline is a later phase than a peak,
so a bottleneck showing both is past its peak.

## top_risk

The count of the seven top signals that are `true` **and** carry a `source_url`
(lifecycle rule R3 in the bottleneck method):

1. `hike_decel_or_no_more_hikes`
2. `all_suppliers_hiking`
3. `capacity_x2_or_equity_raise`
4. `ltas_prepay_noncancellable`
5. `low_pe_peak_eps_or_not_a_bubble`
6. `customer_affordability_or_spec_downgrade`
7. `supplier_inventory_rebuild_or_reservations_in_backlog`

An unsourced signal is `null` (unknown), never `false`, and never counts.

## What the stage changes

- **tightening:** the lagging-ring highlight applies (fired trigger, price not
  followed). It is a description, never a forecast, and never scored.
- **peaking / resolving:** no lagging ring. Members get a grey "cycle peaking/easing"
  tag with `top_risk`. In ring candidates, owners become candidate *down* legs, and
  `next_node` becomes a candidate *up* leg.
- **unclear:** nothing is drawn or proposed from the stage.
