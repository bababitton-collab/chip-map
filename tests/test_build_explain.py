"""A failed build step says why, where it can be read without the log.

The Actions log needs a sign-in; the step summary and check-run annotations
do not. On 2026-10-02 a build failed with nothing public but "exit code 1".
"""
from __future__ import annotations

from chains import build_all as B


def test_a_failing_step_is_streamed_kept_and_explained(tmp_path, monkeypatch, capsys):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("CHIP_MAP_DOMAIN", "semi")
    rc, lines = B._run(["-c", "print('reading · prices'); raise ValueError('no rows for HPQ.US')"])
    assert rc != 0
    assert "reading · prices" in lines                       # non-ASCII survives the pipe
    B._explain("track", rc, lines)
    md = summary.read_text(encoding="utf-8")
    assert "build stopped at `track` (semi)" in md
    assert "**ValueError: no rows for HPQ.US**" in md
    assert "Traceback (most recent call last)" in md
    out = capsys.readouterr().out
    assert "::error title=semi%3A track::ValueError: no rows for HPQ.US" in out


def test_a_systemexit_message_with_no_traceback_is_still_named():
    md, ann = B.explanation("live", 1, ["wrote x", "", "live.json is 293,621 bytes, over the 250,000 limit"])
    assert ann.endswith("::live.json is 293,621 bytes, over the 250,000 limit")
    assert "Traceback:" not in md


def test_only_the_last_sixty_lines_are_kept_in_the_summary():
    lines = [f"line {i}" for i in range(200)] + ["RuntimeError: late"]
    md, _ = B.explanation("pages", 1, lines)
    assert "line 140" not in md and "line 141" in md and "RuntimeError: late" in md


def test_workflow_command_escaping():
    assert B._escape("a%b\nc") == "a%25b%0Ac"
    assert B._escape("semi: x, y", prop=True) == "semi%3A x%2C y"
