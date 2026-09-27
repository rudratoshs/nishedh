"""Read a marketplace listing and extract what it says about radio equipment.

The rulebook is the CCPA's Guidelines for the Prevention and Regulation of Illegal Listing and Sale
of Radio Equipment including Walkie Talkies on E-Commerce Platforms, 2025: listings must state the
frequency range and Equipment Type Approval (ETA); 446.0-446.2 MHz (PMR446) walkie-talkies are
licence-exempt; mobile signal boosters and wireless jammers may not be listed at all.

This module only reads text; `nishedh.verdict.radio` applies the rules. Precision rules, each pinned
by a "must not flag" test:
- "signal booster" only counts for mobile-network boosters, not Wi-Fi extenders, TV antennas,
  phone cases, stickers or apps; "jammer" only next to a signal word, never "jammer-free";
- a brand name alone (Baofeng, Retevis) only counts with a radio word or model number, and phones,
  smartwatches, books, costumes, network modules and cellular PoC radios are not walkie-talkies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from nishedh.extract.pesticide import Found
from nishedh.registry.names import clean

_I = re.IGNORECASE
DEVICE = re.compile(
    r"walk(?:ie|y)s?[\s-]?talk(?:ie|y)s?|talk(?:ie|y)s?[\s-]?walk(?:ie|y)s?|two[\s-]?way\s+radios?|"
    r"\bpmr[\s-]?446\b|\b(?:uhf|vhf|gmrs|frs|ham|handheld|portable|amateur)\s+(?:radio|transceiver)s?\b|"
    r"\btalkabout\b|\b(?:baofeng|retevis|kenwood|icom|midland|tidradio|radioddity)\b(?=.{0,40}\b(?:radio|transceiver|"
    r"walkie|uv-?\d|bf-?\d|gt-?\d|rt-?\d|td-?[a-z]?\d|tk-?\d|ic-?\d))|\bbf-?888s?\b|\buv-?5r\b|\buv-?82\b",
    _I,
)
# Not walkie-talkies even when the words appear.
NOT_RADIO = re.compile(
    r"\bsmart\s?watch|\bwatch\b|\bphones?\b|\bsmartphone|\brugged\b|\bbook\b|\bcostume\b|\bpoc\b|\b4g\b|\blte\b|"
    r"\bsfp\b|\bmodule\b|\bnrf24|\bleash\b|\bdog\b|\bapp\b|\bgame\b|\bsticker\b|\bposter\b|\bt-?shirt\b",
    _I,
)
# A booster, repeater or amplifier named right after a mobile-network word ("mobile phone network
# booster", "2g/3g/4g/5g Quad Band Signal Booster", "4G LTE Amplifier", "GSM 900MHz Cell Phone Signal
# Repeater"), or one "for mobile/cell phones". A booster word elsewhere in a title about phones
# ("Phone Cooling Fan Booster", "5G Phone with Signal Booster Feature") does not count.
_NET = r"(?:mobile|cell(?:ular)?|phones?|gsm|[2345]g|lte|network|signal|jio|airtel|bsnl|sim|(?:tri|quad|dual|full)[\s-]?band)"
BOOSTER = re.compile(
    rf"\b{_NET}\b(?:[\s/&,-]+[\w.]+){{0,2}}?[\s/&,-]+(?:boosters?|repeaters?|amplifiers?)\b|"
    r"\b(?:boosters?|repeaters?|amplifiers?)\s+for\s+(?:all\s+)?(?:mobile|cell)",
    _I,
)
NOT_BOOSTER = re.compile(
    r"wi-?fi\s+(?:range\s+|signal\s+|dual\s+band\s+)?(?:extender|booster|repeater)|wireless\s+(?:range\s+)?extender|"
    r"range\s+extender|router|access\s+point|\btv\b|\bdth\b|set[\s-]?top|sticker|\bcase\b|\bcover\b|\bapp\b|download|"
    r"immun|\bantenna\s+for\s+(?:tv|dth)|\bspeakers?\b|\baudio\b|\bsound\b|\bvoice\b|\bmusic\b|\bbattery\b|"
    r"power\s*bank|\bcharger\b|\bseat\b|\bbass\b|ethernet|\brj45\b|\bpoe\b|\bswitch\b|\bcable\b|\bmesh\b|"
    r"\bgam(?:e|ing)\b|\bfan\b|supplement|capsules?|testosterone|\bplan\b|recharge|\bgps\b|microphone|vibration|"
    r"\bfeature\b|\bmotor\b|\bspring\b|\btray\b|pedal|guitar|\bmbps\b|wireless\s+repeater|range\s+booster|\bram\b",
    _I,
)
JAMMER = re.compile(
    r"(?:mobile|signal|gps|drone|cell(?:ular)?|network|wi-?fi|rf|gsm|4g|5g)(?:[\s-]+phones?)?\s+(?:signal\s+)?(?:jammers?|blockers?)|"
    r"\bjammers?\s+for\s+(?:mobile|gps|drone|cell|phone|signal)",
    _I,
)
NOT_JAMMER = re.compile(r"jammer[\s-]?free|noise[\s-]?cancell?ing|\bheadphones?\b|\bearbuds?\b", _I)
# Products sold for a radio but not radio equipment themselves. Strong words make a title an
# accessory wherever they appear ("Walkie Talkie 2-Pin Acoustic Tube Earpiece"); weak words only
# when they come before the device name or with "for" ("Pouch Case for Walkie Talkies"), so a radio
# sold "with carrying case" is still a radio.
ACCESSORY_STRONG = re.compile(
    r"\b(?:earpieces?|ear\s?piece|headsets?|earphones?|holsters?|holders?|mounts?|chargers?|batter(?:y|ies)|"
    r"antennas?|speaker\s+mic|programming\s+cable|\d-pin|acoustic\s+tube|pouch|screen\s+guard|tempered\s+glass|"
    r"protector)\b",
    _I,
)
ACCESSORY_WEAK = re.compile(r"\b(?:case|cover|strap|clip|belt|stand|bag|cable)\b", _I)
# "Walkie Talkie 3-Pack with Earphone, Wall Charger" is a radio sold with accessories, and
# "Walkie Talkie 1800mAh Battery 5W" states the radio's battery, not a battery for sale.
_BUNDLED = re.compile(r"\bwith\b|\bincl\w*|\bplus\b|\+|\bintegrated\b|\bbuilt[\s-]?in\b|\bkit\b", _I)
_SPEC = re.compile(r"\d+\s*mah\s+(?:li-?ion\s+)?batter(?:y|ies)", _I)
TOY = re.compile(r"\btoys?\b|\bkids?\b|\bchildren\b|\bspy\s+gear\b", _I)
LICENCE_FREE = re.compile(r"licen[cs]e[\s-]?free|no\s+licen[cs]e|100\s*%\s*legal|fully\s+legal|legal\s+to\s+use", _I)

_NUM = r"\d{1,4}(?:[.,]\d+)?"
_UNIT = r"([kmg])?hz"
_RANGE = rf"{_NUM}\s*(?:[kmg]?hz)?\s*(?:-|–|~|to)\s*{_NUM}"
# One or more ranges sharing a unit: "400-470 MHz", "136-174/400-520MHz", "136-174hz" (a common
# misprint of MHz), "2.4-2.4835 GHz".
_GROUP = re.compile(rf"({_RANGE}(?:\s*(?:/|,|and|&)\s*{_RANGE})*)\s*{_UNIT}\b", _I)
_RANGE_ONE = re.compile(rf"({_NUM})\s*(?:[kmg]?hz)?\s*(?:-|–|~|to)\s*({_NUM})", _I)
# A single frequency needs an explicit kHz/MHz/GHz: a bare "50/60Hz" is a charger's mains rating.
_SINGLE = re.compile(rf"({_NUM})\s*([kmg])hz\b", _I)
_BAND_WORD = re.compile(r"\b(uhf|vhf|frs|gmrs|pmr[\s-]?446|cb\s+radio)\b", _I)
ETA = re.compile(r"\bETA[\s:-]*SD[\s:-]*\d{11}\b", _I)
ETA_CLAIM = re.compile(r"\bETA\b|\bWPC\b|type\s+approv", _I)


@dataclass(frozen=True)
class Band:
    low_mhz: float
    high_mhz: float
    evidence: Found


@dataclass
class RadioExtraction:
    device: list[Found] = field(default_factory=list)
    booster: list[Found] = field(default_factory=list)
    jammer: list[Found] = field(default_factory=list)
    accessory: list[Found] = field(default_factory=list)
    not_radio: list[Found] = field(default_factory=list)
    toy: list[Found] = field(default_factory=list)
    bands: list[Band] = field(default_factory=list)
    band_words: list[Found] = field(default_factory=list)   # "UHF", "FRS": a band family without numbers
    eta_numbers: list[str] = field(default_factory=list)
    eta_claims: list[Found] = field(default_factory=list)   # "ETA approved", "WPC" without a number
    licence_free_claims: list[Found] = field(default_factory=list)

    @property
    def is_radio_equipment(self) -> bool:
        """A walkie-talkie, mobile booster or jammer; accessories and other products are not."""
        if (self.booster or self.jammer) and not self.accessory:
            return True
        return bool(self.device) and not self.accessory and not self.not_radio


def _mhz(value: str, unit: str | None) -> float:
    v = float(value.replace(",", "."))
    return {"k": v / 1000, "g": v * 1000}.get((unit or "m").lower(), v)


def extract_radio(fields: dict[str, str]) -> RadioExtraction:
    """`fields` maps a field name ("title", "specifications", ...) to its text."""
    out = RadioExtraction()
    seen_eta: set[str] = set()
    for name, raw in fields.items():
        text = clean(raw or "")
        if not text:
            continue
        is_title = name == "title"
        for rx, bucket in ((DEVICE, out.device), (TOY, out.toy), (LICENCE_FREE, out.licence_free_claims),
                           (_BAND_WORD, out.band_words)):
            bucket.extend(Found(name, m.group(0)) for m in rx.finditer(text))
        if is_title:
            # Product type is decided by the title: a specification saying "with belt clip" or a
            # description mentioning a phone does not change what is being sold.
            out.not_radio.extend(Found(name, m.group(0)) for m in NOT_RADIO.finditer(text))
            if not NOT_BOOSTER.search(text):
                out.booster.extend(Found(name, m.group(0)) for m in BOOSTER.finditer(text))
            if not NOT_JAMMER.search(text):
                out.jammer.extend(Found(name, m.group(0)) for m in JAMMER.finditer(text))
            # Where the product itself is named: a walkie-talkie or a booster. Accessory words after it
            # describe what comes in the box ("Signal Booster ... Integrated Indoor Antenna").
            first_device = min(next((m.start() for m in DEVICE.finditer(text)), len(text)),
                               next((m.start() for m in BOOSTER.finditer(text)), len(text)))
            specs = [m.span() for m in _SPEC.finditer(text)]
            for m in ACCESSORY_STRONG.finditer(text):
                bundled = m.start() > first_device and _BUNDLED.search(text[first_device : m.start()])
                spec = any(s <= m.start() < e for s, e in specs)
                if not bundled and not spec:
                    out.accessory.append(Found(name, m.group(0)))
            # A weak word names the product when it comes before the device name, is followed by
            # "for", or ends the title ("... Walkie Talkies Belt Clip -10 Pack") without "with".
            tail = re.sub(r"[\s\-|,()]*(?:pack\s+of\s+\d+|\d+\s*(?:pack|pcs|pieces?|set))?[\s\-|,()]*$", "", text, flags=_I)
            for m in ACCESSORY_WEAK.finditer(text):
                at_end = m.end() >= len(tail) - 6 and not _BUNDLED.search(text[first_device : m.start()])
                if m.start() < first_device or re.search(rf"{re.escape(m.group(0))}\s+for\b", text, _I) or at_end:
                    out.accessory.append(Found(name, m.group(0)))
        covered: list[tuple[int, int]] = []
        for g in _GROUP.finditer(text):
            unit = g.group(2)
            for m in _RANGE_ONE.finditer(g.group(1)):
                lo, hi = sorted((_mhz(m.group(1), unit), _mhz(m.group(2), unit)))
                if _plausible(lo) and _plausible(hi):
                    out.bands.append(Band(lo, hi, Found(name, g.group(0))))
            covered.append(g.span())
        for m in _SINGLE.finditer(text):
            if any(s <= m.start() < e for s, e in covered):
                continue
            f = _mhz(m.group(1), m.group(2))
            if _plausible(f):
                out.bands.append(Band(f, f, Found(name, m.group(0))))
        for m in ETA.finditer(text):
            number = "ETA-SD-" + re.sub(r"\D", "", m.group(0))
            if number not in seen_eta:
                seen_eta.add(number)
                out.eta_numbers.append(number)
        if not out.eta_numbers:
            out.eta_claims.extend(Found(name, m.group(0)) for m in ETA_CLAIM.finditer(text))
    return out


def _plausible(mhz: float) -> bool:
    """Radio bands between about 20 MHz and 6 GHz; this drops pack sizes, distances and model numbers."""
    return 20 <= mhz <= 6000
