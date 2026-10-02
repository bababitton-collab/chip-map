"""data/domains/public.json: only the public fields, and the /domains/ page built from it.

The file is written in the private research repo (watchlist/export_public.py).
Internal working fields must never reach the public repo: not as a key, and not
as a quoted name anywhere in the text.
"""
from __future__ import annotations

import json
from pathlib import Path

from chains import domains_page
from chains.paths import data_root

PUBLIC = data_root() / "domains" / "public.json"
NEVER = ("candidate_tier", "tier_a_owners", "note", "risks", "context", "price_flag", "kill")
FIELDS = {"id", "level", "name", "limits_edge", "links_to", "owners", "hurt", "status_public", "next_check",
          "bottleneck_ids"}
STATUSES = {None, "Constrained · not yet priced", "Constrained · priced", "Gated by development", "Easing"}


def keys(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from keys(v)
    elif isinstance(o, list):
        for v in o:
            yield from keys(v)


def test_no_internal_field_name_appears_anywhere_in_public_json():
    text = PUBLIC.read_text(encoding="utf-8")
    doc = json.loads(text)
    leaked = set(keys(doc)) & set(NEVER)
    assert not leaked, leaked
    for name in NEVER:
        assert f'"{name}"' not in text, name


def test_every_domain_carries_exactly_the_public_fields_and_a_public_status():
    doc = json.loads(PUBLIC.read_text(encoding="utf-8"))
    assert doc["domains"]
    for d in doc["domains"]:
        assert set(d) == FIELDS, d["id"]
        assert d["status_public"] in STATUSES, d["id"]
        assert d["level"] in {k for k, _ in domains_page.LEVELS}
        nc = d["next_check"]
        assert nc is None or (len(nc["date"]) == 10 and nc["event"]), d["id"]


def test_the_excluded_statuses_are_not_exported():
    ids = {d["id"] for d in json.loads(PUBLIC.read_text(encoding="utf-8"))["domains"]}
    assert not ids & {"smr", "titanium_sponge", "copper", "goes"}


def test_the_page_renders_bands_in_order_and_says_it_is_not_a_forecast(tmp_path: Path):
    page = domains_page.render(tmp_path, data_root(), ["semi", "energy"])
    order = [page.index(f'data-level="{k}"') for k, _ in domains_page.LEVELS]
    assert order == sorted(order)
    assert domains_page.FOOTER in page
    assert 'href="/domains/"' in page and 'aria-current="page"' in page
