"""Map the chain map's exchange labels and ticker suffixes onto EODHD codes.

EVERY CODE HERE WAS READ OFF THE SUBSCRIPTION, NOT REMEMBERED
-------------------------------------------------------------
The obvious suffixes -- ``.T`` for Tokyo, ``.KS`` for Korea, ``.HK`` for Hong
Kong -- are Yahoo Finance's, not EODHD's, and several do not exist here at all.
The codes below come from ``GET /api/exchanges-list/`` on 2026-09-08, which
returned 70 exchanges.

The important part of that list is what is NOT in it:

    no Japan (Tokyo)      no Hong Kong      no Singapore
    no Italy (Milan)      no India

Those are not typos to be worked around with a different suffix. The
subscription does not carry the exchange, so a symbol listed only there has no
price on this plan. :data:`UNAVAILABLE` records them by name so the coverage
report can say *why* a ticker failed rather than only that it did.

Korea is the one where the Yahoo habit actively misleads: KRX is ``KO`` here,
not ``KS``.
"""
from __future__ import annotations

# EODHD codes confirmed present, 2026-09-08
US = "US"

# exchange label as written in the chain map -> EODHD code
BY_EXCHANGE: dict[str, str] = {
    "NASDAQ": US,
    "NYSE": US,
    "KRX": "KO",
    "KOSDAQ": "KQ",
    "TWSE": "TW",
    "TPEx": "TWO",
    "Taipei Exchange": "TWO",
    "SZSE": "SHE",
    "SSE": "SHG",
    "XETRA": "XETRA",
    "Xetra (Frankfurt)": "XETRA",
    "Euronext Amsterdam": "AS",
    "Euronext Paris": "PA",
    "Euronext Brussels": "BR",
    "Vienna Stock Exchange": "VI",
    "SIX": "SW",
    "TSX": "TO",
    "LSE": "LSE",
}

# the ticker's own suffix, in the Yahoo style the map was written in
BY_SUFFIX: dict[str, str] = {
    "KS": "KO",       # Korea Stock Exchange -- NOT "KS" at EODHD
    "KQ": "KQ",
    "TW": "TW",
    "TWO": "TWO",
    "SZ": "SHE",
    "SS": "SHG",
    "DE": "XETRA",
    "AS": "AS",
    "PA": "PA",
    "BR": "BR",
    "VI": "VI",
    "SW": "SW",
    "TO": "TO",
    "L": "LSE",
}

# exchanges the subscription does not carry at all, with the reason spelled out
UNAVAILABLE: dict[str, str] = {
    "T": "Tokyo Stock Exchange -- not in the EODHD exchange list on this plan",
    "TSE": "Tokyo Stock Exchange -- not in the EODHD exchange list on this plan",
    "HK": "Hong Kong Exchange -- not in the EODHD exchange list on this plan",
    "HKEX": "Hong Kong Exchange -- not in the EODHD exchange list on this plan",
    "SI": "Singapore Exchange -- not in the EODHD exchange list on this plan",
    "SGX": "Singapore Exchange -- not in the EODHD exchange list on this plan",
    "MI": "Borsa Italiana (Milan) -- not in the EODHD exchange list on this plan",
    "Euronext Milan": "Borsa Italiana (Milan) -- not in the EODHD exchange list",
    "NS": "India (NSE) -- not in the EODHD exchange list on this plan",
    "BO": "India (BSE) -- not in the EODHD exchange list on this plan",
}


def resolve(symbol: str, exchange: str | None) -> tuple[str | None, str | None]:
    """Return (EODHD ticker, reason it cannot be built).

    The ticker's own suffix wins over the exchange label: the map's ``exchange``
    field is prose in places ("TSE / TSE / TSE / KOSDAQ") while the suffix is
    machine-written.
    """
    if not symbol:
        return None, "no ticker"
    base, _, suffix = symbol.rpartition(".")
    if not base:                       # no dot at all -> a US listing
        base, suffix = symbol, ""

    if suffix:
        if suffix in UNAVAILABLE:
            return None, UNAVAILABLE[suffix]
        code = BY_SUFFIX.get(suffix)
        if code:
            return f"{base}.{code}", None
        return None, f"unknown ticker suffix .{suffix}"

    label = (exchange or "").strip()
    if label in UNAVAILABLE:
        return None, UNAVAILABLE[label]
    code = BY_EXCHANGE.get(label)
    if code:
        return f"{base}.{code}", None

    # The label is often prose: "TWSE / NYSE", "NYSE (ADR) / TWSE 2330".
    # Take the first exchange named in it rather than falling through.
    for name, mapped in sorted(BY_EXCHANGE.items(), key=lambda kv: -len(kv[0])):
        if name.lower() not in label.lower():
            continue
        # "2330 / TSM" on "TWSE / NYSE" is two listings of one company, paired
        # positionally. A NUMERIC ticker is never the US one, so skip a US
        # venue for it and keep reading the label.
        if mapped == US and base.isdigit():
            continue
        return f"{base}.{mapped}", None
    for name, why in UNAVAILABLE.items():
        if len(name) > 2 and name.lower() in label.lower():
            return None, why

    # A BARE NUMERIC ticker is never a US listing -- US symbols are alphabetic.
    # "2330" with an unreadable label is Taiwan, not a NASDAQ company, and
    # guessing .US here silently prices whatever happens to own that symbol.
    if base.isdigit():
        return None, (f"numeric ticker {base} with an unrecognised exchange "
                      f"label {label!r} -- needs a person, not a default")
    return f"{base}.{US}", None
