"""Second-ring candidates for every open, uncommitted question, for a person to
re-draft from. Nothing here is committed or scored.

    python tools/ring2_candidates.py [--day 2026-10-01] [--only semi/smsg_pre]

Two sources of candidates per question:

  edge        chains.rings.second_ring on the current map: suppliers of the
              first ring, minus anything serving both sides or the other
              side's layer (the mixed-exposure rule). Media-only "reported"
              edges never reach it.
  bottleneck  a map bottleneck that touches the first ring. Tightening and
              fired: the side that owns it gains its propagation nodes and
              the other side its hurt nodes. Peaking or resolving: its owners
              are candidate LOSE (the cycle is turning against them) and its
              next_node candidate WIN.

Every leg carries what stands behind it: the edge's source and source type,
the bottleneck's stage and top_risk, the node's exposure, and whether it is
lagging (chains/lagging.py). The draft basket from the ring2-recommit branch
is shown beside it for comparison only; it is read from git and nothing is
taken from it.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from chains import domains, lagging, mapfile, preregister, rings, stages  # noqa: E402
from chains.paths import commitments_path, map_path, watch_path  # noqa: E402

DRAFT_REF = "ring2-recommit"
# A person's decision on a question (e.g. "stays v1", and why), carried onto
# every regeneration of the file instead of living only in a chat.
NOTES = REPO / "data" / "ring2-notes.json"


def draft_rows(dom: str) -> dict[str, dict]:
    try:
        raw = subprocess.run(["git", "show", f"{DRAFT_REF}:data/{dom}/watch.json"],
                             capture_output=True, text=True, encoding="utf-8",
                             check=True, cwd=REPO).stdout
    except subprocess.CalledProcessError:
        return {}
    return {r["id"]: r for r in json.loads(raw)}


ANALYST = ("trendforce.com", "crugroup.com", "benchmarkminerals.com", "lightcounting.com")
PRIMARY = ("sec.gov", "investor.", "investors.", "/ir/", "ir.", "/news-releases", "/newsroom",
           "/supplier-day", "/fileadmin/")


def guess_type(src) -> str:
    """A GUESS for an edge that predates source_type, from its URL(s): the
    strongest of the list wins. Labelled as a guess wherever it is shown."""
    refs = src if isinstance(src, list) else [src or ""]
    kinds = []
    for r in refs:
        r = str(r).lower()
        kinds.append("analyst" if any(a in r for a in ANALYST)
                     else "primary" if any(k in r for k in PRIMARY) else "media")
    return ("primary" if "primary" in kinds else "analyst" if "analyst" in kinds else "media")


def edge_info(doc: dict, leg: str, parents: list[str]) -> list[dict]:
    out = []
    for e in doc.get("edges", []):
        if e.get("from") == leg and e.get("to") in parents and e.get("type") == "supplies":
            out.append({"to": e["to"], "what": e.get("what", ""),
                        "source": e.get("source"),
                        "source_type": e.get("source_type")
                        or f"{guess_type(e.get('source'))} (guessed from the URL; edge predates the closure)"})
    return out


def bn_info(doc: dict, leg: str, lag: dict) -> list[dict]:
    out = []
    for b in doc.get("bottlenecks", []):
        roles = [k for k in ("owners", "hurt", "propagation") if leg in (b.get(k) or [])]
        if not roles:
            continue
        lg = next((e for e in lag.get(leg, []) if e["b"] == b["id"]), None)
        out.append({"bottleneck": b["id"], "role": roles[0], "stage": b["stage"],
                    "top_risk": b["top_risk"], "trigger": b["trigger"]["status"],
                    "exposure": (b.get("exposure") or {}).get(leg),
                    "lagging": bool(lg and lg.get("kind") == "lag" and lg.get("lagging"))})
    return out


def bottleneck_candidates(doc: dict, win: list[str], lose: list[str]) -> tuple[dict, dict]:
    cw, cl = {}, {}
    for b in doc.get("bottlenecks", []):
        owners = set(b.get("owners") or [])
        stage, fired = b.get("stage"), b["trigger"]["status"] == "fired"
        if stage == "tightening" and fired:
            for side_first, gain, hurt in ((win, cw, cl), (lose, cl, cw)):
                if owners & set(side_first):
                    for i in b.get("propagation") or []:
                        gain.setdefault(i, []).append(f"bottleneck:{b['id']} (propagation)")
                    for i in b.get("hurt") or []:
                        hurt.setdefault(i, []).append(f"bottleneck:{b['id']} (hurt)")
        elif stage in ("peaking", "resolving"):
            touched = (owners | set(b.get("hurt") or []) | set(b.get("propagation") or []))
            if touched & (set(win) | set(lose)):
                for i in owners:
                    cl.setdefault(i, []).append(f"bottleneck:{b['id']} ({stage}: owner)")
                for i in b.get("next_node") or []:
                    cw.setdefault(i, []).append(f"bottleneck:{b['id']} ({stage}: next_node)")
    return cw, cl


def for_question(doc: dict, row: dict, draft: dict | None, lag: dict) -> dict:
    win, lose = list(row.get("win") or []), list(row.get("lose") or [])
    first = set(win) | set(lose)
    sr = rings.second_ring(doc, win, lose)
    parents = {r["from"]: [] for r in sr["ring2_edges"]}
    for r in sr["ring2_edges"]:
        parents[r["from"]].append(r["to"])
    bw, bl = bottleneck_candidates(doc, win, lose)
    sides = {"win": {i: ["edge"] for i in sr["win2"]}, "lose": {i: ["edge"] for i in sr["lose2"]}}
    for side, extra in (("win", bw), ("lose", bl)):
        for i, why in extra.items():
            if i not in first:
                sides[side].setdefault(i, []).extend(why)
    both = set(sides["win"]) & set(sides["lose"])        # no sign: the mixed rule
    legs = {}
    for side in ("win", "lose"):
        legs[side] = [{"id": i, "via": sides[side][i],
                       "edges": edge_info(doc, i, parents.get(i, [])),
                       "bottlenecks": bn_info(doc, i, lag)}
                      for i in sides[side] if i not in both]
    d_w = list((draft or {}).get("ring2_win") or [])
    d_l = list((draft or {}).get("ring2_lose") or [])
    cw, cl = [x["id"] for x in legs["win"]], [x["id"] for x in legs["lose"]]
    return {
        "qid": row["id"], "answer_date": row["d"], "kind": row.get("kind"),
        "first_ring": {"win": win, "lose": lose},
        "draft_ring2": {"win": d_w, "lose": d_l,
                        "confidence": (draft or {}).get("ring2_confidence")},
        "candidates": legs,
        "dropped_as_mixed": sorted(both),
        "vs_draft": {"win_kept": [i for i in d_w if i in cw], "win_dropped": [i for i in d_w if i not in cw],
                     "win_added": [i for i in cw if i not in d_w],
                     "lose_kept": [i for i in d_l if i in cl], "lose_dropped": [i for i in d_l if i not in cl],
                     "lose_added": [i for i in cl if i not in d_l]},
        "empty": {"win": not cw, "lose": not cl},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=dt.datetime.now(dt.timezone.utc).date().isoformat())
    ap.add_argument("--only")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    out = []
    notes = json.loads(NOTES.read_text(encoding="utf-8")) if NOTES.exists() else {}
    for dom in domains.discover():
        doc = mapfile.load(map_path(dom))
        if doc.get("bottlenecks"):
            doc["bottlenecks"] = stages.annotate(doc["bottlenecks"])   # computed, never stored
        lag = lagging.compute(doc) if doc.get("bottlenecks") else {}
        drafts = draft_rows(dom)
        committed_v2 = {e["qid"] for e in json.loads(commitments_path(dom).read_text(encoding="utf-8"))
                        if "contract v2" in (e.get("revision_note") or "")}
        for row in json.loads(watch_path(dom).read_text(encoding="utf-8")):
            if (row.get("observe_only") or row["d"] <= a.day or row["id"] in committed_v2
                    or preregister.is_v2(row)):
                continue
            if a.only and a.only != f"{dom}/{row['id']}":
                continue
            q = for_question(doc, row, drafts.get(row["id"]), lag)
            note = notes.get(f"{dom}/{row['id']}")
            out.append({"domain": dom, **q, **({"note": note} if note else {})})
    out.sort(key=lambda q: (q["answer_date"], q["domain"], q["qid"]))
    path = Path(a.out or REPO / "data" / f"ring2-candidates-{a.day}.json")
    path.write_text(json.dumps({"generated": a.day, "note": __doc__.strip().splitlines()[0],
                                "questions": out}, indent=1, ensure_ascii=False) + "\n",
                    encoding="utf-8", newline="\n")
    print(f"{len(out)} question(s) -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
