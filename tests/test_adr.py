"""Name matching for depositary receipts.

Every case below is a real one from the 2026-09-08 probe. Two earlier versions
of this matcher shipped wrong answers -- the first accepted four wrong
companies, the second rejected six right ones -- so the cases that broke it are
the tests.
"""
from __future__ import annotations

import pytest

from chains import adr

# how many US names contain each token, from the vendor's own 51,111 symbols
DF = {"tokyo": 155, "japan": 486, "carrier": 36, "steel": 120, "pet": 90,
      "electronic": 300, "quartz": 20, "mitsui": 30, "sumitomo": 25,
      "mitsubishi": 40, "nippon": 60, "fine": 200, "techno": 80,
      "ohka": 1, "kogyo": 6, "ajinomoto": 2, "lasertec": 1, "advantest": 1,
      "shin": 8, "etsu": 2, "disco": 4, "agc": 5, "resonac": 0, "fujimi": 2,
      "chemicals": 90, "chemical": 140, "electric": 200, "industries": 180,
      "lifestyle": 30, "holdings": 0, "toray": 2, "ibiden": 1, "hoya": 3}


def m(company: str, vendor: str) -> adr.Match:
    return adr.score_candidate("X", company, vendor, DF)


# -- the wrong companies the first version accepted ------------------------

@pytest.mark.parametrize("company, vendor, why", [
    ("Tokyo Ohka Kogyo", "Tokyo Lifestyle Co., Ltd.",
     "a EUV photoresist maker and a retailer, sharing a city"),
    ("PET carrier film", "Carrier Alliance Holdings Inc",
     "sharing the word carrier"),
    ("Japan Electronic Materials Corp", "WisdomTree Japan SmallCap Dividend Fund",
     "a company and an ETF, sharing a country"),
    ("Resonac Holdings", "TIM Participacoes SA",
     "sharing nothing at all"),
    ("Mitsui Chemicals", "Mitsui & Co. Ltd",
     "a short vendor name that used to score 1.0 under min()"),
    ("Sumitomo Chemical", "Sumitomo Mitsui Financial Group Inc",
     "a keiretsu name is not a company name"),
])
def test_the_wrong_company_is_rejected(company, vendor, why):
    assert not m(company, vendor).confident, why


# -- the right companies the second version rejected -----------------------

@pytest.mark.parametrize("company, vendor", [
    ("Mitsui Chemicals", "Mitsui Chemicals Inc ADR"),
    ("Sumitomo Chemical", "Sumitomo Chemical Co Ltd ADR"),
    ("Mitsubishi Electric", "Mitsubishi Electric Corp ADR"),
    ("Sumitomo Electric Industries", "Sumitomo Electric Industries Ltd ADR"),
    ("Nippon Steel", "Nippon Steel Corp ADR"),
    ("Tokyo Electron", "Tokyo Electron Ltd PK"),
    ("Tokyo Ohka Kogyo", "Tokyo Ohka Kogyo Co. Ltd"),
    ("Shin-Etsu Chemical", "Shin-Etsu Chemical Co Ltd ADR"),
    ("Lasertec", "Lasertec Corporation"),
    ("Ajinomoto", "Ajinomoto Co. Inc"),
    ("DISCO Corporation", "Disco Corp ADR"),
    ("Ibiden", "Ibiden Co.Ltd"),
])
def test_the_right_company_is_accepted(company, vendor):
    assert m(company, vendor).confident, f"{company} vs {vendor}"


# -- why each guard is needed ---------------------------------------------

def test_an_industry_word_is_not_stripped():
    """'chemical' is the whole difference between Mitsui Chemicals and Mitsui &
    Co. An earlier stoplist removed it and made the two identical."""
    assert "chemicals" in adr.normalise("Mitsui Chemicals")
    assert "electric" in adr.normalise("Mitsubishi Electric")


def test_corporate_form_IS_stripped():
    assert adr.normalise("Disco Corp ADR") == ["disco"]
    assert adr.normalise("Tokyo Electron Ltd PK") == ["tokyo", "electron"]


def test_the_denominator_is_max_not_min():
    """min() let any short vendor name score a perfect match against a long
    company name. max() asks how much of BOTH names is accounted for."""
    long_vs_short = m("Mitsui Chemicals", "Mitsui & Co. Ltd")
    assert long_vs_short.score == pytest.approx(0.5)


def test_a_single_common_token_is_not_identity():
    """Two long names can share one word and be unrelated. The word has to be
    rare enough to name a company by itself."""
    out = m("Tokyo Ohka Kogyo", "Tokyo Lifestyle Co., Ltd.")
    assert out.shared == ["tokyo"]
    assert out.rare_shared == []


def test_a_single_RARE_token_is_identity():
    out = m("Ajinomoto", "Ajinomoto Co. Inc")
    assert out.rare_shared == ["ajinomoto"] and out.confident


def test_two_shared_tokens_stand_without_rarity():
    """Neither 'nippon' nor 'steel' is rare, but both together are the name."""
    out = m("Nippon Steel", "Nippon Steel Corp ADR")
    assert len(out.shared) == 2 and out.confident


def test_a_rename_scores_zero_and_must_not_be_auto_accepted():
    """ASMPT was ASM Pacific Technology; Resonac was Showa Denko. A rename is
    indistinguishable from a wrong ticker by name alone, which is exactly why
    those are reported for a person instead of assigned."""
    assert not m("ASMPT", "Asm Pacific Technology Ltd ADR").confident
    assert not m("Resonac Holdings", "Showa Denko KK").confident


def test_token_frequency_counts_names_not_occurrences():
    idx = [("A", "Tokyo Electron"), ("B", "Tokyo Gas"), ("C", "Tokyo Tokyo Inc")]
    df = adr.token_frequency(idx)
    assert df["tokyo"] == 3, "three names, even though C repeats the word"
    assert df["electron"] == 1
