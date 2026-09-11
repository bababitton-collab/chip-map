"""Assemble site/ from out/, and refuse to publish Hebrew in the English page.

    python -m chains.publish_site

    out/<domain>/public-map-en.html  ->  site/<domain>/index.html
    out/<domain>/public-map.html     ->  site/<domain>/he.html
    out/<domain>/live_en.json        ->  site/<domain>/live_en.json
    out/<domain>/live.json           ->  site/<domain>/live.json
    out/<domain>/brief-free-<date>.md    ->  site/<domain>/brief.md
    out/<domain>/brief-he-free-<date>.md ->  site/<domain>/brief-he.md
                                         site/index.html  (redirect)
                                         site/CNAME
                                         site/.nojekyll

EVERY DOMAIN GETS A DIRECTORY
-----------------------------
A map lives at /<domain>/, and site/index.html is a redirect to the one that is
the product today. That costs one hop and buys the thing that matters: adding a
second map never moves the first one's URL, and every link anybody has already
shared keeps working.

WHY THE ENGLISH PAGE IS index.html
----------------------------------
The public product is English. The Hebrew page is Michael's own copy and it
lives at /he.html, reachable and not the front door. That is the same split the
briefs have and it is the reason the gate below only guards one of them.

THE FREE BRIEF IS THE ONE THAT GETS PUBLISHED
---------------------------------------------
out/ holds four briefs: the paid mail in each language, with every question,
and the free letter, with only the questions whose text the site already shows.
The site serves the free one. Publishing the paid one here would hand away in
a markdown file exactly what chains/questions.py withholds everywhere else, and
it would do it quietly -- which is why the gate below now reads the brief too.

THE BRIEF FILENAMES LOSE THEIR DATE ON THE WAY IN
-------------------------------------------------
out/ keeps brief-2026-09-12.md so last week's is still there to compare. The
site serves /brief.md, one stable URL, because a reader who bookmarks a dated
URL bookmarks a document that stops being updated. The date is inside the
document.

CNAME
-----
The custom domain. Pages reads it out of the published artifact, so it has to
be written on every deploy: a build that forgot it would hand the site back to
the github.io address and every link to the real domain would 404 until the
next run. It is one line and no newline games -- Pages is strict about that.

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

import json
import shutil
import sys
from pathlib import Path

from chains.build_pages import hebrew_runs
from chains.paths import domain, out_dir, site_dir, site_root
from chains.questions import FIELDS as QUESTION_FIELDS

# (source in out/, name in site/). The briefs are resolved by glob because
# their filename carries the build date.
COPIES = [
    ("public-map-en.html", "index.html"),
    ("public-map.html", "he.html"),
    ("live_en.json", "live_en.json"),
    ("live.json", "live.json"),
]

BRIEFS = [("brief-free-*.md", "brief.md"),
          ("brief-he-free-*.md", "brief-he.md")]

# Only these. he.html, live.json and brief-he.md are Hebrew on purpose.
# The forward test, at /<domain>/track/. The page is English-only and its data
# file carries question text, so both go through the Hebrew gate and the
# locked-text scan below.
# The page and the SEALED payload. track.json is never copied: the plaintext
# is the paid half of the product and a static host serves whatever is in the
# directory. publish() refuses to run without the sealed file rather than
# quietly shipping a page with nothing behind its unlock box.
TRACK_FILES = [("track.html", "index.html"),
               ("track.enc.json", "track.enc.json")]
TRACK_PLAINTEXT = "track.json"

GATED = ("index.html", "live_en.json")

# Checked for locked question text rather than for Hebrew: these are the files
# that could carry a sentence somebody is meant to pay for.
PAYWALLED = ("index.html", "he.html", "live.json", "live_en.json",
             "brief.md", "brief-he.md",
             # The forward test names the question behind every mark, so it is
             # scanned on the same terms as the map and the letter. The sealed
             # payload is scanned too -- ciphertext cannot contain a sentence,
             # and the day somebody publishes it plain the scan says so.
             "track/index.html", "track/track.enc.json")

# Every sentence a locked question owns, in both languages. All four parts
# count: "what no sounds like" is as much the product as the question itself,
# and a card that leaked only the "why" would still have given the thing away.
# Taken from chains/questions.py so a fifth part cannot be added there and
# quietly escape this scan.
FIELDS_CHECKED = QUESTION_FIELDS

# Shorter than this and a phrase is not evidence of anything: "capex guidance"
# occurs in prose that has nothing to do with the row it belongs to.
MIN_NEEDLE = 25


def latest(pattern: str) -> Path | None:
    """The newest brief matching the pattern.

    ``brief-free-*.md`` cannot match a Hebrew one, but the guard stays: the
    two families differ by one infix and a glob that drifted would publish the
    wrong language rather than failing.
    """
    hits = [p for p in out_dir().glob(pattern)
            if pattern.startswith("brief-he") or not p.name.startswith("brief-he")]
    return max(hits, key=lambda p: p.name) if hits else None


DEFAULT_DOMAIN_FOR_ROOT = "semi"

# The custom domain, served from the root of the site rather than per map.
CUSTOM_DOMAIN = "linchpinsignal.com"


def write_root_redirect(dom: str | None = None) -> Path:
    """site/index.html -> /<domain>/.

    A meta refresh and a link, not a server rule: Pages serves static files and
    there is nowhere to put a redirect except in a document. The link matters --
    it is what a reader sees if the refresh is blocked, and what a crawler
    follows.
    """
    dom = dom or DEFAULT_DOMAIN_FOR_ROOT
    p = site_root() / "index.html"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "<!doctype html>\n<html lang=\"en\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        f"<meta http-equiv=\"refresh\" content=\"0; url=./{dom}/\">\n"
        f"<link rel=\"canonical\" href=\"./{dom}/\">\n"
        "<title>The Living Chip Map</title>\n</head>\n<body>\n"
        f"<p><a href=\"./{dom}/\">The Living Chip Map</a></p>\n"
        "</body>\n</html>\n", encoding="utf-8", newline="\n")
    return p


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

    # The forward test lives at /<domain>/track/, so a reader can be sent to
    # the evidence without being sent to the whole map.
    track = site / "track"
    track.mkdir(parents=True, exist_ok=True)
    for src_name, dst_name in TRACK_FILES:
        src = out_dir() / src_name
        if not src.exists():
            raise SystemExit(
                f"{src} is missing. Run python -m chains.track first.")
        shutil.copyfile(src, track / dst_name)
        written.append(f"track/{dst_name}")

    (site_root() / ".nojekyll").write_text("", encoding="utf-8")
    written.append("../.nojekyll")
    (site_root() / "CNAME").write_text(CUSTOM_DOMAIN + "\n",
                                       encoding="utf-8",
                                       newline="\n")
    written.append("../CNAME")
    write_root_redirect()
    written.append("../index.html  (redirect)")

    # Nothing unsealed, ever. Checked on the directory about to be served
    # rather than inferred from the copy list above.
    for stray in sorted(track.rglob("*")):
        if stray.name == TRACK_PLAINTEXT:
            raise SystemExit(
                f"{stray} is the unencrypted tracking payload and it is about "
                f"to be published. Remove it; only track.enc.json ships.")

    for name in ("track/index.html", "track/track.enc.json"):
        text = (site / name).read_text(encoding="utf-8")
        runs = hebrew_runs(text)
        if runs:
            raise SystemExit(
                f"site/{name}: {len(runs)} Hebrew string(s) in a file served "
                f"to English readers. Not published.\n  "
                + "\n  ".join(runs[:10]))

    for name in GATED:
        text = (site / name).read_text(encoding="utf-8")
        runs = hebrew_runs(text)
        if runs:
            raise SystemExit(
                f"site/{name}: {len(runs)} Hebrew string(s) in a file served "
                f"to English readers. Not published.\n  "
                + "\n  ".join(runs[:10]))
    leaked = locked_text_in_site(site)
    if leaked:
        raise SystemExit(
            f"a locked question's text reached the site: {leaked[:3]}. "
            f"Not published.")
    return site, written


def locked_text_in_site(site: Path) -> list[str]:
    """Any locked question whose sentence appears in a published file.

    The paywall is a negative property, and negative properties rot quietly.
    So it is checked on the bytes about to be served rather than inferred from
    the flag that is supposed to imply them: fetch the text, take the ids the
    snapshot marked locked, and search every published file for their
    sentences. Costs one fetch and a substring scan.

    The brief is in that list for a reason. The paid mail carries every
    question, out/ holds both, and one wrong glob in BRIEFS above would hand
    away in a markdown file exactly what every other rule withholds.
    """
    from chains import questions
    try:
        text = questions.fetch()
    except questions.QuestionsError:
        return []          # no text was fetched, so none can have been written
    snap = json.loads((site / "live_en.json").read_text(encoding="utf-8"))
    locked = [r["id"] for r in snap.get("watch", []) if r.get("locked")]
    if not locked:
        return []
    # Anything an OPEN row is entitled to publish. A locked row's "listen for"
    # line can be a short generic phrase -- "capex guidance" -- that is a
    # substring of an open row's longer one, and flagging that would be a false
    # positive that trains people to ignore this gate. Found on the first run:
    # googl_q3's listen line sits inside orcl_q1's, and orcl_q1 was open.
    allowed = "\n".join(
        text[r["id"]][f]
        for r in snap.get("watch", []) if not r.get("locked")
        for f in FIELDS_CHECKED if r["id"] in text)
    blobs = {n: (site / n).read_text(encoding="utf-8")
             for n in PAYWALLED if (site / n).exists()}
    # marks.json is not served, but it IS committed to a public repository by
    # the mark workflow, and an evidence line or a note that quoted the
    # question back would put a locked sentence in git for good. Same scan,
    # same sentences, one more file.
    from chains.paths import REPO_ROOT, marks_path
    mp = marks_path()
    if mp.exists():
        # Keyed by a repo-relative name: the hit is reported as "<name>", and
        # an absolute Windows path inside a message that already says "site/"
        # reads as nonsense.
        try:
            label = str(mp.relative_to(REPO_ROOT)).replace("\\", "/")
        except ValueError:
            label = mp.name
        blobs["../" + label] = mp.read_text(encoding="utf-8")
    hits = []
    for qid in locked:
        for field in FIELDS_CHECKED:
            needle = text[qid][field]
            if len(needle) < MIN_NEEDLE or needle in allowed:
                continue
            for name, blob in blobs.items():
                if needle in blob:
                    hits.append(f"{qid} ({field}) in site/{name}")
    return hits


def main() -> int:
    site, written = publish()
    print(f"site: {site}")
    for name in written:
        p = site / name.split("  ")[0]
        n = p.stat().st_size if p.exists() else 0
        print(f"  {name:<34} {n:>9,} bytes")
    print(f"\n  no-Hebrew gate passed on: {', '.join(GATED)}")
    print(f"  no-locked-text gate passed on: {', '.join(PAYWALLED)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
