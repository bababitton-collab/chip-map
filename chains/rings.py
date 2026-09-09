"""The second ring: what the first ring depends on.

WHAT THIS IS
------------
A watch question registers two baskets by hand: ``win`` and ``lose``. Those are
the direct claim -- if Oracle buys more, NVIDIA wins. The second ring is the
next hop out, and it is not a second claim: it is the first claim's mechanical
consequence, read off edges that were already in the map before the question
was asked.

DIRECTION
---------
A map edge is ``{from: supplier, to: customer}``, so "A -> B" says B depends on
A. The second ring of a first-ring node is what that node DEPENDS ON: the
edges arriving at it, taken back to their suppliers. NVIDIA sells more, so
TSMC, Micron and Amkor sell more.

The other traversal -- following a node's outgoing edges to its other customers
-- is a different and weaker statement. Those are the peers competing for the
same supply, and they move for a different reason than the first ring does, or
in the opposite direction. This module does not draw them.

WHAT IS EXCLUDED, AND WHY
-------------------------
* Edges that are not ``supplies``. The map also carries ``competes``,
  ``substitutes`` and ``customer_of``. A competitor of a winner is not a
  second-order winner, and putting one in the basket would state the opposite
  of what the drawing claims.
* The reporting company. It is the subject of the question, not a consequence
  of it.
* Anything already in ``win`` or ``lose``. It is in the first ring; it is not
  also in the second.
* Anything the map cannot price. A basket leg with no price symbol cannot be
  scored, so it is not a leg.
* Anything reached from BOTH sides. A node that supplies a winner and a loser
  has no sign, and a node drawn with no sign is a guess.

Nodes only, and only the top-level ``edges`` list. ``sub_edges`` connect
subnodes, whose ``ticker`` field is prose ("private (delisted 2024)") and
several of which resolve to the same listed parent -- Cymer's ticker is ASML.
A second ring built from those would double-count a company under two names.

ORDER
-----
Three rules, in this order.

1. MULTIPLICITY. A node supplying two of the first-ring companies outranks any
   node supplying one. That is the whole reason to draw a second ring: a name
   that appears twice is exposed to the answer twice, and it is the closest
   thing the map has to a second-order signal rather than a second-order list.

2. ROUND ROBIN across the first ring, in the basket's own order. Every parent
   contributes its best before any parent contributes twice. Without this the
   node with the most mapped inputs takes the whole ring -- NVIDIA has
   seventeen suppliers in this map and AMD has two, and a straight ranking
   would draw a card about NVIDIA's supply chain and call it a card about
   Oracle's quarter.

3. Within one parent: the edge's ``share`` when it is a number, largest first;
   otherwise the order the map lists its edges in. The ``share`` field is
   usually a sentence out of a 10-K ("TSMC 19% of KLA FY2026 revenue"), and a
   sentence does not sort -- pulling "19" out of that prose would be inventing
   a ranking the map never stated. No edge in the current map carries a numeric
   share, so today rule 3 is the map's own order.

The result is a pure function of two committed files and nothing else.
"""
from __future__ import annotations

from chains import mapfile

# Eight a side. The drawing shows eight across both sides and counts the rest,
# and a basket wider than this stops being a claim about a mechanism and starts
# being a sector ETF.
MAX_PER_SIDE = 8

# The only edge type that carries the meaning "this one's volume is that one's
# revenue". See the module docstring.
SUPPLIES = "supplies"

# The label rides into live.json 39 times over, once per watch row, and that
# file has a hard ceiling. The first clause is the relationship; the rest is
# usually the evidence for it, which the map keeps in ``source``.
MAX_LABEL = 56


def _short(what: str | None) -> str:
    """The first clause of an edge's ``what``, capped."""
    s = (what or "").split(";")[0].strip()
    return s[:MAX_LABEL - 1] + "…" if len(s) > MAX_LABEL else s


def priceable(doc: dict) -> set[str]:
    """Node ids the ledger could actually score.

    The same test the ledger uses, deliberately: a second-ring node that cannot
    be priced would be drawn as a claim and then silently dropped from the
    basket that is supposed to test it.
    """
    return {n["id"] for n in doc.get("nodes", [])
            if n.get("ticker") and n.get("price_symbol")
            and n.get("price_symbol_kind") != "none"}


def numeric_share(value: object) -> float | None:
    """A share that is a number, or None because it is a sentence.

    The map's ``share`` is nearly always prose with a figure inside it. Reading
    that figure out would be a ranking this module invented, attributed to the
    map. Only a value that is already a number counts.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().rstrip("%").strip())
        except ValueError:
            return None
    return None


def suppliers_of(doc: dict, node_id: str) -> list[dict]:
    """The supply edges arriving at ``node_id``, best first (rule 3 above)."""
    edges = [(i, e) for i, e in enumerate(doc.get("edges", []))
             if e.get("type") == SUPPLIES and e.get("to") == node_id]

    def key(pair):
        i, e = pair
        sh = numeric_share(e.get("share"))
        return (0, -sh, i) if sh is not None else (1, 0.0, i)

    edges.sort(key=key)
    return [e for _, e in edges]


def _side(doc: dict, parents: list[str], blocked: set[str],
          ok: set[str]) -> list[dict]:
    """One side's candidates: {id, parents, labels}, ordered, uncapped.

    Uncapped because the both-sides rule has to see everything either side
    reached before either side is cut down -- capping first would let a node
    survive on one side only because the other side's copy fell off the end.
    """
    # Every parent's own shortlist, and the edge that justified each entry.
    shortlist: dict[str, list[str]] = {}
    label: dict[tuple[str, str], str] = {}
    for p in parents:
        picks = []
        for e in suppliers_of(doc, p):
            c = e["from"]
            if c in blocked or c not in ok:
                continue
            if (c, p) in label:          # two edges, same pair: keep the first
                continue
            label[(c, p)] = _short(e.get("what"))
            picks.append(c)
        shortlist[p] = picks

    # Rule 1's input: how many of the first ring each candidate feeds.
    parents_of: dict[str, list[str]] = {}
    for p in parents:
        for c in shortlist[p]:
            parents_of.setdefault(c, []).append(p)

    # Rule 2: one pick per parent per pass, in the basket's order.
    order: list[str] = []
    taken: set[str] = set()
    cursor = {p: 0 for p in parents}
    while True:
        moved = False
        for p in parents:
            picks = shortlist[p]
            i = cursor[p]
            while i < len(picks) and picks[i] in taken:
                i += 1
            cursor[p] = i
            if i < len(picks):
                taken.add(picks[i])
                order.append(picks[i])
                cursor[p] = i + 1
                moved = True
        if not moved:
            break

    # Rule 1 wins, and the sort is stable, so the round robin decides ties.
    order.sort(key=lambda c: -len(parents_of[c]))
    return [{"id": c, "parents": parents_of[c],
             "labels": [label[(c, p)] for p in parents_of[c]]}
            for c in order]


def second_ring(doc: dict | None, win: list[str], lose: list[str],
                reporter: str | None = None) -> dict:
    """``{win2, lose2, ring2_edges}`` for one watch row.

    Pure: the same map and the same baskets give the same answer forever, which
    is what lets a forecast registered against it be a forward test.
    """
    doc = mapfile.load() if doc is None else doc
    ok = priceable(doc)
    first = set(win) | set(lose) | ({reporter} if reporter else set())

    w = _side(doc, list(win), first, ok)
    l = _side(doc, list(lose), first, ok)

    # A node both sides reached has no sign. It leaves both.
    both = {r["id"] for r in w} & {r["id"] for r in l}
    w = [r for r in w if r["id"] not in both][:MAX_PER_SIDE]
    l = [r for r in l if r["id"] not in both][:MAX_PER_SIDE]

    # Every edge that produced a kept node, not one per node: a supplier that
    # feeds two of the first ring is one circle with two lines into it, and
    # dropping the second line would hide the reason it ranked first.
    #
    # The edge is stored the way the map states it -- supplier to customer --
    # so the drawing reads a direction that was recorded, not one derived here.
    edges = [{"from": r["id"], "to": p, "label": lab}
             for r in w + l
             for p, lab in zip(r["parents"], r["labels"])]
    return {"win2": [r["id"] for r in w], "lose2": [r["id"] for r in l],
            "ring2_edges": edges}


def for_rows(rows: list[dict], doc: dict | None = None,
             by_ticker: dict[str, str] | None = None) -> None:
    """Attach the second ring to every watch row, in place.

    ``reporter`` is the row's own company, matched through its ticker: the
    watch list names it as a ticker and the map keys on an id.
    """
    doc = mapfile.load() if doc is None else doc
    if by_ticker is None:
        by_ticker = {str(n.get("ticker", "")).upper(): n["id"]
                     for n in doc.get("nodes", []) if n.get("ticker")}
    for r in rows:
        got = second_ring(doc, r.get("win") or [], r.get("lose") or [],
                          by_ticker.get(str(r.get("tk") or "").upper()))
        r.update(got)
