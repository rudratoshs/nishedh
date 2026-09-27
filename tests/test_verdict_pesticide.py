"""PesticideRules: one reason code per case, on listing text modelled on real Sep 2026 listings."""

import pytest

from nishedh.extract.pesticide import PesticideExtractor
from nishedh.registry import pesticides as P
from nishedh.verdict.base import Reason, Verdict
from nishedh.verdict.pesticide import PesticideRules


@pytest.fixture(scope="module")
def judge():
    reg = P.load()
    ex, rules = PesticideExtractor(reg), PesticideRules(reg)
    return lambda **fields: rules.assess(ex.extract(fields))


def test_not_a_pesticide(judge):
    assert judge(title="BAOFENG BF-888S Walkie Talkie 16 Channels") is None


@pytest.mark.parametrize("title", [
    "Bayer Roundup Herbicide – Glyphosate 41% SL Weed Killer - 2 ltr",
    "Sumitomo Excel Mera 71 Glyphosate 71% SG Herbicide – 100 gm",          # ammonium-salt form
    "TRESOL 2,4-D Amine Salt 58% SL Selective Systemic Herbicide (500ml)",  # name starting with digits
    "Sweep Power Herbicide – Glufosinate 13.5% SL - 500 ml",                # registered as Glufosinate Ammonium
    "Syngenta Calaris Xtra (Mesotrione 2.27% W/W + Atrazine 22.7% W/W SC) Herbicide",  # combination
    "Thiamethoxam 25% WG insecticide",                                       # registered list spells it Thiomethoxam
])
def test_registered_products_are_clear(judge, title):
    f = judge(title=title)
    assert f.reason is Reason.CLEAR and f.verdict is Verdict.REGISTERED, (title, f.checks[0].explanation)


def test_banned_chemical(judge):
    f = judge(title="Phorate 10% CG insecticide granules")
    assert (f.verdict, f.reason, f.confidence) == (Verdict.BANNED, Reason.BANNED_ITEM, "high")
    assert f.checks[0].source == "banned_refused_restricted" and "S.O. 3951" in f.checks[0].explanation


def test_banned_synonym(judge):
    assert judge(title="Gamma-HCH powder insecticide").reason is Reason.BANNED_ITEM


def test_partial_ban_is_medium_confidence(judge):
    f = judge(title="Sodium Cyanide pesticide powder")
    assert f.reason is Reason.BANNED_ITEM and f.confidence == "medium"


def test_refused_chemical(judge):
    f = judge(title="Disulfoton 5% GR insecticide")
    assert f.reason is Reason.NOT_IN_REGISTRY and "refused registration" in f.checks[0].explanation


def test_undisclosed_active_formula_is_high_confidence_missing_information(judge):
    f = judge(title="Herbicide Plus Bamboo Killer Granules – 5% Active Formula Weed Killer")
    assert (f.verdict, f.reason, f.confidence) == (Verdict.UNREGISTERED_OR_HIDDEN, Reason.INFORMATION_MISSING, "high")
    assert "Rule 19" in f.checks[0].explanation


def test_no_chemical_named(judge):
    f = judge(title="Weed and Root Remover 200G Ready to Use | Fast Acting Deep Penetrating Formula")
    assert (f.reason, f.confidence) == (Reason.INFORMATION_MISSING, "medium")


def test_unknown_name_with_strength_is_missing_information_not_an_accusation(judge):
    # The Cyclosinone case: a name on no list may be a brand or an unregistered chemical.
    f = judge(title="Cyclosinone Herbicide 20% SC")
    assert f.reason is Reason.INFORMATION_MISSING and "brand name or an unregistered chemical" in f.checks[0].explanation


def test_brand_next_to_a_named_chemical_is_ignored(judge):
    f = judge(title="Roundup 41% SL herbicide with Glyphosate 41% SL")
    assert f.reason is Reason.CLEAR


def test_widely_sold_brand_alone_is_matched_to_its_chemical(judge):
    # A registered glyphosate brand sold without the chemical named must not be flagged.
    f = judge(title="Roundup 41% SL Herbicide 1 Litre")
    assert f.reason is Reason.CLEAR and "Glyphosate" in f.checks[0].explanation


@pytest.mark.parametrize("title", ["Bayer Jump, Fipronil 80 WG (80% w/w)", "Carbofuran 3G granules",
                                   "Chlorpyrifos 20 EC 1 litre"])
def test_strength_without_percent_sign_is_read(judge, title):
    f = judge(title=title)
    assert f.reason is not Reason.REGISTRY_MISMATCH and "states no strength" not in f.checks[0].explanation, title


def test_grams_are_not_a_strength(judge):
    f = judge(title="Thimet 500 G")
    assert "500" not in f.checks[0].explanation


def test_unregistered_strength_is_only_a_low_confidence_mismatch(judge):
    f = judge(title="Glyphosate 99% SL herbicide")
    assert (f.reason, f.confidence) == (Reason.REGISTRY_MISMATCH, "low")


def test_restricted_use_is_a_note_not_a_flag(judge):
    f = judge(title="Chlorpyrifos 20% EC insecticide")
    assert f.reason is Reason.CLEAR and any("restricted" in n for n in f.notes)


def test_most_serious_reason_wins(judge):
    f = judge(title="Combo pack: Glyphosate 41% SL and Phorate 10% CG")
    assert f.reason is Reason.BANNED_ITEM and len(f.checks) == 2


def test_every_check_cites_its_evidence(judge):
    f = judge(title="Weed killer 1L", specifications="Active ingredient: Paraquat Dichloride 24% SL")
    assert f.reason is Reason.CLEAR
    assert f.checks[0].evidence[0].field == "specifications"


def test_first_check_explains_the_finding(judge):
    f = judge(title="Southern Ag Crossbow Specialty Herbicide 2 4 D & Triclopyr Weed & Brush Killer")
    assert f.checks[0].reason is f.reason and "Triclopyr" in f.checks[0].explanation


# ---- Regression tests from the second independent review (27 Sep 2026) -----------------------

@pytest.mark.parametrize("title", [
    "Copper Water Bottle 1 Litre", "Sodium Bicarbonate Baking Soda", "Hydrogen Peroxide 3% Solution",
    "Aluminium Ladder 6 ft", "Methyl Salicylate Pain Relief Oil", "Cotton Tunic for women",
    "Machete Knife 18 inch Steel", "Arsenal FC Jersey 2026", "Listerine Mouthwash with Thymol",
    "Citral lemongrass oil 100ml", "Weed Remover Tool Hand Weeder", "Herbicide Sprayer Nozzle Set",
    "Insecticide Treated Mosquito Net", "Weed Management by Dr. Surinder Singh Rana",
    "Garden Pressure Sprayer 5L for pest control",
])
def test_must_not_flag_ordinary_products(judge, title):
    assert judge(title=title) is None, title


@pytest.mark.parametrize("title,key", [
    ("DDVP 76% EC insecticide", "dichlorvos"),
    ("Tedion 8% EC acaricide", "tetradifon"),
    ("Ekatir 25 EC insecticide", "thiometon"),
    ("Nuvan 100 ml insecticide", "dichlorvos"),        # trade name
    ("Thimet 10G insecticide", "phorate"),             # trade name
    ("Endosalfan 35% EC pesticide", "endosulfan"),     # misspelt banned chemical
])
def test_banned_by_abbreviation_trade_name_or_typo(judge, title, key):
    f = judge(title=title)
    assert f.reason is Reason.BANNED_ITEM, (title, f.checks[0].explanation)


@pytest.mark.parametrize("title", ["Glyphosate41% SL herbicide", "Imidacloprid17.8% SL insecticide", "Glyphosate 41%, herbicide"])
def test_glued_or_punctuated_strength(judge, title):
    f = judge(title=title)
    assert f.reason is Reason.CLEAR and f.confidence == "high", (title, f.checks[0].explanation)


def test_unknown_chemical_next_to_a_registered_one_is_not_hidden(judge):
    f = judge(title="Combo: Glyphosate 41% SL and Cyclosinone 20% SC weedicide")
    assert f.reason is Reason.INFORMATION_MISSING and "Cyclosinone" in f.checks[0].explanation


def test_salt_family_does_not_merge_different_chemicals(judge):
    f = judge(title="Sulfuryl fluoride fumigant 99% insecticide")
    assert "Sulphur" not in f.checks[0].explanation and "Sulfur " not in f.checks[0].explanation


def test_methyl_ester_is_its_own_chemical(judge):
    f = judge(title="Chlorpyrifos methyl 20% EC insecticide")
    assert f.checks[0].evidence[0].text.lower().startswith("chlorpyrifos methyl")


def test_combination_confidence_follows_the_match(judge):
    f = judge(title="Syngenta Calaris Xtra (Mesotrione 2.27% W/W + Atrazine 22.7% W/W SC) Herbicide")
    assert (f.reason, f.confidence) == (Reason.CLEAR, "high")


def test_registered_formulation_without_a_code_matches(judge):
    f = judge(title="TRESOL 2,4-D Sodium Salt 80% WP Selective Post Emergence Herbicide")
    assert f.reason is Reason.CLEAR


def test_active_ingredient_phrase_without_strength_is_medium(judge):
    f = judge(title="Root Stop Herbicid Granular Weed With Active Ingredient Low Toxicity")
    assert (f.reason, f.confidence) == (Reason.INFORMATION_MISSING, "medium")
    assert "never names it" in f.checks[0].explanation


def test_bare_family_name_says_which_forms_are_registered(judge):
    f = judge(title="Crossbow Specialty Herbicide 2 4 D weed killer")
    assert "registered as" in f.checks[0].explanation


def test_generic_schedule_bracket_words_are_not_trade_names(judge):
    # Schedule entry "Serratia marcescens GPS 5 (Bacteria)" must not turn "Bacterial" into a chemical.
    f = judge(title="Go Garden Trichoderma Bio Fungicide for plants - Prevents Fungal and Bacterial Diseases")
    assert all("Serratia" not in c.explanation for c in f.checks)


# ---- Combination formulations must match chemicals, strengths and code (external review, 27 Sep 2026) ----

def test_registered_combination_is_clear(judge):
    f = judge(title="Acephate 25% + Fenvalerate 3% EC insecticide")
    assert (f.reason, f.confidence) == (Reason.CLEAR, "high") and len(f.checks) == 1


@pytest.mark.parametrize("title", [
    "Acephate 1% + Fenvalerate 1% EC insecticide",       # wrong strengths
    "Acephate 99% + Fenvalerate 99% EC insecticide",     # impossible strengths
    "Acephate 25% + Fenvalerate 3% WP insecticide",      # right strengths, wrong formulation code
])
def test_same_chemicals_at_other_strengths_or_code_are_a_mismatch(judge, title):
    f = judge(title=title)
    assert f.reason is Reason.REGISTRY_MISMATCH and "registered together only as" in f.checks[0].explanation, title


def test_combination_without_strengths_is_clear_but_says_so(judge):
    f = judge(title="Acephate + Fenvalerate insecticide")
    assert (f.reason, f.confidence) == (Reason.CLEAR, "medium") and "could be compared" in f.checks[0].explanation


def test_combination_with_a_banned_chemical_stays_banned(judge):
    f = judge(title="Combo pack: Glyphosate 41% SL and Phorate 10% CG")
    assert f.reason is Reason.BANNED_ITEM


def test_grams_per_litre_combination(judge):
    assert judge(title="Azoxystrobin 120 g/l + Tebuconazole 240 g/l SC fungicide").reason is Reason.CLEAR


def test_registry_typo_in_a_strength_is_never_guessed(judge):
    # The PDF prints "Triafamone 20%+ Ethoxysulfuron l0%WG" (a letter for a digit): Bayer's Council Active.
    f = judge(title="Council Active Herbicide – Triafamone 20% + Ethoxysulfuron 10% WG - 60 gms")
    assert (f.reason, f.confidence) == (Reason.CLEAR, "medium")


def test_name_split_before_its_last_letter_is_not_a_typo(judge):
    # "Acephate 50%+ Fiproni l5% WDG" is Fipronil 5%.
    assert judge(title="Acephate 50% + Fipronil 5% WDG").reason is Reason.CLEAR
    assert judge(title="Acephate 50% + Fipronil 15% WDG").reason is Reason.REGISTRY_MISMATCH


# ---- Registry text that cannot be read cleanly never causes a flag (second review, 27 Sep 2026) ----

@pytest.mark.parametrize("title", [
    "Vitavax Power Carboxin 17.5% + Thiram 17.5% FF",                          # PDF: "Thiram1 7.5%"
    "Triticonazole 8% + Pyraclostrobin 4% FS",                                  # PDF: "40% g/l"
    "Syngenta Miravis Duo Pydiflumetofen 7.5% + Difenoconazole 12.5% SC",       # w/v given in brackets
    "Sedaxane 2.5% + Fludioxonil 2.5% FS",                                      # same
    "Fluroxypyr 13.8% + Metribuzin 5.6% EC",                                    # PDF: "Fluroxpyr + (Meptyl 20%)"
    "Acephate 50% + Fipronil 5% WG",                                            # registered as WDG
    "BASF Opera Pyraclostrobin 12.5% + Epoxiconazole 4.7% w/w SE",              # registered in g/l
    "Sulphur 84% + Azoxystrobin 6% SC",                                         # w/v given in brackets
    "Solomon Betacyfluthrin 8.49% + Imidacloprid 19.81% OD",                    # PDF: "Imidacloprid1 9.81%"
    "Iprodione 25% + Carbendazim 25% WP",                                       # PDF: "Iprodion"
])
def test_registered_products_written_oddly_in_the_registry_are_clear(judge, title):
    f = judge(title=title)
    assert f.reason is Reason.CLEAR, (title, f.checks[0].explanation)


@pytest.mark.parametrize("title", ["Thiamethoxam 100 g insecticide", "Bifenthrin 50 g insecticide"])
def test_pack_size_in_grams_is_not_a_strength(judge, title):
    f = judge(title=title)
    assert f.reason is Reason.CLEAR and "states no strength" in f.checks[0].explanation


def test_granule_strengths_are_still_read(judge):
    assert judge(title="Carbofuran 3G granules insecticide").checks[0].explanation.startswith("Carbofuran 3%")
