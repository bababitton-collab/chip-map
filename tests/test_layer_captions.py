"""The layer captions say what each column holds.

L3 is Arm, Cadence and Synopsys: they sell design tools and licences, not
chips, so "design" alone read as a column of chip designers. L4 is the fabless
designers and the memory IDMs, companies that sell chips under their own name:
chipmakers. L5 is where the chips are made and packaged, and keeps its name.
"""
from __future__ import annotations

import json

from chains.paths import map_path

LAYERS = json.loads(map_path().read_text(encoding="utf-8"))["labels"]["layers"]


def test_l3_names_tools_and_licences():
    assert LAYERS["L3"] == {"he": "כלי תכנון", "en": "design tools & IP"}


def test_l4_names_chipmakers():
    assert LAYERS["L4"] == {"he": "יצרני שבבים", "en": "chipmakers"}


def test_l5_is_unchanged():
    assert LAYERS["L5"] == {"he": "מפעל ואריזה", "en": "fab & packaging"}
