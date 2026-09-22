"""Which maps this mark run should walk.

Every map, normally. With ``--force`` in play it is the one map that owns
the question: --force names a single id, an id belongs to one map, and
mark.py raises on a map that does not have it -- so walking all of them
would turn a forced dry run red on every map but one.

An id no map owns exits non-zero rather than printing an empty list. A run
that walked nothing and reported success would be the quietest possible way
to lose a typo.

    python -m chains.mark_domains            # every map
    python -m chains.mark_domains abb_q3     # the map(s) that own this id

The id is an ARGUMENT, not an environment variable: chains/paths.py's
docstring is the one place a reader should have to look to learn what this
build reads from the environment, and a one-shot debugging input does not
belong on that list. tests/test_isolation.py holds that line.
"""
from __future__ import annotations

import json
import sys

from chains import domains
from chains.paths import watch_path


def owners(qid: str) -> list[str]:
    """The maps whose watch list carries this question."""
    out = []
    for dom in domains.discover():
        try:
            rows = json.loads(watch_path(dom).read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            continue
        if any(r.get("id") == qid for r in rows):
            out.append(dom)
    return out


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    qid = (argv[0] if argv else "").strip()
    found = domains.discover()
    if not found:
        print("no buildable domain under data/", file=sys.stderr)
        return 1
    if qid:
        found = owners(qid)
        if not found:
            print(f"--force {qid}: no map has a question with that id",
                  file=sys.stderr)
            return 1
    print(" ".join(found))
    return 0


if __name__ == "__main__":                                # pragma: no cover
    raise SystemExit(main())
