"""The site's own copy, for the pages that belong to no single map.

    data/site.json

WHY A FILE AND NOT A CONSTANT
-----------------------------
Every map already keeps its own vocabulary in its own map.json -- its name,
its value line, its layers, its benchmark -- because the engine should not
have to be edited to add an industry. The front door has the same problem one
level up: its headline describes the whole site, and while there was one map
that headline could be the map's own sentence and nobody noticed. With two it
has to say something neither map says alone, and a sentence typed into the
template would be site copy living in the engine -- exactly what the map files
exist to prevent, one scope out.

So the words live beside the maps they are about, in data/, and the engine
reads them. A site that declares nothing gets the empty string and the page
falls back to the wording it already had: adding this file cannot change a
page that does not ask for it.

WHAT BELONGS HERE AND WHAT DOES NOT
------------------------------------
Copy about the SITE. Not copy about a map -- that is the map's own file, and
splitting one industry's words across two places is how they drift. Not
numbers: every figure on the front door is read from what is published, and a
number typed here would be true on the day somebody typed it.
"""
from __future__ import annotations

import json

FILENAME = "site.json"


def path():
    from chains.paths import data_root
    return data_root() / FILENAME


def load() -> dict:
    """The site file, or an empty one. Never raises on absence.

    Absence is a valid state -- it is what every site looked like before this
    file existed -- and it has to stay valid, or this module becomes a file
    every deployment is required to carry to build at all.
    """
    p = path()
    if not p.exists():
        return {}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as e:
        raise ValueError(f"{p} is not valid JSON ({e})") from None
    return doc if isinstance(doc, dict) else {}


def copy(*keys: str, default: str = "") -> str:
    """One string, by its path through the file. Missing reads as ``default``.

    English only, and not by accident: these are the pages the public product
    is served in, and chains/publish_site.py refuses to publish a Hebrew
    character in any of them. A site file that offered a Hebrew key would be
    offering a value that cannot be used.
    """
    node: object = load()
    for k in keys:
        if not isinstance(node, dict):
            return default
        node = node.get(k)
    return str(node).strip() if isinstance(node, str) and node.strip() \
        else default


__all__ = ["load", "copy", "path", "FILENAME"]
