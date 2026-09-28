"""Search and filters on the map, and the link that carries them.

Three rules hold this together:

  one predicate   the rail's list and the canvas's dimming read the same
                  function, so the picture cannot disagree with the list
                  beside it
  counted, never  "n of N stations" is counted from the predicate every time
  typed           it is shown
  only real       a filter exists only where the map already carries the
  fields          field. There is no region filter because there is no region
                  in the data, and the field called `country` holds an
                  exchange (NASDAQ, XETRA, TSE), not a country.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from chains.paths import templates_dir

EN = "live-map-en.html"
SITE = Path(__file__).resolve().parents[1] / "site"


def tpl(name=EN):
    return (templates_dir() / name).read_text(encoding="utf-8")


def slice_between(src, start, end):
    i = src.index(start)
    return src[i:src.index(end, i)]


def node(script, tmp_path, name="t.js"):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    p = tmp_path / name
    p.write_text(script, encoding="utf-8")
    return subprocess.run(["node", str(p)], capture_output=True,
                          check=True).stdout.decode("utf-8")


# -- the predicate, run as shipped ---------------------------------------------
HARNESS = """
const LAYER_HE = {L1:'materials', L2:'equipment', L9:'power'};
let railQ = %(q)s;
const nodes = %(nodes)s;
function pulseOf(n){
  if(!n.cp || !n.cp.length) return null;
  const ps = n.cp.map(c=>c.pressure).filter(v=>v!=null);
  if(!ps.length) return {kind:'a'};
  const p = ps.reduce((a,b)=>a+b,0)/ps.length;
  return {kind: p>0?'t':'e', p};
}
%(block)s
Object.assign(FILTERS, %(filters)s);
process.stdout.write(JSON.stringify({
  matched: nodes.filter(nodeMatches).map(n=>n.id),
  narrowing: narrowing(),
  count: nodes.filter(nodeMatches).length + ' of ' + nodes.length}));
"""

NODES = [
    {"id": "a", "name": "Alpha Corp", "ticker": "ALP", "layer": "L1",
     "cp": [{"pressure": 0.2}]},                       # tightening
    {"id": "b", "name": "Beta Ltd", "ticker": "BET", "layer": "L1",
     "cp": [{"pressure": -0.3}]},                      # eroding
    {"id": "c", "name": "Gamma SA", "ticker": "GAM", "layer": "L2",
     "cp": [{"pressure": None}]},                      # unmeasured
    {"id": "d", "name": "Delta Inc", "ticker": "DEL", "layer": "L2",
     "cp": []},                                        # not on a chokepoint
    {"id": "e", "name": "Epsilon", "ticker": "EPS", "layer": "L9"},
]


def run(tmp_path, q="", **filters):
    src = tpl()
    block = slice_between(src, "const FILTERS = {layer:''",
                          "function matchSet()")
    js = HARNESS % {
        "q": json.dumps(q), "nodes": json.dumps(NODES),
        "block": block,
        "filters": json.dumps({k: v for k, v in filters.items()}),
    }
    return json.loads(node(js, tmp_path))


def test_no_search_and_no_filter_matches_everything(tmp_path):
    got = run(tmp_path)
    assert got["matched"] == ["a", "b", "c", "d", "e"]
    assert got["narrowing"] is False


def test_search_matches_name_ticker_and_layer(tmp_path):
    assert run(tmp_path, q="alpha")["matched"] == ["a"]
    assert run(tmp_path, q="BET")["matched"] == ["b"]
    # The layer's own name, which is how a reader finds a company they cannot
    # name -- and the reason "GE" also matches everything in "generation".
    assert run(tmp_path, q="equipment")["matched"] == ["c", "d"]


def test_search_is_case_insensitive(tmp_path):
    assert run(tmp_path, q="AlPhA")["matched"] == ["a"]


@pytest.mark.parametrize("kind,want", [
    ("tightening", ["a"]),
    ("eroding", ["b"]),
    ("unmeasured", ["c"]),
])
def test_the_pulse_filter_splits_the_three_states(kind, want, tmp_path):
    assert run(tmp_path, pulse=kind)["matched"] == want


def test_a_station_on_no_chokepoint_has_no_pulse_to_filter_by(tmp_path):
    """d and e sit on nothing, so no pulse value can select them. They are not
    quietly folded into "cannot be measured", which means something else."""
    for kind in ("tightening", "eroding", "unmeasured"):
        assert "d" not in run(tmp_path, pulse=kind)["matched"]
        assert "e" not in run(tmp_path, pulse=kind)["matched"]


def test_the_chokepoint_filter_is_a_yes_or_a_no(tmp_path):
    assert run(tmp_path, cp="yes")["matched"] == ["a", "b", "c"]
    assert run(tmp_path, cp="no")["matched"] == ["d", "e"]


def test_the_layer_filter_uses_the_maps_own_keys(tmp_path):
    assert run(tmp_path, layer="L1")["matched"] == ["a", "b"]
    assert run(tmp_path, layer="L9")["matched"] == ["e"]


def test_filters_combine_with_and(tmp_path):
    """Layer AND chokepoint AND pulse AND the search, all at once."""
    assert run(tmp_path, layer="L1", cp="yes")["matched"] == ["a", "b"]
    assert run(tmp_path, layer="L1", pulse="eroding")["matched"] == ["b"]
    assert run(tmp_path, q="alpha", layer="L1", cp="yes",
               pulse="tightening")["matched"] == ["a"]
    # One conjunct that excludes everything excludes everything.
    assert run(tmp_path, layer="L9", pulse="tightening")["matched"] == []


def test_the_count_is_counted_from_the_predicate(tmp_path):
    assert run(tmp_path, cp="yes")["count"] == "3 of 5"
    assert run(tmp_path)["count"] == "5 of 5"


def test_any_filter_or_a_search_counts_as_narrowing(tmp_path):
    assert run(tmp_path, q="a")["narrowing"] is True
    assert run(tmp_path, cp="no")["narrowing"] is True
    assert run(tmp_path, q="   ")["narrowing"] is False, "whitespace is not a search"


# -- the canvas reads the same predicate ---------------------------------------
def test_the_canvas_dims_by_the_same_function_the_list_filters_by():
    src = tpl()
    assert "let rows = nodes.filter(nodeMatches);" in src
    assert "const KEEP = NARROW ? matchSet() : null;" in src
    assert "nodes.forEach(n=>{ if(KEEP.has(n.id)) paintNode(n); });" in src


def test_a_dimmed_station_is_drawn_not_hidden():
    """The shape of the chain is the point of the picture. A filter that
    removed stations would leave a reader looking at a different map."""
    src = tpl()
    assert "nodes.forEach(paintNode);" in src, "every station is painted first"
    assert "ctx.fillRect(" in slice_between(src, "if(NARROW){", "if(camOn) ctx.restore();")


def test_an_edge_survives_only_when_both_of_its_ends_do():
    src = tpl()
    assert "if(KEEP.has(e.from) && KEEP.has(e.to)) paintEdge(e,i);" in src


def test_the_veil_is_the_background_colour_and_not_a_new_one():
    src = tpl()
    veil = slice_between(src, "if(NARROW){", "edges.forEach((e,i)=>{ if(KEEP")
    assert "tok('--bg')" in veil
    for bad in ("rgba(", "#fff", "opacity:"):
        assert bad not in veil.replace("'#0b0e14'", ""), bad


# -- only fields the map carries -----------------------------------------------
def test_only_three_filters_exist_and_each_names_a_real_field():
    src = tpl()
    assert "const FILTERS = {layer:'', cp:'', pulse:''};" in src
    bar = slice_between(src, "function filterBarHTML()", "function countText()")
    # One field() helper emits the select, so the three are counted by the
    # three ids it is called with rather than by the attribute it writes.
    assert [i for i in ("rf-layer", "rf-cp", "rf-pulse") if f"'{i}'" in bar] \
        == ["rf-layer", "rf-cp", "rf-pulse"]
    assert bar.count("field('rf-") == 3


def test_no_filter_is_offered_over_a_field_the_map_does_not_have():
    src = tpl()
    bar = slice_between(src, "function filterBarHTML()", "function countText()")
    for invented in ("region", "country", "risk", "severity", "criticality"):
        assert f'data-f="{invented}"' not in bar, invented


def test_the_field_called_country_is_an_exchange_and_is_not_used_as_a_place():
    """Every node carries `country`, and every value in it is a venue --
    NASDAQ, XETRA, TSE, KRX. Filtering "where is this company" by it would be
    wrong in a way a reader could not see, so it is not offered."""
    if not (SITE / "energy" / "live_en.json").is_file():
        pytest.skip("no build in site/ to read")
    doc = json.loads((SITE / "energy" / "live_en.json").read_text(encoding="utf-8"))
    vals = {n.get("country") for n in doc.get("nodes") or [] if n.get("country")}
    assert vals, "the field exists"
    assert vals & {"NASDAQ", "NYSE", "XETRA", "LSE"}, vals
    assert "country" not in slice_between(tpl(), "function nodeMatches(n)",
                                          "function matchSet()")


# -- the URL -------------------------------------------------------------------
def test_only_public_state_is_written_to_the_url():
    src = tpl()
    assert "const URL_KEYS = ['q','layer','cp','pulse','station','rail'];" in src
    w = slice_between(src, "function writeURL()", "function readURL()")
    for key in ("'q'", "'layer'", "'cp'", "'pulse'", "'station'", "'rail'"):
        assert f"set({key}," in w, key


def test_the_url_is_replaced_and_never_pushed():
    """A filter is not a page. Thirty of them in the back button is thirty
    presses to leave the map."""
    src = tpl()
    w = slice_between(src, "function writeURL()", "function readURL()")
    assert "history.replaceState" in w
    assert "pushState" not in src


def test_the_recording_flags_are_never_written_into_a_shared_link():
    src = tpl()
    w = slice_between(src, "function writeURL()", "function readURL()")
    for flag in ("rec", "legacy", "emph", "freeze"):
        assert f"set('{flag}'" not in w, flag
    assert "if(REC || _urlBooting) return;" in w


def test_every_restored_parameter_is_validated():
    src = tpl()
    r = slice_between(src, "function readURL()", "function buildRail()")
    assert "layers.includes(v)" in r
    assert "v==='yes' || v==='no'" in r
    assert "['tightening','eroding','unmeasured'].includes(v)" in r
    assert "byId[st]" in r, "a station id must name a station that exists"
    assert "try{" in r, "a malformed URL may not throw"


def test_the_search_restored_from_a_url_is_bounded():
    """A URL is a stranger's input."""
    assert ".slice(0, 80)" in slice_between(tpl(), "function readURL()",
                                            "function buildRail()")


def test_there_is_a_copy_link_control_and_it_is_text():
    src = tpl()
    assert "class=\"rcopy\"" in src
    assert "Copy link" in src and "Link copied" in src
    # No icon font, no SVG sprite: a mono label, like every other control.
    bar = slice_between(src, '<div class="ractions">', '</div>')
    assert "<svg" not in bar and "<i " not in bar


def test_every_filter_has_a_visible_label_tied_to_its_control():
    """Three unlabelled selects reading "All layers / Any / Any pulse" were
    three guesses."""
    src = tpl()
    bar = slice_between(src, "function filterBarHTML()", "function countText()")
    assert 'class="reyebrow" for="${id}"' in bar
    for ident in ("rf-layer", "rf-cp", "rf-pulse"):
        assert f"'{ident}'" in bar, ident
    for label in ("RAIL.lLayer", "RAIL.lCp", "RAIL.lPulse"):
        assert label in bar, label
    assert "Layer" in src and "Chokepoint" in src and "Pulse" in src


def test_the_chokepoint_options_say_what_they_select():
    src = tpl()
    for wording in ("All stations", "Chokepoints only", "Not chokepoints"):
        assert wording in src, wording
    assert "anyCp" not in src, "the bare 'Any' is gone"


def test_sort_is_labelled_and_kept_apart_from_the_filters():
    """It changes the order of what is shown, never what is shown."""
    src = tpl()
    assert 'class="rfield rsortrow"' in src
    assert 'for="rf-sort"' in src and 'id="rf-sort"' in src
    assert ".srail .rsortrow{margin-top:10px;padding-top:10px;border-top:" in src
    # And it is outside the filter block, so a Clear that resets the filters
    # does not silently reorder the list as well.
    bar = slice_between(src, "function filterBarHTML()", "function countText()")
    assert "rsort" not in bar


def test_the_count_is_announced_to_a_screen_reader():
    src = tpl()
    assert 'class="rcount" role="status" aria-live="polite"' in src


# -- the drawer overlays the map, it does not narrow it ------------------------
def test_between_1024_and_1439_the_drawer_is_an_overlay():
    """As a grid column it took its 300px out of the canvas: at 1200 the map
    went to 900, every column narrowed with it, and the layer names broke
    mid-word. This shipped, and P1's round-3 shots missed it because they
    were all taken with the drawer shut."""
    src = tpl()
    block = slice_between(src, "@media (min-width:1024px) and (max-width:1439px){",
                          "/* Full width, immediately after the map. */")
    assert "position:absolute" in block
    assert "--rail-w:300px" not in block, "the grid column is what narrowed the map"
    assert "border-inline-start:1px solid var(--rule)" in block
    assert "background:var(--panel)" in block


def test_the_docked_rail_above_1440_still_takes_its_own_column():
    src = tpl()
    assert "@media (min-width:1440px){ .stage{--rail-w:300px} .srail{display:block} }" in src


def test_escape_closes_the_drawer_and_returns_focus_to_its_button():
    src = tpl()
    close = slice_between(src, "function closeDrawer()", "function railClose()")
    assert "classList.remove('rail-open')" in close
    assert "aria-expanded','false'" in close
    assert "b.focus()" in close
    # And it backs out one level at a time: inside a station, Escape returns
    # to the list rather than throwing the drawer away.
    key = slice_between(src, "rail.addEventListener('keydown'", "const btn =")
    assert "if(railOpenId){" in key and "railClose(); return;" in key
    assert "closeDrawer()" in key


def test_clear_filters_resets_every_one_of_them():
    src = tpl()
    clear = slice_between(src, "if(ev.target.closest('.rclear'))", "const copy")
    assert "railQ = ''" in clear
    assert "FILTERS.layer = FILTERS.cp = FILTERS.pulse = ''" in clear
