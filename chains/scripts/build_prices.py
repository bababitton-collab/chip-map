"""Download the price layer for every symbol the map names.

    python chains/scripts/build_prices.py

One request per symbol from 2019-01-01. Writes under <root>/chains/prices/.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chains import exchanges, mapfile, prices                 # noqa: E402
from chains.paths import api_token                            # noqa: E402
from chains.providers.eodhd import EODHDClient                  # noqa: E402


def resolve_challenger(c: dict) -> str | None:
    """A challenger's ticker, in EODHD form, or None if it has no listing.

    A challenger record has no ``exchange`` field; the venue, when it is known
    at all, sits in a parenthetical: "WAF (Xetra)". The ticker parser strips
    parentheses because they usually hold commentary, so the venue is read back
    out of the raw text here rather than lost -- Siltronic resolved to WAF.US,
    a US symbol belonging to somebody else, before this.
    """
    raw = str(c.get("ticker_or_private") or "")
    venue = c.get("exchange")
    if not venue:
        for name in exchanges.BY_EXCHANGE:
            if f"({name.lower()}" in raw.lower():
                venue = name
                break
    cands = mapfile.candidate_tickers(raw)
    for cand in cands:
        sym, _why = exchanges.resolve(cand, venue)
        if sym:
            return sym
    return None


def main() -> int:
    doc = mapfile.load()
    node_syms = prices.symbols_in_map(doc)
    chal_syms = prices.challenger_symbols(doc, resolve_challenger)
    symbols = node_syms + [s for s in chal_syms if s not in node_syms]
    print(f"map v{doc.get('version')}: {len(node_syms)} node/subnode symbols, "
          f"{len(chal_syms)} challenger symbols, {len(symbols)} distinct\n")

    with EODHDClient(api_token(), rate_per_min=900) as client:
        done = prices.fetch_all(client, symbols, start=prices.START)

    got = {k: v for k, v in done.items() if v}
    empty = [k for k, v in done.items() if not v]
    print(f"\nstored {len(got)} series, {sum(got.values()):,} rows total")
    if empty:
        print(f"no data for {len(empty)}: {', '.join(empty)}")
    thin = sorted(((v, k) for k, v in got.items()))[:12]
    print("\nthinnest series (rows since 2019-01-01):")
    for n, k in thin:
        print(f"  {k:<14} {n:>6,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
