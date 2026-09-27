"""Radio pack: extraction and rules, on titles modelled on real Sep 2026 walkie-talkie listings."""

import pytest

from nishedh.extract.radio import extract_radio
from nishedh.verdict.base import Reason
from nishedh.verdict.radio import assess_radio


def judge(title, **more):
    return assess_radio(extract_radio({"title": title, **more}))


def bands(title):
    return [(b.low_mhz, b.high_mhz) for b in extract_radio({"title": title}).bands]


@pytest.mark.parametrize("title", [
    "ZORBES 2 Pack Walkie Talkie 2-Pin Acoustic Tube Earpiece Headset with Mic",
    "Smars Earphone Microphone for Walkie Talkie Two Way Radio Earphones 2-Pin",
    "LUITON Universal Radio Case Two Way Radio Holder Universal Pouch for Walkie Talkies",
    "NOVEL BL-1 2800mAh 3.7V Li-ion Rechargeable Battery Compatible with Baofeng",
    "Softer Screen Guard for Blackview Xplore 1 Walkie Talkie",
    "Garden Hose Pipe 20m",
])
def test_accessories_and_other_products_are_not_judged(title):
    assert judge(title) is None


def test_radio_sold_with_accessories_is_still_a_radio():
    assert extract_radio({"title": "Bf-888 Walkie Talkie 3-Pack with Earphone, Built-in LED Torch, Wall Charger, Battery"}).is_radio_equipment
    assert extract_radio({"title": "Walkie Talkie PMR446 with carrying case"}).is_radio_equipment


def test_frequency_parsing():
    assert bands("Baofeng UV-5R 136-174/400-520MHz dual band") == [(136.0, 174.0), (400.0, 520.0)]
    assert bands("BAOFENG UV-5R Walkie Talkie VHF 136-174hz UHF 400-470hz") == [(136.0, 174.0), (400.0, 470.0)]
    assert bands("PMR446 446.00625 - 446.19375 MHz") == [(446.00625, 446.19375)]
    assert bands("Walkie talkie 462.5625 MHz FRS") == [(462.5625, 462.5625)]
    assert bands("Pack of 2, 500 ml") == []


def test_eta_number_is_normalised():
    assert extract_radio({"title": "Walkie Talkie ETA SD 20201208695"}).eta_numbers == ["ETA-SD-20201208695"]


def test_booster_is_banned_high():
    f = judge("4G Mobile Signal Booster Network Repeater for home")
    assert (f.reason, f.confidence) == (Reason.BANNED_ITEM, "high") and "4(i)(b)" in f.checks[0].explanation


def test_jammer_is_banned_high():
    assert judge("GPS Jammer for car").reason is Reason.BANNED_ITEM


def test_licensed_uhf_band_is_banned_high():
    f = judge("Baofeng BF-888S UHF 400-470MHz Walkie Talkie Long Range")
    assert (f.reason, f.confidence) == (Reason.BANNED_ITEM, "high")


def test_cb_27mhz_is_an_exempt_band_not_banned():
    f = judge("Portable Walkie Talkie Set 27 MHz CB radio")
    assert f.reason is not Reason.BANNED_ITEM


def test_band_neither_licensed_nor_exempt_is_low_review():
    f = judge("Walkie Talkie 350 MHz long range")
    assert any(c.reason is Reason.REGISTRY_MISMATCH and c.confidence == "low" and "needs review" in c.explanation
               for c in f.checks)


@pytest.mark.parametrize("title", [
    "TP-Link Wi-Fi Range Extender Signal Booster 300Mbps", "Mobile Signal Booster Sticker for phone",
    "Cell Phone Signal Booster Case", "Mobile Signal Booster app free download",
    "TV Antenna Signal Booster Amplifier DTH", "Noise Cancelling Headphones Jammer Free ANC",
    "Immunity Booster Kadha 100g", "The Baofeng Radio Revolution (book)", "walkies for dogs leash",
    "SFP transceiver 10G LC", "Transceiver module NRF24L01", "Kids Smartwatch with walkie talkie function",
    "Blackview rugged phone walkie talkie PTT", "Walkie Talkie Costume for kids", "TIDRADIO TD-M15 PoC Radio 4G",
    "Walkie Talkie Stand Desk holder",
    "Original BF-A58S A58S Two Way Radio Walkie Talkies Belt Clip -10 Pack",
])
def test_must_not_flag_non_radio_products(title):
    assert judge(title) is None, title


@pytest.mark.parametrize("title", [
    "4G Mobile Signal Booster Network Repeater for home", "GSM 3G 4G mobile network booster kit",
    "Mobile jammer 8 band signal blocker", "GPS jammer for car",
    "Motorola Talkabout T42 two way radio", "Kenwood TK-3000 UHF 450-520MHz handheld radio",
    "2 pcs Walkie Talkie 16 Channel Rechargeable 1800mAh Li-ion Battery Long Range",
])
def test_real_radio_equipment_is_judged(title):
    assert judge(title) is not None, title


def test_ghz_and_decimal_frequencies():
    assert bands("Walkie talkie 2.4GHz digital") == [(2400.0, 2400.0)]
    assert bands("Radio 2.4-2.4835 GHz") == [(2400.0, 2483.5)]
    assert judge("Walkie talkie 2.4GHz digital kids").reason is not Reason.BANNED_ITEM


def test_title_only_findings_are_low_and_say_so():
    f = assess_radio(extract_radio({"title": "BAOFENG 4 Pack Long Range Walkie Talkies"}), title_only=True)
    assert f.confidence == "low" and "only the search-result title" in f.checks[0].explanation


def test_licence_free_claim_adds_a_misleading_claim_note():
    f = judge("Baofeng UV-5R 136-174/400-520MHz licence free 100% legal")
    assert f.reason is Reason.BANNED_ITEM and any("misleading" in n for n in f.notes)


def test_no_frequency_and_no_eta_is_missing_information():
    f = judge("BAOFENG 4 Pack Long Range Walkie Talkies")
    assert (f.reason, f.confidence) == (Reason.INFORMATION_MISSING, "medium")
    assert {c.reason for c in f.checks} == {Reason.INFORMATION_MISSING} and len(f.checks) == 2


def test_band_word_without_numbers_is_mentioned():
    f = judge("Motorola GP 328 UHF walkie talkie")
    assert "UHF" in f.checks[0].explanation


def test_exempt_band_with_unchecked_eta_is_clear_but_low_confidence():
    f = judge("Walkie Talkie PMR446 446.00625-446.19375 MHz ETA-SD-20201208695")
    assert (f.reason, f.confidence) == (Reason.CLEAR, "low")   # certificate not looked up (see test_eta.py)


def test_exempt_band_without_eta_is_missing_information():
    assert judge("PMR446 walkie talkie 446.0-446.2 MHz").reason is Reason.INFORMATION_MISSING


def test_toys_are_noted():
    f = judge("KGS Red Walkie Talkie with 2 Player System Toy for Kids")
    assert f.reason is Reason.INFORMATION_MISSING and any("toy" in n for n in f.notes)


# ---- Short-range-device bands are "needs review", never banned (external review, 27 Sep 2026) ----

@pytest.mark.parametrize("title", ["Low power short range walkie talkie 433.05-434.79 MHz", "LPD walkie talkie 433 MHz",
                                   "Walkie talkie 865-867 MHz"])
def test_short_range_device_band_needs_review_not_banned(title):
    f = assess_radio(extract_radio({"title": title}), {}, title)
    assert f is not None and f.reason is not Reason.BANNED_ITEM
    assert any(c.reason is Reason.REGISTRY_MISMATCH and "low-power short-range" in c.explanation for c in f.checks)


def test_licensed_band_near_433_is_still_flagged():
    f = assess_radio(extract_radio({"title": "Walkie talkie 430-440 MHz"}), {}, "")
    assert f is not None and f.reason is Reason.BANNED_ITEM


def test_mains_rating_is_not_a_radio_band():
    ex = extract_radio({"title": "Motorola T82 PMR446 446.0-446.2 MHz", "specifications": "Charger input: 100-240V 50/60Hz"})
    assert [(b.low_mhz, b.high_mhz) for b in ex.bands] == [(446.0, 446.2)]
