"""The data behind focus mode, checked without a browser.

Every supplier link carries a group the map names in both languages; the two
Spruce Pine producers carry the chokepoint flag; and the rows the page draws
are exactly the links straight into a station, once per supplier.
"""
from __future__ import annotations

import json

from chains import build_pages as bp
from chains import live_snapshot
from chains.paths import map_path

MAP = json.loads(map_path().read_text(encoding="utf-8"))
GROUPS = (MAP.get("labels") or {}).get("groups") or {}


def test_every_supplier_link_names_a_group_the_map_defines():
    links = [e for e in MAP["edges"] if e.get("type") == "supplies"] + MAP["sub_edges"]
    missing = [(e["from"], e["to"]) for e in links if e.get("group") not in GROUPS]
    assert missing == [], f"{len(missing)} link(s) without a known group: {missing[:5]}"


def test_every_group_is_named_in_both_languages_and_used():
    assert GROUPS
    for key, names in GROUPS.items():
        assert names.get("en") and names.get("he"), key
        assert not bp.hebrew_runs(names["en"]), key
    used = {e.get("group") for e in MAP["edges"] + MAP["sub_edges"]}
    assert set(GROUPS) <= used, f"defined but unused: {set(GROUPS) - used}"


def test_the_spruce_pine_producers_are_the_flagged_chokepoint_subnodes():
    flagged = sorted(s["id"] for s in MAP["subnodes"] if s.get("chokepoint"))
    assert flagged == ["quartz_corp", "sibelco_spruce_pine"]
    assert all(s.get("chokepoint") is True for s in MAP["subnodes"] if s["id"] in flagged)


def test_focus_rows_are_the_links_straight_into_a_station():
    f = live_snapshot.focus_for(MAP, "en")
    into = lambda sid: [r["from"] for r in f["up"] if r["to"] == sid]  # noqa: E731
    assert set(into("shinetsu")) == {"hemlock", "wacker", "tokuyama", "quartz_crucibles",
                                     "fujimi_wafer", "toyo_gosei", "maruzen_petrochem"}
    for sid in ("shinetsu", "tsmc", "nvda"):
        assert len(into(sid)) == len(set(into(sid))), f"{sid}: a supplier listed twice"
    assert {"intc", "samsung"}.isdisjoint(into("tsmc")), "substitutes are not suppliers"
    assert "sibelco_spruce_pine" not in into("shinetsu"), "it feeds the crucible makers"
    assert all(r["g"] in f["groups"] and r["w"] in (1, 2, 3) for r in f["up"])


def test_focus_names_subnodes_and_carries_their_flags():
    f = live_snapshot.focus_for(MAP, "en")
    node_ids = {n["id"] for n in MAP["nodes"]}
    for r in f["up"]:
        assert r["from"] in node_ids or r["from"] in f["subs"], r
    assert f["subs"]["quartz_crucibles"]["name"].startswith("Quartz crucible makers")
    assert f["subs"]["quartz_crucibles"]["cp"] is False
    he = live_snapshot.focus_for(MAP, "he")
    assert he["groups"]["quartz"] == GROUPS["quartz"]["he"]
    assert f["groups"]["quartz"] == GROUPS["quartz"]["en"]


def test_the_second_tier_is_the_set_the_panel_lists_beneath_them():
    f = live_snapshot.focus_for(MAP, "en")
    under = {(r["from"], r["to"]) for r in f["under"] if r["at"] == "shinetsu"}
    assert under == {("sibelco_spruce_pine", "quartz_crucibles"), ("quartz_corp", "quartz_crucibles")}
    # TSMC holds CP3 and CP4: the panel lists one beneath each. CP4's --
    # Ajinomoto Fine-Techno, on Ajinomoto's line -- IS Ajinomoto, so it is drawn
    # as that station, once, beside Ibiden, carrying what the entry supplies.
    assert {(r["from"], r["to"]) for r in f["under"] if r["at"] == "tsmc"} == {
        ("neon_chain", "linde"), ("ajinomoto", "ibiden")}
    aji = next(r for r in f["under"] if r["at"] == "tsmc" and r["from"] == "ajinomoto")
    assert aji["what"], "the absorbed entry's text rides on the station"
    assert "ajinomoto" not in {r["from"] for r in f["up"] if r["to"] == "tsmc"}, "not drawn twice"
    for r in f["under"]:
        assert r["to"] in {u["from"] for u in f["up"] if u["to"] == r["at"]}, "a child is drawn beside its parent"
        node_ids = {n["id"] for n in MAP["nodes"]}
        assert (r["from"] in f["subs"] or r["from"] in node_ids) and r["w"] in (1, 2, 3)
    assert f["subs"]["sibelco_spruce_pine"]["cp"] is True and f["subs"]["quartz_corp"]["cp"] is True


def test_no_display_name_carries_a_note():
    """A name is a name: a dash aside, a cross-reference or a long parenthetical
    is a curator's note and lives in ``note``."""
    import re
    bad = [(s["id"], s["name"]) for coll in ("nodes", "subnodes") for s in MAP[coll]
           if "—" in s["name"] or "see CP" in s["name"]
           or any(len(p) > 20 for p in re.findall(r"\(([^)]*)\)", s["name"]))]
    assert bad == []


def test_a_supplier_that_is_also_a_station_is_drawn_once_as_the_station():
    f = live_snapshot.focus_for(MAP, "en")
    into = lambda sid: [r["from"] for r in f["up"] if r["to"] == sid]  # noqa: E731
    t = into("tsmc")
    assert "kla" not in t and "lam" not in t
    assert t.count("klac") == 1 and t.count("lrcx") == 1
    subs = {s["id"]: s for s in MAP["subnodes"]}
    for station, sub in (("klac", "kla"), ("lrcx", "lam")):
        row = next(r for r in f["up"] if r["from"] == station and r["to"] == "tsmc")
        assert subs[sub]["what"].strip() in row["what"], (station, row.get("what"))
    assert {"cymer", "berliner_glas"} <= set(into("asml")), "a subsidiary feeding its own station stays itself"
    assert "cloud_eda" in into("snps"), "a category priced by one member is not that member"


def test_no_two_focus_labels_carry_the_same_company_name():
    f = live_snapshot.focus_for(MAP, "en")
    names = {n["id"]: n["name"] for n in MAP["nodes"]}
    name = lambda i: names.get(i) or f["subs"][i]["name"]  # noqa: E731
    for sid in names:
        labels = ([name(r["from"]) for r in f["up"] if r["to"] == sid and r["from"] != sid]
                  + [name(r["from"]) for r in f["under"] if r["at"] == sid])
        low = [x.casefold() for x in labels]
        assert len(low) == len(set(low)), (sid, sorted({x for x in low if low.count(x) > 1}))


def test_every_note_rides_to_the_page():
    f = live_snapshot.focus_for(MAP, "en")
    assert f["notes"] == {s["id"]: s["note"] for s in MAP["subnodes"] if s.get("note")}
    assert len(f["notes"]) >= 51


def test_the_focus_files_are_published_and_gated():
    from chains import publish_site
    assert ("focus_en.json", "focus_en.json") in publish_site.COPIES
    assert ("focus.json", "focus.json") in publish_site.COPIES
    assert "focus_en.json" in publish_site.GATED, "the English file is checked for Hebrew"
    assert {"focus.json", "focus_en.json"} <= set(publish_site.PAYWALLED)


def test_fujimi_is_named_fujimi_and_keeps_its_note():
    s = next(s for s in MAP["subnodes"] if s["id"] == "fujimi_wafer")
    assert s["name"] == "Fujimi"
    assert s["note"] == "wafer polishing slurry — see CP3 fujimi"


def test_the_english_focus_rows_carry_no_hebrew():
    blob = json.dumps(live_snapshot.focus_for(MAP, "en"), ensure_ascii=False)
    assert bp.hebrew_runs(blob) == []
