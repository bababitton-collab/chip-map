"""The paywall, as one table.

The rule used to live in three places -- the page knew a locked row carries no
text, the brief knew which sections to skip, publish_site scanned the bytes
afterwards to catch what the other two got wrong. That last one exists because
the first two disagreed at least once.

This is the table. If the product's line moves, it moves here, and every
builder follows because none of them decides. It moved on 2026-09-13: the past
is public proof, the future is the product.
"""
from __future__ import annotations

import pytest

from chains import access

# The free field set for a domain, in full. A new surface that is not in this
# table fails ``tier`` rather than defaulting to free -- which is how a paywall
# leaks: not by a decision, but by an omission.
TABLE = [
    # (kind, ctx, expected)
    ("map", {}, "free"),
    ("edge", {}, "free"),
    ("layer", {}, "free"),
    ("pulse", {}, "free"),
    ("chokepoint", {}, "free"),
    ("calendar_row", {}, "free"),
    ("brand", {}, "free"),
    ("method", {}, "free"),
    ("forecast_closed", {}, "free"),

    # the one worked example: its text and first ring, nothing more
    ("question_text", {"nearest": True}, "free"),
    ("constellation", {"nearest": True}, "free"),

    # anything answered is public, in full
    ("question_text", {"answered": True}, "free"),
    ("constellation", {"answered": True}, "free"),
    ("mark", {"answered": True}, "free"),
    ("ring2", {"answered": True}, "free"),
    ("forecast_active", {"answered": True}, "free"),
    ("member_prices", {"answered": True}, "free"),
    ("contract", {"answered": True}, "free"),

    # and everything not yet answered is the product
    ("question_text", {}, "locked"),
    ("constellation", {}, "locked"),
    ("mark", {}, "locked"),
    ("mark", {"nearest": True}, "locked"),
    ("ring2", {}, "locked"),
    ("ring2", {"nearest": True}, "locked"),
    ("forecast_active", {}, "locked"),
    ("forecast_active", {"nearest": True}, "locked"),
    ("member_prices", {}, "locked"),
    ("member_prices", {"nearest": True}, "locked"),
    ("contract", {}, "locked"),
    ("contract", {"nearest": True}, "locked"),
]


@pytest.mark.parametrize("kind,ctx,want", TABLE)
def test_the_table(kind, ctx, want):
    assert access.tier(kind, ctx) == want


def test_the_table_covers_every_kind():
    """A kind nobody wrote a row for is a kind nobody decided about."""
    assert {k for k, _c, _w in TABLE} == set(access.KINDS)


def test_an_unknown_kind_is_an_error_not_a_guess():
    with pytest.raises(access.AccessError) as e:
        access.tier("something_new")
    assert "defaulting to free" in str(e.value)


def test_a_resolved_question_is_free_in_full():
    """A skeptic who has to pay to check the record is being asked to take it
    on trust. Every kind is free once the answer is in."""
    for kind in access.KINDS:
        for ctx in ({"answered": True}, {"answered": True, "nearest": True}):
            assert access.tier(kind, ctx) == "free", (kind, ctx)


def test_what_is_still_ahead_never_opens_early():
    """Not even for the one worked example: its mark, members, prices, second
    ring and contract bytes wait for the answer."""
    for kind in access.LOCKED_UNTIL_ANSWERED:
        for ctx in ({}, {"nearest": True}, {"answered": False}):
            assert access.tier(kind, ctx) == "locked", (kind, ctx)


def test_a_finished_forecast_is_always_free():
    """The record is the evidence, and evidence nobody can see is not
    evidence."""
    for ctx in ({}, {"nearest": True}, {"answered": True}):
        assert access.tier("forecast_closed", ctx) == "free"


def test_the_map_itself_is_free_in_every_context():
    for kind in ("map", "edge", "layer", "pulse", "chokepoint"):
        assert access.tier(kind, {"answered": False}) == "free"


def test_a_date_is_free_because_a_date_is_not_a_finding():
    assert access.tier("calendar_row") == "free"


# -- the helper the builders actually call -----------------------------------

def test_the_nearest_question_is_open():
    assert access.open_question({"id": "a"}, nearest_id="a") is True


def test_a_later_question_is_not():
    assert access.open_question({"id": "b"}, nearest_id="a") is False


def test_an_answered_question_is_open_whichever_one_it_is():
    assert access.open_question({"id": "z", "answered": True},
                                nearest_id="a") is True


# -- nothing here knows what a chip is ---------------------------------------

def test_the_rule_is_domain_neutral():
    """A second map gets the same paywall without a line of code.

    Checked on the CODE, not the prose: this package's docstrings explain the
    rule by naming the things it must not touch, and a check that flagged its
    own explanation could only be made to pass by deleting the explanation.
    ``docstring_ids`` is the same helper the engine-isolation test uses.
    """
    import ast
    import pathlib

    from tests.test_isolation import docstring_ids
    src = pathlib.Path("chains/access.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    docs = docstring_ids(tree)
    words = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docs:
                words.append(node.value)
        elif isinstance(node, ast.Name):
            words.append(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            words.append(node.name)
    body = " ".join(words).lower()
    for word in ("chip", "semi", "wafer", "nvidia", "tsmc", "asml", "foundry"):
        assert word not in body, (word, body[:300])
