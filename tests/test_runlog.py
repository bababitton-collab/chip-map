"""The weekly run record: chained, so a rewritten history is detectable."""
from __future__ import annotations

import json

import pytest

from chains import runlog


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(runlog, "out_dir", lambda: tmp_path)


def test_an_empty_record_verifies():
    assert runlog.verify()["ok"] is True
    assert runlog.head() == runlog.GENESIS


def test_records_chain_to_one_another():
    a = runlog.append({"result": "ok", "started": "2026-09-12"})
    b = runlog.append({"result": "ok", "started": "2026-09-19"})
    assert b["prev_hash"] == a["hash"]
    assert runlog.verify()["ok"] is True


def test_editing_an_old_run_breaks_the_chain_at_that_run():
    runlog.append({"result": "failed", "failed_step": "prices"})
    runlog.append({"result": "ok"})
    p = runlog.path()
    lines = p.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[0])
    rec["payload"]["result"] = "ok"          # make a failure look like a success
    lines[0] = json.dumps(rec, sort_keys=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = runlog.verify()
    assert out["ok"] is False and out["first_break_seq"] == 1


def test_a_forged_hash_still_breaks_the_next_record():
    runlog.append({"result": "failed"})
    runlog.append({"result": "ok"})
    p = runlog.path()
    lines = p.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[0])
    rec["payload"]["result"] = "ok"
    rec["hash"] = runlog.digest(rec["payload"], rec["prev_hash"])
    lines[0] = json.dumps(rec, sort_keys=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert runlog.verify()["first_break_seq"] == 2


def test_the_file_digest_ties_a_run_to_the_file_it_produced(tmp_path):
    f = tmp_path / "live.json"
    f.write_text("{}", encoding="utf-8")
    assert runlog.file_digest(f) == runlog.file_digest(f)
    assert runlog.file_digest(tmp_path / "missing.json") is None
