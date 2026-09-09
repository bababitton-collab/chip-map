"""Write chain_fundamentals.json from EDGAR.

    python chains/scripts/build_fundamentals.py

US filers only; every other entry gets an explicit null block with a reason.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chains import edgar, fundamentals, mapfile   # noqa: E402
from chains.paths import out_dir                  # noqa: E402


def main() -> int:
    doc = mapfile.load()
    with edgar.Source() as source:
        out = fundamentals.build(doc, source, verbose=True)
    p = out_dir()
    p.mkdir(parents=True, exist_ok=True)
    f = p / "chain_fundamentals.json"
    f.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")),
                 encoding="utf-8")
    have = [k for k, v in out.items() if v["fundamentals"]]
    print(f"wrote {f}  ({f.stat().st_size / 1024:,.0f} KB)")
    print(f"  entries {len(out)}, with fundamentals {len(have)}")
    if edgar.CONTACT.startswith("CONTACT-"):
        print("  note: chains/edgar.py CONTACT is still the placeholder; "
              "SEC asks for a real address in the User-Agent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
