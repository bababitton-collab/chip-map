"""The EW_MAP universe each commitment is scored against, frozen.

    python -m chains.ew_universe --freeze        # a person, once; then commit

WHY
---
EW_MAP is "the equal-weight of the map's priced nodes". The contract names
it as a sentence, so adding a node to the map moves the benchmark under
every question already committed -- silently, and the hashes still verify.
The guard in chains/preregister.py caught that, but only for entries that
carry a fingerprint (15 of 92 on 2026-10-01) and only by failing the build,
which meant the map could not grow at all while a one-sided question was
open.

So each commitment's universe is written down once, and scoring reads it
from here instead of from the live map:

    data/<domain>/ew_universes/<sha256>.json   {sha256, n, symbols}
    data/<domain>/ew_universes/index.json      {qid: {fingerprint, source,
                                                       commit, verified}}

``--freeze`` rebuilds every committed question's universe from map.json AT
THE GIT COMMIT that recorded its hash. Where the entry carries an ew_map
fingerprint the rebuild must reproduce it exactly, or nothing is written.
Where it does not, the rebuild is stored with ``verified: false``: the
best record there is of what the map held that day, labelled as such.
Commitment records are never edited.

A commitment made later (``preregister --write``) records the live map's
universe, which is already the fingerprint it stores. That is "new
commitments use the current map".
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

INDEX = "index.json"


class UniverseError(RuntimeError):
    """A frozen universe that does not say what the commitment says."""


def fingerprint(symbols: list[str]) -> dict:
    """The same bytes preregister.ew_map_fingerprint hashes."""
    syms = sorted(set(symbols))
    blob = json.dumps(syms, separators=(",", ":")).encode("utf-8")
    return {"sha256": hashlib.sha256(blob).hexdigest(), "n": len(syms),
            "symbols": syms}


def priced(doc: dict) -> list[str]:
    from chains.preregister import priced_symbols
    return priced_symbols(doc)


def as_doc(symbols: list[str]) -> dict:
    """A map holding exactly these priced nodes, for code that reads a map."""
    return {"nodes": [{"id": s, "price_symbol": s, "price_symbol_kind": "primary"}
                      for s in symbols]}


def _dir(dom: str | None = None) -> Path:
    from chains.paths import data_dir
    return data_dir(dom) / "ew_universes"


def load_index(dom: str | None = None) -> dict:
    p = _dir(dom) / INDEX
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def load_universe(fp: str, dom: str | None = None) -> list[str]:
    p = _dir(dom) / f"{fp}.json"
    rec = json.loads(p.read_text(encoding="utf-8"))
    if fingerprint(rec["symbols"])["sha256"] != fp:
        raise UniverseError(f"{p.name} does not hash to its own name")
    return rec["symbols"]


def frozen_for(qid: str, dom: str | None = None,
               index: dict | None = None) -> list[str] | None:
    rec = (index if index is not None else load_index(dom)).get(qid)
    return load_universe(rec["fingerprint"], dom) if rec else None


def symbols_for(qid: str, current: list[str], dom: str | None = None,
                index: dict | None = None) -> list[str]:
    """What EW_MAP is made of for this question: frozen if it is, else live."""
    got = frozen_for(qid, dom, index)
    return current if got is None else got


def all_frozen(dom: str | None = None) -> list[str]:
    """Every symbol any frozen universe needs, so the price step keeps them."""
    out: set[str] = set()
    for rec in load_index(dom).values():
        out.update(load_universe(rec["fingerprint"], dom))
    return sorted(out)


def write(qid: str, symbols: list[str], source: str, commit: str | None,
          verified: bool, dom: str | None = None) -> str:
    fp = fingerprint(symbols)
    d = _dir(dom)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{fp['sha256']}.json").write_text(
        json.dumps(fp, indent=1) + "\n", encoding="utf-8", newline="\n")
    idx = load_index(dom)
    idx[qid] = {"fingerprint": fp["sha256"], "source": source,
                "commit": commit, "verified": verified}
    (d / INDEX).write_text(json.dumps(dict(sorted(idx.items())), indent=1)
                           + "\n", encoding="utf-8", newline="\n")
    return fp["sha256"]


def problems(dom: str | None, committed: list[dict]) -> list[str]:
    """Every committed question has a frozen universe, and it is the one its
    entry's fingerprint names, where it has one."""
    idx = load_index(dom)
    out = []
    for e in committed:
        rec = idx.get(e["qid"])
        if rec is None:
            out.append(f"{e['qid']}: no frozen EW_MAP universe. Run "
                       f"python -m chains.ew_universe --freeze")
            continue
        try:
            load_universe(rec["fingerprint"], dom)
        except (OSError, UniverseError, KeyError, ValueError) as err:
            out.append(f"{e['qid']}: frozen EW_MAP universe unreadable ({err})")
            continue
        stored = (e.get("ew_map") or {}).get("sha256")
        if stored and stored != rec["fingerprint"]:
            out.append(f"{e['qid']}: frozen EW_MAP universe {rec['fingerprint'][:8]} "
                       f"is not the one committed ({stored[:8]})")
    return out


# ------------------------------------------------------------ the rebuild
def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


def commit_of(sha: str, path: str, rev: str = "HEAD") -> str:
    """The first commit on ``rev`` whose ``path`` carries this hash."""
    got = _git("log", rev, "--reverse", "--format=%H", f"-S{sha}", "--", path)
    first = got.split()
    if not first:
        raise UniverseError(f"hash {sha[:8]} never appears in {path}")
    return first[0]


def rebuild(dom: str, rev: str = "HEAD") -> list[dict]:
    """Each committed question's universe, from the map at its commit.

    Raises on the first entry whose stored fingerprint cannot be reproduced,
    naming it. Writes nothing; ``freeze`` does.
    """
    from chains.paths import commitments_path, map_path
    root = Path(_git("rev-parse", "--show-toplevel").strip())
    cpath = commitments_path(dom).resolve().relative_to(root).as_posix()
    mpath = map_path(dom).resolve().relative_to(root).as_posix()
    entries = json.loads(_git("show", f"{rev}:{cpath}"))
    out, maps = [], {}
    for e in entries:
        c = commit_of(e["sha256"], cpath, rev)
        if c not in maps:
            maps[c] = json.loads(_git("show", f"{c}:{mpath}"))
        syms = priced(maps[c])
        fp = fingerprint(syms)["sha256"]
        stored = (e.get("ew_map") or {}).get("sha256")
        if stored and stored != fp:
            raise UniverseError(
                f"{dom}/{e['qid']}: the map at {c[:8]} gives EW_MAP {fp[:8]}, "
                f"the entry recorded {stored[:8]}. Not frozen.")
        out.append({"qid": e["qid"], "symbols": syms, "commit": c,
                    "verified": bool(stored)})
    return out


def freeze(dom: str, rev: str = "HEAD") -> list[dict]:
    got = rebuild(dom, rev)                 # all or nothing
    for g in got:
        write(g["qid"], g["symbols"], "git", g["commit"], g["verified"], dom)
    return got


def main(argv: list[str] | None = None) -> int:
    import argparse

    from chains import domains
    ap = argparse.ArgumentParser(prog="python -m chains.ew_universe")
    ap.add_argument("--freeze", action="store_true", required=True)
    ap.add_argument("--domain", action="append")
    a = ap.parse_args(argv)
    for dom in a.domain or domains.discover():
        try:
            got = freeze(dom)
        except UniverseError as e:
            print(f"ew_universe: STOP -- {e}")
            return 1
        fps = {fingerprint(g["symbols"])["sha256"][:8] for g in got}
        print(f"{dom}: {len(got)} frozen, {sum(g['verified'] for g in got)} "
              f"verified against a stored fingerprint, {len(fps)} universe(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
