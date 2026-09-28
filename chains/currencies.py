"""What a venue quotes in. One table, read by everything that needs it.

    from chains import currencies
    currencies.of("RR.LSE")      -> "GBX"
    currencies.of("FOO.ZZZ")     -> "UNKNOWN"

WHY THIS MODULE EXISTS
----------------------
There were two of these tables. chains/prices.py kept one to label a stored
series and chains/liquidity.py kept another to convert traded value into
dollars, and they drifted, which is the only thing two copies of a fact ever
do. By the time anyone looked they disagreed about London -- prices said GBP,
liquidity said GBX -- and London quotes in pence, so the map published
Rolls-Royce at "GBP 1485.20" for a share worth about fourteen pounds eighty.
Neither table was checked against the other because nothing could check them.

They also disagreed by omission. liquidity had Hong Kong and prices did not,
so two stored series carried the label "UNKNOWN"; before that, NEITHER had it
and 2269.HK's traded value read 7.8x high for as long as nobody looked.

So: one table, one function, and a test that walks every price line on every
map and fails if the answer is UNKNOWN or if the two callers could ever
disagree again. The bug class is not "we got London wrong". It is "the same
fact was written down twice".

UNKNOWN IS THE ANSWER, NOT A DEFAULT
------------------------------------
A suffix that is not here returns "UNKNOWN" and never "USD". Guessing dollars
is how a line in another currency gets measured as though it were already
converted: it reads richer than it is, by exactly the exchange rate, and
nothing raises. prices.py already took this line; liquidity.py did not, and
that is the bug it shipped. Now there is only one answer to give.

A caller that cannot proceed on UNKNOWN should say so loudly. The liquidity
gate does: it looks for an UNKNOWN->USD rate, finds none, and refuses the leg
rather than passing it at par.

PENCE
-----
London prices in pence, not pounds, and the code for that is GBX. It is not a
display preference: a number labelled GBP that is really pence is wrong by a
factor of a hundred. Anything converting from GBX divides by a hundred after
finding the GBP rate -- see chains.liquidity.Measure.fx.
"""
from __future__ import annotations

# Exchange suffix -> the currency that venue quotes in. The suffix is this
# repository's own spelling (see chains/exchanges.py); the provider layer
# translates it for whichever vendor is current.
#
# Add a venue here in the same commit that adds a node using it. A symbol can
# be fetched, stored and drawn without an entry, and the only sign is a label
# nobody reads.
BY_SUFFIX: dict[str, str] = {
    "US": "USD",
    # Europe
    "XETRA": "EUR", "F": "EUR", "AS": "EUR", "PA": "EUR", "BR": "EUR",
    "VI": "EUR", "MC": "EUR", "LS": "EUR", "HE": "EUR", "IR": "EUR",
    "SW": "CHF",
    "LSE": "GBX",          # pence, not pounds
    "CO": "DKK", "ST": "SEK", "OL": "NOK",
    # Asia
    "TW": "TWD", "TWO": "TWD",
    "KO": "KRW", "KQ": "KRW",
    "SHG": "CNY", "SHE": "CNY",
    "HK": "HKD",
    "T": "JPY",            # Tokyo
    "NS": "INR",           # India, NSE
    # Americas and Pacific
    "TO": "CAD", "AU": "AUD",
}

UNKNOWN = "UNKNOWN"


def of(symbol: str) -> str:
    """The currency a symbol trades in, from its exchange suffix.

    A symbol with no suffix at all is UNKNOWN too. A bare ticker is a US
    ticker in the vendor's spelling, not in this repository's -- everything
    stored here carries its venue -- so treating it as USD would be reading a
    convention this side does not use.
    """
    _, _, suffix = symbol.rpartition(".")
    return BY_SUFFIX.get(suffix.upper(), UNKNOWN)


def known(suffix: str) -> bool:
    return suffix.upper() in BY_SUFFIX


__all__ = ["BY_SUFFIX", "UNKNOWN", "known", "of"]
