"""Assemble site/ from out/, and refuse to publish Hebrew in the English page.

    python -m chains.publish_site

    out/<domain>/public-map-en.html  ->  site/<domain>/index.html
    out/<domain>/public-map.html     ->  site/<domain>/he.html
    out/<domain>/live_en.json        ->  site/<domain>/live_en.json
    out/<domain>/live.json           ->  site/<domain>/live.json
    out/<domain>/brief-free-<date>.md    ->  site/<domain>/brief.md
    out/<domain>/brief-he-free-<date>.md ->  site/<domain>/brief-he.md
                                         site/index.html  (landing page)
                                         site/CNAME
                                         site/.nojekyll

EVERY DOMAIN GETS A DIRECTORY
-----------------------------
A map lives at /<domain>/, and site/index.html is a landing page that leads to
the one that is the product today. Adding a second map never moves the first
one's URL, and every link anybody has already shared keeps working. Every
number and capability on the landing page is read from the files published
beside it -- see chains/landing.py -- so it is written after they are copied.

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
from chains.questions import FIELDS as QUESTION_FIELDS, languages_for

# (source in out/, name in site/). The briefs are resolved by glob because
# their filename carries the build date.
COPIES = [
    ("public-map-en.html", "index.html"),
    ("public-map.html", "he.html"),
    ("live_en.json", "live_en.json"),
    ("live.json", "live.json"),
    # Focus mode's rows, beside the snapshots they were drawn from. The pages
    # inline them at build time; they are published too, so what the map drew
    # around a station is a file anyone can read.
    ("focus_en.json", "focus_en.json"),
    ("focus.json", "focus.json"),
    # Free and never paywalled: the hash of every question's scoring contract,
    # published before its answer date. Hashes and dates only, no sentence.
    ("commitments.json", "commitments.json"),
    # Free: every RESOLVED question's whole card, with the contract bytes the
    # Verify control hashes. Gated in chains/track.py, scanned again below.
    ("track_public.json", "track_public.json"),
]

BRIEFS = [("brief-free-*.md", "brief.md"),
          ("brief-he-free-*.md", "brief-he.md")]

# The Hebrew half of a published map, by its name in site/. A domain whose map
# declares languages: ["en"] never writes these: chains/build_pages.py builds
# no Hebrew page for it, so he.html has no source, and the Hebrew snapshot and
# letter would be served beside a site that has no page to read them. Skipped
# by destination name rather than by removing them from the lists above,
# because a bilingual map still publishes every one of them.
HE_ONLY = ("he.html", "live.json", "focus.json", "brief-he.md")


def publishes_hebrew(dom: str | None = None) -> bool:
    return "he" in languages_for(dom)

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

# The chart library the per-question pages draw with, vendored in the repo and
# served from this host: the pages pull no script from a CDN, so a reader's
# browser talks to nobody but this site and the charts keep working when a CDN
# does not. Apache-2.0 -- the notice is inside the file and the licence ships
# beside it. Kept out of TRACK_FILES because these are assets, not pages: they
# carry no analytics and no question text, and they are gated below on exactly
# the same terms as everything else that is published.
TRACK_ASSETS = ["lightweight-charts.standalone.production.js",
                "lightweight-charts.LICENSE.txt"]

GATED = ("index.html", "live_en.json", "focus_en.json", "track_public.json",
         # the landing page, at the site root
         "../index.html")

# Checked for locked question text rather than for Hebrew: these are the files
# that could carry a sentence somebody is meant to pay for.
PAYWALLED = ("index.html", "he.html", "live.json", "live_en.json",
             "focus.json", "focus_en.json",
             "track_public.json", "../index.html",
             "brief.md", "brief-he.md",
             # The forward test names the question behind every mark, so it is
             # scanned on the same terms as the map and the letter. The sealed
             # payload is scanned too -- ciphertext cannot contain a sentence,
             # and the day somebody publishes it plain the scan says so.
             "track/index.html", "track/track.enc.json",
             # The vendored library ships inside the same directory. Scanned
             # too: a script is exactly the sort of file nobody reads, and a
             # question's sentence must not be able to ride into the site
             # inside one.
             *(f"track/{a}" for a in TRACK_ASSETS))

# Every sentence a locked question owns, in both languages. All four parts
# count: "what no sounds like" is as much the product as the question itself,
# and a card that leaked only the "why" would still have given the thing away.
# Taken from chains/questions.py so a fifth part cannot be added there and
# quietly escape this scan.
FIELDS_CHECKED = QUESTION_FIELDS

# Shorter than this and a phrase is not evidence of anything: "capex guidance"
# occurs in prose that has nothing to do with the row it belongs to.
MIN_NEEDLE = 25


def latest(pattern: str, dom: str | None = None) -> Path | None:
    """The newest brief matching the pattern.

    ``brief-free-*.md`` cannot match a Hebrew one, but the guard stays: the
    two families differ by one infix and a glob that drifted would publish the
    wrong language rather than failing.
    """
    hits = [p for p in out_dir(dom).glob(pattern)
            if pattern.startswith("brief-he") or not p.name.startswith("brief-he")]
    return max(hits, key=lambda p: p.name) if hits else None


def root_domain() -> str:
    """Which map the site's front door describes.

    The first domain there is, which is the default one while it exists. Not
    a name written here: the engine should not have to be edited to add an
    industry, and that includes learning which one is the front page.
    """
    from chains import domains
    found = domains.discover()
    return found[0] if found else domain()

# The custom domain, served from the root of the site rather than per map.
CUSTOM_DOMAIN = "linchpinsignal.com"


def write_landing(src: Path, dom: str, live: list[str] | None = None) -> Path:
    """site/index.html: the front door, built from the files in ``src``.

    Called after they are copied, so every number on it and every capability it
    describes is read from what is actually about to be served.
    """
    from chains import landing
    p = site_root() / "index.html"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(landing.render(src, dom, f"https://{CUSTOM_DOMAIN}/",
                                live=live),
                 encoding="utf-8", newline="\n")
    return p


def copy_detail_pages(built: Path, track: Path) -> list[str]:
    """The per-question pages, at /<domain>/track/<qid>/.

    Named after their question, so they are found rather than listed the way
    index.html is -- and every one that is found goes through the same two
    gates as the page above it: no Hebrew, and no locked question's sentence.
    A directory with no index.html in it is not a page and is not copied.
    """
    out: list[str] = []
    if not built.is_dir():
        return out
    for src in sorted(built.glob("*/index.html")):
        qdir = track / src.parent.name
        qdir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, qdir / "index.html")
        out.append(f"track/{src.parent.name}/index.html")
    return out


def publish(dst: Path | None = None,
            dom: str | None = None) -> tuple[Path, list[str]]:
    """Copy one domain in, then gate it. Returns (site dir, what was written).

    ``dom`` is threaded rather than read from the environment inside each
    helper, so one process can publish several maps in turn without editing
    the environment underneath itself between them.
    """
    dom = dom or domain()
    site = dst or site_dir(dom)
    site.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    hebrew = publishes_hebrew(dom)
    # An English-only map leaves its Hebrew half behind, and says so rather
    # than skipping in silence: a file that stops being published is exactly
    # the sort of change that should be visible in the run's output.
    stale = [n for n in HE_ONLY if not hebrew and (site / n).exists()]
    for src_name, dst_name in COPIES:
        if dst_name in HE_ONLY and not hebrew:
            continue
        src = out_dir(dom) / src_name
        if not src.exists():
            raise SystemExit(
                f"{src} is missing. Run python -m chains.build_all first; "
                f"publishing a partial site would serve a page whose data "
                f"file is last week's.")
        shutil.copyfile(src, site / dst_name)
        written.append(dst_name)

    for pattern, dst_name in BRIEFS:
        if dst_name in HE_ONLY and not hebrew:
            continue
        src = latest(pattern, dom)
        if src is None:
            raise SystemExit(f"no {pattern} in {out_dir()}")
        shutil.copyfile(src, site / dst_name)
        written.append(f"{dst_name}  (from {src.name})")

    # A map that used to publish Hebrew and no longer declares it would
    # otherwise keep serving the last Hebrew page it ever built, from a
    # directory nothing rewrites.
    for name in stale:
        (site / name).unlink()
        written.append(f"{name}  (REMOVED -- this map declares English only)")

    # The forward test lives at /<domain>/track/, so a reader can be sent to
    # the evidence without being sent to the whole map.
    track = site / "track"
    track.mkdir(parents=True, exist_ok=True)
    for src_name, dst_name in TRACK_FILES:
        src = out_dir(dom) / src_name
        if not src.exists():
            raise SystemExit(
                f"{src} is missing. Run python -m chains.track first.")
        shutil.copyfile(src, track / dst_name)
        written.append(f"track/{dst_name}")

    for name in TRACK_ASSETS:
        src = out_dir(dom) / "track" / name
        if not src.exists():
            raise SystemExit(
                f"{src} is missing. Run python -m chains.track first; the "
                f"question pages load it, and publishing without it would "
                f"serve pages whose charts cannot draw.")
        shutil.copyfile(src, track / name)
        written.append(f"track/{name}")

    detail_pages = copy_detail_pages(out_dir(dom) / "track", track)
    written.extend(detail_pages)

    (site_root() / ".nojekyll").write_text("", encoding="utf-8")
    written.append("../.nojekyll")
    (site_root() / "CNAME").write_text(CUSTOM_DOMAIN + "\n",
                                       encoding="utf-8",
                                       newline="\n")
    written.append("../CNAME")
    # The front door, read from the files just copied beside it.
    if site.name == root_domain():
        from chains import domains as registry
        write_landing(site, site.name, registry.discover())
        written.append("../index.html  (landing page)")

    # Nothing unsealed, ever. Checked on the directory about to be served
    # rather than inferred from the copy list above.
    for stray in sorted(track.rglob("*")):
        if stray.name == TRACK_PLAINTEXT:
            raise SystemExit(
                f"{stray} is the unencrypted tracking payload and it is about "
                f"to be published. Remove it; only track.enc.json ships.")

    for name in ("track/index.html", "track/track.enc.json",
                 *(f"track/{a}" for a in TRACK_ASSETS), *detail_pages):
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
    leaked = locked_text_in_site(site, dom)
    if leaked:
        raise SystemExit(
            f"a locked question's text reached the site: {leaked[:3]}. "
            f"Not published.")
    return site, written


def locked_text_in_site(site: Path, dom: str | None = None) -> list[str]:
    """Any locked question whose sentence appears in a published file.

    ``dom`` names the map being gated. It matters twice over: the question
    text fetched below is that domain's section of the corpus, and so is the
    marks file scanned at the end. Reading the first domain's instead would
    clear a second industry's site against the wrong sentences -- a gate that
    passes by looking somewhere else is worse than no gate. This is not
    hypothetical: ``--all-domains`` publishes every map from one process and
    sets nothing in the environment, so a fetch with no domain to go on falls
    back to the first map and is handed ids the second one never heard of.

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
        text = questions.fetch(dom=dom)
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
    # The per-question pages carry a resolved question's whole text, and they
    # are named after the question -- so they cannot be listed in PAYWALLED
    # ahead of time. They are found here instead: belonging to a resolved
    # question is what makes them legal, and this scan is what proves it.
    for p in sorted((site / "track").glob("*/index.html")):
        blobs[f"track/{p.parent.name}/index.html"] = p.read_text(encoding="utf-8")
    # marks.json is not served, but it IS committed to a public repository by
    # the mark workflow, and an evidence line or a note that quoted the
    # question back would put a locked sentence in git for good. Same scan,
    # same sentences, one more file.
    from chains.paths import REPO_ROOT, marks_path
    mp = marks_path(dom)
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


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", default=None,
                    help="which map under data/ to publish")
    ap.add_argument("--all-domains", action="store_true",
                    help="publish every domain found under data/, in order")
    args = ap.parse_args(argv)
    if args.all_domains:
        from chains import domains as registry
        found = registry.discover()
        if not found:
            print(f"no buildable domain under {registry.root()}")
            return 1
        rc = 0
        for dom in found:
            print(f"\n=== {dom} " + "=" * (60 - len(dom)))
            rc = _one(dom) or rc
        return rc
    return _one(args.domain)


def _one(dom: str | None = None) -> int:
    site, written = publish(dom=dom)
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
