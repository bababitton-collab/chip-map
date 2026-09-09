"""Find a US-listed line for a company whose home exchange we cannot price.

WHY THIS EXISTS
---------------
EODHD's coverage is 70 exchanges and Japan is not among them, on any tier. That
is the provider's full coverage, not a subscription tier to buy. 40 of the
chain map's entries are Tokyo-listed, and between them they hold five of the
fourteen chokepoints -- silicon wafers, EUV photoresist, ABF film, mask blanks
and ATE. Losing them loses the part of the map that makes it interesting.

Most large Japanese industrials have a US depositary receipt, usually an
unsponsored OTC line. Those ARE on the US exchange list, so they cost nothing
extra. They are a worse price series than the home line -- thinner, wider
spreads, a stale print when Tokyo is shut and New York is open -- and for a
chart rebased to 100 that is acceptable, as long as it is labelled.

THE FAILURE MODE THAT MATTERS
-----------------------------
An OTC ticker that resolves to the WRONG company is worse than a missing one: a
missing series shows as a gap and gets fixed, while a wrong series shows as a
line and gets believed. So a candidate is accepted only if EODHD's own name for
the symbol matches the company in the map. Where the name does not match, the
candidate is REPORTED for a person rather than assigned -- and several will not
match for good reasons, because companies rename. AGC was Asahi Glass; Resonac
was Showa Denko. A rename looks exactly like a wrong ticker to a string
comparison, which is why the decision is not automated.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Lines to try first, supplied with the instruction. Each is still verified by
# name against what EODHD returns -- being on this list is a hint, not a fact.
KNOWN_LINES: dict[str, str] = {
    "shinetsu": "SHECY",
    "sumco": "SUOPY",
    "ajinomoto": "AJINY",
    "ajinomoto_ref": "AJINY",
    "ajinomoto_plants": "AJINY",
    "advantest": "ATEYY",
    "advantest_hbm_ref": "ATEYY",
    "hoya": "HOCPY",
    "tel": "TOELY",
    "tel_tsv": "TOELY",
    "disco": "DSCSY",
    "lasertec": "LSRCY",
    "ibiden": "IBIDF",
    "ibiden_cp8": "IBIDF",
    "fujifilm_resist": "FUJIY",
    "sumitomo_chem_resist": "SOMMY",
    "mitsui_pellicle": "MITUY",
    "nippon_steel_goes": "NPSCY",
    "mitsubishi_eml": "MIELY",
    "sumitomo_inp_sub": "SMTOY",
    "agc_blanks": "ASGLY",
    "ebara_plating_cmp": "EBCOY",
    "hitachi_bushings": "HTHIY",
    "asmpt": "ASMVY",
}

# ONLY corporate form. Not industry words: "chemical" is what distinguishes
# Mitsui Chemicals from Mitsui & Co, and stripping it made the two identical.
STOPWORDS = {
    "co", "ltd", "limited", "inc", "incorporated", "corp", "corporation",
    "company", "holdings", "holding", "group", "adr", "adrs", "ads", "drc",
    "unsponsored", "sponsored", "the", "kabushiki", "kaisha", "kk", "sa",
    "nv", "ag", "plc", "spa", "se", "and", "of", "new", "class", "gmbh",
    "pk", "reg", "shs", "spons", "unsp", "cl",
}

def normalise(name: str) -> list[str]:
    """Lowercase identity tokens, with the boilerplate removed."""
    txt = re.sub(r"\(.*?\)", " ", str(name or "")).lower()
    txt = txt.replace("-", " ").replace(".", " ").replace(",", " ")
    txt = re.sub(r"[^a-z0-9 ]", " ", txt)
    return [t for t in txt.split() if t and t not in STOPWORDS and len(t) > 1]


@dataclass
class Match:
    symbol: str
    vendor_name: str
    score: float
    shared: list[str]
    rare_shared: list[str] | None = None

    @property
    def confident(self) -> bool:
        """Most of BOTH names accounted for, and the overlap must identify.

        Two independent guards, because each catches what the other misses:

        the ratio (over max, not min) stops a short vendor name matching a long
        company name on one word -- "Mitsui Chemicals" against "Mitsui & Co";

        the rarity requirement stops two long names matching on a common word --
        "Tokyo Ohka Kogyo" against "Tokyo Lifestyle". A single shared token is
        only enough when that token is rare enough to name a company on its own
        ("ajinomoto", "lasertec"); two or more shared tokens stand by themselves.
        """
        if self.score < MIN_NAME_OVERLAP:
            return False
        return len(self.shared) >= 2 or bool(self.rare_shared)


MIN_NAME_OVERLAP = 0.6

# a token in more names than this identifies an industry or a country, not a
# company: "tokyo" (155), "japan" (486), "carrier" (36), "steel" (120)
RARE_TOKEN_MAX_DOCS = 12


def token_frequency(index: list[tuple[str, str]]) -> dict[str, int]:
    """How many distinct company names each token appears in."""
    df: dict[str, int] = {}
    for _code, name in index:
        for t in set(normalise(name)):
            df[t] = df.get(t, 0) + 1
    return df


def compare(map_name: str, vendor_name: str,
            df: dict[str, int] | None = None) -> Match:
    a, b = normalise(map_name), normalise(vendor_name)
    shared = [t for t in a if t in b]
    denom = max(len(a), len(b)) or 1
    rare = None
    if df is not None:
        rare = [t for t in shared if df.get(t, 0) <= RARE_TOKEN_MAX_DOCS]
    return Match("", vendor_name, len(shared) / denom, shared, rare)


def score_candidate(symbol: str, map_name: str, vendor_name: str,
                    df: dict[str, int] | None = None) -> Match:
    m = compare(map_name, vendor_name, df)
    m.symbol = symbol
    return m


def search_us_list(map_name: str, index: list[tuple[str, str]],
                   df: dict[str, int] | None = None,
                   limit: int = 5) -> list[Match]:
    """Best name matches for a company in EODHD's US symbol list.

    ``index`` is (code, name) for every US symbol. Returns the strongest
    matches, scored, for a person to confirm -- never auto-applied on its own.
    Ranked by rare-token overlap first, because that is what identifies.
    """
    want = normalise(map_name)
    if not want:
        return []
    out: list[Match] = []
    for code, name in index:
        b = normalise(name)
        if not b:
            continue
        shared = [t for t in want if t in b]
        if not shared:
            continue
        rare = ([t for t in shared if df.get(t, 0) <= RARE_TOKEN_MAX_DOCS]
                if df is not None else None)
        out.append(Match(code, name, len(shared) / (max(len(want), len(b)) or 1),
                         shared, rare))
    out.sort(key=lambda m: (-len(m.rare_shared or []), -m.score, len(m.symbol)))
    return out[:limit]
