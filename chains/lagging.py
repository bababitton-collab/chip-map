"""Which rings have not moved yet: a description, never a forecast.

    python -m chains.lagging --snapshot     # append today's set to the history

A bottleneck in data/<domain>/map.json ("bottlenecks") whose physical trigger
has FIRED and whose stage is TIGHTENING says the scarce input is already
repricing. Its owners and its propagation nodes are the companies that would
capture that. Some of them have moved a lot; some have not.

    ret_252    the node's own 252-session return, from the repo price store
    leader     the owner of that bottleneck with the highest ret_252
    lagging    ret_252 < +150%  and  leader_ret - ret_252 >= 100 points

That is all it says. It is not scored, it carries no hit rate, and it appears
on the node card and as a thin ring on the map and nowhere else. The history
file exists so it can be forward-tested later, by a dated test written in
advance -- not so it can be read backwards now.

A bottleneck whose stage is peaking or resolving gets no lagging flag at all:
a laggard in a cycle that is turning is not "behind", it may simply be right.
Its members carry a grey "cycle peaking/easing" tag with the top-risk count
instead. A stage that could not be sourced ("unclear") gets nothing.
"""
from __future__ import annotations

import datetime as dt
import json

SESSIONS = 252
MAX_RET = 1.5          # +150%: a node above this has already broken out
MIN_GAP = 1.0          # 100 points behind its bottleneck's leader
TIGHT = "tightening"
TURNING = ("peaking", "resolving")


def ret_252(symbol: str | None) -> float | None:
    """Return over the last 252 sessions of the symbol's own adjusted closes."""
    if not symbol:
        return None
    from chains import prices
    df = prices.load(symbol)
    closes = [c for c in df["adj_close"].to_list() if c]
    if len(closes) <= SESSIONS:
        return None
    return closes[-1] / closes[-1 - SESSIONS] - 1


def is_lagging(ret: float | None, leader_ret: float | None) -> bool:
    return (ret is not None and leader_ret is not None
            and ret < MAX_RET and (leader_ret - ret) >= MIN_GAP)


def compute(doc: dict, ret=ret_252) -> dict[str, list[dict]]:
    """{node_id: [one entry per bottleneck it is a member of]}."""
    sym = {n["id"]: n.get("price_symbol") for n in doc.get("nodes", [])
           if n.get("price_symbol_kind") != "none"}
    name = {n["id"]: n["name"] for n in doc.get("nodes", [])}
    out: dict[str, list[dict]] = {}
    for b in doc.get("bottlenecks", []):
        trig = b.get("trigger") or {}
        if trig.get("status") != "fired":
            continue
        members = list(dict.fromkeys(list(b.get("owners") or [])
                                     + list(b.get("propagation") or [])))
        stage = b.get("stage")
        if stage in TURNING:
            for i in members:
                out.setdefault(i, []).append({
                    "b": b["id"], "bname": b["name"], "kind": "cycle",
                    "stage": stage, "top_risk": b.get("top_risk", 0)})
            continue
        if stage != TIGHT:
            continue
        rets = {i: ret(sym.get(i)) for i in members}
        owners = [i for i in b.get("owners") or [] if rets.get(i) is not None]
        if not owners:
            continue
        lead = max(owners, key=lambda i: rets[i])
        for i in members:
            r = rets.get(i)
            if r is None:
                continue
            out.setdefault(i, []).append({
                "b": b["id"], "bname": b["name"], "kind": "lag",
                "fired": trig.get("date"), "ret": round(r, 4),
                "leader": name.get(lead, lead), "leader_id": lead,
                "leader_ret": round(rets[lead], 4),
                "exposure": (b.get("exposure") or {}).get(i),
                "lagging": is_lagging(r, rets[lead])})
    return out


def rows_for(day: str, got: dict[str, list[dict]]) -> list[dict]:
    """The lagging set, flat, as the history keeps it."""
    return [{"date": day, "node": i, "bottleneck": e["b"], "ret_252": e["ret"],
             "leader": e["leader_id"], "leader_ret": e["leader_ret"]}
            for i, es in sorted(got.items()) for e in es
            if e["kind"] == "lag" and e["lagging"]]


def snapshot(doc: dict, day: str, path) -> int:
    """Append today's set, replacing any rows already written for today."""
    hist = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    hist = [r for r in hist if r["date"] != day] + rows_for(day, compute(doc))
    path.write_text(json.dumps(hist, indent=1) + "\n", encoding="utf-8", newline="\n")
    return sum(1 for r in hist if r["date"] == day)


def main(argv: list[str] | None = None) -> int:
    import argparse

    from chains import mapfile
    from chains.paths import data_dir
    ap = argparse.ArgumentParser(prog="python -m chains.lagging")
    ap.add_argument("--snapshot", action="store_true", required=True)
    a = ap.parse_args(argv)
    doc = mapfile.load()
    if not doc.get("bottlenecks"):
        print("lagging: this map declares no bottlenecks; nothing to record")
        return 0
    day = dt.datetime.now(dt.timezone.utc).date().isoformat()
    n = snapshot(doc, day, data_dir() / "lagging_history.json")
    print(f"lagging: {n} node(s) lagging on {day}; descriptive, not scored")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
