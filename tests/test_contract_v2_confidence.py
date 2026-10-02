"""Contract v2's confidence: S, M or W, in the hash only when present.

The author's confidence is part of the claim, so it is hashed. It is
optional, because mu_fq4 was committed v2 without it and those bytes may not
move. It is tallied apart (a weak call that hits is not a strong call that
hits), drawn as a small tag on an open card, and never shipped on a locked
row, because the locked contract's bytes stay paid.
"""
from __future__ import annotations

import json

import pytest

from chains import live_snapshot, preregister as P, track
from chains.paths import templates_dir, watch_path

TEXT = {"yes_en": "Yes looks like this.", "no_en": "No looks like that."}
MU_FQ4_V2 = "c4be08e4e586c4ec246aea8a04df21ca62b54e19e92d6be6598e769ed5624b9c"
PH = str(track.PRIMARY_HORIZON)


def v2_row(**over):
    r = {"id": "q", "d": "2026-12-01", "win": ["mu"], "lose": ["samsung"], "kind": "share",
         "ring2_win": ["tel"], "ring2_lose": ["advantest"],
         "ring2_rationale": {"win": "Equipment into the winner.", "lose": "Tester into the loser."}}
    r.update(over)
    return r


# -- the hash -------------------------------------------------------------------
def test_confidence_is_in_the_hash_only_when_present():
    plain = P.contract(v2_row(), TEXT)
    assert P.RING2_CONFIDENCE not in plain
    weak = P.contract(v2_row(ring2_confidence="W"), TEXT)
    assert weak[P.RING2_CONFIDENCE] == "W"
    assert {k: v for k, v in weak.items() if k != P.RING2_CONFIDENCE} == plain
    assert P.digest(v2_row(ring2_confidence="W"), TEXT) != P.digest(v2_row(ring2_confidence="S"), TEXT)
    assert P.digest(v2_row(ring2_confidence="W"), TEXT) != P.digest(v2_row(), TEXT)


def test_mu_fq4_still_hashes_to_its_published_value():
    from chains import questions
    try:
        texts = questions.fetch(dom="semi")
    except Exception as e:                       # no question store here
        pytest.skip(f"questions store unavailable ({type(e).__name__})")
    row = next(r for r in json.loads(watch_path("semi").read_text(encoding="utf-8"))
               if r["id"] == "mu_fq4")
    assert P.RING2_CONFIDENCE not in row
    assert P.digest(row, texts.get("mu_fq4")) == MU_FQ4_V2


@pytest.mark.parametrize("bad", ["high", "s", 1, ""])
def test_a_confidence_that_is_not_s_m_or_w_is_refused(bad):
    with pytest.raises(P.PreregisterError):
        P.contract(v2_row(ring2_confidence=bad), TEXT)


def test_a_confidence_with_no_second_ring_is_refused():
    v1 = {"id": "q", "d": "2026-12-01", "win": ["mu"], "lose": [], "kind": "tide",
          "ring2_confidence": "M"}
    with pytest.raises(P.PreregisterError):
        P.contract(v1, TEXT)


# -- locked rows ----------------------------------------------------------------
def test_a_locked_row_ships_no_confidence():
    assert "ring2_confidence" in live_snapshot.LOCKED_STRIP
    row = {"id": "q", "locked": True, **v2_row(ring2_confidence="M")}
    for k in live_snapshot.LOCKED_STRIP:
        row.pop(k, None)
    assert "ring2_confidence" not in row


# -- the tallies ------------------------------------------------------------------
HIT = {"spread": 0.02, "hit": True, "date": "2026-11-30", "spread_sox": 0.01}
MISS = {"spread": -0.01, "hit": False, "date": "2026-11-30", "spread_sox": -0.01}


def card(qid, version, h, conf=None):
    r = {"qid": qid, "state": "tracking", "direction": 1, "day_index": 25,
         "entry_date": "2026-10-30", "horizons": {}, "horizons2": {}}
    if version == 2:
        r["contract_version"] = 2
        r["horizons2"] = {PH: h}
        if conf:
            r["ring2_confidence"] = conf
    else:
        r["horizons"] = {PH: h}
    return r


def test_v2_is_split_by_confidence_and_an_empty_tier_is_absent():
    rows = [card("a", 1, HIT), card("s", 2, HIT, "S"), card("w1", 2, MISS, "W"),
            card("w2", 2, HIT, "W"), card("mu", 2, HIT)]          # mu: no confidence
    v = track.record_by_contract(rows)["versions"]
    assert (v["2"]["n"], v["2"]["hits"]) == (4, 3)                 # all v2
    tiers = v["2"]["by_confidence"]
    assert set(tiers) == {"S", "W"}                                # M scored nothing: absent
    assert (tiers["S"]["n"], tiers["S"]["hits"]) == (1, 1)
    assert (tiers["W"]["n"], tiers["W"]["hits"]) == (2, 1)
    assert "by_confidence" not in v["1"]


def test_a_v2_record_with_no_confidence_anywhere_has_no_tiers():
    v = track.record_by_contract([card("a", 1, HIT), card("mu", 2, HIT)])["versions"]
    assert "by_confidence" not in v["2"]


def test_the_record_card_carries_the_confidence_of_a_v2_question_only():
    assert track.by_confidence([card("a", 1, HIT)]) == {}


# -- the page ---------------------------------------------------------------------
def tpl(name):
    return (templates_dir() / name).read_text(encoding="utf-8")


def test_the_track_page_draws_a_tier_only_where_it_scored():
    js = tpl("track-cards.js")
    assert "['S','M','W'].filter(c => C[c] && C[c].n)" in js
    assert 'data-confidence="${c}"' in js
    # Once both versions have scored the pooled hits are gone; no "undefined/N".
    assert "R.hits == null" in js


@pytest.mark.parametrize("name", ["live-map.html", "live-map-en.html"])
def test_the_card_tags_the_confidence_and_a_locked_card_has_none_to_tag(name):
    s = tpl(name)
    assert "function confTag(w)" in s and "${confTag(w)}" in s
    assert "CONF.lv[c] ?" in s                                    # nothing without a value


def test_the_english_tag_reads_confidence_strong_medium_weak():
    s = tpl("live-map-en.html")
    assert "const CONF = {lbl:'Confidence', lv:{S:'strong', M:'medium', W:'weak'}};" in s
