"""Where chip-map reads and writes. Everything from the environment.

    CHIP_MAP_DATA    curated input   default ./data
    CHIP_MAP_OUT     derived output  default ./out
    CHIP_MAP_SITE    what is served  default ./site
    CHIP_MAP_PRICES  price parquets  default ./out/prices
    EODHD_API_TOKEN  required by the prices step only
    ANSWERS_URL      optional; see chains/answers.py

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

MAP_FILENAME = "semi_chain_v2.json"
WATCH_FILENAME = "watch.json"
WATCH_EN_FILENAME = "watch_en.json"
FALLBACK_MAP_FILENAME = "semiconductors-ai-compute.json"
ANSWERS_FILENAME = "answers.json"

# chains/paths.py -> the repository root
REPO_ROOT = Path(__file__).resolve().parents[1]

# The page templates: hand-written HTML and JS, curated the same way the map
# is, read by chains/build_pages.py and never written by a scheduled run.
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

TOKEN_ENV = "EODHD_API_TOKEN"
ANSWERS_URL_ENV = "ANSWERS_URL"


def _dir(env: str, default: str) -> Path:
    """An environment override, or a path relative to the repository root."""
    v = os.environ.get(env)
    return Path(v).expanduser().resolve() if v else (REPO_ROOT / default)


def data_dir() -> Path:
    """Curated input: the map and the two watch lists. Tracked."""
    return _dir("CHIP_MAP_DATA", "data")


def out_dir() -> Path:
    """Derived output. Regenerable, large, gitignored."""
    return _dir("CHIP_MAP_OUT", "out")


def site_dir() -> Path:
    """What GitHub Pages serves. Assembled by chains/publish_site.py."""
    return _dir("CHIP_MAP_SITE", "site")


def prices_dir() -> Path:
    """The price parquets. Separately overridable because CI caches this one
    directory -- restoring it is what makes the weekly run incremental."""
    v = os.environ.get("CHIP_MAP_PRICES")
    return Path(v).expanduser().resolve() if v else (out_dir() / "prices")


def map_path() -> Path:
    """The curated map.

    ``CHIP_MAP_PATH`` overrides it for a one-off -- reading a candidate v3
    before it is committed, say -- but the default is always the tracked copy,
    so a run is reproducible from a commit hash alone.
    """
    override = os.environ.get("CHIP_MAP_PATH")
    if override:
        return Path(override)
    p = data_dir() / MAP_FILENAME
    return p if p.exists() else data_dir() / FALLBACK_MAP_FILENAME


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


def answers_path() -> Path:
    """The exported answers, when they arrive as a file rather than a URL."""
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
