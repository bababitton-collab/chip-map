"""Assemble site/ from out/, and refuse to publish Hebrew in the English page.

    python -m chains.publish_site

    out/public-map-en.html  ->  site/index.html
    out/public-map.html     ->  site/he.html
    out/live_en.json        ->  site/live_en.json
    out/live.json           ->  site/live.json
    out/brief-<date>.md     ->  site/brief.md
    out/brief-he-<date>.md  ->  site/brief-he.md
                                site/.nojekyll

WHY THE ENGLISH PAGE IS index.html
----------------------------------
The public product is English. The Hebrew page is Michael's own copy and it
lives at /he.html, reachable and not the front door. That is the same split the
briefs have and it is the reason the gate below only guards one of them.

THE BRIEF FILENAMES LOSE THEIR DATE ON THE WAY IN
-------------------------------------------------
out/ keeps brief-2026-09-12.md so last week's is still there to compare. The
site serves /brief.md, one stable URL, because a reader who bookmarks a dated
URL bookmarks a document that stops being updated. The date is inside the
document.

.nojekyll
---------
Without it Pages runs the files through Jekyll, which ignores anything starting
with an underscore and rewrites what it does not ignore. Nothing here wants
that.

THE GATE RUNS LAST, HERE, ON WHAT WILL ACTUALLY BE SERVED
----------------------------------------------------------
chains/build_pages.py already refuses to write a public English page containing
a Hebrew character. This checks the copy in site/ -- the bytes Pages will serve
-- and it checks live_en.json too, which the build could not: the page fetches
that file at read time, so Hebrew in it reaches an English reader without ever
appearing in the HTML the earlier gate saw.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from chains.build_pages import hebrew_runs
from chains.paths import out_dir, site_dir

# (source in out/, name in site/). The briefs are resolved by glob because
# their filename carries the build date.
COPIES = [
    ("public-map-en.html", "index.html"),
    ("public-map.html", "he.html"),
    ("live_en.json", "live_en.json"),
    ("live.json", "live.json"),
]

BRIEFS = [("brief-*.md", "brief.md"), ("brief-he-*.md", "brief-he.md")]

# Only these two. he.html and live.json are Hebrew on purpose.
GATED = ("index.html", "live_en.json")


def latest(pattern: str) -> Path | None:
    """The newest brief matching the pattern.

    ``brief-*.md`` also matches ``brief-he-*.md``, so the Hebrew ones are
    excluded explicitly rather than by hoping the sort separates them.
    """
    hits = [p for p in out_dir().glob(pattern)
            if pattern.startswith("brief-he") or not p.name.startswith("brief-he")]
    return max(hits, key=lambda p: p.name) if hits else None


def publish(dst: Path | None = None) -> tuple[Path, list[str]]:
    """Copy everything in, then gate. Returns (site dir, what was written)."""
    site = dst or site_dir()
    site.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    for src_name, dst_name in COPIES:
        src = out_dir() / src_name
        if not src.exists():
            raise SystemExit(
                f"{src} is missing. Run python -m chains.build_all first; "
                f"publishing a partial site would serve a page whose data "
                f"file is last week's.")
        shutil.copyfile(src, site / dst_name)
        written.append(dst_name)

    for pattern, dst_name in BRIEFS:
        src = latest(pattern)
        if src is None:
            raise SystemExit(f"no {pattern} in {out_dir()}")
        shutil.copyfile(src, site / dst_name)
        written.append(f"{dst_name}  (from {src.name})")

    (site / ".nojekyll").write_text("", encoding="utf-8")
    written.append(".nojekyll")

    for name in GATED:
        text = (site / name).read_text(encoding="utf-8")
        runs = hebrew_runs(text)
        if runs:
            raise SystemExit(
                f"site/{name}: {len(runs)} Hebrew string(s) in a file served "
                f"to English readers. Not published.\n  "
                + "\n  ".join(runs[:10]))
    return site, written


def main() -> int:
    site, written = publish()
    print(f"site: {site}")
    for name in written:
        p = site / name.split("  ")[0]
        n = p.stat().st_size if p.exists() else 0
        print(f"  {name:<34} {n:>9,} bytes")
    print(f"\n  no-Hebrew gate passed on: {', '.join(GATED)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
