"""Scope recall: a product that is in a category must reach the rules, and one that is not must not.

A listing judged out of scope never gets a verdict, so a miss here is invisible to every verdict
test. Titles are real listings from the 27 Sep 2026 snapshot (external review, 27 Sep 2026).
"""

import pytest

from nishedh.extract.pesticide import PesticideExtractor
from nishedh.extract.radio import extract_radio
from nishedh.registry.pesticides import load


@pytest.fixture(scope="module")
def extractor():
    return PesticideExtractor(load())


@pytest.mark.parametrize("title", [
    "Syngenta Actara 5G X 10 Sachets, Quickly penetrates the leaf surface, Powder",
    "Hitweed Maxx 1ltr (Godrej)",
    "Garden Genie Trichoderma Viride Powder (2x106 CFU/gm) 500 Gm",
    "OrganicDews Beauveria bassiana + Verticillium lecanii+ Metarhizium anisopliae Bio for Plants - 1 Kg Each",
    "OrganicDews Metarhizium anisopliae 1 Kg (1x10^8 CFU/g) for Plants 1 Kg",
    "Herbicide Plus Bamboo Killer Granules – 5% Active Formula Weed Killer",
    "Bayer Roundup Herbicide – Glyphosate 41% SL Weed Killer - 2 ltr",
])
def test_pesticides_are_in_scope(extractor, title):
    assert extractor.extract({"title": title}).is_pesticide, title


@pytest.mark.parametrize("title", [
    "Kraft Seeds Hand Weeder - 1 Pc (Orange Handle, Black Blade), Weed Remover Tool With Handle",
    "BUY SURETY New Collection Backpack Pressure Sprayer",
    "Buy Weed Management by Dr. Surinder Singh Rana",
    "GREENSEA Zinnia Mixed color Flower seed for Gardening",
    "Patanjali Divya Jwar Nashak Kwath – Immunity & Fever Care",
    # Botanical sprays that name no pesticide active are out of scope by design (see README limits).
    "Ugaoo Neem Oil Spray for Plants & Garden - Highly Effective on Plant Insects (250 ml)",
    "Nature's Bounty Probiotic Bacillus subtilis 10 Billion CFU Gut Health Capsules",
    "Pseudomonas fluorescens Bio Fertilizer Liquid 1L",
    "Trichoderma harzianum biocontrol book by Dr. Sharma",
])
def test_non_pesticides_stay_out_of_scope(extractor, title):
    assert not extractor.extract({"title": title}).is_pesticide, title


@pytest.mark.parametrize("title", [
    "RJLINK 3G/4G/5G triband mobile phone signal booster all sim working jio/airtel/vi/bsnl boost network",
    "Lintratek jio/2G/3G/4G triband mobile phone signal booster & data complete kit area coverage 6500 sq.feet",
    "RJLINK 2G/3G/4G/5G quad band mobile phone network booster all sim working jio/airtel/vi/bsnl",
    "Cellexxa 2g/3g/4g/5g Quad Band Signal Booster All Sim Supported Booster Network Boosts & Data",
    "Full Band 4g Lte/gprs Signal Booster For Cars Compatible 4g/gsm/3g/lte/gprs Cell Phones 700/850/1700 Mhz 5g Wi-fi",
    "Baofeng BF-888S UHF 400-470MHz Walkie Talkie Long Range",
    "Mobile phone jammer 8 band portable",
    "Cell phone jammer for exam hall",
    "Cellular phone signal repeater 900/1800 MHz",
    "Signal booster for mobile phones, all networks",
    "Cell phone amplifier for home 4G LTE",
    "Cellular Amplifier Kit Tri Band",
    "4G LTE Amplifier Kit for Home",
    "Mobile Signal Booster with Antenna",
    "Cell Phone Signal Booster for Car Truck and RV, 5G Ready 4G LTE, Integrated Indoor Antenna 50dB Max Gain",
])
def test_radio_equipment_is_in_scope(title):
    assert extract_radio({"title": title}).is_radio_equipment, title


@pytest.mark.parametrize("title", [
    "TP-Link AC750 WiFi Range Extender | Up to 750Mbps | Dual Band WiFi Extender, Repeater, WiFi Signal Booster",
    "5 PCS Phone Signal Boosters, Universal Cellphone Signal Stickers for Outdoor Camping",
    "Qiwa Wifi Extender Repeater Signal Booster, 300mbps Router Antenna Booster",
    "SHIDU S611 Portable Wireless Voice Amplifier with LED",
    "LUITON Radio Holder Radio Holster Baofeng Case Two Way Radio Pouch for Walkie Talkies",
    "Enakshi® Universal 5G LTE 18dBi High Gain | Wireless Module Router Signal Booster for Enhanced Connectivity",
    "Battery booster for mobile phone 10000 mAh",
    "Voice booster for mobile calls",
    "Phone amplifier speaker for mobile, portable bass",
    "Samsung Galaxy S25 5G",
    "TIDRADIO TD-M15 Global Long Range Walkie PoC Radio",
    "Noise cancelling headphones jammer-free Bluetooth",
    # Booster words in titles about phones that are not mobile signal boosters (third review).
    "TP-Link 8 Port Gigabit Network Switch with Signal Amplifier",
    "PoE Network Repeater Extender 100m Ethernet Signal Amplifier",
    "Netgear EX3700 Wireless Repeater 750Mbps Dual Band Range Booster",
    "Netgear Orbi WiFi 6 Mesh System Dual Band Repeater for Phones",
    "Samsung Galaxy S24 5G Phone with Signal Booster Feature 8GB RAM",
    "SIM Card Holder Tray for Mobile Phone with Booster Spring",
    "Gaming Mobile Phone Cooling Fan Booster",
    "Mobile Testosterone Booster Supplement 60 Capsules Phone Order",
    "Immune Booster Herbal Mobile Pack",
    "Hotstar Mobile Data Booster Plan Recharge Jio",
    "GPS Signal Booster Repeater for Car Navigation and Mobile",
    "Wireless Microphone Signal Booster for Mobile Phone Vlog",
    "Boss RC-1 Guitar Loop Repeater Pedal phone jack",
    "Baofeng UV-5R Repeater Cable for Mobile Radio",
    "Antenna for mobile signal booster",
])
def test_non_radio_products_stay_out_of_scope(title):
    assert not extract_radio({"title": title}).is_radio_equipment, title


@pytest.mark.parametrize("title", ["Thimet 10 G Phorate Granules 1kg", "Rogor 30 EC Dimethoate 500ml",
                                   "Furadan 3G Carbofuran 1kg", "Roundup 41 SL Glyphosate 1L"])
def test_trade_name_with_a_code_only_strength_stays_in_scope(extractor, title):
    ex = extractor.extract({"title": title})
    assert ex.is_pesticide and all(c.strength_pct is not None for c in ex.chemicals), title


def test_pack_count_after_a_trade_name_is_not_a_strength(extractor):
    ex = extractor.extract({"title": "Syngenta Actara 5G X 10 Sachets"})
    assert ex.is_pesticide and ex.chemicals[0].strength_pct is None
