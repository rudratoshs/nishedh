"""Pin the pesticide registry to the official PDFs (CIB&RC lists as on 31.03.2026 / 31.07.2026).

Counts and entries below were checked against the PDFs by hand. If a list is replaced, these
tests fail on purpose: re-check the new PDF, then update the expected values and sources.json.
"""

import json

import pytest

from nishedh.registry import pesticides as P
from nishedh.registry.names import key


@pytest.fixture(scope="module")
def reg() -> P.PesticideRegistry:
    return P.build()


def test_sources_are_hash_verified(tmp_path):
    src = P.REGISTRY_DIR
    (tmp_path / "raw").mkdir()
    meta = json.loads((src / "sources.json").read_text())
    for s in meta["pesticides"]:
        (tmp_path / "raw" / s["file"]).write_bytes((src / "raw" / s["file"]).read_bytes())
    meta["pesticides"][0]["sha256"] = "0" * 64
    (tmp_path / "sources.json").write_text(json.dumps(meta))
    (tmp_path / "restricted_pesticides.json").write_text((src / "restricted_pesticides.json").read_text())
    with pytest.raises(ValueError, match="SHA-256"):
        P.build(tmp_path)


def test_registered_molecules(reg):
    # 371 entries (last serial 372; 277 is skipped in the PDF). Two chemicals are listed twice under
    # different spellings (Cyazofamid / Cyzofamide, Oxathiapiprolin / Oxathiapipron): 369 chemicals.
    assert len(set(reg.registered.values())) == 369
    assert reg.registered["thiamethoxam"] == "Thiomethoxam"      # official misspelling, standard key
    assert reg.registered["chlorpyrifos"] == "Chlorpyriphos"
    assert "ipasalt" not in reg.registered and "neemproducts" not in reg.registered
    assert reg.registered["beflubutamid"] == "Beflubutamid"  # serial 36: dropped by the table reader, recovered from text
    assert reg.registered["decamethrin"] == reg.registered["deltamethrin"] == "Deltamethrin (Decamethrin)"
    assert reg.registered["glyphosate"] == "Glyphosate (IPA Salt)"
    assert "paraquatdichloride" in reg.registered


def test_schedule():
    serials = set(P._serial_items(P.REGISTRY_DIR / "raw" / "insecticides_in_the_schedule_as_on_31.07.2026.pdf"))
    assert serials == set(range(1, 1028)) - {662, 794}          # the PDF skips these two serials


def test_schedule_index(reg):
    assert "imidacloprid" in reg.schedule
    assert "fungus" not in reg.schedule and "isomermixture" not in reg.schedule


def test_cyclosinone_is_on_no_list(reg):
    # The CCPA orders of 16 and 22 Sep 2026 rest on this: no chemical of this name is scheduled or registered.
    k = key("Cyclosinone")
    assert not any(k in x for x in reg.schedule) and not any(k in x for x in reg.registered)


def test_formulations(reg):
    serials = {f.serial for f in reg.formulations}
    # Serials absent from the PDF. 776, 906 and 1104 are absent because the PDF printed 774, 904
    # and 1093 twice instead; both rows of each duplicate are kept.
    skipped_in_pdf = {267, 574, 576, 578, 583, 584, 613, 615, 617, 618, 620, 776, 906, 939, 1000, 1104, 1152}
    assert serials == set(range(1, 1178)) - skipped_in_pdf
    assert len(reg.formulations) == 1163
    raws = {f.raw for f in reg.formulations}
    assert {"Emamectin benzoate 3.8% + Thiamethoxam 20% WDG", "Benalaxyl 8.0 %+Mancozeb 65%WP",
            "Mesosulfuron methyl 3% +Iodosulfuronmethylsodium0.6% WG"} <= raws
    two_four_d = [f for f in reg.formulations if f.raw.startswith("2,4-D Amine")]
    assert two_four_d and all(f.components == ("24daminesalt",) for f in two_four_d)
    f39 = next(f for f in reg.formulations if f.serial == 39)
    assert f39.raw == "Bifenthrin 10% WP" and f39.category == "INSECTICIDES"  # recovered from text
    combo = next(f for f in reg.formulations if f.raw.startswith("Acephate 50%+ Imidacloprid"))
    assert combo.components == ("acephate", "imidacloprid")
    fipronil = next(f for f in reg.formulations if "Fiproni l5%" in f.raw)
    assert "fipronil" in fipronil.components                  # PDF typo handled
    assert sum(f.category == "HERBICIDES" for f in reg.formulations) > 200
    assert "PLANT GROTH REGULATORS" not in {f.category for f in reg.formulations}


def test_banned_lists_match_pdf(reg):
    assert len(reg.banned) == 49 and len(reg.export_only) == 5
    assert len(reg.withdrawn) == 8 and len(reg.refused) == 18
    banned = {x.key for x in reg.banned}
    assert {"alachlor", "endosulfan", "dichlorvos", "methomyl", "trichlorfon"} <= banned
    assert next(x for x in reg.banned if x.key == "dicofol").note.startswith("S.O. 4294(E)")
    assert "nicotinesulfate" in {x.key for x in reg.export_only}
    assert [x.name for x in reg.withdrawn][-1] == "Warfarin"
    assert "vamidothion" in {x.key for x in reg.refused}


def test_banned_list_synonyms(reg):
    by_name = {x.name: x for x in (*reg.banned, *reg.refused)}
    assert by_name["Lindane"].synonyms == ("gammahch",)
    assert by_name["Dibromochloropropane"].synonyms == ("dbcp",)
    assert by_name["Dibromochloropropane"].note == "S.O. 569 (E) dated 25th July 1989"
    assert set(by_name["Thiodemeton / Disulfoton"].keys) >= {"thiodemeton", "disulfoton"}
    assert "camphechlor" in by_name["Toxaphene"].synonyms


def test_restricted_transcription(reg):
    names = [x.name for x in reg.restricted]
    assert len(names) == 16 and names[0] == "Aluminium Phosphide" and names[-1] == "Trifluralin"
    assert all(x.note for x in reg.restricted)


def test_round_trip(reg):
    again = P.PesticideRegistry.from_json(reg.to_json())
    assert again == reg
