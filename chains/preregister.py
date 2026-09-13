"""Public pre-registration: every dated question's scoring contract, hashed
before its answer date.

    python -m chains.preregister --check                 # the build
    python -m chains.preregister --write                 # a person, then a commit
    python -m chains.preregister --write --recommit QID  # before its date only

WHAT IS FIXED IN ADVANCE
------------------------
A forecast is only a forward test if what it is scored against could not move
after the answer was known. The CONTRACT is that thing and nothing else: the
two baskets, the tide/share kind, the sentences that decide whether the answer
was yes or no, the horizons and the one that is headline, the two benchmarks,
and which way the sign runs. It is built from the watch row and the English
yes/no wording, serialised canonically and hashed with SHA-256.

THE HASH IS FREE, THE BYTES COME LATER
--------------------------------------
commitments.json carries the hash, the day it was committed and the answer
date. It is public and never paywalled. The contract itself carries the yes/no
sentences, which stay paid until the question is answered -- so it is revealed
on the card once the answer is in, and the page recomputes the hash in the
reader's own browser. Nothing on the page has to be taken on trust.

WHO WRITES THE FILE
-------------------
A person, with --write, and then a commit: the git commit is the external
timestamp and committed_at says the same thing inside the file. The build never
writes it. A CI run that stamped a new question with its own date would make
the date mean "the last build" instead of "the day it was committed", and it
would move on every run because CI does not commit data back. The build runs
--check instead, which fails when a question has no commitment or its contract
no longer hashes to the committed value.

A DATE ONCE WRITTEN IS NEVER MOVED
----------------------------------
Stickiness is on the pair (qid, sha256). The same contract keeps its date on
every later run. A CHANGED contract is refused: keeping the old date beside a
new hash would say the new contract was fixed on a day it did not exist. It can
be re-committed with --recommit, which stamps today, and only while the answer
date is still ahead. Once the answer date has come nothing can be re-committed.
A question dropped from the watch list keeps its commitment in the file -- a
published hash is not withdrawn by deleting the row it came from.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

from chains import forecast
from chains.answers import HORIZONS, HORIZONS_R2, PRIMARY_HORIZON

# Every horizon any order is read at. The primary one is the headline; the rest
# are secondary, and the contract names them so none can be added afterwards.
CONTRACT_HORIZONS = tuple(sorted(set(HORIZONS) | set(HORIZONS_R2)))
BENCHMARKS = {"ew": "EW_MAP: equal-weight of the map's priced nodes",
              "sox": forecast.SOX_SYMBOL}
SIGN_CONVENTION = "yes -> win basket up / lose basket down; no -> inverted"

CONTRACT_FIELDS = ("qid", "win", "lose", "kind", "yes_criteria",
                   "no_criteria", "horizons", "primary_horizon", "benchmarks",
                   "sign_convention", "observe_only")
ENTRY_FIELDS = ("qid", "answer_date", "committed_at", "sha256",
                "primary_horizon", "valid_preregistration")


class PreregisterError(ValueError):
    """A commitment that cannot be made, or kept, honestly."""


def _qid(row: dict) -> str:
    return row.get("id") or row["qid"]


def _wording(row: dict, text: dict | None, part: str) -> str:
    """The English yes/no sentence, from the row if it carries one, else from
    the questions source. Trimmed at the ends and nowhere else."""
    for src in (row, text or {}):
        v = src.get(f"{part}_en")
        if v:
            return str(v).strip()
    return ""


# ---------------------------------------------------------------- the contract
def contract(row: dict, text: dict | None = None) -> dict:
    """Exactly the fields that must not move once committed, and no others.

    Prose that is not a scoring rule -- who, the label, the date, the leaks --
    stays out, so correcting it does not look like moving the goalposts. The
    answer date is carried by the commitment entry, where it is checked.
    """
    qid = _qid(row)
    yes = _wording(row, text, "yes")
    if not yes:
        raise PreregisterError(
            f"{qid}: no yes wording. A contract with no rule for classifying "
            f"the answer fixes nothing, so it is not committed.")
    return {
        "qid": qid,
        "win": sorted(row.get("win") or []),
        "lose": sorted(row.get("lose") or []),
        "kind": row.get("kind"),
        "yes_criteria": yes,
        "no_criteria": _wording(row, text, "no"),
        "horizons": list(CONTRACT_HORIZONS),
        "primary_horizon": PRIMARY_HORIZON,
        "benchmarks": dict(BENCHMARKS),
        "sign_convention": SIGN_CONVENTION,
        "observe_only": bool(row.get("observe_only")),
    }


def canonical(row: dict, text: dict | None = None) -> bytes:
    """The bytes that are hashed, and the bytes that are later revealed."""
    return json.dumps(contract(row, text), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False
                      ).encode("utf-8")


def digest(row: dict, text: dict | None = None) -> str:
    return hashlib.sha256(canonical(row, text)).hexdigest()


def commitment(row: dict, text: dict | None = None) -> dict:
    b = canonical(row, text)
    return {"qid": _qid(row), "sha256": hashlib.sha256(b).hexdigest(),
            "contract_bytes_len": len(b)}


# ------------------------------------------------------------- the entries
def _entry(qid: str, answer_date: str, committed_at: str, sha: str) -> dict:
    return {"qid": qid, "answer_date": answer_date,
            "committed_at": committed_at, "sha256": sha,
            "primary_horizon": PRIMARY_HORIZON,
            # Strictly before. Committed on the answer date itself is not a
            # preregistration: the answer may already have been public.
            "valid_preregistration": committed_at < answer_date}


def entries(rows: list[dict], texts: dict | None, prior: list[dict] | None,
            today: dt.date | None = None,
            recommit: frozenset | set = frozenset()) -> list[dict]:
    """The commitments file as it should now read. Sticky on (qid, sha256)."""
    day = (today or dt.datetime.now(dt.timezone.utc).date()).isoformat()
    by = {e["qid"]: e for e in (prior or [])}
    out, seen = [], set()
    for r in rows:
        qid = _qid(r)
        seen.add(qid)
        sha = commitment(r, (texts or {}).get(qid))["sha256"]
        old = by.get(qid)
        if old is None:
            committed = day
        elif old["sha256"] == sha:
            committed = old["committed_at"]
        elif qid not in recommit:
            raise PreregisterError(
                f"{qid}: its contract no longer hashes to the value committed "
                f"on {old['committed_at']}. Keeping that date beside a new hash "
                f"would misstate when this contract was fixed. Restore the "
                f"contract, or re-commit it with --recommit {qid} while its "
                f"answer date ({r['d']}) is still ahead.")
        elif day >= r["d"]:
            raise PreregisterError(
                f"{qid}: cannot re-commit -- its answer date {r['d']} has come. "
                f"A contract changed after its answer is not a preregistration.")
        else:
            committed = day
        out.append(_entry(qid, r["d"], committed, sha))
    for e in prior or []:
        if e["qid"] not in seen:
            out.append(dict(e))
    return out


def check(rows: list[dict], texts: dict | None,
          committed: list[dict]) -> list[str]:
    """Why the committed file does not match the questions, or [] if it does."""
    by = {e["qid"]: e for e in committed}
    problems = []
    for r in rows:
        qid = _qid(r)
        e = by.get(qid)
        if e is None:
            problems.append(f"{qid}: no commitment")
            continue
        if tuple(e) != ENTRY_FIELDS:
            problems.append(f"{qid}: entry fields are {list(e)}")
        sha = commitment(r, (texts or {}).get(qid))["sha256"]
        if e["sha256"] != sha:
            problems.append(f"{qid}: contract changed since it was committed "
                            f"on {e['committed_at']}")
        if e["answer_date"] != r["d"]:
            problems.append(f"{qid}: answer date moved from "
                            f"{e['answer_date']} to {r['d']}")
        if e["valid_preregistration"] != (e["committed_at"] < r["d"]):
            problems.append(f"{qid}: valid_preregistration is wrong")
        if e["primary_horizon"] != PRIMARY_HORIZON:
            problems.append(f"{qid}: primary_horizon is "
                            f"{e['primary_horizon']}, not {PRIMARY_HORIZON}")
    return problems


def reveal(row: dict, text: dict | None, entry: dict) -> dict:
    """What a resolved card carries: the commitment, and the exact bytes that
    were hashed for it, as text."""
    return {"sha256": entry["sha256"], "committed_at": entry["committed_at"],
            "answer_date": entry["answer_date"],
            "primary_horizon": entry["primary_horizon"],
            "valid_preregistration": entry["valid_preregistration"],
            "contract": canonical(row, text).decode("utf-8")}


def reveals(rows: list[dict], texts: dict | None,
            committed: list[dict]) -> dict[str, dict]:
    by = {e["qid"]: e for e in committed}
    return {_qid(r): reveal(r, (texts or {}).get(_qid(r)), by[_qid(r)])
            for r in rows if _qid(r) in by}


# ------------------------------------------------------------------ the file
def load(path: Path | None = None) -> list[dict]:
    from chains.paths import commitments_path
    p = path or commitments_path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def dump(items: list[dict], path: Path | None = None) -> Path:
    from chains.paths import commitments_path
    p = path or commitments_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(items, indent=1, ensure_ascii=False) + "\n",
                 encoding="utf-8", newline="\n")
    return p


def main(argv: list[str] | None = None) -> int:
    import argparse
    import shutil

    from chains import questions
    from chains.paths import commitments_path, out_dir, watch_path

    ap = argparse.ArgumentParser(prog="python -m chains.preregister")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true",
                      help="the build: fail on a missing or changed commitment")
    mode.add_argument("--write", action="store_true",
                      help="record new questions; commit the file afterwards")
    ap.add_argument("--recommit", nargs="*", default=[],
                    help="re-commit these changed contracts (before their "
                         "answer date only)")
    a = ap.parse_args(argv)

    rows = json.loads(watch_path().read_text(encoding="utf-8"))
    texts = questions.fetch()
    path = commitments_path()
    prior = load(path)

    if a.write:
        try:
            got = entries(rows, texts, prior, recommit=frozenset(a.recommit))
        except PreregisterError as e:
            print(f"preregister: {e}")
            return 1
        dump(got, path)
        known = {e["qid"] for e in prior}
        new = [e["qid"] for e in got if e["qid"] not in known]
        late = [e["qid"] for e in got if not e["valid_preregistration"]]
        print(f"wrote {path}  ({len(got)} commitments, {len(new)} new)")
        print(f"  not a valid preregistration: {', '.join(late) or 'none'}")
        print("  commit this file: the commit is the timestamp")
        return 0

    problems = check(rows, texts, prior)
    if problems:
        print(f"preregister: {len(problems)} problem(s) in {path}")
        for p in problems:
            print(f"  {p}")
        print("  python -m chains.preregister --write, then commit the file")
        return 1
    out = out_dir()
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, out / "commitments.json")
    ok = sum(1 for e in prior if e["valid_preregistration"])
    print(f"preregister: {len(rows)} questions committed and unchanged "
          f"({ok} valid preregistrations); copied to {out / 'commitments.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["contract", "canonical", "digest", "commitment", "entries",
           "check", "reveal", "reveals", "load", "dump", "PreregisterError",
           "CONTRACT_FIELDS", "ENTRY_FIELDS", "CONTRACT_HORIZONS",
           "BENCHMARKS", "SIGN_CONVENTION"]
