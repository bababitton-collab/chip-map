"""Event catalysts, contract v3: a standing rule per bottleneck, an append-only
event log, and a forecast minted from the moment an event was captured.

A company report is one catalyst among many: a price letter, an allocation, a
prepayment, a capacity release or an export rule can move a bottleneck as
much. So instead of a dated question per event, each bottleneck carries a RULE,
hashed and committed before any event it will score:

  tightening event   up = owners + next_node        down = hurt
  top / resolving    up = former customers (hurt)   down = owners
                          + next_node

The baskets are fixed when the rule is committed, from the bottleneck record
as it stands then, and the hash covers them. Expected sign is +1: the up basket
beats the down basket. With one side empty, that side is the map's
equal-weight (EW of the rule's frozen universe, basket members excluded).

Entry is the first close after captured_at, in each member's own market.
Horizon 20 sessions is primary; 5, 10 and 40 are diagnostics.

Anti-cherry-picking (spec 2026-10-01):
  * every qualifying event is logged, boring ones too; never deleted. A later
    line {"amends": id, ...} marks it ineligible, with a reason.
  * eligible = dated, sourced primary or analyst, captured within a day of the
    event date. Media-only events are logged and not scored.
  * events on one bottleneck within 10 sessions cluster: the first mints, the
    rest attach to it.
  * v3 is tallied by itself, never pooled with report questions, and split by
    event type and by the bottleneck's stage at capture.

price_jump is an alarm, not a forecast: a priced map node moving >= 4 sigma in
a session, or >= +25% over 5 sessions, is logged with a 48-hour deadline to be
classified as propagation, new bottleneck or one-off.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from pathlib import Path

CONTRACT = "v3"
TIGHTENING = ("price_letter_up", "allocation", "lta_signed", "prepayment", "large_po",
              "strategic_investment", "design_win", "capacity_cut", "outage",
              "export_restriction", "demand_raise")
RESOLVING = ("no_more_hikes", "price_cut", "capacity_x2", "new_entrant_qualified",
             "export_relief", "double_order_evidence", "reservation_conversion_drop")
HORIZONS = {"primary": 20, "diagnostic": [5, 10, 40]}
CLUSTER_SESSIONS = 10
SCORED_SOURCES = ("primary", "analyst")
CAPTURE_DAYS = 1
ENTRY = "first close after captured_at, in each member's own market"
BENCHMARK = "equal-weight of the rule's frozen universe, basket members excluded"
ELIGIBILITY = ("dated; source_type primary or analyst with a source_url; captured within "
               f"{CAPTURE_DAYS} day of the event date. Media-only: logged, not scored.")
JUMP_SIGMA, JUMP_5D, JUMP_LOOKBACK = 4.0, 0.25, 250
CLASSES = ("propagation", "new_bottleneck", "one_off")


def class_of(event_type: str) -> str:
    if event_type in TIGHTENING:
        return "tightening"
    if event_type in RESOLVING:
        return "resolving"
    raise ValueError(f"unknown event type {event_type!r}")


# ------------------------------------------------------------------ rules
def _basket(ids, symbol_of: dict) -> dict:
    return {i: symbol_of[i] for i in dict.fromkeys(ids) if i in symbol_of}


def rule(b: dict, symbol_of: dict, universe_sha: str) -> dict:
    """The standing rule for one bottleneck, without its hash."""
    nxt = list(b.get("next_node") or [])
    sides = {"tightening": (list(b.get("owners") or []) + nxt, list(b.get("hurt") or [])),
             "resolving": (list(b.get("hurt") or []) + nxt, list(b.get("owners") or []))}
    dm = {}
    for cls, (up, down) in sides.items():
        both = set(up) & set(down)       # a node on both sides cancels; it is left out
        u = _basket([i for i in up if i not in both], symbol_of)
        d = _basket([i for i in down if i not in both], symbol_of)
        dm[cls] = {"event_types": list(TIGHTENING if cls == "tightening" else RESOLVING),
                   "up": u, "down": d, "sign": 1, "scoreable": bool(u or d)}
    return {"contract": CONTRACT, "bottleneck_id": b["id"],
            "event_types": list(TIGHTENING + RESOLVING), "direction_map": dm,
            "entry": ENTRY, "horizons": HORIZONS, "benchmark": BENCHMARK,
            "ew_universe_sha256": universe_sha, "eligibility": ELIGIBILITY,
            "cluster_sessions": CLUSTER_SESSIONS}


def canonical(r: dict) -> bytes:
    body = {k: v for k, v in r.items() if k != "sha256"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def digest(r: dict) -> str:
    return hashlib.sha256(canonical(r)).hexdigest()


def build_rules(doc: dict, today: str, universe: dict | None = None) -> dict:
    """Rules for every bottleneck. ``universe``: the frozen one, once rules
    exist, so a node added to the map later does not re-hash them."""
    from chains import ew_universe
    from chains.preregister import priced_symbols
    symbol_of = {n["id"]: n["price_symbol"] for n in doc.get("nodes", [])
                 if n.get("price_symbol") and n.get("price_symbol_kind") != "none"}
    uni = universe or ew_universe.fingerprint(priced_symbols(doc))
    rules = []
    for b in doc.get("bottlenecks") or []:
        r = rule(b, symbol_of, uni["sha256"])
        rules.append({**r, "sha256": digest(r)})
    return {"contract": CONTRACT, "written": today, "ew_universe": uni, "rules": rules}


def rules_path(dom: str | None = None) -> Path:
    from chains.paths import data_dir
    return data_dir(dom) / "event_rules.json"


def load_rules(dom: str | None = None) -> dict:
    p = rules_path(dom)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"rules": []}


def rule_problems(doc_rules: dict) -> list[str]:
    """A stored hash that no longer matches its rule, or a universe that moved."""
    out = []
    uni = doc_rules.get("ew_universe") or {}
    if doc_rules.get("rules"):
        from chains import ew_universe
        if ew_universe.fingerprint(uni.get("symbols") or [])["sha256"] != uni.get("sha256"):
            out.append("event_rules: frozen universe does not hash to its sha256")
    for r in doc_rules.get("rules", []):
        if digest(r) != r.get("sha256"):
            out.append(f"event_rules: {r['bottleneck_id']} does not hash to its sha256")
        if r.get("ew_universe_sha256") != uni.get("sha256"):
            out.append(f"event_rules: {r['bottleneck_id']} names another universe")
    return out


def merge_rules(old: dict, new: dict) -> tuple[dict, list[str]]:
    """Committed rules never change; a bottleneck without a rule gets one.
    A rule whose content would change is refused and named."""
    if not old.get("rules"):
        return new, []
    have = {r["bottleneck_id"]: r for r in old["rules"]}
    changed = [r["bottleneck_id"] for r in new["rules"]
               if r["bottleneck_id"] in have and r["sha256"] != have[r["bottleneck_id"]]["sha256"]]
    added = [r for r in new["rules"] if r["bottleneck_id"] not in have]
    return {**old, "rules": old["rules"] + added}, changed


def add_rules(old: dict, doc: dict, ids: list[str], today: str) -> tuple[dict, list[dict]]:
    """Append rules for ``ids``, never touching a committed entry.

    Each new rule also names what confirms it (the bottleneck's trigger as
    recorded) and what kills it (its kill criteria), and both are hashed. A
    bottleneck that already has a committed rule gets a second, later entry
    that names the one it supersedes; lookups by bottleneck take the latest.
    The frozen universe of the file is reused; a file with none freezes the
    map's priced nodes now.
    """
    from chains import ew_universe
    from chains.preregister import priced_symbols
    uni = old.get("ew_universe") or ew_universe.fingerprint(priced_symbols(doc))
    symbol_of = {n["id"]: n["price_symbol"] for n in doc.get("nodes", [])
                 if n.get("price_symbol") and n.get("price_symbol_kind") != "none"}
    by = {b["id"]: b for b in doc.get("bottlenecks") or []}
    last = {r["bottleneck_id"]: r for r in old.get("rules", [])}
    added = []
    for bid in ids:
        b = by[bid]
        t = b.get("trigger") or {}
        r = rule(b, symbol_of, uni["sha256"])
        r["confirming"] = {"status": t.get("status"), "date": t.get("date"), "what": t.get("what"),
                           "source_url": t.get("source_url")}
        r["kill"] = [k.get("criterion") for k in b.get("kill") or []]
        r["written"] = today
        if bid in last:
            r["supersedes"] = last[bid]["sha256"]
        added.append({**r, "sha256": digest(r)})
    return {"contract": CONTRACT, "written": old.get("written", today), "ew_universe": uni,
            "rules": list(old.get("rules", [])) + added}, added


def latest_rules(doc_rules: dict) -> dict:
    """{bottleneck id: its latest rule} (a superseding entry comes later in the file)."""
    return {r["bottleneck_id"]: r for r in doc_rules.get("rules", [])}


# ------------------------------------------------------------------ the log
def events_path(dom: str | None = None) -> Path:
    from chains.paths import data_dir
    return data_dir(dom) / "events.jsonl"


def alarms_path(dom: str | None = None) -> Path:
    """price_jump records. Written by the daily build, which never commits to
    main, so CI carries this file on the live branch (as lagging_history)."""
    from chains.paths import data_dir
    return data_dir(dom) / "alarms.jsonl"


def read_log(dom: str | None = None) -> list[dict]:
    """Alarms first, so an amendment in events.jsonl can classify one."""
    return read_lines(alarms_path(dom)) + read_lines(events_path(dom))


def read_lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def fold(lines: list[dict]) -> list[dict]:
    """Records with their amendments applied, in capture order. An amendment
    may add fields or set eligible/classification; it never removes a record."""
    by, order = {}, []
    for x in lines:
        if "amends" in x:
            if x["amends"] in by:
                rec = by[x["amends"]]
                rec.update({k: v for k, v in x.items() if k not in ("amends", "id")})
                rec.setdefault("amended", []).append(x.get("at"))
            continue
        by[x["id"]] = dict(x)
        order.append(x["id"])
    return [by[i] for i in order]


def append(path: Path, rec: dict) -> None:
    ids = {x.get("id") for x in read_lines(path)}
    if "amends" not in rec and rec["id"] in ids:
        raise ValueError(f"{rec['id']} is already in the log")
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")


def append_only_problems(committed: str, current: str) -> list[str]:
    """The committed log must be a prefix of the working one, line for line."""
    a, b = committed.splitlines(), current.splitlines()
    if b[:len(a)] != a:
        return ["events.jsonl: a committed line was changed or removed (append-only)"]
    return []


def utc(ts: str) -> dt.datetime:
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def eligibility(ev: dict, rules: dict) -> tuple[bool, str]:
    r = rules.get(ev.get("bottleneck"))
    if r is None:
        return False, "no committed rule for this bottleneck"
    try:
        cls = class_of(ev["event_type"])
    except ValueError as e:
        return False, str(e)
    if not r["direction_map"][cls]["scoreable"]:
        return False, f"rule has no priced {cls} basket"
    if not ev.get("event_date"):
        return False, "undated"
    if not ev.get("source_url"):
        return False, "no source"
    if ev.get("source_type") not in SCORED_SOURCES:
        return False, f"{ev.get('source_type') or 'unknown'} source: logged, not scored"
    late = (utc(ev["captured_at"]).date() - dt.date.fromisoformat(ev["event_date"])).days
    if late > CAPTURE_DAYS:
        return False, f"captured {late} days after the event (limit {CAPTURE_DAYS})"
    if utc(ev["captured_at"]).date() < dt.date.fromisoformat(ev["event_date"]):
        return False, "captured before its own date"
    return True, ""


def capture(*, bottleneck: str, event_type: str, event_date: str, what: str,
            source_url: str | None, source_type: str | None, captured_at: str,
            doc: dict, rules_doc: dict) -> dict:
    """One event record, eligibility decided now and written with it."""
    from chains import stages
    rules = {r["bottleneck_id"]: r for r in rules_doc.get("rules", [])}
    b = next((x for x in doc.get("bottlenecks") or [] if x["id"] == bottleneck), None)
    ev = {"kind": "event", "id": f"ev-{event_date}-{bottleneck}-{event_type}",
          "bottleneck": bottleneck, "event_type": event_type, "event_date": event_date,
          "what": what, "source_url": source_url, "source_type": source_type,
          "captured_at": captured_at,
          "stage_at_capture": stages.stage(b)[0] if b else None,
          "rule_sha256": (rules.get(bottleneck) or {}).get("sha256")}
    ok, why = eligibility(ev, rules)
    ev["eligible"], ev["reason"] = ok, why
    return ev


# ------------------------------------------------------------------ minting
def _calendar(r: dict) -> str:
    """The symbol whose sessions count the 10-session cluster window."""
    for cls in ("tightening", "resolving"):
        for side in ("up", "down"):
            for s in r["direction_map"][cls][side].values():
                return s
    return ""


def mint(events: list[dict], rules_doc: dict, line) -> list[dict]:
    """A forecast per eligible, unclustered event; clustered ones attach.
    ``line(symbol)`` gives a chains.sessions.Line (injected for tests)."""
    rules = {r["bottleneck_id"]: r for r in rules_doc.get("rules", [])}
    out, last = [], {}
    for ev in events:
        if ev.get("kind") != "event" or not ev.get("eligible"):
            continue
        r = rules[ev["bottleneck"]]
        ts = utc(ev["captured_at"]).timestamp()
        cal = line(_calendar(r))
        s0 = cal.session0(ts)
        head = last.get(ev["bottleneck"])
        if head and s0 - head["_s0"] < CLUSTER_SESSIONS:
            head["attached"].append(ev["id"])
            continue
        cls = class_of(ev["event_type"])
        dm = r["direction_map"][cls]
        f = {"event": ev["id"], "bottleneck": ev["bottleneck"], "event_type": ev["event_type"],
             "class": cls, "stage": ev.get("stage_at_capture"), "rule_sha256": r["sha256"],
             "captured_at": ev["captured_at"], "up": dm["up"], "down": dm["down"],
             "sign": dm["sign"], "attached": [], "_s0": s0,
             "entry_date": cal.dates[s0].isoformat() if s0 < len(cal.dates) else None}
        last[ev["bottleneck"]] = f
        out.append(f)
    for f in out:
        f.pop("_s0")
    return out


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def score(f: dict, universe: list[str], line) -> dict:
    """Signed excess per horizon: (up - EW) - (down - EW), an empty side read
    as EW itself. None while a horizon is not complete for every side."""
    ts = utc(f["captured_at"]).timestamp()
    basket = set(f["up"].values()) | set(f["down"].values())
    out = {}
    for h in sorted([HORIZONS["primary"]] + HORIZONS["diagnostic"]):
        def r(syms):
            return _mean(line(s).ret(ts, 1, h) for s in syms)
        ew = r([s for s in universe if s not in basket])
        up = r(f["up"].values()) if f["up"] else ew
        dn = r(f["down"].values()) if f["down"] else ew
        out[str(h)] = None if None in (ew, up, dn) else f["sign"] * (up - dn)
    return out


# ------------------------------------------------------------------ the alarm
def jump(closes: list[float]) -> dict | None:
    """The last session's move if it trips the alarm, else None."""
    if len(closes) < JUMP_LOOKBACK + 2:
        return None
    lr = [math.log(b / a) for a, b in zip(closes[-JUMP_LOOKBACK - 2:-1], closes[-JUMP_LOOKBACK - 1:])]
    hist, last = lr[:-1], lr[-1]
    mu = sum(hist) / len(hist)
    sd = math.sqrt(sum((x - mu) ** 2 for x in hist) / (len(hist) - 1))
    z = (last - mu) / sd if sd else 0.0
    r5 = closes[-1] / closes[-6] - 1
    if abs(z) >= JUMP_SIGMA or r5 >= JUMP_5D:
        return {"z": round(z, 2), "r1": round(math.exp(last) - 1, 4), "r5": round(r5, 4)}
    return None


def alarms(doc: dict, now: dt.datetime, log: list[dict], line) -> list[dict]:
    """price_jump records for today's movers, one per node per session."""
    seen = {x["id"] for x in log}
    out = []
    for n in doc.get("nodes", []):
        s = n.get("price_symbol")
        if not s or n.get("price_symbol_kind") == "none":
            continue
        ln = line(s)
        if not ln.closes:
            continue
        mv = jump(ln.closes)
        rid = f"pj-{n['id']}-{ln.dates[-1].isoformat()}"
        if mv and rid not in seen:
            out.append({"kind": "alarm", "id": rid, "event_type": "price_jump", "node": n["id"],
                        "symbol": s, "session": ln.dates[-1].isoformat(), "move": mv,
                        "captured_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "investigate_by": (now + dt.timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "classification": None})
    return out


# ------------------------------------------------------------------ the page
def display(dom: str | None = None, line=None) -> list[dict]:
    """What the bottleneck card shows: each event, its forecast and score."""
    from chains.sessions import Line
    line = line or Line
    rules_doc = load_rules(dom)
    log = fold(read_log(dom))
    if not log:
        return []
    cache = {}

    def ln(s):
        if s not in cache:
            cache[s] = line(s)
        return cache[s]
    minted = {f["event"]: f for f in mint(log, rules_doc, ln)}
    attached = {a: f["event"] for f in minted.values() for a in f["attached"]}
    uni = (rules_doc.get("ew_universe") or {}).get("symbols") or []
    out = []
    for x in log:
        row = {"id": x["id"], "kind": x["kind"], "type": x["event_type"]}
        if x["kind"] == "alarm":
            row.update(node=x["node"], date=x["session"], move=x["move"],
                       by=x["investigate_by"], cls=x.get("classification"))
        else:
            f = minted.get(x["id"])
            row.update(b=x["bottleneck"], date=x["event_date"], what=x["what"], src=x["source_url"],
                       st=x["source_type"], ok=x["eligible"], why=x.get("reason") or None,
                       cl=class_of(x["event_type"]), att=attached.get(x["id"]))
            if f:
                sc = score(f, uni, ln)
                row.update(entry=f["entry_date"], up=list(f["up"]), down=list(f["down"]),
                           h={k: None if v is None else round(v * 100, 2) for k, v in sc.items()})
        out.append(row)
    return out
