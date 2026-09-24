"""Map the chain map's exchange labels and ticker suffixes onto the codes
this repository stores symbols under.

Those codes are EODHD's, inherited: they are what every map, every parquet
filename and every committed liquidity record already spells symbols with, so
they stayed when the vendor went. chains/providers/yahoo.py translates them on
the way out to whatever the current price source calls the same venue. The
table below is therefore the repository's own spelling, not a vendor's.

EVERY CODE HERE WAS READ OFF THE SUBSCRIPTION, NOT REMEMBERED
-------------------------------------------------------------
The obvious suffixes -- ``.T`` for Tokyo, ``.KS`` for Korea, ``.HK`` for Hong
Kong -- are Yahoo Finance's, not these, and several did not exist on the plan
that set them.
The codes below come from ``GET /api/exchanges-list/`` on 2026-09-08, which
returned 70 exchanges.

The important part of that list is what is NOT in it:

    no Japan (Tokyo)      no Singapore
    no Italy (Milan)      no India

Those are not typos to be worked around with a different suffix. The
subscription does not carry the exchange, so a symbol listed only there has no
price on this plan. :data:`UNAVAILABLE` records them by name so the coverage
report can say *why* a ticker failed rather than only that it did.

Korea is the one where the Yahoo habit actively misleads: KRX is ``KO`` here,
not ``KS``.

HONG KONG, ADDED 2026-09-23
---------------------------
Hong Kong was on the list above until it was probed directly and found to
serve: ``2269.HK``, ``0700.HK`` and ``9988.HK`` all return daily bars, and
``USDHKD.FOREX`` returns the peg. The plan changed under the list rather than
the list being wrong when it was written -- ``/api/exchanges-list/`` now
answers 404 on this subscription, so the 2026-09-08 enumeration above can no
longer be re-run and only what has been probed by hand is changed here.

Listing the exchange is half the fix. A venue quotes in its own currency, and
:data:`chains.liquidity.CURRENCY_BY_EXCHANGE` is what converts it; while HK
was absent there, its closes were silently read as dollars and 2269.HK's
traded value came out 7.8x too high. The two tables are added to together.
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
    "HKEX": "HK",
    "SEHK": "HK",
    "Hong Kong Exchange": "HK",
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
    "HK": "HK",
    "TO": "TO",
    "L": "LSE",
}

# exchanges the subscription does not carry at all, with the reason spelled out
UNAVAILABLE: dict[str, str] = {
    "T": "Tokyo Stock Exchange -- not in the EODHD exchange list on this plan",
    "TSE": "Tokyo Stock Exchange -- not in the EODHD exchange list on this plan",
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
