"""The map's edge set: every node connected, every edge sourced.

v2.2 added 45 supplier->customer edges and took the map from 34 to 79. Before
that, 15 of the 49 nodes had no edge at all -- they were drawn on the map and
connected to nothing, which reads as "this company supplies nobody" rather than
"nobody wrote the edge yet". These tests fail on any future map that
reintroduces one.
"""
from __future__ import annotations

import datetime as dt

import pytest

from chains import mapfile

DOC = mapfile.load()
NODE_IDS = {n["id"] for n in DOC["nodes"]}
EDGES = DOC.get("edges", [])


def test_the_map_has_edges_at_all():
    assert len(EDGES) >= 79, "v2.2 carries 79; a smaller number means loss"


@pytest.mark.parametrize("nid", sorted(NODE_IDS))
def test_every_node_appears_in_at_least_one_edge(nid):
    """A node with no edge is a company drawn on a supply-chain map that the
    map says supplies nobody and is supplied by nobody. That is a claim, and it
    is almost always a false one."""
    touched = any(e.get("from") == nid or e.get("to") == nid for e in EDGES)
    assert touched, f"{nid} appears in no edge"


def test_no_edge_points_at_something_that_is_not_a_node():
    """The page draws every edge it is given, so a dangling endpoint is a line
    to nowhere rather than a silently skipped record."""
    dangling = [(e.get("from"), e.get("to")) for e in EDGES
                if e.get("from") not in NODE_IDS or e.get("to") not in NODE_IDS]
    assert dangling == []


def test_no_edge_points_at_itself():
    assert [(e["from"], e["to"]) for e in EDGES if e["from"] == e["to"]] == []


def test_edges_are_unique_by_endpoints():
    seen = [(e.get("from"), e.get("to")) for e in EDGES]
    dupes = {p for p in seen if seen.count(p) > 1}
    assert dupes == set(), f"duplicate edges: {dupes}"


# Two cohorts, and conflating them would either fail on the legacy edges or
# excuse the new ones. The original 34 predate the provenance convention and
# carry what/criticality/source. The 45 added in v2.2 also carry share and
# as_of. The floor below is what stops the newer standard being lost.
SOURCED = [e for e in EDGES if e.get("as_of")]
V22_EDGE_FLOOR = 45


@pytest.mark.parametrize("field", ["what", "source", "criticality"])
def test_every_edge_carries_the_universal_fields(field):
    """An edge with no source is an assertion rather than a finding."""
    missing = [(e.get("from"), e.get("to")) for e in EDGES if not e.get(field)]
    assert missing == [], f"{len(missing)} edge(s) with no {field}: {missing[:5]}"


def test_a_source_may_be_a_named_filing_rather_than_a_url():
    """Five edges cite "Astera Labs FY2025 10-K" and the like. A named SEC
    filing is stronger provenance than a link, not weaker: it survives the URL
    rotting. So the requirement is that a source identifies something, not that
    it is clickable."""
    assert all(len(str(e.get("source", "")).strip()) > 8 for e in EDGES)


def test_the_sourced_cohort_does_not_shrink():
    assert len(SOURCED) >= V22_EDGE_FLOOR, (
        f"{len(SOURCED)} edges carry an as_of; v2.2 established "
        f"{V22_EDGE_FLOOR}. Losing provenance is a regression."
    )


@pytest.mark.parametrize("field", ["share", "as_of"])
def test_the_sourced_cohort_carries_the_stricter_fields(field):
    missing = [(e.get("from"), e.get("to")) for e in SOURCED if field not in e]
    assert missing == [], f"{field} absent on {missing[:5]}"


def test_share_is_present_even_where_it_is_null():
    """Present-and-null says "no percentage is disclosed" -- true of 22 of the
    45, where the filing names the relationship without quantifying it. An
    ABSENT key would say "nobody looked", and the page cannot tell those apart.
    An invented number would be worse than either."""
    assert all("share" in e for e in SOURCED)
    assert any(e.get("share") is None for e in SOURCED)


def test_every_as_of_is_a_real_date():
    bad = []
    for e in SOURCED:
        try:
            dt.date.fromisoformat(str(e.get("as_of")))
        except (ValueError, TypeError):
            bad.append((e.get("from"), e.get("to"), e.get("as_of")))
    assert bad == []


def test_criticality_is_one_of_the_known_levels():
    assert {e.get("criticality") for e in EDGES} <= {"high", "medium", "low"}
