"""The layer captions say what each column holds.

L3 is Arm, Cadence and Synopsys: they sell design tools and licences, not
chips, so "design" alone read as a column of chip designers. L4 is the fabless
designers and the memory IDMs, companies that sell chips under their own name:
chipmakers. L5 is where the chips are made and packaged.

2026-10-01: the semi closure split L4 into logic & accelerators (L4) and
memory & storage (L4b), and L5 took the package substrates.
"""
from __future__ import annotations

import json

from chains.paths import map_path

LAYERS = json.loads(map_path().read_text(encoding="utf-8"))["labels"]["layers"]


def test_l3_names_tools_and_licences():
    assert LAYERS["L3"] == {"he": "כלי תכנון", "en": "design tools & IP"}


def test_l4_is_logic_and_l4b_is_memory():
    assert LAYERS["L4"] == {"he": "לוגיקה ומאיצים", "en": "logic & accelerators"}
    assert LAYERS["L4b"] == {"he": "זיכרון ואחסון", "en": "memory & storage"}


def test_l5_names_the_substrates_it_now_holds():
    assert LAYERS["L5"] == {"he": "ייצור, אריזה ומצעים", "en": "fab, packaging & substrates"}


def test_every_sub_column_sorts_after_its_parent():
    keys = sorted(k for k in LAYERS if k != "L9")
    assert keys == ["L1", "L1b", "L2", "L3", "L4", "L4b", "L5", "L6", "L6b", "L6c", "L7"]
