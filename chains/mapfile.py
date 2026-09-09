"""Read the chain map and pull the tickers out of it.

WHAT THIS NAMESPACE IS, AND WHAT IT MUST NEVER TOUCH
-----------------------------------------------------
``chains`` is context for the chokepoint map, and it is self-contained. It
grew inside a trading repository and was an explicit non-input to that
strategy's universe; it now lives on its own, and the rule that kept the two
apart is the same rule that keeps this repository buildable anywhere: no
import of the project it came from, and no path that leaves this tree.

That is not a convention to remember. It is pinned by
``tests/test_isolation.py``, which walks every module in this package and
fails on either. Everything written lives under ``out/``.

The original reason is still worth recording, because it is why the map may
never quietly become a stock screen: a chart about chokepoints and a strategy
that trades a universe are different objects with different standards of
evidence. A hand-curated list of interesting companies used as a selection
rule is the definition of a biased universe.

THE TICKER FIELD IS PROSE
-------------------------
It is written for a person, not a parser. Real values in v2 include::

    "4063.T"
    "private"
    "state-backed"
    "2317.TW / TSM"
    "6146.T (TSE) / 佳一 sub in CN; Coorstek = private"
    "005930.KS parent)"
    "private (US Commerce Dept holds equity via $150M CHIPS award)"

So a ticker is extracted, not read: split on separators, drop parentheticals
and anything after a semicolon, then keep only what still looks like a ticker.
Anything that does not survive is reported as unparsed rather than guessed at
-- a wrong ticker silently prices the wrong company, which is worse than a gap.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from chains import exchanges
from chains.paths import map_path

# a bare ticker: letters/digits, optionally dotted with a suffix
TICKER_RE = re.compile(r"^[A-Za-z0-9]{1,8}(?:\.[A-Za-z]{1,4})?$")
# only ever applied to free text, and only the dotted form -- see candidate_tickers
DOTTED_IN_PROSE_RE = re.compile(r"\b[A-Za-z0-9]{1,8}\.[A-Za-z]{1,4}\b")

PRIVATE_MARKERS = ("private", "state-owned", "state owned", "state-backed",
                   "state backed", "state-linked", "unlisted", "delisted")

NOT_A_TICKER = {
    "private", "state-backed", "state backed", "none", "n/a", "na", "-", "",
    "consortium", "various", "multiple", "unlisted", "mixed",
    "n", "a", "tbd", "unknown", "state", "various szse",
}

# A field that OPENS with one of these is describing an absence, and anything
# ticker-shaped later in it belongs to somebody else: "n/a (NVDA Rubin CPX...)"
# yielded "n", and "private ($134M Series A/A1/A2)" yielded "A1".
ABSENCE_PREFIXES = ("private", "state", "various", "n/a", "na ", "none",
                    "unlisted", "tbd", "unknown", "multiple", "consortium")


@dataclass
class Entry:
    """One company in the map that we might be able to price."""

    kind: str                 # node | subnode | challenger
    id: str
    name: str
    raw_ticker: str
    exchange: str | None
    ticker: str | None = None         # EODHD form
    reason: str | None = None         # why there is no ticker
    chokepoint_ids: list[str] = field(default_factory=list)
    layer: str | None = None

    @property
    def fetchable_in_principle(self) -> bool:
        return self.ticker is not None


def load(path: Path | str | None = None) -> dict:
    p = Path(path) if path else map_path()
    if not p.exists():
        raise FileNotFoundError(
            f"chain map not found at {p}. Drop semi_chain_v2.json there."
        )
    return json.loads(p.read_text(encoding="utf-8"))


def candidate_tickers(raw: str | None) -> list[str]:
    """Every plausible ticker inside one prose ticker field, in order.

    Order matters: the first is the primary listing, and the coverage probe
    falls back to the later ones only when the first is unavailable.
    """
    if not raw:
        return []
    text = str(raw).strip()
    low = text.lower()
    if low in NOT_A_TICKER or low.startswith(ABSENCE_PREFIXES):
        return []
    # drop anything after a semicolon: it is commentary, not an alternative
    text = text.split(";")[0]
    # drop parenthesised asides, which are exchange names or explanations
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[()]", " ", text)
    out: list[str] = []
    for piece in re.split(r"[/,]| or ", text):
        tok = piece.strip().strip(".").strip()
        if not tok or tok.lower() in NOT_A_TICKER:
            continue
        if TICKER_RE.match(tok):
            out.append(tok)
            continue
        # A field like "601600.SS et al." is one ticker followed by prose.
        # Pull DOTTED tickers only: an undotted word is far too easy to
        # mistake for one -- "et", "al", "TPE" and "sub" all match the bare
        # ticker shape, and pricing the wrong company is worse than a gap.
        out.extend(m.group(0) for m in DOTTED_IN_PROSE_RE.finditer(tok))
    return out


def _entry(kind: str, rec: dict, raw_key: str = "ticker") -> Entry:
    raw = rec.get(raw_key)
    e = Entry(
        kind=kind,
        id=str(rec.get("id") or rec.get("name") or "?"),
        name=str(rec.get("name") or ""),
        raw_ticker=str(raw) if raw is not None else "",
        exchange=rec.get("exchange"),
        chokepoint_ids=list(rec.get("chokepoint_ids") or []),
        layer=rec.get("layer"),
    )
    cands = candidate_tickers(raw)
    if not cands:
        text = str(raw or "").strip().lower()
        if text in NOT_A_TICKER or text.startswith(PRIVATE_MARKERS):
            # The SUBNODE is private even when the field names a listed parent
            # or peer: "private (Cosmo Energy 5021.T)" is not Cosmo Energy.
            e.reason = "no ticker: private, delisted or state-owned"
        elif not text:
            e.reason = "no ticker: blank"
        else:
            e.reason = "unparsed prose -- may name a listed company, needs a person"
        return e
    for c in cands:
        tick, why = exchanges.resolve(c, e.exchange)
        if tick:
            e.ticker, e.reason = tick, None
            return e
        e.reason = why
    return e


def entries(doc: dict, include_challengers: bool = False) -> list[Entry]:
    """Every node and subnode, and optionally every challenger.

    The instruction for the coverage probe is nodes and subnodes. Challengers
    are carried separately because a challenger without a price is a missing
    overlay marker, not a missing chart line.
    """
    out = [_entry("node", n) for n in doc.get("nodes", [])]
    out += [_entry("subnode", n) for n in doc.get("subnodes", [])]
    if include_challengers:
        out += challengers(doc)
    return out


def challengers(doc: dict) -> list[Entry]:
    out: list[Entry] = []
    for cp_id, lst in (doc.get("challengers") or {}).items():
        for c in lst or []:
            rec = dict(c)
            rec["id"] = f"{cp_id}:{c.get('name', '?')[:40]}"
            rec["chokepoint_ids"] = [cp_id]
            out.append(_entry("challenger", rec, raw_key="ticker_or_private"))
    return out


def holders(doc: dict) -> dict[str, list[str]]:
    """chokepoint id -> the node ids that hold it."""
    return {c["id"]: list(c.get("node_ids") or []) for c in doc.get("chokepoints", [])}
