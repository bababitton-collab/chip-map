"""Contract v3: rules, eligibility, minting, clustering, scoring and the alarm."""
from __future__ import annotations

import datetime as dt

import pytest

from chains import events as E

B = {"id": "foil", "owners": ["own"], "hurt": ["cust"], "next_node": ["nxt"],
     "trigger": {"status": "fired", "date": "2026-08-01", "source_url": "u"}}
SYM = {"own": "OWN.US", "cust": "CUST.US", "nxt": "NXT.US", "other": "OTH.US"}


def rules_doc():
    r = E.rule(B, SYM, "u" * 64)
    return {"ew_universe": {"symbols": sorted(SYM.values())}, "rules": [{**r, "sha256": E.digest(r)}]}


class FakeLine:
    """Closes on consecutive US weekdays-as-days from 2026-08-03, one per day."""
    def __init__(self, closes):
        from chains.sessions import close_utc
        self.dates = [dt.date(2026, 8, 3) + dt.timedelta(days=i) for i in range(len(closes))]
        self.closes = list(closes)
        self.ts = [close_utc("US", d) for d in self.dates]

    def session0(self, ts):
        from bisect import bisect_right
        return bisect_right(self.ts, ts)

    def ret(self, ts, a, b):
        i0 = self.session0(ts)
        lo, hi = i0 + a - 1, i0 + b
        return None if lo < 0 or hi >= len(self.closes) else self.closes[hi] / self.closes[lo] - 1


def test_baskets_follow_the_class():
    dm = rules_doc()["rules"][0]["direction_map"]
    assert (list(dm["tightening"]["up"]), list(dm["tightening"]["down"])) == (["own", "nxt"], ["cust"])
    assert (list(dm["resolving"]["up"]), list(dm["resolving"]["down"])) == (["cust", "nxt"], ["own"])


def test_the_hash_covers_the_baskets():
    r = rules_doc()["rules"][0]
    moved = {**r, "direction_map": {**r["direction_map"],
                                    "resolving": {**r["direction_map"]["resolving"], "up": {"cust": "CUST.US"}}}}
    assert E.digest(moved) != r["sha256"] and E.rule_problems({"rules": [moved]})


def test_committed_rules_never_change():
    old = rules_doc()
    new = rules_doc()
    new["rules"][0] = {**new["rules"][0], "sha256": "x"}
    assert E.merge_rules(old, new)[1] == ["foil"]


def ev(**k):
    base = dict(bottleneck="foil", event_type="capacity_x2", event_date="2026-08-05", what="w",
                source_url="https://x", source_type="primary", captured_at="2026-08-05T12:00:00Z")
    base.update(k)
    rules = {r["bottleneck_id"]: r for r in rules_doc()["rules"]}
    ok, why = E.eligibility(base, rules)
    return {**base, "kind": "event", "id": f"e-{base['captured_at']}", "eligible": ok, "reason": why}


def test_eligibility():
    assert ev()["eligible"]
    assert "media" in ev(source_type="media")["reason"]
    assert "days after" in ev(captured_at="2026-08-09T00:00:00Z")["reason"]
    assert not ev(source_url=None)["eligible"]
    assert "no committed rule" in ev(bottleneck="nope")["reason"]


def test_entry_is_the_first_close_after_capture_and_clusters_attach():
    lines = {s: FakeLine([100] * 60) for s in SYM.values()}
    a = ev(captured_at="2026-08-05T12:00:00Z")                  # before the US close of 08-05
    b = ev(captured_at="2026-08-08T12:00:00Z", event_date="2026-08-08")   # 3 sessions later
    c = ev(captured_at="2026-08-20T23:00:00Z", event_date="2026-08-20")   # 15 sessions later
    fs = E.mint([a, b, c], rules_doc(), lines.__getitem__)
    assert [f["event"] for f in fs] == [a["id"], c["id"]]
    assert fs[0]["entry_date"] == "2026-08-05" and fs[0]["attached"] == [b["id"]]
    assert fs[1]["entry_date"] == "2026-08-21"


def test_score_is_up_minus_down_and_an_empty_side_is_ew():
    lines = {"OWN.US": FakeLine([100] * 3 + [90] * 60), "CUST.US": FakeLine([100] * 3 + [110] * 60),
             "NXT.US": FakeLine([100] * 3 + [130] * 60), "OTH.US": FakeLine([100] * 63)}
    f = E.mint([ev(captured_at="2026-08-04T12:00:00Z", event_date="2026-08-04")],
               rules_doc(), lines.__getitem__)[0]                # resolving: up cust+nxt, down own
    s = E.score(f, sorted(SYM.values()), lines.__getitem__)
    assert s["20"] == pytest.approx((0.10 + 0.30) / 2 - (-0.10))
    f2 = {**f, "down": {}}
    assert E.score(f2, sorted(SYM.values()), lines.__getitem__)["20"] == pytest.approx(0.20 - (-0.10 + 0.0) / 2)   # own leaves the basket, joins EW


def test_price_jump():
    flat = [100.0]
    for i in range(299):
        flat.append(flat[-1] * (1.01 if i % 2 else 0.99))
    assert E.jump(flat) is None
    assert E.jump(flat[:-5] + [flat[-6] * 1.06 ** k for k in range(1, 6)])["r5"] >= 0.25
    assert abs(E.jump(flat + [flat[-1] * 0.85])["z"]) >= 4


def test_log_is_append_only_and_amendments_fold(tmp_path):
    p = tmp_path / "events.jsonl"
    E.append(p, {"kind": "event", "id": "a", "eligible": True})
    with pytest.raises(ValueError):
        E.append(p, {"kind": "event", "id": "a"})
    first = p.read_text(encoding="utf-8")
    E.append(p, {"amends": "a", "at": "t", "eligible": False, "reason": "dup source"})
    assert E.fold(E.read_lines(p)) == [{"kind": "event", "id": "a", "eligible": False,
                                        "reason": "dup source", "at": "t", "amended": ["t"]}]
    assert not E.append_only_problems(first, p.read_text(encoding="utf-8"))
    assert E.append_only_problems(p.read_text(encoding="utf-8"), first)
