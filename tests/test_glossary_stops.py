"""Jargon that is also an ordinary English word, and the rule that tells them apart.

On the live map the Micron card read "Will Micron confirm it is on track for
its 2027 HBM share target" with "track" underlined and a definition of a litho
coater under it, and Coater in the Terms line, on a card about memory share
with no coater anywhere in it. "track" is a legitimate synonym for the
coater/developer track; whole-word matching simply cannot tell that sense from
the idiom.

The fix is a ``stop`` list per term. These tests hold the three things that
fix has to keep true: the idioms are off, the jargon is still on, and the two
matchers -- chains/glossary.py, which decides WHICH terms a card shows, and
chains/templates/glossary.js, which places them -- agree about every question
on the site. A disagreement between those two is a chip with no underline, or
worse, an underline the chip row never sanctioned.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from chains import domains, glossary
from chains.paths import map_path, out_dir, templates_dir

FIELDS = ("q", "yes", "no", "why")


def terms():
    return glossary.load("semi")


# -- 1. the ten idioms the audit found ----------------------------------------
# Every one of these was a live or latent false positive: the word is ordinary
# English and the term it took is a piece of semiconductor equipment.
IDIOMS = [
    ("semi/mu_fq4", "coater",
     "Will Micron confirm it is on track for its 2027 HBM share target, and "
     "put a number on the HBM4 ramp?"),
    ("semi/amkr_q3", "coater",
     '"Discussions ongoing", construction on track, no name.'),
    ("semi/intc_q3", "soc_test",
     "This is the sharpest yes-or-no test on the list: does a US foundry "
     "alternative to TSMC exist or not."),
    ("semi/hanmi_q3", "soc_test",
     "This is the test of whether a chokepoint holder can lose the lock fast."),
    ("semi/absolics", "soc_test",
     "This is the cleanest binary test in materials."),
    ("defense/ge_aero_q3", "soc_test",
     "Whether output actually moves is the test of whether castings were the "
     "binding constraint."),
    ("defense/lmt_q3", "soc_test",
     "Lockheed is the largest buyer of solid rocket motors and the biggest "
     "single test of whether munitions demand is converting into delivered "
     "revenue."),
    ("defense/mp_ndpr_q3", "soc_test",
     "It is the nearest dated test of whether the only integrated US magnet "
     "chain is ramping on schedule."),
    ("medicine/novartis_q3", "soc_test",
     "Novartis is the largest test of whether that cap has moved."),
    ("energy/powl_q4", "process_node",
     "Powell's switchgear is a smaller, tighter node in the power chain."),
]


@pytest.mark.parametrize("where,tid,text", IDIOMS,
                         ids=[f"{w}-{t}" for w, t, _ in IDIOMS])
def test_an_idiom_does_not_take_the_term_that_spells_it(where, tid, text):
    assert tid not in glossary.find(text, terms(), limit=99), where
    assert f'data-gl="{tid}"' not in glossary.mark(text, terms()), where


# -- and the real sense is untouched -------------------------------------------
REAL = [
    ("coater", "TEL is the sole supplier of the coaters that apply EUV resist."),
    ("soc_test", "HBM or GPU test orders named, a customer identified."),
    ("soc_test", "Advantest is the single test chokepoint."),
    ("process_node", "A production-node dry-resist paper from TSMC or Intel."),
    ("process_node", "Will Samsung show 2nm foundry yields improving?"),
]


@pytest.mark.parametrize("tid,text", REAL)
def test_the_jargon_still_matches(tid, text):
    """A stop list that turned the term off everywhere would 'fix' this by
    deleting the feature."""
    assert tid in glossary.find(text, terms(), limit=99)


def test_a_stopped_span_leaves_a_later_one_alone():
    """Covered, not merely nearby: one idiom in a sentence must not silence a
    real use of the same word further along it."""
    text = ("Construction is on track, and TEL still supplies the track that "
            "coats every EUV wafer.")
    assert "coater" in glossary.find(text, terms(), limit=99)
    marked = glossary.mark(text, terms())
    assert marked.count('data-gl="coater"') == 1, marked


# -- 2. a stop phrase has to be about its own term ------------------------------
def test_every_stop_phrase_contains_one_of_its_terms_match_strings():
    """A stop entry that does not contain a word the term matches on can never
    fire. It is dead config that reads as a guarantee."""
    dead = []
    for t in terms():
        for phrase in t.get("stop") or []:
            low = phrase.lower()
            if not any(m.lower() in low for m in t["match"]):
                dead.append((t["id"], phrase))
    assert dead == [], dead


def test_a_stop_phrase_is_matched_whatever_the_case():
    """An idiom is an idiom at the start of a sentence too."""
    assert "coater" not in glossary.find(
        "On track for the 2027 target.", terms(), limit=99)


def test_stop_is_optional():
    """Most terms need none, and a term without one behaves exactly as before."""
    assert any(not t.get("stop") for t in terms())
    assert "hbm" in glossary.find("HBM4 ramp", terms(), limit=99)


# -- 3. every ordinary word in the match list has been looked at ----------------
# A new all-lowercase match string is a new chance for this bug. Adding one
# fails here until somebody has written it down, which is the moment to ask
# whether it has an idiom.
REVIEWED = {
    "2nm", "300mm", "advanced packaging", "aeroderivative", "anchor customer",
    "backlog", "base die", "blade castings", "blades", "bonder", "bonders",
    "bookings", "capex", "capital expenditure", "castings", "coater",
    "coaters", "consensus", "customer mix", "data center revenue",
    "datacenter revenue", "dry resist", "electrical steel", "electrical-steel",
    "export ban", "export controls", "export license", "export licenses",
    "export suspension", "fab", "fabs", "fiscal year", "foundries", "foundry",
    "gallium", "gas turbine", "gas-turbine", "germanium", "glass substrate",
    "gross margin", "guidance", "guide", "guided", "half-year",
    "high-bandwidth memory", "indium phosphide", "indium-phosphide",
    "large power transformer", "lead time", "lead times", "magnets", "margin",
    "mask", "mask blank", "mask blanks", "mask-blank", "mask-inspection",
    "masks", "node", "operating margin", "operating profit", "orders",
    "packaging", "photoresist", "preliminary", "preliminary numbers",
    "process node", "q/q", "quarter on quarter", "rare earth", "rare-earth",
    "remaining performance obligations", "resist", "second source",
    "second-source", "semi-test", "sequentially", "slots", "substrate",
    "substrates", "supplier mix", "test", "track", "transceiver",
    "transceivers", "transformer", "transformers", "wafer",
    "wafer-fab equipment", "wafers", "yield", "yields",
}


def test_every_case_insensitive_match_string_has_been_reviewed():
    lower = {m for t in terms() for m in t["match"] if m == m.lower()}
    new = sorted(lower - REVIEWED)
    assert new == [], (
        f"new case-insensitive match string(s) {new}: each one is an ordinary "
        f"English word to the matcher. Check it against a common idiom, add a "
        f"`stop` list if it has one, then add it to REVIEWED.")


# -- 4. the two matchers agree over every question on the site ------------------
# The file is written for a browser: it hangs itself off `window` and wires
# two listeners to `document`. Node has neither, so both are stubbed with just
# enough to let the module finish loading. Nothing about matching is stubbed.
HARNESS = """
const window = globalThis;
const noop = () => {};
globalThis.document = {addEventListener: noop, createElement: () => ({style: {},
  appendChild: noop, setAttribute: noop, classList: {add: noop, remove: noop}}),
  body: {appendChild: noop}};
globalThis.addEventListener = noop;
%(js)s
window.GL.use(%(terms)s);
const out = {};
for (const [qid, text] of Object.entries(%(texts)s)) out[qid] = window.GL.find(text, 99);
process.stdout.write(JSON.stringify(out));
"""


def every_question_text():
    """Every question on every map, locked rows included.

    out/<dom>/track.json is the full local payload. It is not published and
    not in git, so this skips where the build has not been run.
    """
    got = {}
    for dom in domains.discover():
        p = out_dir(dom) / "track.json"
        if not p.exists():
            continue
        for r in json.loads(p.read_text(encoding="utf-8")).get("forecasts") or []:
            text = " ".join(str(r.get(f) or "") for f in FIELDS)
            if text.strip():
                got[f"{dom}/{r.get('qid')}"] = text
    return got


def test_the_python_and_javascript_matchers_agree_on_every_question(tmp_path):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    texts = every_question_text()
    if not texts:
        pytest.skip("no built payload; run python -m chains.track first")
    ts = terms()
    shipped = {t["id"]: {"label": t["label"], "def": t["en"],
                         "match": list(t["match"]),
                         "stop": list(t.get("stop") or [])} for t in ts}
    js = (templates_dir() / "glossary.js").read_text(encoding="utf-8")
    src = tmp_path / "gl.js"
    src.write_text(HARNESS % {"terms": json.dumps(shipped, ensure_ascii=False),
                              "js": js.replace("\r\n", "\n"),
                              "texts": json.dumps(texts, ensure_ascii=False)},
                   encoding="utf-8")
    out = subprocess.run(["node", str(src)], capture_output=True,
                         check=True).stdout.decode("utf-8")
    from_js = json.loads(out)
    disagree = {}
    for qid, text in texts.items():
        py = glossary.find(text, ts, limit=99)
        if py != from_js.get(qid):
            disagree[qid] = {"python": py, "js": from_js.get(qid)}
    assert disagree == {}, json.dumps(disagree, indent=1)[:2000]


# -- 5. the card that started this ---------------------------------------------
def test_the_micron_card_no_longer_offers_a_definition_of_a_coater():
    """mu_fq4 is answered at the 2026-09-30 US close. Until then it is one of
    the two open cards on the site, and it was the one with the bug."""
    doc = json.loads(map_path("semi").read_text(encoding="utf-8"))
    assert doc                       # the map is there; the row comes from out/
    texts = every_question_text()
    text = texts.get("semi/mu_fq4")
    if text is None:
        pytest.skip("no built payload; run python -m chains.track first")
    ids = glossary.find(text, terms(), limit=glossary.MAX_PER_CARD)
    assert "coater" not in ids, ids
    assert "hbm" in ids, "the terms a reader does need are still there"
    marked = glossary.mark(text, terms())
    assert ">track</abbr>" not in marked
    assert re.search(r'data-gl="hbm">HBM', marked)
