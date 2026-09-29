"""What the site is allowed to claim about preregistration, and the four
states the forecast ledger has to tell apart.

The claim and the ledger are one problem, not two. The site said every
contract was set before its answer while one was not, and the ledger said no
answer had been marked while one had. Both are the same failure: copy that
asserts something the data underneath it can contradict.
"""
from __future__ import annotations

import json

import pytest

from chains import domains, sitenav, track
from chains.paths import commitments_path, templates_dir

RULE = sitenav.PREREGISTRATION_RULE
# Where each template says it: a literal, or the slot the engine fills with it.
RULE_SLOT = {"landing.html": "{{prereg_rule}}",
             "track-site.html": RULE,
             "track.html": "__PREREG_RULE__"}
# The hero no longer carries the caveat; the trust line under it does, and it
# is the line that has to hold on a build with nothing committed.
HERO = "Public contracts · Forward results · No backtests"


def tpl(name: str) -> str:
    return (templates_dir() / name).read_text(encoding="utf-8")


# -- the claim ----------------------------------------------------------------
def test_the_homepage_hero_no_longer_claims_every_contract_was_early():
    s = tpl("landing.html")
    assert HERO in s
    assert "Every forecast's scoring rules are set before the answer" not in s


def test_no_page_claims_that_every_contract_beat_its_answer():
    """The six locations the audit found, plus anything added since.

    A sitewide absolute is false the moment one commitment is late, and one
    is: semi's orcl_q1, committed three days after its answer date.
    """
    absolutes = [
        "Every forecast's scoring rules are set before the answer",
        "Every forecast recorded before the answer",
        "Every question was registered",
        "Every question is pre-registered before its answer date",
        "each with yes/no criteria set before the answer",
        "pre-registered, so anyone can verify it",
    ]
    bad = []
    for name in ("landing.html", "track-site.html", "track.html",
                 "track-detail.html", "live-map.html", "live-map-en.html"):
        s = tpl(name)
        bad += [f"{name}: {a}" for a in absolutes if a in s]
    src = (templates_dir().parent / "sitenav.py").read_text(encoding="utf-8")
    bad += [f"sitenav.py: {a}" for a in absolutes if a in src]
    assert not bad, bad


def test_the_qualified_rule_replaces_them():
    """Sentence case and the closing period vary with where it sits in the
    prose; the rule itself does not."""
    for name, slot in RULE_SLOT.items():
        assert slot in tpl(name), name
    # The descriptor is a label, not the rule: it says what the record is,
    # and says nothing about when any contract was committed.
    assert sitenav.TRACK_RECORD_DESCRIPTOR == "Public contracts · Forward scored"
    assert "every" not in sitenav.TRACK_RECORD_DESCRIPTOR.lower()


def test_the_rule_is_only_claimed_where_there_is_a_commitment_file():
    """Inside landing.html every statement of it sits in an IF:prereg block.

    A build with no commitments.json has nothing preregistered, and a page
    that explains the preregistration rule anyway is describing a thing it
    does not have. The nav descriptor is the deliberate exception: it defines
    the word for the whole site rather than claiming anything was hashed."""
    s = tpl("landing.html")
    blocks = []
    i = 0
    while "<!--IF:prereg-->" in s[i:]:
        a = s.index("<!--IF:prereg-->", i)
        b = s.index("<!--END:prereg-->", a)
        blocks.append(s[a:b])
        i = b
    covered = "".join(blocks)
    slot = RULE_SLOT["landing.html"]
    assert s.count(slot) == covered.count(slot) == 1
    # And the shorter restatement beside the three steps, which is the same
    # claim in fewer words and needs the same file behind it.
    short = "Late commitments remain public but do not count as preregistered"
    assert s.count(short) == covered.count(short) == 1


def test_the_methods_section_says_what_happens_to_a_late_commitment():
    """This asserted one exact sentence, and a later copy pass reworded it.

    The wording is not the thing worth pinning; the fact is. A page that
    explains the hashing and then leaves out what happens when a commitment
    arrives late is back to implying there are none, which is the failure
    this module exists to catch. Both wordings below say it, so both pass --
    dropping it altogether does not.
    """
    s = tpl("landing.html")
    accepted = (
        "A commitment made on or after the answer date is marked as not a "
        "valid preregistration.",
        "Commitments made on or after the answer date are marked invalid as "
        "preregistrations.",
        "Late commitments are labeled and never counted as preregistered.",
        "Late commitments remain public but do not count as preregistered.",
    )
    assert any(a in s for a in accepted), (
        "landing.html no longer states what happens to a late commitment")


def test_no_backtests_is_still_claimed_because_it_is_still_true():
    assert "No backtests" in tpl("landing.html")


# -- the per-map audit line ---------------------------------------------------
def test_the_audit_line_is_computed_not_typed():
    """Every map, from its own commitments.json. A typed number is true on
    the day it is typed and wrong the next time a question commits."""
    for dom in domains.discover():
        entries = json.loads(commitments_path(dom).read_text(encoding="utf-8"))
        valid = sum(1 for e in entries if e["valid_preregistration"])
        late = len(entries) - valid
        got = track.prereg_audit(dom)
        assert got == (f"{valid}/{len(entries)} contracts committed before "
                       f"the answer · {late} committed late."), dom


def test_the_audit_line_matches_the_field_the_gate_decides_with():
    """It counts valid_preregistration, which preregister sets from
    committed_at < answer_date. The page cannot disagree with the gate."""
    for dom in domains.discover():
        for e in json.loads(commitments_path(dom).read_text(encoding="utf-8")):
            assert e["valid_preregistration"] == (
                e["committed_at"] < e["answer_date"]), (dom, e["qid"])


def test_a_map_with_nothing_committed_says_nothing_rather_than_zero():
    assert track.prereg_audit("no-such-domain") == ""


def test_the_track_page_has_somewhere_to_put_it():
    assert track.AUDIT_PLACEHOLDER in tpl("track.html")


# -- the one late commitment --------------------------------------------------
def test_exactly_one_commitment_is_late_and_it_is_orcl_q1():
    late = [(dom, e["qid"], e["committed_at"], e["answer_date"])
            for dom in domains.discover()
            for e in json.loads(commitments_path(dom).read_text(encoding="utf-8"))
            if not e["valid_preregistration"]]
    assert late == [("semi", "orcl_q1", "2026-09-13", "2026-09-10")], late


def test_the_late_one_is_labelled_with_both_dates():
    js = tpl("track-cards.js")
    assert "LATE COMMITMENT · NOT PREREGISTERED" in js
    assert "after the answer date" in js
    assert "never counted as preregistered" in js
    assert "p.committed_at" in js and "p.answer_date" in js


def test_the_late_one_is_not_hidden():
    """It stays in commitments.json and on its card. A record that drops its
    own exception is not a record."""
    entries = json.loads(commitments_path("semi").read_text(encoding="utf-8"))
    assert any(e["qid"] == "orcl_q1" for e in entries)


# -- the four ledger states ---------------------------------------------------
@pytest.mark.parametrize("name", ["live-map.html", "live-map-en.html"])
def test_the_ledger_reads_answers_before_scores(name):
    """The bug: it branched on `rows` -- the scored forecasts -- and printed
    "no answer has been marked yet" when semi had one. A mixed answer points
    nowhere, produces no forecast, and left rows empty."""
    s = tpl(name)
    i = s.index("if(!rows.length){")
    head = s[max(0, i - 2000):i]
    assert "D.answers" in head, f"{name}: the states must be read from answers"
    assert "No answer has been marked yet" not in s


@pytest.mark.parametrize("name", ["live-map-en.html"])
def test_all_four_states_have_their_own_words(name):
    s = tpl(name)
    for want in ("No answers recorded yet",
                 "next expected answer",
                 "Partial \\u00b7 observation only",
                 "This answer remains in the public record but does not "
                 "enter the score.",
                 "Answered \\u00b7 scoring pending"):
        assert want in s, want


def test_observation_only_is_never_green_or_red():
    """It is in the record and out of the score. Colouring it either way
    states an outcome the answer never produced."""
    s = tpl("live-map.html")
    block = s[s.index(".ldg-obs{"):s.index(".ldg-obs{") + 400]
    assert "var(--rule)" in block
    for colour in ("--pos", "--neg", "green", "red", "#3fd18b", "#ff5a3c"):
        assert colour not in block, f"observation-only must stay neutral: {colour}"


def test_pending_is_amber_and_never_drawn_as_a_score():
    s = tpl("live-map.html")
    assert ".ldg-pending-tag{color:var(--amber)" in s.replace(
        ".ldg-pending .ldg-tag,", "")
    i = s.index("const settled =")
    assert "primary_horizon" in s[i - 300:i + 200]


def test_amber_marks_the_expected_date_and_not_an_outcome():
    s = tpl("live-map.html")
    block = s[s.index(".ldg-next{"):s.index(".ldg-next{") + 120]
    assert "var(--amber)" in block
    i = s.index("LT.nextAnswer")
    assert "ldg-next" in s[i - 200:i + 200]


# -- what the real data actually contains today -------------------------------
def test_only_two_of_the_four_states_exist_in_live_data():
    """Recorded so the next person does not go looking for screenshots of
    the other two. Nothing is scored anywhere and nothing sits in an open
    scoring window; the four states are unit-tested, not all photographable.
    """
    answered = {}
    for dom in domains.discover():
        p = commitments_path(dom).parent / "marks.json"
        if not p.exists():
            answered[dom] = 0
            continue
        m = json.loads(p.read_text(encoding="utf-8"))
        answered[dom] = len((m.get("answers") or {}) if isinstance(m, dict) else m)
    assert answered["semi"] == 1
    assert all(v == 0 for k, v in answered.items() if k != "semi"), answered


# -- the four states, executed rather than grepped -----------------------------
# The states are chosen in JavaScript, so the only honest test of them runs the
# template's own code. Both slices are lifted verbatim out of live-map-en.html:
# the labels, the state selection and the card rendering are the shipped ones,
# and the harness supplies only what the surrounding page would have supplied.
HARNESS = """
const tiles = {innerHTML:''};
const cards = {innerHTML:''};
function gate(){ return '<!--gate-->'; }
function poolGate(){}
function tok(){ return '#888888'; }
function nameOf(i){ return i; }
const D = %(D)s, rows = %(rows)s, S = %(S)s;
const byQ = {};
(D.watch||[]).forEach(w=>{ byQ[w.id] = w; });
function ledger(){
%(prelude)s
%(rowcards)s
  return 'scored-branch';
}
// States 1 and 2 return before the scoring branch, so `reached` is undefined
// there; JSON drops an undefined value, which would silently delete the key.
const reached = ledger() || 'returned-early';
process.stdout.write(JSON.stringify(
  {tiles: tiles.innerHTML, cards: cards.innerHTML, reached: reached}));
"""


def _slice(src: str, start: str, end: str) -> str:
    i = src.index(start)
    j = src.index(end, i)
    return src[i:j + len(end)]


def _ledger(D, rows, S, tmp_path):
    import shutil
    import subprocess
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    src = tpl("live-map-en.html").replace("\r\n", "\n")
    js = tmp_path / "ledger.js"
    js.write_text(HARNESS % {
        "D": json.dumps(D), "rows": json.dumps(rows), "S": json.dumps(S),
        # STATUS is declared twice in the page, on purpose and identically,
        # so each section owns its own; the ledger is anchored on its LT,
        # which is the one thing in the file unique to it.
        "prelude": (_slice(src, "const STATUS = {open:", "};") + "\n"
                    + _slice(src, "const LT = {h2:'Measured outcomes'",
                             "}).join('');\n    return;\n  }")),
        "rowcards": _slice(src, "function spark(series){",
                           "\n  }).join('');"),
    }, encoding="utf-8")
    out = subprocess.run(["node", str(js)], capture_output=True,
                         check=True).stdout.decode("utf-8")
    return json.loads(out)


WATCH = [{"id": "q1", "who": "Acme Q3", "d": "2026-09-10"}]
SUM = {"primary_horizon": 20, "n": 0}


def _row(qid="q1", horizons=None):
    return {"qid": qid, "direction": 1, "order": 1, "status": "yes",
            "marked_at": "2026-09-11", "entry_session": "2026-09-11",
            "entry_close": 100.0, "sessions": 3, "symbols": [],
            "series": [], "horizons": horizons or {}}


def test_state_1_nothing_answered_names_the_date_and_no_outcome(tmp_path):
    got = _ledger({"answers": {}, "watch": WATCH,
                   "cal": [{"d": "2026-10-22", "days": 24}]}, [], SUM, tmp_path)
    assert "No answers recorded yet." in got["tiles"]
    assert "next expected answer" in got["tiles"] and "2026-10-22" in got["tiles"]
    assert got["cards"] == ""
    assert got["reached"] != "scored-branch"
    # The amber is on the date, never on a verdict word.
    assert 'class="ldg-next"' in got["tiles"]
    for word in ("confirmed", "refuted", "hit", "miss"):
        assert word not in got["tiles"]


def test_state_1_without_a_known_date_says_only_that_nothing_is_answered(tmp_path):
    got = _ledger({"answers": {}, "watch": WATCH, "cal": []}, [], SUM, tmp_path)
    assert "No answers recorded yet." in got["tiles"]
    assert "next expected answer" not in got["tiles"]


def test_state_2_is_the_bug_semi_had(tmp_path):
    """One answer, marked mixed, nothing scorable. The page used to say no
    answer had been marked at all."""
    got = _ledger({"answers": {"q1": {"status": "mixed",
                                      "marked_at": "2026-09-11"}},
                   "watch": WATCH, "cal": []}, [], SUM, tmp_path)
    assert "No answers recorded yet." not in got["tiles"]
    assert "1 answer recorded" in got["tiles"] and "0 scored" in got["tiles"]
    assert "Partial · observation only" in got["cards"]
    assert ("This answer remains in the public record but does not enter the "
            "score.") in got["cards"]
    assert "Acme Q3" in got["cards"] and "marked 2026-09-11" in got["cards"]


def test_state_2_counts_answers_in_the_plural_correctly(tmp_path):
    got = _ledger({"answers": {"q1": {"status": "mixed"},
                               "q2": {"status": "none"}},
                   "watch": WATCH, "cal": []}, [], SUM, tmp_path)
    assert "2 answers recorded · 0 scored" in got["tiles"]


def test_state_2_never_colours_an_observation_as_an_outcome(tmp_path):
    got = _ledger({"answers": {"q1": {"status": "mixed"}}, "watch": WATCH,
                   "cal": []}, [], SUM, tmp_path)
    for cls in ('class="pos"', 'class="neg"', "hit", "miss"):
        assert cls not in got["cards"], cls


def test_an_open_answer_is_not_an_answer(tmp_path):
    """status 'open' is the absence of an answer, not a third kind of one."""
    got = _ledger({"answers": {"q1": {"status": "open"}}, "watch": WATCH,
                   "cal": []}, [], SUM, tmp_path)
    assert "No answers recorded yet." in got["tiles"]


def test_state_3_answered_and_still_scoring_is_amber_not_a_score(tmp_path):
    """Horizons exist at 5 and 10; the primary is 20 and has not closed."""
    got = _ledger(
        {"answers": {"q1": {"status": "yes"}}, "watch": WATCH, "cal": []},
        [_row(horizons={"5": {"excess": 0.01, "hit": True},
                        "10": {"excess": 0.02, "hit": True}, "20": None})],
        SUM, tmp_path)
    assert got["reached"] == "scored-branch"
    assert "Answered · scoring pending" in got["cards"]
    assert "ldg-pending-tag" in got["cards"]


def test_state_4_scored_at_the_primary_horizon_drops_the_pending_tag(tmp_path):
    got = _ledger(
        {"answers": {"q1": {"status": "yes"}}, "watch": WATCH, "cal": []},
        [_row(horizons={"5": {"excess": 0.01, "hit": True},
                        "20": {"excess": 0.03, "hit": True}})],
        SUM, tmp_path)
    assert got["reached"] == "scored-branch"
    assert "Answered · scoring pending" not in got["cards"]
    assert "hit" in got["cards"]


def test_the_pending_tag_follows_the_primary_horizon_and_not_the_number_20(tmp_path):
    """A map whose primary horizon is 40 is still pending at 20."""
    got = _ledger(
        {"answers": {"q1": {"status": "yes"}}, "watch": WATCH, "cal": []},
        [_row(horizons={"20": {"excess": 0.03, "hit": True}})],
        {"primary_horizon": 40, "n": 0}, tmp_path)
    assert "Answered · scoring pending" in got["cards"]


# -- the late commitment, as the card actually draws it ------------------------
def _card_html(prereg, tmp_path):
    """The shipped renderer, run over one answered question."""
    import shutil
    import subprocess
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    src = (templates_dir() / "track-cards.js").read_text(encoding="utf-8")
    payload = {"as_of": "2026-09-28", "summary": {}, "forecasts": [
        {"qid": "orcl_q1", "who": "Oracle Q1", "state": "reported",
         "status": "mixed", "d": prereg["answer_date"],
         "report_date": prereg["answer_date"], "members": [],
         "prereg": prereg}]}
    js = tmp_path / "card.js"
    js.write_text("globalThis.window = {};\n" + src
                  + "\nconst root = {};\nwindow.renderTrack(root, "
                  + json.dumps(payload) + ");\n"
                  + "process.stdout.write(root.innerHTML);\n",
                  encoding="utf-8")
    return subprocess.run(["node", str(js)], capture_output=True,
                          check=True).stdout.decode("utf-8")


def _orcl_prereg():
    """The real entry, not a fixture. If the record changes, this test moves
    with it rather than quietly testing a number nobody ships."""
    for e in json.loads(commitments_path("semi").read_text(encoding="utf-8")):
        if e["qid"] == "orcl_q1":
            return {"sha256": e["sha256"], "committed_at": e["committed_at"],
                    "answer_date": e["answer_date"],
                    "valid_preregistration": e["valid_preregistration"],
                    "primary_horizon": e.get("primary_horizon", 20),
                    "contract": "placeholder contract bytes"}
    raise AssertionError("orcl_q1 is not in semi's commitments")


def test_the_late_card_says_committed_not_preregistered(tmp_path):
    html = _card_html(_orcl_prereg(), tmp_path)
    assert "LATE COMMITMENT \u00b7 NOT PREREGISTERED" in html
    assert 'class="late-commit"' in html
    assert "Committed 2026-09-13, after the answer date 2026-09-10." in html
    assert "never counted as preregistered" in html
    # The headline word is "Committed", never "Pre-registered".
    head = html[html.index("data-prereg="):]
    assert head[:600].count("Pre-registered") == 0


def test_a_contract_committed_in_time_carries_no_such_marker(tmp_path):
    """The marker is a statement about one entry, not decoration on all of
    them: with a valid commitment it must be absent entirely."""
    p = dict(_orcl_prereg(), committed_at="2026-09-01",
             valid_preregistration=True)
    html = _card_html(p, tmp_path)
    assert "LATE COMMITMENT" not in html and "late-commit" not in html
    assert "Pre-registered 2026-09-01" in html


def test_the_marker_is_amber_and_not_a_verdict_colour(tmp_path):
    """Amber is the site's "expected, not settled" colour. Green and red mean
    a registered direction was confirmed or refuted, which this is not."""
    html = _card_html(_orcl_prereg(), tmp_path)
    i = html.index('class="late-commit"')
    block = html[i:i + 300]
    assert "#f2b632" in block
    for colour in ("#3fd18b", "#ff5a3c", "green", "red"):
        assert colour not in block, colour
