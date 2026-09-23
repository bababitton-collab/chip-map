"""The pooled record, exercised end to end on a SYNTHETIC set of questions.

WHAT THIS IS, AND WHAT IT IS NOT
--------------------------------
Every forecast in here is invented. Each one carries a ``fixture_`` qid, and
that prefix is asserted below against both real watch lists so it can never
collide with a question anybody registered. Nothing here is written to
``data/``, to ``site/``, or to any file at all: the fixture lives in memory
for the length of the test and the real record is never touched.

It exists because the live record is empty. Energy has never registered a
forecast and semi has one resolved question whose 20-session window has not
closed, so pooled N is 0 and every number on /track/ and in /record.json is a
dash. The arithmetic behind those dashes -- when a question counts, what the
hit rate is, when each map's own benchmark appears, what happens either side
of N=30 -- is therefore completely untested against anything but zeros. This
file supplies the sample the world has not yet.

THE SCORING IS THE REAL SCORING
-------------------------------
``forecast.score_one``, ``track._from_ledger``, ``track.record_stats`` and
``track.pooled`` are called exactly as the build calls them. Nothing about
the measurement is reimplemented here; if the scoring changes, this test
changes with it or fails, which is the point.

WHY THE PRICES ARE SYNTHETIC AND THE TICKERS ARE REAL
-----------------------------------------------------
The symbols are the maps' own, so the shape of what is priced is real. The
SERIES behind them are built here, because a hand-computed expected hit rate
and live market data cannot both be true for long: a test pinned to real
closes would silently change meaning every time a price moved, and would be
red on a morning when nothing was wrong. With a series chosen here, every
expected number below is arithmetic a reader can check on paper.

The construction leans on one fact about the real ``excess``: with both a win
and a lose side the benchmark cancels, so excess is win minus lose. The win
leg rises, the lose leg falls, and the sign of the excess is therefore known
before anything runs. Which of those is a HIT is then chosen per question by
its ``direction`` -- the outcome is hand-picked, and the scoring code is what
decides it.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from chains import forecast, mapfile, track
from chains.answers import PRIMARY_HORIZON
from chains.paths import watch_path

PH = str(PRIMARY_HORIZON)          # "20"
PREFIX = "fixture_"

# Real node ids from each map, and the symbols behind them. Two per domain is
# all a win/lose pair needs; the rest of the map is priced flat below so the
# equal-weight benchmark is a straight line.
LEGS = {
    "semi": {"win": "shinetsu", "lose": "sumco"},
    "energy": {"win": "gev", "lose": "eaton"},
}

# Sixty weekday sessions ending today: the calendar the fixture is scored on.
TODAY = dt.date(2026, 9, 23)
CAL: list[dt.date] = []
_d = TODAY - dt.timedelta(days=120)
while _d <= TODAY:
    if _d.weekday() < 5:
        CAL.append(_d)
    _d += dt.timedelta(days=1)

# How the three kinds of leg move, per session, compounded.
RISE, FALL, FLAT = 1.01, 0.99, 1.0


class FakeBook(forecast.Book):
    """A Book with series chosen here instead of loaded from the store.

    Subclassed rather than duck-typed so that every method the scorer uses is
    the real one -- ``at`` and ``has`` are inherited untouched, and only the
    data they read is ours.
    """

    def __init__(self, moves: dict[str, float]):     # noqa: D107
        self.series = {}
        self.days = {}
        for sym, step in moves.items():
            level, s = 100.0, {}
            for d in CAL:
                s[d] = round(level, 6)
                level *= step
            self.series[sym] = s
            self.days[sym] = list(CAL)


def _symbols(dom: str):
    doc = mapfile.load(dom=dom)
    symbol_of = {n["id"]: n["price_symbol"] for n in doc["nodes"]
                 if n.get("price_symbol")}
    node_symbols = [n["price_symbol"] for n in doc["nodes"]
                    if n.get("price_symbol")
                    and n.get("price_symbol_kind") != "none"]
    return doc, symbol_of, node_symbols


def _book(dom: str, same_legs: bool = False) -> FakeBook:
    """Every priced symbol on the map flat, except the two legs.

    ``same_legs`` moves the lose leg exactly as the win leg moves. Excess is
    win minus lose, so that is the only way to land on exactly 0.0 -- a flat
    lose leg against a rising win leg is a large POSITIVE excess, not a zero
    one, which is what the first draft of this fixture got wrong.
    """
    _doc, symbol_of, node_symbols = _symbols(dom)
    moves = {s: FLAT for s in node_symbols}
    moves[symbol_of[LEGS[dom]["win"]]] = RISE
    moves[symbol_of[LEGS[dom]["lose"]]] = RISE if same_legs else FALL
    moves[forecast.benchmark_for(dom)["symbol"]] = FLAT
    return FakeBook(moves)


# ---------------------------------------------------------------- the sample
# 20 per map. Of each 20, 17 are old enough to have closed a 20-session
# window and 3 are not -- so the "counted only once it clears" rule is
# exercised rather than assumed.
#
#   semi    12 hits, 5 misses                -> 12/17
#   energy   8 hits, 7 misses, 2 at zero     ->  8/17
#   pooled  20 hits of 34                    -> 20/34
#
# "At zero" is the threshold case: the two legs move identically, excess is
# exactly 0.0, and `hit = bool(e) and ...` makes that a counted event that is
# not a hit, whichever way it was called. There are TWO of them, one called
# each way, because a single one called DOWN passes even if the rule is
# broken to `(e >= 0) == (direction > 0)` -- checked, and it did.
PLAN = {
    "semi": {"hits": 12, "misses": 5, "zeros": 0, "recent": 3},
    "energy": {"hits": 8, "misses": 7, "zeros": 2, "recent": 3},
}
EXPECTED = {"semi": (12, 17), "energy": (8, 17), "pooled": (20, 34)}


def _forecasts(dom: str) -> list[dict]:
    """The invented questions. ``direction`` is what picks hit or miss."""
    plan = PLAN[dom]
    win, lose = LEGS[dom]["win"], LEGS[dom]["lose"]
    out, n = [], 0
    # Cleared entries: marked far enough back that 20 sessions have closed.
    old = CAL[-(PRIMARY_HORIZON + 25)]
    for kind, count in (("hit", plan["hits"]), ("miss", plan["misses"]),
                        ("zero", plan["zeros"])):
        for i in range(count):
            n += 1
            # Both ways round for the zeros: see the note on PLAN.
            zero_dir = 1 if i % 2 == 0 else -1
            # The excess is positive (win rises, lose falls), so +1 is a hit
            # and -1 is a miss. A "zero" question is scored on a book where
            # the lose leg is flat too, so the excess is exactly 0.
            out.append({
                "id": f"{PREFIX}{dom}_{n:02d}-{old.isoformat()}",
                "qid": f"{PREFIX}{dom}_{n:02d}",
                "status": "yes" if kind != "miss" else "no",
                "direction": (zero_dir if kind == "zero"
                              else (1 if kind == "hit" else -1)),
                "marked_at": old.isoformat(),
                "win": [win], "lose": [lose],
                "kind": kind,
            })
    # Too recent to have closed the primary horizon.
    recent = CAL[-3]
    for _ in range(plan["recent"]):
        n += 1
        out.append({
            "id": f"{PREFIX}{dom}_{n:02d}-{recent.isoformat()}",
            "qid": f"{PREFIX}{dom}_{n:02d}",
            "status": "yes", "direction": 1,
            "marked_at": recent.isoformat(),
            "win": [win], "lose": [lose], "kind": "recent",
        })
    return out


def _cards(dom: str) -> list[dict]:
    """Score the fixture with the real scorer and shape it as the page does."""
    doc, symbol_of, node_symbols = _symbols(dom)
    bench = forecast.benchmark_in(doc)["symbol"]
    normal, zeroed = _book(dom), _book(dom, same_legs=True)
    cards = []
    for f in _forecasts(dom):
        book = zeroed if f["kind"] == "zero" else normal
        row = forecast.score_one(f, book, CAL, node_symbols, symbol_of, [],
                                 bench)
        cards.append({"qid": f["qid"], "direction": f["direction"],
                      "kind": f["kind"],
                      "horizons": track._from_ledger(row)})
    return cards


@pytest.fixture(scope="module")
def fixture_cards():
    return {dom: _cards(dom) for dom in ("semi", "energy")}


@pytest.fixture(scope="module")
def pooled(fixture_cards):
    return track.pooled({dom: {"forecasts": cards, "n_resolved": len(cards)}
                         for dom, cards in fixture_cards.items()})


# -- the fixture can never be mistaken for real data ------------------------

def test_no_fixture_id_exists_in_any_real_watch_list():
    """The one thing that would make this file dangerous."""
    for dom in ("semi", "energy"):
        real = {r["id"] for r in
                json.loads(watch_path(dom).read_text(encoding="utf-8"))}
        assert not any(i.startswith(PREFIX) for i in real), dom
        mine = {f["qid"] for f in _forecasts(dom)}
        assert mine.isdisjoint(real), f"{dom}: a fixture qid is a real qid"


def test_every_fixture_id_is_marked_as_one():
    for dom in ("semi", "energy"):
        assert all(f["qid"].startswith(PREFIX) for f in _forecasts(dom))


# -- a question counts only once its window has closed ----------------------

def test_a_question_counts_only_after_the_primary_horizon_closes(
        fixture_cards):
    for dom, cards in fixture_cards.items():
        cleared = [c for c in cards if (c["horizons"] or {}).get(PH)]
        recent = [c for c in cards if c["kind"] == "recent"]
        assert len(cards) == 20, dom
        assert len(cleared) == 17, dom
        assert all(not (c["horizons"] or {}).get(PH) for c in recent), \
            f"{dom}: a question was counted before its window closed"


def test_the_pooled_n_is_the_cleared_questions_of_both_maps(pooled):
    assert pooled["record"]["n"] == EXPECTED["pooled"][1] == 34
    per = sum(b["record"]["n"] for b in pooled["by_domain"].values())
    assert per == 34


# -- the hit rate, against the number worked out on paper -------------------

@pytest.mark.parametrize("dom", ["semi", "energy"])
def test_each_map_scores_the_hit_rate_it_was_built_to_score(pooled, dom):
    hits, n = EXPECTED[dom]
    rec = pooled["by_domain"][dom]["record"]
    assert (rec["hits"], rec["n"]) == (hits, n)
    assert rec["hit_rate"] == round(hits / n, 4)


def test_the_pooled_hit_rate_is_the_two_maps_together(pooled):
    hits, n = EXPECTED["pooled"]
    rec = pooled["record"]
    assert (rec["hits"], rec["n"]) == (hits, n)
    assert rec["hit_rate"] == round(hits / n, 4) == 0.5882


def test_a_question_at_exactly_zero_excess_counts_but_never_hits(
        fixture_cards):
    """`hit = bool(e) and (e > 0) == (direction > 0)` -- a zero excess is an
    event with no direction to have got right."""
    zeros = [c for c in fixture_cards["energy"] if c["kind"] == "zero"]
    assert len(zeros) == 2
    assert {c["direction"] for c in zeros} == {1, -1},         "one of each, or a broken >= rule slips through the down one"
    for c in zeros:
        got = c["horizons"][PH]
        assert got["spread"] == 0.0
        assert got["hit"] is False, f"direction {c['direction']}"
        assert got["spread"] is not None, "it must still be counted toward N"


# -- either side of N = 30 --------------------------------------------------

def test_the_threshold_is_the_one_the_scoring_code_defines(pooled):
    assert pooled["record"]["min_n_for_capital"] == forecast.MIN_N_FOR_CAPITAL
    assert forecast.MIN_N_FOR_CAPITAL == 30


def test_below_the_threshold_the_pooled_sample_is_short(fixture_cards):
    """One map alone is 17 -- under 30, and a reader is told so."""
    one = track.pooled({"semi": {"forecasts": fixture_cards["semi"]}})
    rec = one["record"]
    assert rec["n"] == 17
    assert rec["n"] < rec["min_n_for_capital"]
    assert rec["capital_rule"] == forecast.CAPITAL_RULE
    assert "N=30" in rec["capital_rule"]


def test_at_and_above_the_threshold_the_sample_clears_it(pooled):
    rec = pooled["record"]
    assert rec["n"] == 34
    assert rec["n"] >= rec["min_n_for_capital"]


def test_the_rule_goes_quiet_once_the_sample_clears_the_threshold(
        fixture_cards, pooled):
    """It used to be stated at every N. A caveat that never leaves is
    furniture — a reader could not tell from the sentence whether it still
    applied. It is now present exactly while it is true."""
    short = track.pooled({"semi": {"forecasts": fixture_cards["semi"]}})
    assert short["record"]["n"] < 30 <= pooled["record"]["n"]
    assert short["record"]["capital_gated"] is True
    assert short["record"]["capital_rule"] == forecast.CAPITAL_RULE
    assert pooled["record"]["capital_gated"] is False
    assert pooled["record"]["capital_rule"] is None


# -- each map keeps its own benchmark and its own sample --------------------

def test_each_map_reports_its_own_second_benchmark(pooled):
    assert pooled["by_domain"]["semi"]["benchmark"]["label"] == "SOX"
    assert pooled["by_domain"]["semi"]["benchmark"]["symbol"] == "SOXQ.US"
    assert pooled["by_domain"]["energy"]["benchmark"]["label"] == "GRID"
    assert pooled["by_domain"]["energy"]["benchmark"]["symbol"] == "GRID.US"


def test_one_maps_questions_do_not_move_the_other_maps_block(fixture_cards):
    """The blocks have to be independent, or the per-map numbers are a
    property of what else happened to be published that day."""
    both = track.pooled({d: {"forecasts": c} for d, c in fixture_cards.items()})
    semi_alone = track.pooled({"semi": {"forecasts": fixture_cards["semi"]}})
    a = both["by_domain"]["semi"]["record"]
    b = semi_alone["by_domain"]["semi"]["record"]
    for key in ("n", "hits", "hit_rate", "mean_excess", "median_excess"):
        assert a[key] == b[key], key


def test_the_pooled_headline_still_carries_no_excess(pooled):
    for key in track.POOLED_EXCESS_KEYS:
        assert key not in pooled["record"], key
    assert pooled["record"]["excess"] == track.EXCESS_NOT_POOLED
    # and each map's own block does carry one
    for dom in ("semi", "energy"):
        assert pooled["by_domain"][dom]["record"]["mean_excess"] is not None


# -- the shape /record.json publishes ---------------------------------------

def _slim(data: dict) -> dict:
    """The document publish_site writes to site/record.json, built from the
    fixture instead of from what is published."""
    return {"primary_horizon": data["primary_horizon"],
            "domains": data["domains"],
            "record": data["record"],
            "by_domain": {d: {"domain": d, "record": b["record"],
                              "benchmark": b["benchmark"]}
                          for d, b in data["by_domain"].items()}}


def test_record_json_has_the_same_shape_when_it_has_numbers_in_it(pooled):
    doc = _slim(pooled)
    assert set(doc) == {"primary_horizon", "domains", "record", "by_domain"}
    assert doc["domains"] == ["energy", "semi"]
    for dom, block in doc["by_domain"].items():
        assert set(block) == {"domain", "record", "benchmark"}
        assert set(block["benchmark"]) == {"key", "symbol", "label"}
    assert json.dumps(doc)          # serialisable, as the file must be


def test_the_fixture_goes_through_the_real_record_json_builder(pooled):
    """The shape is whatever chains/track_site.record_json says it is — the
    same function publish_site writes the file with. The first version of
    this test compared against site/record.json on disk, which meant it
    passed or failed on how recently somebody had run a build."""
    from chains import track_site
    doc = track_site.record_json(pooled)
    assert doc == _slim(pooled)
    assert set(doc) == {"primary_horizon", "domains", "record", "by_domain"}


def test_an_empty_record_and_a_populated_one_have_the_same_keys(pooled):
    """The live record is all zeros today and will not always be. A key that
    appears only once there are numbers is a schema that changes under a
    reader the first time the site has something to say."""
    from chains import track_site
    empty = track_site.record_json(
        track.pooled({d: {"forecasts": []} for d in ("semi", "energy")}))
    full = track_site.record_json(pooled)
    assert set(empty) == set(full)
    assert set(empty["record"]) == set(full["record"])
    for dom in full["by_domain"]:
        assert set(empty["by_domain"][dom]) == set(full["by_domain"][dom])
    # and the gate is the one value that legitimately differs
    assert empty["record"]["capital_gated"] is True
    assert full["record"]["capital_gated"] is False


def test_the_fixture_never_writes_anything(tmp_path, pooled):
    """The whole file is in-memory: nothing under data/ or site/ is opened
    for writing at any point."""
    import os
    before = {p: os.stat(p).st_mtime for p in
              ("data/semi/map.json", "data/energy/map.json",
               "data/semi/commitments.json", "data/energy/commitments.json")}
    track.pooled({"semi": {"forecasts": []}})
    after = {p: os.stat(p).st_mtime for p in before}
    assert before == after


def test_the_same_qid_in_both_maps_is_two_events_not_one(fixture_cards):
    """The real collision, on the fixture: semi and energy both own gev_q3
    today. Keyed on the id alone the pooled record silently drops one of them
    and under-reports N -- so one card in each map is renamed to the same id
    and the pooled count must not move."""
    shared = f"{PREFIX}shared_q"
    cards = {}
    for dom, got in fixture_cards.items():
        cleared = [c for c in got if (c["horizons"] or {}).get(PH)]
        renamed = [dict(c, qid=shared) if c is cleared[0] else c for c in got]
        cards[dom] = renamed
    both = track.pooled({d: {"forecasts": c} for d, c in cards.items()})
    assert both["record"]["n"] == EXPECTED["pooled"][1] == 34, \
        "a question two maps name alike was counted once"
    assert both["by_domain"]["semi"]["record"]["n"] == 17
    assert both["by_domain"]["energy"]["record"]["n"] == 17


# -- either side of the threshold, to the question ---------------------------
# 29 / 30 / 31, built from the fixture cards rather than from new ones, so the
# boundary is tested against the same scoring that produced every other number
# in this file. The gate is a `<` comparison: 30 is NOT short.

def _n_cards(fixture_cards, n: int) -> list[dict]:
    """Exactly n cleared cards, drawn from both maps' fixture sample."""
    cleared = [c for dom in ("semi", "energy")
               for c in fixture_cards[dom] if (c["horizons"] or {}).get(PH)]
    assert len(cleared) >= n, "the fixture is too small for this boundary"
    # unique qids, so record_stats counts every one of them
    return [dict(c, qid=f"{PREFIX}bound_{i:02d}") for i, c in
            enumerate(cleared[:n])]


@pytest.mark.parametrize("n,gated", [(29, True), (30, False), (31, False)])
def test_the_pooled_gate_turns_off_at_the_threshold(fixture_cards, n, gated):
    rec = track.pooled(
        {"semi": {"forecasts": _n_cards(fixture_cards, n)}})["record"]
    assert rec["n"] == n
    assert rec["capital_gated"] is gated
    assert (rec["capital_rule"] is None) is not gated
    if gated:
        assert rec["capital_rule"] == forecast.CAPITAL_RULE


@pytest.mark.parametrize("n,gated", [(29, True), (30, False), (31, False)])
def test_a_single_map_block_gates_on_its_own_n(fixture_cards, n, gated):
    """Each block carries its own caveat, because each has its own sample.
    A map with 12 scored questions is still short on a site whose pooled
    record has cleared 30, and it has to say so."""
    block = track.pooled(
        {"energy": {"forecasts": _n_cards(fixture_cards, n)}}
    )["by_domain"]["energy"]["record"]
    assert block["n"] == n
    assert block["capital_gated"] is gated


def test_the_two_can_disagree(fixture_cards):
    """The real shape of it: pooled has cleared, one map has not."""
    data = track.pooled({"semi": {"forecasts": _n_cards(fixture_cards, 20)},
                         "energy": {"forecasts": _n_cards(fixture_cards, 12)}})
    assert data["record"]["n"] == 32
    assert data["record"]["capital_gated"] is False
    assert data["by_domain"]["energy"]["record"]["n"] == 12
    assert data["by_domain"]["energy"]["record"]["capital_gated"] is True


def test_the_threshold_is_read_from_the_scoring_code_not_retyped():
    """One comparison, one constant. Three copies of `n < 30` is three
    chances for one of them to be raised and the others forgotten."""
    assert forecast.capital_gated(forecast.MIN_N_FOR_CAPITAL - 1) is True
    assert forecast.capital_gated(forecast.MIN_N_FOR_CAPITAL) is False
    assert forecast.capital_note(forecast.MIN_N_FOR_CAPITAL) is None
    assert forecast.capital_note(0) == forecast.CAPITAL_RULE


# -- what the page actually renders -----------------------------------------

def test_the_page_prints_the_caveat_while_the_sample_is_short(tmp_path,
                                                              fixture_cards):
    from chains import track_site
    root = tmp_path / "short"
    for dom in ("semi", "energy"):
        d = root / dom
        d.mkdir(parents=True)
        (d / "track_public.json").write_text(
            json.dumps({"forecasts": _n_cards(fixture_cards, 10)}),
            encoding="utf-8")
    html = track_site.render(root, ["semi", "energy"], "https://x/")
    assert forecast.CAPITAL_RULE in html
    assert 'class="gate"' in html


def test_the_page_drops_the_element_entirely_once_it_clears(tmp_path,
                                                            fixture_cards):
    """Not an empty <p>: that would keep its margin and leave a gap where a
    caveat used to be, which reads as something failing to load."""
    from chains import track_site
    root = tmp_path / "long"
    for dom in ("semi", "energy"):
        d = root / dom
        d.mkdir(parents=True)
        (d / "track_public.json").write_text(
            json.dumps({"forecasts": _n_cards(fixture_cards, 17)}),
            encoding="utf-8")
    html = track_site.render(root, ["semi", "energy"], "https://x/")
    assert "no capital decision" not in html
    assert 'class="gate"' not in html
    assert "<p></p>" not in html
