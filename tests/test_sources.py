"""Sources are lists, and every reference gets a link of its own.

A source used to be one string, and several were joined with " ; ". The panel
put that whole string into a single href, which opened nothing. The map now
keeps several references as a list; this file holds it there, holds the two
readers of it -- the snapshot and the panel -- to one link per reference, and
holds the two Spruce Pine quartz producers to what their sources say.
"""
from __future__ import annotations

import json

import pytest

from chains import live_snapshot
from chains.paths import map_path, out_dir, templates_dir

MAP = json.loads(map_path().read_text(encoding="utf-8"))
TPL = (templates_dir() / "live-map.html").read_text(encoding="utf-8")
SOURCE_KEYS = ("source", "signal_source")

CNN = "https://www.cnn.com/2024/10/02/tech/semiconductor-supply-chain-north-carolina-helene/index.html"
AP = "https://www.inc.com/associated-press/helene-destroyed-a-town-thats-the-source-of-quartz-for-most-tech-products/90983974"
USGS = "https://pubs.usgs.gov/periodicals/mcs2026/mcs2026-quartz.pdf"
CPHYS = "https://www.construction-physics.com/p/does-all-semiconductor-manufacturing"


def _source_fields(o, path="$"):
    if isinstance(o, dict):
        for k, v in o.items():
            p = f"{path}.{k}"
            if k in SOURCE_KEYS:
                yield p, v
            else:
                yield from _source_fields(v, p)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _source_fields(v, f"{path}[{i}]")


# -- the file ----------------------------------------------------------------------

def test_no_source_field_joins_references_with_a_semicolon():
    bad = [p for p, v in _source_fields(MAP)
           for ref in (v if isinstance(v, list) else [v])
           if isinstance(ref, str) and " ; " in ref]
    assert bad == [], f"{len(bad)} joined source field(s): {bad[:5]}"


def test_a_source_list_holds_only_real_references():
    for p, v in _source_fields(MAP):
        if isinstance(v, list):
            assert v, f"{p}: an empty list is no source"
            assert all(isinstance(r, str) and r and r == r.strip() for r in v), p


# -- the two Spruce Pine producers --------------------------------------------------

SPRUCE_PINE = [
    ("sibelco_spruce_pine", "Sibelco",
     [USGS, "https://www.sibelco.com/en/materials/high-purity-quartz", CPHYS]),
    ("quartz_corp", "Quartz Corp",
     [USGS, "https://www.thequartzcorp.com/articles/history", CPHYS]),
]
SUBS = {s["id"]: s for s in MAP["subnodes"]}


@pytest.mark.parametrize("sid,short,refs", SPRUCE_PINE)
def test_a_spruce_pine_producer_stays_where_it_was(sid, short, refs):
    s = SUBS[sid]
    assert (s["tier"], s["supplies_to"], s["chokepoint_ids"]) == \
        (2, "quartz_crucibles", ["CP6"])
    assert s["sole_source"] is False


@pytest.mark.parametrize("sid,short,refs", SPRUCE_PINE)
def test_a_spruce_pine_producer_has_a_short_canvas_name(sid, short, refs):
    s = SUBS[sid]
    assert s["short"] == short
    assert len(s["name"]) > len(short), "the full name stays for the panel row"


@pytest.mark.parametrize("sid,short,refs", SPRUCE_PINE)
def test_the_share_is_an_estimate_with_what_it_rests_on(sid, short, refs):
    """80-90% is what CNN reports, and CNN adds that the exact amount is
    proprietary. AP names both producers and gives no figure. Nothing else
    rides on the share line: the tonnage is a separate estimate, in notes."""
    sh = SUBS[sid]["share"]
    assert sh == {"value": "80–90% (industry estimate)", "source": [CNN, AP],
                  "as_of": "2024-10", "note": "no producer publishes a figure"}


@pytest.mark.parametrize("sid,short,refs", SPRUCE_PINE)
def test_the_row_cites_usgs_2026_and_the_producer(sid, short, refs):
    s = SUBS[sid]
    assert s["source"][:len(refs)] == refs
    assert s["as_of"] == "2026-01"


# -- the snapshot -------------------------------------------------------------------

def test_the_snapshot_reads_any_source_as_a_list():
    assert live_snapshot.sources(None) == []
    assert live_snapshot.sources("") == []
    assert live_snapshot.sources(" https://a.example/x ") == ["https://a.example/x"]
    assert live_snapshot.sources(["https://a.example", "", "10-K"]) == \
        ["https://a.example", "10-K"]


def test_share_text_is_cut_where_a_sentence_ends():
    clip = live_snapshot.clip
    assert clip("Short enough.", 90) == "Short enough."
    long = ("Wacker + Hemlock ~75% of semiconductor-grade polysilicon; one of "
            "only five producers at leading-edge purity worldwide")
    out = clip(long, 90)
    assert out == "Wacker + Hemlock ~75% of semiconductor-grade polysilicon…"
    assert len(out) <= 90


def test_without_a_sentence_end_the_cut_is_a_whole_word():
    out = live_snapshot.clip("word " * 40, 60)
    assert out.endswith("word…") and len(out) <= 60
    assert live_snapshot.clip("s" * 400, 60) == "s" * 59 + "…"


def _fresh_snapshot():
    p = out_dir() / "live_en.json"
    if not p.exists() or p.stat().st_mtime < map_path().stat().st_mtime:
        pytest.skip("live_en.json not built since the last map change")
    return json.loads(p.read_text(encoding="utf-8"))


def test_the_built_snapshot_carries_lists_and_short_names():
    live = _fresh_snapshot()
    rows = [r for c in live["cps"] for coll in ("subs", "sigs") for r in c[coll]]
    assert all(isinstance(r["src"], list) for r in rows)
    assert not [r for r in rows for u in r["src"] if " ; " in u]
    cp6 = {s["id"]: s for s in next(c for c in live["cps"] if c["id"] == "CP6")["subs"]}
    for sid, short, refs in SPRUCE_PINE:
        row = cp6[sid]
        assert row["short"] == short
        assert row["share"] == "80–90% (industry estimate)"
        assert row["src"] == [CNN, AP]
        assert row["refs"][:len(refs)] == refs


# -- the panel ----------------------------------------------------------------------

def test_no_row_puts_a_source_straight_into_an_href():
    assert 'href="${s.src}"' not in TPL


def test_the_supplier_and_challenger_rows_cite_one_link_per_reference():
    # One builder, shared by the rows of a chokepoint a station holds and one it
    # is exposed to.
    i = TPL.index("const subRow=s=>")
    row = TPL[i:TPL.index("\n", i)]
    assert "srcCited(s.share,s.src)" in row and "srcLinks(s.refs,' · ')" in row
    assert "${srcCited(s.signal,s.src)}" in TPL
    assert "const srcRefs=v=>(Array.isArray(v)?v:(v?[v]:[])).filter(Boolean);" in TPL
    assert "r.filter((u,k)=>k!==i).map(srcLink)" in TPL


def test_a_focus_label_is_the_full_name_and_the_panel_keeps_it():
    """The satellite fan that drew the short canvas names is gone. Focus mode
    names a supplier in full, and ``short`` stays in the data for the rest."""
    assert "name:st?st.name:sub.name" in TPL
    assert "label:(o.s.short" not in TPL
