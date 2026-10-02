"""Contract v2, part two: what is minted, what is scored, what is drawn.

Part one fixed the CLAIM -- see tests/test_contract_v2.py. This is what
happens to it afterwards.

Three things have to hold, and each of them is a way the record could quietly
become untrue:

1. MINTING. A v2 question's scored forecast comes from the basket in its
   contract. If anything hands the minter a different basket -- an older code
   path, the edge derivation, a hand-edited file -- it stops, loudly, rather
   than registering a claim nobody signed.
2. SCORING. The official number is read from the second ring for a v2
   question and from the first ring for a v1 one, and the two versions are
   never averaged together. A hit rate over the mixture describes neither.
3. DRAWING. The card shows the basket that is scored, in the colours that
   mean "this is the claim", and shows the first ring for what it now is.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from chains import answers, preregister as P, track
from chains.paths import templates_dir, watch_path

PH = str(track.PRIMARY_HORIZON)


def row(qid="mu_fq4"):
    rows = json.loads(watch_path("semi").read_text(encoding="utf-8"))
    return next(r for r in rows if r["id"] == qid)


def fc(qid, win, lose, order=1, marked="2026-09-30", direction=1):
    r = {"id": f"{qid}-{marked}", "qid": qid, "marked_at": marked,
         "status": "yes", "direction": direction, "win": list(win),
         "lose": list(lose), "benchmark": "EW_MAP",
         "horizons": list(answers.ORDERS[order])}
    if order != 1:
        r["order"] = order
        r["id"] = answers.twin_id(qid, marked)
    return r


# -- 1. minting ---------------------------------------------------------------
def test_a_v2_question_mints_its_twin_from_the_contract_not_from_the_edges():
    """The map's edges did not make this claim and cannot amend it."""
    want = P.ring2_of(row())
    got = answers.derived_baskets()["mu_fq4"]
    assert got == want
    out = answers.with_twins([fc("mu_fq4", ["mu"], ["skhynix", "samsung"])])
    twin = next(r for r in out if r.get("order") == 2)
    assert (twin["win"], twin["lose"]) == (list(want[0]), list(want[1]))
    assert twin["horizons"] == [5, 10, 20, 40]


def test_the_first_ring_is_still_minted_beside_it():
    """v2 does not delete the direct forecast. It relabels it."""
    direct = fc("mu_fq4", ["mu"], ["skhynix", "samsung"])
    out = answers.with_twins([direct])
    orders = sorted(r.get("order", 1) for r in out)
    assert orders == [1, 2]
    kept = next(r for r in out if r.get("order", 1) == 1)
    assert (kept["win"], kept["lose"]) == (["mu"], ["skhynix", "samsung"])


def test_the_twin_is_entered_on_the_same_mark_as_the_direct_forecast():
    """Entry is the first close after the mark, for both. A second ring
    entered on a different day would be a different experiment."""
    direct = fc("mu_fq4", ["mu"], ["skhynix", "samsung"],
                marked="2026-09-30T21:05:00Z")
    twin = next(r for r in answers.with_twins([direct])
                if r.get("order") == 2)
    assert twin["marked_at"] == direct["marked_at"]
    assert twin["id"].endswith("2026-09-30-r2")


# -- the guard ----------------------------------------------------------------
def test_minting_a_v2_question_from_the_wrong_basket_fails_loudly():
    """THE GUARD. If the v2 minting path is missing, no forecast is
    registered at all -- the one thing a preregistration cannot survive is a
    number recorded under a hash that promised a different basket."""
    wrong = {"mu_fq4": (["asml"], ["advantest"])}
    with pytest.raises(answers.MintError) as e:
        answers.with_twins([fc("mu_fq4", ["mu"], ["skhynix", "samsung"])],
                           wrong)
    msg = str(e.value)
    assert "contract-v2" in msg and "nobody signed" in msg
    assert "globalwafers" in msg and "advantest" in msg


def test_the_guard_fires_on_the_derived_ring_too():
    """The specific way this goes wrong: someone rebuilds baskets2 from
    chains/rings.py, which for mu_fq4 is empty, and the twin silently
    vanishes instead of being scored."""
    from chains import mapfile, rings
    doc = mapfile.load(dom="semi")
    by_tk = {str(n.get("ticker", "")).upper(): n["id"]
             for n in doc["nodes"] if n.get("ticker")}
    w = row()
    got = rings.second_ring(doc, w["win"], w["lose"],
                            by_tk.get(str(w["tk"]).upper()))
    derived = {"mu_fq4": (got["win2"], got["lose2"])}
    with pytest.raises(answers.MintError):
        answers.with_twins([fc("mu_fq4", ["mu"], ["skhynix", "samsung"])],
                           derived)


def test_a_v1_question_is_not_touched_by_the_guard():
    ok = {"intc_q3": (["hoya"], ["sumco"])}
    out = answers.with_twins([fc("intc_q3", ["intc"], ["tsmc"])], ok)
    twin = next(r for r in out if r.get("order") == 2)
    assert (twin["win"], twin["lose"]) == (["hoya"], ["sumco"])


def test_a_stored_v2_twin_whose_legs_drifted_is_refused():
    """A v1 twin is FROZEN -- it is derived, and the derivation may improve.
    A v2 twin is REGISTERED, so it is held to the first ring's rule instead
    and drift is refused."""
    ids = {"mu_fq4", "intc_q3"}
    b1 = {"mu_fq4": (["mu"], ["skhynix", "samsung"])}
    reg = {"mu_fq4": P.ring2_of(row())}
    good = fc("mu_fq4", *P.ring2_of(row()), order=2)
    assert answers.check_forecast(good, ids, b1, None, reg) is None
    bad = fc("mu_fq4", ["asml"], ["advantest"], order=2)
    why = answers.check_forecast(bad, ids, b1, None, reg)
    assert why and "hashed into its preregistration" in why


def test_a_v1_twin_is_still_frozen_when_the_derivation_moves():
    """The other half: no registered ring, so the old rule still applies and
    a stored twin survives an improvement to chains/rings.py."""
    ids = {"intc_q3"}
    b1 = {"intc_q3": (["intc"], ["tsmc"])}
    stored = fc("intc_q3", ["hoya"], ["sumco"], order=2)
    assert answers.check_forecast(stored, ids, b1, None, {}) is None


# -- 2. scoring ---------------------------------------------------------------
def card(version, h1, h2, **over):
    r = {"qid": f"q{version}", "state": "tracking", "direction": 1,
         "day_index": 25, "entry_date": "2026-10-01",
         "horizons": {PH: h1} if h1 else {},
         "horizons2": {PH: h2} if h2 else {}}
    if version == 2:
        r["contract_version"] = 2
    r.update(over)
    return r


HIT = {"spread": 2.0, "hit": True, "date": "2026-10-28", "spread_sox": 1.0}
MISS = {"spread": -1.0, "hit": False, "date": "2026-10-28", "spread_sox": -1.0}


def test_a_v2_question_is_scored_on_its_second_ring():
    r = card(2, h1=MISS, h2=HIT)
    assert track.scored_ring(r) == 2
    assert track.scored_horizons(r)[PH] is HIT
    o = track.official(r)
    assert o["counts"] and o["scored_ring"] == 2
    assert "the second ring it registered" in o["reason"]


def test_a_v1_question_is_scored_on_its_first_ring():
    r = card(1, h1=HIT, h2=MISS)
    assert track.scored_ring(r) == 1
    assert track.scored_horizons(r)[PH] is HIT
    o = track.official(r)
    assert o["counts"] and o["scored_ring"] == 1


def test_a_v2_question_with_only_a_first_ring_result_is_not_scored_yet():
    """Its direct reaction has locked and its claim has not. The claim is
    what counts, so the card is pending, not scored."""
    o = track.official(card(2, h1=HIT, h2=None))
    assert not o["counts"] and o["state"] == "pending"


def test_the_direct_reaction_never_reaches_the_official_mean():
    """The sharp one. A v2 question whose first ring hit and second ring
    missed must count as a miss."""
    stats = track.record_stats([card(2, h1=HIT, h2=MISS)])
    assert stats["n"] == 1 and stats["hits"] == 0
    assert stats["mean_excess"] == -1.0


def test_the_direct_reaction_is_reported_beside_the_score():
    stats = track.record_stats([card(2, h1=HIT, h2=MISS)])
    assert stats["direct"]["n"] == 1 and stats["direct"]["hits"] == 1
    assert stats["direct"]["diagnostic"] is True
    assert stats["direct"]["label"] == track.DIRECT_LABEL


def test_an_all_v1_record_carries_no_direct_block():
    """A count of a thing that does not exist, in a file with a hard ceiling."""
    assert "direct" not in track.record_stats([card(1, h1=HIT, h2=None)])


# -- the two versions are never pooled ---------------------------------------
def rows_both():
    return [card(1, h1=HIT, h2=None, qid="a"),
            card(1, h1=HIT, h2=None, qid="b"),
            card(2, h1=HIT, h2=MISS, qid="c")]


def test_the_two_versions_are_tallied_apart():
    got = track.record_by_contract(rows_both())
    v = got["versions"]
    assert set(v) == {"1", "2"}
    assert v["1"]["n"] == 2 and v["1"]["hits"] == 2
    assert v["2"]["n"] == 1 and v["2"]["hits"] == 0
    assert v["1"]["label"] == "Direct (contract v1)"
    assert v["2"]["label"] == track.SCORED_LABEL
    assert got["mixed"] is True


def test_the_pooled_hit_rate_disappears_once_both_versions_have_scored():
    rec = track.unpooled(track.record_stats(rows_both()), rows_both())
    for k in track.POOLED_VERSION_KEYS:
        assert k not in rec, f"{k} is a number over a mixture of two claims"
    assert rec["versions_not_pooled"] == track.VERSIONS_NOT_POOLED
    # N survives: counting questions is honest whatever they registered.
    assert rec["n"] == 3
    assert rec["by_contract"]["versions"]["1"]["hit_rate"] == 1.0


def test_an_all_v1_record_is_byte_for_byte_what_it_always_was():
    """The site's whole history is v1. A record that suddenly grew a split
    saying "100% of this is v1" would be reporting on this code, not on the
    record -- and live.json has a hard size ceiling."""
    rows = [card(1, h1=HIT, h2=None, qid="a")]
    plain = track.record_stats(rows)
    assert track.unpooled(dict(plain), rows) == plain
    assert "by_contract" not in track.unpooled(dict(plain), rows)


def test_one_version_scored_and_one_not_still_reports_a_headline():
    """Two versions present, only one with a locked result. There is nothing
    to pool yet, so the headline stands and the split is shown."""
    rows = [card(1, h1=HIT, h2=None, qid="a"),
            card(2, h1=None, h2=None, qid="c", state="marked",
                 entry_date=None)]
    rec = track.unpooled(track.record_stats(rows), rows)
    assert rec["n"] == 1 and rec["hit_rate"] == 1.0
    assert rec["by_contract"]["mixed"] is False


# -- 3. the card --------------------------------------------------------------
def template(name="live-map-en.html"):
    return (templates_dir() / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["live-map.html", "live-map-en.html"])
def test_a_v2_card_draws_the_registered_ring_and_not_the_derived_one(name):
    """Both templates: the English one is generated from the Hebrew and a
    branch that only reached one of them would ship a different card per
    language."""
    t = template(name)
    assert "function ring2Registered(" in t
    assert "contract_version === 2" in t
    v2 = t[t.index("if(v2){"):t.index("// --- ring 2, derived")]
    assert "ring2For(" not in v2, "the derived ring has no place on a v2 card"
    assert "T.mixed" not in v2, "'serves both sides' is about the derivation"
    assert "#3fd18b" in v2 and "#ff5a3c" in v2, "up if yes / down if yes"
    assert "T.diag" in v2 and "T.scored" in v2


def test_the_first_ring_of_a_v2_card_is_grey_and_labelled_a_diagnostic():
    t = template()
    assert "col=v2?'#7d8797':(o.win?'#3fd18b':'#ff5a3c')" in t
    assert "diag:'direct reaction · diagnostic'" in t
    assert "scored:'second ring · the scored basket'" in t


def test_the_hebrew_template_says_the_same_thing_in_hebrew():
    from chains import build_pages
    t = template("live-map.html")
    i = t.index("diag:'")
    assert build_pages.hebrew_runs(t[i:i + 60]), (
        "the source template is Hebrew; an English string here would reach "
        "the Hebrew page")


def test_the_v2_ring_is_drawn_from_the_centre_not_from_a_first_ring_node():
    """There are no edges behind these circles. The author did not claim
    any, and a line from a first-ring node would assert one."""
    t = template()
    v2 = t[t.index("if(v2){"):t.index("// --- ring 2, derived")]
    assert "M${CX+22},${CY}" in v2
    assert "${R1X+p.r}" not in v2


def test_the_track_card_reads_the_scored_ring():
    js = (templates_dir() / "track-cards.js").read_text(encoding="utf-8")
    assert "const hz = (v2 ? r.horizons2 : r.horizons) || {}" in js
    assert "Second ring (scored)" in js and "Direct (diagnostic)" in js
    assert "data-official-ring=" in js


def test_the_track_record_shows_the_split_and_never_averages_it():
    js = (templates_dir() / "track-cards.js").read_text(encoding="utf-8")
    assert "function byContract(" in js
    assert "if(keys.length < 2) return ''" in js
    assert "data-not-pooled" in js


# -- the live payload ---------------------------------------------------------
def test_the_snapshot_ships_the_registered_ring_for_a_v2_row():
    import inspect

    from chains import live_snapshot
    src = inspect.getsource(live_snapshot)
    assert "_prereg.ring2_of(r)" in src
    assert 'r["ring2_edges"] = []' in src
    assert 'r.pop("mixed", None)' in src


def test_mu_fq4_is_the_question_all_of_this_is_about():
    """The first v2 question. The second, smsg_pre, came in wave 1 on
    2026-10-02 (confidence M); this test is where a new one is noticed."""
    rows = json.loads(watch_path("semi").read_text(encoding="utf-8"))
    assert sorted(r["id"] for r in rows if P.is_v2(r)) == ["mu_fq4", "smsg_pre"]
    w = row()
    assert w["d"] == "2026-09-30"
    assert P.ring2_of(w) == (["globalwafers", "shinetsu", "tel"],
                             ["advantest"])
