"""The site-wide record at /track/: pooled where pooling means something.

Two maps, two records. N and the hit rate pool -- a hit is a yes/no outcome
and it means the same thing on either map. The excess does not: it is measured
against each map's OWN equal-weight benchmark, so an average of the two
answers "excess over what?" with "over a mixture of two markets nobody holds".
This file holds that line, and the one that made pooling possible at all: two
maps may name a question alike, and the pooled record must count both.
"""
from __future__ import annotations

import json

import pytest

from chains import track, track_site
from chains.answers import PRIMARY_HORIZON

PH = str(PRIMARY_HORIZON)


def _card(qid, spread, hit, direction=1):
    return {"qid": qid, "id": qid, "direction": direction,
            "horizons": {PH: {"spread": spread, "hit": hit}}}


def _payload(cards):
    return {"forecasts": cards, "n_resolved": len(cards)}


# -- the collision that made this necessary ----------------------------------

def test_a_question_two_maps_name_alike_is_counted_twice():
    """semi and energy both own gev_q3 today. They are different questions
    about different chains with different baskets, and the pooled record
    must not swallow one of them."""
    p = track.pooled({"semi": _payload([_card("gev_q3", 0.02, True)]),
                      "energy": _payload([_card("gev_q3", -0.01, False)])})
    assert p["record"]["n"] == 2
    assert p["record"]["hits"] == 1
    assert p["by_domain"]["semi"]["record"]["n"] == 1
    assert p["by_domain"]["energy"]["record"]["n"] == 1


def test_one_map_repeating_a_question_still_counts_it_once():
    """The dedup that was there before must survive: one event per question
    per map, not one row per row."""
    card = _card("a", 0.02, True)
    assert track.record_stats([card, dict(card)])["n"] == 1


def test_a_record_with_no_domain_keys_exactly_as_it_always_did():
    assert track.record_stats([_card("a", 0.01, True)])["n"] == 1


# -- the headline is the sum of the maps --------------------------------------

def test_the_headline_n_is_the_sum_of_every_map():
    p = track.pooled({
        "semi": _payload([_card("a", 0.01, True), _card("b", 0.02, True)]),
        "energy": _payload([_card("c", -0.01, False)])})
    per = sum(b["record"]["n"] for b in p["by_domain"].values())
    assert p["record"]["n"] == per == 3
    assert p["record"]["hit_rate"] == round(2 / 3, 4)


def test_the_headline_carries_no_pooled_excess():
    """The one number on this page that would be meaningless."""
    p = track.pooled({"semi": _payload([_card("a", 0.10, True)]),
                      "energy": _payload([_card("b", -0.10, False)])})
    for key in track.POOLED_EXCESS_KEYS:
        assert key not in p["record"], key
    assert p["record"]["excess"] == track.EXCESS_NOT_POOLED


def test_every_map_keeps_its_own_excess_and_its_own_benchmark():
    p = track.pooled({"semi": _payload([_card("a", 0.10, True)]),
                      "energy": _payload([_card("b", -0.10, False)])})
    assert p["by_domain"]["semi"]["record"]["mean_excess"] == 0.1
    assert p["by_domain"]["energy"]["record"]["mean_excess"] == -0.1
    assert p["by_domain"]["semi"]["benchmark"]["label"] == "SOX"
    assert p["by_domain"]["energy"]["benchmark"]["label"] == "GRID"


# -- the page ------------------------------------------------------------------

def _site(tmp_path, doms):
    for name, cards in doms.items():
        d = tmp_path / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "track_public.json").write_text(json.dumps(_payload(cards)),
                                             encoding="utf-8")
    return tmp_path


def test_the_page_is_built_from_an_empty_directory_upwards(tmp_path):
    """Nothing published yet is not an empty record, it is no page: a number
    about a site with no record on it would be a claim about nothing."""
    with pytest.raises(track_site.TrackSiteError):
        track_site.render(tmp_path, ["semi", "energy"], "https://x/")


def test_the_page_shows_the_pooled_n_and_a_block_per_map(tmp_path):
    root = _site(tmp_path, {"semi": [_card("a", 0.01, True),
                                     _card("gev_q3", 0.02, True)],
                            "energy": [_card("gev_q3", -0.01, False)]})
    html = track_site.render(root, ["semi", "energy"], "https://x/")
    assert html.count('class="domrec"') == 2
    assert "3</b> scored questions" in html.replace("<b>", "</b>") or \
        ">3<" in html
    assert 'href="/semi/track/"' in html and 'href="/energy/track/"' in html
    # each block names its own benchmark, and only its own
    semi_block = html.split('class="domrec"')[1]
    energy_block = html.split('class="domrec"')[2]
    which = (semi_block, energy_block) if "Chip" in semi_block \
        else (energy_block, semi_block)
    assert "SOX" in which[0] and "GRID" not in which[0]
    assert "GRID" in which[1] and "SOX" not in which[1]


def test_the_page_names_only_maps_that_published_a_record(tmp_path):
    root = _site(tmp_path, {"semi": [_card("a", 0.01, True)]})
    html = track_site.render(root, ["semi", "energy"], "https://x/")
    assert html.count('class="domrec"') == 1
    assert 'href="/energy/track/"' not in html


def test_the_page_never_prints_a_pooled_excess(tmp_path):
    root = _site(tmp_path, {"semi": [_card("a", 0.10, True)],
                            "energy": [_card("b", -0.10, False)]})
    html = track_site.render(root, ["semi", "energy"], "https://x/")
    head = html.split('class="head"')[1].split("</ul>")[0]
    assert "excess" not in head.lower(), \
        "the headline must not carry an excess of any kind"
    import html as _h
    assert track.EXCESS_NOT_POOLED in _h.unescape(html),         "the page must say why, where a reader can see it"


def test_the_page_carries_no_hebrew(tmp_path):
    from chains.build_pages import hebrew_runs
    root = _site(tmp_path, {"semi": [_card("a", 0.01, True)]})
    assert hebrew_runs(track_site.render(root, ["semi"], "https://x/")) == []
