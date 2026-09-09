"""Where chip-map reads and writes. Everything from the environment.

    CHIP_MAP_DOMAIN  which map to build   default "semi"
    CHIP_MAP_DATA    curated input   default ./data
    CHIP_MAP_OUT     derived output  default ./out
    CHIP_MAP_SITE    what is served  default ./site
    CHIP_MAP_PRICES  price parquets  default ./out/prices
    EODHD_API_TOKEN  required by the prices step only
    QUESTIONS_URL    required; the question text, see chains/questions.py
    ANSWERS_URL      optional; see chains/answers.py
    SIGNUP_URL       optional; where the page's CTA points

ONE ENGINE, MANY MAPS
---------------------
Everything under data/ is namespaced by DOMAIN: data/semi/ holds the
semiconductor map and its questions, and a second domain is a second directory
with the same three files. Nothing in the package knows what a chokepoint is
made of -- the layer names, the metro lines and their colours, the board's
lanes and every chokepoint's title all live in the map's ``labels`` block, so
the same code draws a different industry by reading a different file.

That is checked mechanically in tests/test_isolation.py: the package may not
contain the vocabulary of any one domain.

INPUT IS TRACKED, OUTPUT IS NOT
-------------------------------
``data/`` holds the curated artifacts: the map, and the two dated-question
lists. Every claim in the map carries a source URL and an ``as_of`` date, and it
changes only when a person decides it should. That is source, it is reviewed in
a diff, and it is in git.

Everything under ``out/`` and ``site/`` is regenerable by definition -- prices
pulled from a vendor, filings pulled from EDGAR, the pages built from both. It
is large, it changes every week, and it is gitignored. A weekly build that
committed its own output would turn the history into a log of vendor responses.

NO ABSOLUTE PATHS, AND NO PATH OUT OF THE REPO
-----------------------------------------------
Every default is relative to the repository root, so a fresh clone builds with
no configuration at all and CI needs only the token. The previous version of
this file resolved a path into a sibling project's tree; that is what tied the
build to one laptop, and it is what this repo exists to undo. The rule is
checked mechanically in tests/test_isolation.py: no module here may name a path
that leaves the repository, and none may import the strategy package this came
from.

The overrides exist for CI, which puts the price cache where the cache action
can restore it, and for a one-off run against a candidate map.
"""
from __future__ import annotations

import os
from pathlib import Path

MAP_FILENAME = "map.json"
WATCH_FILENAME = "watch.json"
WATCH_EN_FILENAME = "watch_en.json"
ANSWERS_FILENAME = "answers.json"
MARKS_FILENAME = "marks.json"

DOMAIN_ENV = "CHIP_MAP_DOMAIN"
DEFAULT_DOMAIN = "semi"

# chains/paths.py -> the repository root
REPO_ROOT = Path(__file__).resolve().parents[1]

# The page templates: hand-written HTML and JS, curated the same way the map
# is, read by chains/build_pages.py and never written by a scheduled run.
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

TOKEN_ENV = "EODHD_API_TOKEN"
ANSWERS_URL_ENV = "ANSWERS_URL"
SIGNUP_URL_ENV = "SIGNUP_URL"


def _dir(env: str, default: str) -> Path:
    """An environment override, or a path relative to the repository root."""
    v = os.environ.get(env)
    return Path(v).expanduser().resolve() if v else (REPO_ROOT / default)


def domain() -> str:
    """Which map this build is about. One word, and it names a directory."""
    v = os.environ.get(DOMAIN_ENV, "").strip() or DEFAULT_DOMAIN
    if not v.isidentifier():
        raise SystemExit(f"{DOMAIN_ENV}={v!r} is not a plain name")
    return v


def data_root() -> Path:
    """Everything curated, for every domain."""
    return _dir("CHIP_MAP_DATA", "data")


def data_dir(dom: str | None = None) -> Path:
    """Curated input for one domain: its map and its two watch lists."""
    return data_root() / (dom or domain())


def out_dir(dom: str | None = None) -> Path:
    """Derived output for one domain. Regenerable, large, gitignored."""
    return _dir("CHIP_MAP_OUT", "out") / (dom or domain())


def site_root() -> Path:
    """What GitHub Pages serves, across every domain."""
    return _dir("CHIP_MAP_SITE", "site")


def site_dir(dom: str | None = None) -> Path:
    """One domain's corner of the site: /<domain>/index.html and its data."""
    return site_root() / (dom or domain())


def prices_dir() -> Path:
    """The price parquets. Separately overridable because CI caches this one
    directory -- restoring it is what makes the weekly run incremental."""
    # Not per-domain: two maps naming the same company should not download it
    # twice, and a price series is the same series whoever is looking at it.
    v = os.environ.get("CHIP_MAP_PRICES")
    return (Path(v).expanduser().resolve() if v
            else _dir("CHIP_MAP_OUT", "out") / "prices")


def map_path() -> Path:
    """The curated map.

    ``CHIP_MAP_PATH`` overrides it for a one-off -- reading a candidate v3
    before it is committed, say -- but the default is always the tracked copy,
    so a run is reproducible from a commit hash alone.
    """
    override = os.environ.get("CHIP_MAP_PATH")
    if override:
        return Path(override)
    return data_dir() / MAP_FILENAME


def watch_path() -> Path:
    """The dated-questions list. Curated input, tracked beside the map."""
    return data_dir() / WATCH_FILENAME


def watch_en_path() -> Path:
    """The English dated-questions list, generated beside the Hebrew one.

    Two files rather than one file with two language columns: the public page
    is English-only and must not carry a Hebrew string anywhere, and the
    cheapest way to guarantee that is for the English build never to open the
    Hebrew file at all.
    """
    return data_dir() / WATCH_EN_FILENAME


def marks_path(dom: str | None = None) -> Path:
    """The marks: what was answered, and the forecasts made from it.

    Curated input, tracked beside the map, and written by a cloud task that
    commits to main through the contents API. That is deliberate: a mark is a
    claim with a date on it, and putting it in git gives it a commit hash and a
    diff instead of a row in somebody's spreadsheet. The forecast ledger's
    whole argument rests on the baskets having been registered before the
    event; the marks belong in the same place for the same reason.
    """
    return data_dir(dom) / MARKS_FILENAME


def answers_path() -> Path:
    """A local override, for a by-hand run. Not written by anything."""
    return out_dir() / ANSWERS_FILENAME


def templates_dir() -> Path:
    """Where the page templates live. Read-only for every scheduled run."""
    return TEMPLATES_DIR


def api_token() -> str:
    """The EODHD token. Only the prices step needs it.

    Read here rather than inside the client so the failure is one clear line at
    the top of the step that needs it, instead of a stack trace out of an HTTP
    library. Every other step runs without it.
    """
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        raise SystemExit(
            f"{TOKEN_ENV} is not set. The prices step needs it; every other "
            f"step does not. In CI it comes from the repository secret.")
    return token


def answers_url() -> str | None:
    """Where to GET the answers, if they are published rather than local."""
    return os.environ.get(ANSWERS_URL_ENV, "").strip() or None


def signup_url() -> str | None:
    """Where the page's call to action points.

    Unset is a normal state, not a missing configuration: the newsletter lives
    on a platform that is not wired up yet, and until it is the page says so
    rather than offering a button that goes nowhere.
    """
    return os.environ.get(SIGNUP_URL_ENV, "").strip() or None
