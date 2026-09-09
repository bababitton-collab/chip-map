"""The snapshot's two hard constraints: the size ceiling and the clock."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from chains import live_snapshot as ls
from chains.paths import out_dir

# build() reads what the earlier steps wrote. On a clean checkout they have not
# run, and a test that needs them is skipped rather than failed: "the pipeline
# has not been run here" is not a defect, and a suite that goes red on a fresh
# clone teaches people to ignore red.
NEEDS_BUILD = [out_dir() / "chain_page.json",
               out_dir() / "chain_fundamentals.json"]
needs_build = pytest.mark.skipif(
    not all(p.exists() for p in NEEDS_BUILD),
    reason="run python -m chains.build_all first (needs out/chain_page.json)")


def snap(n_sigs=1, signal="x" * 400, approach="y" * 400):
    """A minimal snapshot shaped like the real one."""
    return {
        "as_of": "2026-09-08", "map_version": "2.1",
        "nodes": [{"id": "a", "role": "r" * 400, "px": None}],
        "edges": [], "flows": [], "fund": {}, "cal": [],
        "cps": [{
            "id": "CP1", "he": "x", "blurb": "b" * 400, "name": "n",
            "holders": [], "chal": [],
            "sigs": [{"signal": signal, "approach": approach}] * n_sigs,
            "subs": [{"what": "w" * 400, "share": "s" * 400}],
            "pressure": None, "hr13": None, "cr13": None, "n_chal_priced": 0,
        }],
        "last_price_date": "2026-09-04",
    }


# -- the ceiling ------------------------------------------------------------

def test_a_small_snapshot_is_written_untrimmed(tmp_path):
    p, size, applied = ls.write(snap(signal="s", approach="a"),
                                tmp_path / "live.json")
    assert applied == [], "nothing to trim"
    assert size < ls.TRIM_AT and p.exists()


def test_an_oversized_snapshot_is_shortened_not_thinned(tmp_path):
    """Strings shrink; the node and chokepoint counts do not."""
    live = snap(n_sigs=4000)
    before = (len(live["nodes"]), len(live["cps"]),
              len(live["cps"][0]["sigs"]), len(live["cps"][0]["subs"]))
    ls.shrink_to_fit(live)
    after = (len(live["nodes"]), len(live["cps"]),
             len(live["cps"][0]["sigs"]), len(live["cps"][0]["subs"]))
    assert before == after, "the ladder dropped a record instead of shortening"
    assert len(live["cps"][0]["sigs"][0]["signal"]) < 400


def test_the_ladder_shortens_in_order_and_stops_when_it_fits():
    live = snap(n_sigs=300)
    applied = ls.shrink_to_fit(live)
    assert applied, "should have needed at least one rung"
    assert applied[0] == ls.TRIM_LADDER[0][0], "cheapest cut first"
    assert len(ls._dump(live)) <= ls.TRIM_AT


def test_a_snapshot_that_cannot_fit_FAILS_rather_than_writing(tmp_path):
    """The artifact database refuses anything over 256 KB, so an oversized file
    does not degrade -- it never arrives. Failing here is the loud version."""
    live = snap()
    live["nodes"] = [{"id": f"n{i}", "role": "", "px": None}
                     for i in range(400_000)]
    with pytest.raises(SystemExit) as e:
        ls.write(live, tmp_path / "live.json")
    assert "over the" in str(e.value)
    assert not (tmp_path / "live.json").exists(), "no partial file"


def test_the_limits_sit_below_what_the_database_refuses():
    """Decimal, not binary. "250 KB" reads as either 250,000 or 256,000 and the
    difference is 6 KB -- more than the headroom at the current size. The
    stricter reading is wrong in the safe direction."""
    assert ls.TRIM_AT < ls.MAX_BYTES < ls.HARD_LIMIT
    assert ls.MAX_BYTES == 250_000 and ls.HARD_LIMIT == 256_000


# -- the clock --------------------------------------------------------------

def test_today_is_not_a_constant():
    """A frozen date drifts a week further from the truth on every weekly run
    while still looking like a live number."""
    src = (ls.__file__)
    text = open(src, encoding="utf-8").read()
    assert "dt.date.today()" in text
    assert "TODAY = dt.date(" not in text, "a hard-coded date crept back in"


def test_a_past_dated_question_drops_out():
    """Absent from the file, not filtered by the page, so a question whose date
    has gone cannot be rendered as still upcoming."""
    today = dt.date(2026, 9, 9)
    watch = [
        {"id": "old", "d": "2020-01-01", "cps": ["CP1"], "confirmed": True,
         "who": "past"},
        {"id": "new", "d": "2099-01-01", "cps": ["CP1"], "confirmed": True,
         "who": "future"},
    ]
    out = ls.calendar_from(watch, today)
    assert [r["id"] for r in out] == ["new"] and out[0]["days"] > 0


def test_a_question_dated_today_is_still_upcoming():
    watch = [{"id": "t", "d": "2026-09-09", "cps": ["CP1"], "confirmed": True}]
    assert len(ls.calendar_from(watch, dt.date(2026, 9, 9))) == 1


def test_a_row_with_no_chokepoint_is_not_a_marker():
    """It stays in the watch list, which the page holds inline. It simply has
    nothing on the map to attach to."""
    watch = [{"id": "a", "d": "2099-01-01", "cps": [], "confirmed": True},
             {"id": "b", "d": "2099-01-01", "cps": ["CP1"], "confirmed": True}]
    assert [r["id"] for r in ls.calendar_from(watch, dt.date(2026, 9, 9))] == ["b"]


def test_the_provisional_flag_survives_into_the_marker():
    """A date the company has not announced must not be rendered as firm."""
    watch = [{"id": "x", "d": "2099-01-01", "cps": ["CP1"], "confirmed": False}]
    assert ls.calendar_from(watch, dt.date(2026, 9, 9))[0]["confirmed"] is False


def test_markers_come_back_in_date_order():
    watch = [{"id": "b", "d": "2099-02-01", "cps": ["CP1"], "confirmed": True},
             {"id": "a", "d": "2099-01-01", "cps": ["CP1"], "confirmed": True}]
    assert [r["id"] for r in ls.calendar_from(watch, dt.date(2026, 9, 9))] ==         ["a", "b"]


def test_the_prose_is_not_shipped_twice():
    """The page carries all 39 rows inline, so q/listen/win/lose must not also
    travel in a file with a hard size ceiling."""
    watch = [{"id": "x", "d": "2099-01-01", "cps": ["CP1"], "confirmed": True,
              "who": "w", "q": "Q" * 500, "listen": "L" * 500,
              "win": ["a"], "lose": ["b"], "tk": "TK"}]
    row = ls.calendar_from(watch, dt.date(2026, 9, 9))[0]
    assert set(row) == {"id", "d", "who", "cps", "confirmed", "days"}


# -- price maths ------------------------------------------------------------

def test_the_return_uses_the_last_bar_on_or_before_the_target():
    rows = [(dt.date(2026, 1, 1), 100.0), (dt.date(2026, 6, 1), 110.0),
            (dt.date(2026, 9, 1), 120.0)]
    assert ls.ret(rows, 92) == pytest.approx(120.0 / 110.0 - 1, rel=1e-9)


def test_a_return_with_no_earlier_bar_is_none_not_zero():
    assert ls.ret([(dt.date(2026, 9, 1), 120.0)], 91) is None


def test_a_zero_earlier_price_gives_none_not_infinity():
    rows = [(dt.date(2026, 1, 1), 0.0), (dt.date(2026, 9, 1), 120.0)]
    assert ls.ret(rows, 91) is None


def test_weekly_keeps_the_last_close_of_each_iso_week():
    rows = [(dt.date(2026, 1, 5), 1.0), (dt.date(2026, 1, 9), 2.0),
            (dt.date(2026, 1, 12), 3.0)]
    assert [v for _, v in ls.weekly(rows)] == [2.0, 3.0]


def test_the_output_is_valid_json_at_every_rung(tmp_path):
    live = snap(n_sigs=500)
    p, _, _ = ls.write(live, tmp_path / "live.json")
    json.loads(p.read_text(encoding="utf-8"))


# -- the tracked watch list -------------------------------------------------

WATCH = ls.load_watch()


def test_the_watch_list_is_the_expected_shape():
    assert isinstance(WATCH, list) and len(WATCH) >= 39


@pytest.mark.parametrize("field", ["id", "d", "confirmed", "who", "cps"])
def test_every_watch_row_carries_its_fields(field):
    missing = [r.get("id", "?") for r in WATCH if field not in r]
    assert missing == []


def test_every_watch_date_parses():
    for r in WATCH:
        dt.date.fromisoformat(r["d"])


def test_every_watch_cps_id_exists_in_the_map():
    """A question pinned to a chokepoint the map does not have is a marker the
    page can never place, and it fails silently."""
    from chains import mapfile
    real = {c["id"] for c in mapfile.load()["chokepoints"]}
    bad = [(r["id"], c) for r in WATCH for c in (r.get("cps") or [])
           if c not in real]
    assert bad == []


def test_watch_ids_are_unique():
    ids = [r["id"] for r in WATCH]
    assert len(ids) == len(set(ids))


def test_confirmed_is_a_boolean_not_a_string():
    """"false" is truthy. A provisional date that reads as confirmed is exactly
    the error this flag exists to prevent."""
    assert all(isinstance(r["confirmed"], bool) for r in WATCH)


def test_the_watch_list_carries_both_confirmed_and_provisional_rows():
    """If everything were confirmed the flag would be decoration. 17 of 39 are
    expected dates from a company's reporting rhythm, not announcements."""
    assert any(r["confirmed"] for r in WATCH)
    assert any(not r["confirmed"] for r in WATCH)


@needs_build
def test_live_json_now_carries_the_watch_list():
    """This is a REVERSAL, and the reason is worth keeping.

    The rule used to be the opposite: the page held all 39 rows inline and
    live.json carried only ``cal``, so the prose would not travel twice into a
    file with a hard ceiling. That was correct while the page was rebuilt
    whenever a row changed. It stopped being correct once the weekly job
    republishes the same HTML: a date the company announced was corrected in
    watch.json and the page went on rendering the copy that was compiled into
    it, because nothing in the weekly chain rebuilt the inline list.

    So the rows travel in the file now, and the inline copy is the fallback for
    a failed fetch. The size budget still holds -- see the ceiling tests above
    -- because the same change stopped shipping 234 unread sparklines.
    """
    live = ls.build()
    assert len(live["watch"]) >= 39
    assert {"q", "listen", "leaks", "lane"} <= set(live["watch"][0])


@needs_build
def test_cal_stays_lean_even_though_watch_does_not():
    """``cal`` is the marker layer, not a second copy of the list. It carries
    join keys and timing only, and it is filtered by date in a way the full
    list deliberately is not."""
    live = ls.build()
    assert all(set(r) <= {"id", "d", "who", "cps", "confirmed", "days"}
               for r in live["cal"])
    assert len(live["cal"]) < len(live["watch"]), (
        "cal should hold only dated rows with a chokepoint")


@needs_build
def test_both_languages_are_built_from_the_same_numbers():
    """Only the prose differs. A price that differed between the two files
    would mean two maps claiming different facts on the same day."""
    he, en = ls.build(lang="he"), ls.build(lang="en")
    assert he["as_of"] == en["as_of"]
    assert he["last_price_date"] == en["last_price_date"]
    assert [n["px"] for n in he["nodes"]] == [n["px"] for n in en["nodes"]]
    assert [c["pressure"] for c in he["cps"]] == [c["pressure"]
                                                 for c in en["cps"]]


@needs_build
def test_the_english_snapshot_carries_no_hebrew():
    """The gate in build_pages is the last line; this is the first."""
    from chains import build_pages
    assert build_pages.hebrew_runs(ls._dump(ls.build(lang="en")).decode()) == []


@needs_build
def test_the_hebrew_snapshot_is_actually_hebrew():
    """Guards against the two languages silently collapsing into one."""
    from chains import build_pages
    assert build_pages.hebrew_runs(ls._dump(ls.build(lang="he")).decode())


@needs_build
def test_a_subnode_carries_only_the_number_it_shows():
    """Subnodes and challengers render a single 13w badge. Shipping them a
    full 52-point price block put 47 KB of unread numbers into a file with a
    hard ceiling -- more than the whole trim ladder can recover."""
    live = ls.build()
    blocks = [s["px"] for c in live["cps"] for s in c["subs"] if s["px"]]
    assert blocks, "no priced subnodes -- the test would pass vacuously"
    assert all(set(b) == {"r13w"} for b in blocks)


def test_answers_default_to_empty_and_are_never_invented(tmp_path,
                                                         monkeypatch):
    """No file, no answers. Not a guess, not a lean, not a default status."""
    monkeypatch.setenv("CHIP_MAP_OUT", str(tmp_path))
    monkeypatch.delenv("ANSWERS_URL", raising=False)
    from chains import answers
    assert answers.load(ids={"mu_fq4"}) == {}


@needs_build
def test_a_bad_answer_row_is_dropped_and_the_snapshot_still_builds(tmp_path):
    """One usable answer, one unusable, and a run that still produces both
    files. The exporter is on the other side of a gap and nobody is watching
    in between; losing Saturday's whole chain to one bad status string would
    be the worse failure."""
    from chains import answers
    p = tmp_path / "answers.json"
    p.write_text(json.dumps({
        "mu_fq4": {"status": "yes", "note": "40% by 2027"},
        "nvda_q3": {"status": "probably"},
    }), encoding="utf-8")

    good, _forecasts, problems = answers.read(p, ids={r["id"] for r in WATCH})
    assert set(good) == {"mu_fq4"}
    assert len(problems) == 1
    assert "nvda_q3" in problems[0] and "probably" in problems[0]

    for lang in ("he", "en"):
        live = ls.build(lang=lang, answers=good)
        assert live["answers"]["mu_fq4"]["status"] == "yes"
        assert live["answers"]["mu_fq4"]["note"] == "40% by 2027"
        assert "nvda_q3" not in live["answers"], "a dropped row was embedded"


@pytest.mark.parametrize("field", ["who", "d", "days", "cps"])
def test_every_cal_row_carries_what_the_panel_reads(field):
    """The panel's "next checkpoint" line reads who, d and days, and finds its
    row by matching the chokepoint against cps. It used to read e.cp and
    nx.he -- neither of which is emitted -- so it silently never rendered."""
    rows = ls.calendar_from(ls.load_watch(), dt.date(2026, 9, 9))
    assert rows, "no calendar rows -- the test would pass vacuously"
    assert [r for r in rows if r.get(field) in (None, "")] == []


def test_a_cal_row_can_be_matched_to_a_chokepoint_by_cps():
    """cps is a list, and the panel membership-tests it. A scalar here would
    make every match fail without erroring."""
    rows = ls.calendar_from(ls.load_watch(), dt.date(2026, 9, 9))
    assert all(isinstance(r["cps"], list) and r["cps"] for r in rows)


# -- the ledger --------------------------------------------------------------

@needs_build
def test_both_snapshots_carry_the_same_ledger():
    """It is ids, symbols and numbers -- no prose -- so one scoring run serves
    both files. A ledger that differed between them would be two different
    records of the same claim."""
    he, en = ls.build(lang="he"), ls.build(lang="en")
    assert he["ledger"] == en["ledger"]


@needs_build
def test_the_ledger_is_present_even_with_nothing_marked():
    """An empty ledger is a valid ledger. The page renders "nothing marked
    yet"; a missing key would render a broken section."""
    live = ls.build(ledger={"summary": {"n_scored": 0}, "rows": []})
    assert "ledger" in live and live["ledger"]["rows"] == []


@needs_build
def test_the_snapshot_stays_under_the_ceiling_with_a_ledger():
    """The assertion the whole trim ladder exists for. write() refuses to
    produce an oversized file; this states the invariant at the call site."""
    for lang in ("he", "en"):
        blob = ls._dump(ls.build(lang=lang))
        assert len(blob) < ls.MAX_BYTES, f"{lang} is {len(blob):,} bytes"


def test_the_first_rung_sheds_the_per_symbol_series_not_the_basket_one():
    """Under pressure the detail goes and the claim stays."""
    assert ls.TRIM_LADDER[0][0] == "ledger per-symbol series"
    live = {"cps": [], "nodes": [], "ledger": {"rows": [
        {"series": [1, 2, 3], "symbols": [{"series": [1, 2, 3]}]}]}}
    ls.TRIM_LADDER[0][1](live)
    row = live["ledger"]["rows"][0]
    assert "series" not in row["symbols"][0]
    assert row["series"] == [1, 2, 3]
