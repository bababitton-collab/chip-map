"""Which maps this engine can build, found by looking rather than by listing.

    from chains import domains
    domains.discover()          -> ["semi", ...]
    domains.missing("energy")   -> ["watch_en.json"]

WHY DISCOVERY AND NOT A REGISTRY FILE
-------------------------------------
A domain is a directory under ``data/`` holding a map and its two question
lists. That is the whole definition, so a list of domains kept anywhere else
would be a second source of truth that can disagree with the directory -- and
the failure mode of disagreement is a domain that exists on disk and is never
built, or one that is built and is not there. Adding an industry is adding a
directory; nothing here has to be edited for it.

The first domain is first because of where it sorts, not because the engine
knows its name. ``paths.DEFAULT_DOMAIN`` leads when it is present -- it is what
a bare command builds, so it is what a report should list first -- and the rest
follow in alphabetical order. No domain is otherwise special.

WHAT MAKES A DIRECTORY A DOMAIN
-------------------------------
The three curated inputs a build cannot start without: the map, and the two
language watch lists. Everything else beside them is optional by design and
each absence already has a defined meaning elsewhere in the package -- no
commitments file is an unregistered domain, no marks file is a domain that has
not answered anything yet, and no glossary is a glossary with no terms. A
brand-new industry therefore builds from three files, and gains the rest as it
earns them.
"""
from __future__ import annotations

from pathlib import Path

from chains.paths import (COMMITMENTS_FILENAME, DEFAULT_DOMAIN, MAP_FILENAME,
                          MARKS_FILENAME, WATCH_EN_FILENAME, WATCH_FILENAME,
                          data_root)

# Without these there is nothing to build.
REQUIRED = (MAP_FILENAME, WATCH_FILENAME, WATCH_EN_FILENAME)


def _optional_names() -> tuple[str, ...]:
    """Files a domain may have. Imported late: this module is read by the
    path layer's callers, and the glossary is a consumer of that layer."""
    from chains.glossary import FILENAME as GLOSSARY_FILENAME
    return (COMMITMENTS_FILENAME, MARKS_FILENAME, GLOSSARY_FILENAME)


def root(where: Path | None = None) -> Path:
    return Path(where) if where is not None else data_root()


def missing(dom: str, where: Path | None = None) -> list[str]:
    """Which required files a candidate directory does not have."""
    d = root(where) / dom
    if not d.is_dir():
        return list(REQUIRED)
    return [n for n in REQUIRED if not (d / n).is_file()]


def is_domain(dom: str, where: Path | None = None) -> bool:
    return not missing(dom, where)


def present(dom: str, where: Path | None = None) -> list[str]:
    """Every file this domain actually has, required and optional."""
    d = root(where) / dom
    if not d.is_dir():
        return []
    return [n for n in (*REQUIRED, *_optional_names()) if (d / n).is_file()]


def discover(where: Path | None = None) -> list[str]:
    """Every buildable domain, the default one first and the rest by name.

    A directory that is half a domain -- a map with no question list, say --
    is NOT returned. It is a work in progress, and a build that picked it up
    would fail somewhere downstream with a message about a missing file
    instead of simply not building something that is not ready.
    """
    d = root(where)
    if not d.is_dir():
        return []
    found = sorted(p.name for p in d.iterdir()
                   if p.is_dir() and not missing(p.name, where))
    lead = [n for n in found if n == DEFAULT_DOMAIN]
    return lead + [n for n in found if n != DEFAULT_DOMAIN]


def require(dom: str, where: Path | None = None) -> str:
    """The domain, or one clear line saying what it is short of.

    Raised rather than returned: every caller of this is about to read those
    files, and a half-built domain should stop the run at the top with the
    list of what to add, not three steps later with a traceback.
    """
    gaps = missing(dom, where)
    if gaps:
        raise SystemExit(
            f"{dom!r} is not a buildable domain: {root(where) / dom} is "
            f"missing {', '.join(gaps)}. A domain is a directory holding "
            f"{', '.join(REQUIRED)}.")
    return dom


__all__ = ["REQUIRED", "discover", "is_domain", "missing", "present",
           "require", "root"]
