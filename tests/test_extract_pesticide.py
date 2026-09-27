"""PesticideExtractor on listing text modelled on real Amazon.in and Google Shopping titles (Sep 2026)."""

import pytest

from nishedh.extract.pesticide import PesticideExtractor
from nishedh.registry import pesticides as P


@pytest.fixture(scope="module")
def ex() -> PesticideExtractor:
    return PesticideExtractor(P.load())


def chems(e):
    return [(c.official_name, c.strength_pct, c.form_code) for c in e.chemicals]


def test_registered_herbicide_with_strength_and_code(ex):
    e = ex.extract({"title": "Bayer Roundup Herbicide – Glyphosate 41% SL Weed Killer - 2 ltr"})
    assert chems(e) == [("Glyphosate (IPA Salt)", 41.0, "SL")]
    assert e.is_pesticide and not e.unrecognised and not e.undisclosed


def test_salt_names_match_their_own_entry(ex):
    e = ex.extract({"title": "TRESOL 2,4-D Amine Salt 58% SL Selective Systemic Herbicide (500ml)"})
    assert chems(e) == [("2,4-D Amine salt", 58.0, "SL")]
    assert not e.unrecognised  # "Amine Salt 58% SL" is part of the matched name, not a second chemical


def test_combination_product(ex):
    e = ex.extract({"title": "Syngenta Calaris Xtra (Mesotrione 2.27% W/W + Atrazine 22.7% W/W SC) Herbicide"})
    names = {c.key for c in e.chemicals}
    assert {"mesotrione", "atrazine"} <= names


def test_strength_written_before_the_name(ex):
    e = ex.extract({"title": "Pro Crabgrass & Grassy Weed Killer - 18.92% Quinclorac"})
    assert [(c.key, c.strength_pct) for c in e.chemicals] == [("quinclorac", 18.92)]


def test_known_official_misspelling_maps_to_the_standard_name(ex):
    e = ex.extract({"title": "Chloropyriphos 20% EC insecticide"})
    assert [(c.key, c.match, c.strength_pct) for c in e.chemicals] == [("chlorpyrifos", "exact", 20.0)]
    assert not e.unrecognised


def test_unseen_misspelling_is_matched_fuzzily_and_marked(ex):
    e = ex.extract({"title": "Imidaclopride 17.8% SL insecticide"})
    assert [(c.key, c.match, c.strength_pct) for c in e.chemicals] == [("imidacloprid", "fuzzy", 17.8)]


def test_banned_synonyms_are_recognised(ex):
    for title, k in (("BHC 10% DP dust insecticide", "benzenehexachloride"), ("Gamma-HCH powder insecticide", "lindane")):
        assert {c.key for c in ex.extract({"title": title}).chemicals} == {k}, title


def test_spaced_short_name(ex):
    e = ex.extract({"title": "Crossbow Specialty Herbicide 2 4 D & Triclopyr"})
    assert "24d" in {c.key for c in e.chemicals}


def test_undisclosed_active_formula_is_the_cyclosinone_pattern(ex):
    e = ex.extract({"title": "Herbicide Plus Bamboo Killer Granules – 5% Active Formula Weed Killer"})
    assert e.is_pesticide and not e.chemicals
    assert [f.text for f in e.undisclosed] == ["5% Active Formula"]


def test_pesticide_without_any_chemical(ex):
    e = ex.extract({"title": "Weed and Root Remover 200G Ready to Use | Fast Acting Deep Penetrating Formula"})
    assert e.is_pesticide and not e.chemicals and not e.undisclosed


def test_unknown_chemical_claim(ex):
    e = ex.extract({"title": "Cyclosinone Herbicide 20% SC Weed Killer"})
    assert [f.text for f in e.unrecognised] == ["Cyclosinone 20% SC"]
    assert not e.chemicals


def test_hindi_transliteration(ex):
    assert ex.extract({"title": "kharpatwar nashak dawa 1 litre"}).is_pesticide


def test_evidence_records_the_field(ex):
    e = ex.extract({"title": "Weed Killer 1L", "specifications": "Active ingredient: Paraquat Dichloride 24% SL"})
    c = e.chemicals[0]
    assert c.evidence.field == "specifications" and c.strength_pct == 24.0


def test_ordinary_products_are_not_pesticides(ex):
    for title in ("Walkie Talkie BF-888S 16 Channels", "Garden Hose Pipe 20m", "Organic Neem Soap 100g"):
        assert not ex.extract({"title": title}).is_pesticide, title
