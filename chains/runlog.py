"""A hash-chained record of every weekly run.

Same idea as the nightly journal, and a separate implementation because chains
may not import swing. Each record carries the SHA-256 of (previous hash + its
own canonical JSON), so editing an earlier run breaks every hash after it and
:func:`verify` names the first record that fails.

WHY A WEEKLY JOB NEEDS ONE
--------------------------
The cloud task refuses a live.json older than 8 days, so a local job that stops
running is eventually visible as a page that stops updating. What that does NOT
tell anyone is which step failed, when it started failing, or whether the file
was stale for two days or seven. A console log answers those and can be edited
or rotated away without trace; a chained record cannot be edited quietly.

It also records the SHA-256 of live.json itself, so the file the cloud task
collected can be matched to the run that produced it.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from chains.paths import out_dir

GENESIS = "0" * 64


def path() -> Path:
    return out_dir() / "weekly_journal.jsonl"


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      default=str)


def digest(payload: dict, prev: str) -> str:
    return hashlib.sha256((prev + _canonical(payload)).encode("utf-8")).hexdigest()


def read_all() -> list[dict]:
    p = path()
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()
            if ln.strip()]


def head() -> str:
    rows = read_all()
    return rows[-1]["hash"] if rows else GENESIS


def append(payload: dict) -> dict:
    prev = head()
    rec = {
        "seq": len(read_all()) + 1,
        "written_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "prev_hash": prev,
        "payload": payload,
    }
    rec["hash"] = digest(rec["payload"], prev)
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(rec, sort_keys=True, default=str) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return rec


def verify() -> dict:
    rows = read_all()
    prev = GENESIS
    for i, r in enumerate(rows):
        if r.get("prev_hash") != prev or digest(r.get("payload", {}), prev) != r.get("hash"):
            return {"ok": False, "records": len(rows), "first_break_seq": i + 1}
        prev = r["hash"]
    return {"ok": True, "records": len(rows), "head": prev,
            "first_break_seq": None}


def file_digest(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
