"""The map cards on the front door, and where every line on them comes from.

The rule the landing page has always had: every number is read from the files
that are about to be served, not from data/ and not from a constant. The cards
add four more lines, and each of them obeys it -- the pulse count, the next
checkpoint, the price date and the preview are all read off the published
snapshot or off the published directory.

Two things they deliberately do not do: grade a map, and show a locked
question. "6 of 14 chokepoints tightening" is a count of a sign; it is not a
risk level, and there is no field behind a risk level. The next checkpoint is
the company and the date, which the board already shows to everyone, and never
the wording, the basket or the diagram.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from chains import landing


def _published(root: Path, name: str, *, nodes=2, cps=None, watch=None,
               as_of="2026-09-29", last_price_date="2026-09-25"):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    doc = {
        "as_of": as_of,
        "last_price_date": last_price_date,
        "nodes": [{"id": f"n{i}", "name": f"N{i}"} for i in range(nodes)],
        "cps": cps if cps is not None else [],
        "watch": watch if watch is not None else [],
        "labels": {},
    }
    (d / "live_en.json").write_text(json.dumps(doc), encoding="utf-8")
    return d


def cards(root, names, dom=None):
    dom = dom or names[0]
    return landing.map_cards(root, names, dom, root / dom)


# -- the pulse count -----------------------------------------------------------
@pytest.mark.parametrize("pressures,want_tight,want_total", [
    ([0.2, 0.1, -0.3, None], 2, 4),
    ([-0.1, -0.2], 0, 2),
    ([0.5], 1, 1),
    ([], 0, 0),
    ([None, None], 0, 2),          # unmeasured is not tightening
    ([0.0], 0, 1),                 # flat is not tightening either
])
def test_the_status_line_counts_the_sign_of_the_pressure(pressures, want_tight,
                                                         want_total, tmp_path):
    _published(tmp_path, "m", cps=[{"id": f"c{i}", "pressure": p}
                                   for i, p in enumerate(pressures)])
    c = cards(tmp_path, ["m"])[0]
    assert c["tightening"] == want_tight
    assert c["chokepoints"] == want_total


def test_the_status_line_is_rendered_as_a_count_and_not_as_a_grade(tmp_path):
    _published(tmp_path, "m", cps=[{"id": "a", "pressure": 0.2},
                                   {"id": "b", "pressure": -0.1}])
    html = landing._map_cards_html(cards(tmp_path, ["m"]), "m")
    assert "1 of 2 chokepoints tightening" in html
    for graded in ("high", "elevated", "critical", "severe", "risk"):
        assert graded not in html.lower(), graded


# -- the next checkpoint -------------------------------------------------------
def test_the_next_checkpoint_is_the_soonest_one_not_the_first_in_the_file(tmp_path):
    _published(tmp_path, "m", as_of="2026-09-29", watch=[
        {"id": "late", "who": "Late Co Q4", "d": "2026-12-01", "confirmed": True},
        {"id": "soon", "who": "Soon Co Q3", "d": "2026-10-02", "confirmed": False},
        {"id": "past", "who": "Past Co Q2", "d": "2026-08-01", "confirmed": True},
    ])
    c = cards(tmp_path, ["m"])[0]
    assert c["next_who"] == "Soon Co Q3"
    assert c["next_date"] == "2026-10-02"
    assert c["next_confirmed"] is False


def test_a_question_whose_date_has_passed_is_not_next(tmp_path):
    _published(tmp_path, "m", as_of="2026-09-29", watch=[
        {"id": "past", "who": "Past Co", "d": "2026-01-01", "confirmed": True}])
    c = cards(tmp_path, ["m"])[0]
    assert c["next_who"] == ""
    html = landing._map_cards_html([c], "m")
    assert "next ·" not in html, "no next date is said rather than an old one"


def test_the_card_never_carries_a_locked_question(tmp_path):
    """The board shows who and when to everybody. The wording, the baskets and
    the diagram are the paid part, and none of them is on this card at any
    lock state."""
    _published(tmp_path, "m", as_of="2026-09-29", watch=[
        {"id": "q", "who": "Acme Q3", "tk": "ACME", "d": "2026-10-10",
         "confirmed": True, "locked": True,
         "q": "SECRET QUESTION TEXT", "win": ["a"], "lose": ["b"],
         "yes": "SECRET YES", "no": "SECRET NO"}])
    html = landing._map_cards_html(cards(tmp_path, ["m"]), "m")
    assert "Acme Q3" in html and "2026-10-10" in html
    for secret in ("SECRET QUESTION TEXT", "SECRET YES", "SECRET NO"):
        assert secret not in html, secret
    assert "<svg" not in html and "cons" not in html


def test_the_date_says_whether_it_is_confirmed_or_expected(tmp_path):
    for confirmed, word in ((True, "confirmed"), (False, "expected")):
        root = Path(tmp_path) / ("y" if confirmed else "n")
        _published(root, "m", as_of="2026-09-29", watch=[
            {"id": "q", "who": "Acme Q3", "d": "2026-10-10",
             "confirmed": confirmed}])
        html = landing._map_cards_html(cards(root, ["m"]), "m")
        assert f"<span>{word}</span>" in html


# -- the price date ------------------------------------------------------------
def test_prices_through_is_read_from_the_snapshot(tmp_path):
    _published(tmp_path, "m", last_price_date="2026-09-18")
    c = cards(tmp_path, ["m"])[0]
    assert c["through"] == "2026-09-18"
    assert "prices through 2026-09-18" in landing._map_cards_html([c], "m")


def test_a_snapshot_with_no_price_date_says_nothing_about_prices(tmp_path):
    _published(tmp_path, "m", last_price_date="")
    html = landing._map_cards_html(cards(tmp_path, ["m"]), "m")
    assert "prices through" not in html


# -- the preview ---------------------------------------------------------------
def test_a_card_gets_a_picture_only_when_one_was_published(tmp_path):
    _published(tmp_path, "m")
    c = cards(tmp_path, ["m"])[0]
    assert c["preview"] == "" and c["preview_mobile"] == ""
    assert "<img" not in landing._map_cards_html([c], "m")

    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "map-m.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    c2 = cards(tmp_path, ["m"])[0]
    assert c2["preview"] == "/assets/map-m.png"
    html = landing._map_cards_html([c2], "m")
    assert '<img src="/assets/map-m.png"' in html
    assert 'loading="lazy"' in html


def test_the_mobile_source_appears_only_with_a_mobile_file(tmp_path):
    _published(tmp_path, "m")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "map-m.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    assert "<source" not in landing._map_cards_html(cards(tmp_path, ["m"]), "m")
    (assets / "map-m-mobile.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    html = landing._map_cards_html(cards(tmp_path, ["m"]), "m")
    assert '<source media="(max-width:760px)" srcset="/assets/map-m-mobile.png"' in html


# -- the card as a whole -------------------------------------------------------
def test_the_whole_card_is_one_link_to_its_map(tmp_path):
    _published(tmp_path, "m")
    html = landing._map_cards_html(cards(tmp_path, ["m"]), "m")
    assert '<a class="mapcard-hit" href="/m/"' in html
    # And the two explicit links stay, outside it -- a link inside a link is
    # not a thing, and Track Record has to be reachable separately.
    assert '<a href="/m/track/">Track Record</a>' in html


def test_every_published_map_gets_a_card(tmp_path):
    for n in ("semi", "energy", "pharma"):
        _published(tmp_path, n)
    got = cards(tmp_path, ["semi", "energy", "pharma"], dom="semi")
    assert [c["name"] for c in got] == ["semi", "energy", "pharma"]


def test_a_map_that_is_not_published_yet_gets_no_card(tmp_path):
    """Read from what is served. A name under data/ with nothing published
    beside it would be a card describing a map nobody can open."""
    _published(tmp_path, "semi")
    got = cards(tmp_path, ["semi", "notyet"], dom="semi")
    assert [c["name"] for c in got] == ["semi"]
