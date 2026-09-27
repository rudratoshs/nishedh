"""The official source behind every check, as shown to a reviewer: title, URL and as-of date.

Pesticide sources come from `data/registry/sources.json` (the exact PDFs parsed, with their hashes);
the rest are fixed. Every URL here was checked to resolve on 27 Sep 2026. The Rules copy on ppqs.gov.in is the
department's consolidated text (it predates Rule 10E of 2022 on online sale, which is not used here).
"""

from __future__ import annotations

from dataclasses import dataclass

from nishedh.registry.pesticides import PesticideRegistry


@dataclass(frozen=True)
class OfficialSource:
    title: str
    url: str
    as_on: str = ""


FIXED = {
    "labelling_rule": OfficialSource(
        "Insecticides Rules, 1971 – Rule 19 (the product label must state the active ingredient, its percentage "
        "and the registration number)",
        "https://ppqs.gov.in/sites/default/files/insecticides_rules_1971.pdf",
    ),
    "ccpa_radio_guidelines_2025": OfficialSource(
        "CCPA Guidelines for the Prevention and Regulation of Illegal Listing and Sale of Radio Equipment "
        "including Walkie Talkies on E-Commerce Platforms, 2025",
        "https://ccpa.doca.gov.in/files/Guidelines%20for%20the%20Prevention%20and%20Regulation%20of%20Illegal"
        "%20Listing%20and%20Sale%20of%20Radio%20Equipment%20including%20Walkie%20Talkies%20on%20ECommerce"
        "%20Platforms,%202025.pdf", "2025-05-27",
    ),
    "ccpa_radio_orders_2026": OfficialSource(
        "CCPA penalties on walkie-talkie listings, 16 Jan 2026 (PIB release)",
        "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2215261", "2026-01-16",
    ),
    "wpc_eta": OfficialSource(
        "Department of Telecommunications – Equipment Type Approval certificate",
        "https://saralsanchar.gov.in/",
    ),
    "ccpa_orders": OfficialSource(
        "CCPA orders on Cyclosinone Herbicide (Amazon 16 Sep 2026; Flipkart and JioMart 22 Sep 2026)",
        "https://ccpa.doca.gov.in/ccpa-orders",
    ),
}
_PESTICIDE_TITLES = {
    "registered_molecules": "CIB&RC – pesticides registered under section 9(3)",
    "registered_formulations": "CIB&RC – registered pesticide formulations",
    "banned_refused_restricted": "CIB&RC – pesticides banned, refused registration and restricted",
    "schedule": "Schedule to the Insecticides Act, 1968",
}


def source_map(reg: PesticideRegistry) -> dict[str, OfficialSource]:
    out = dict(FIXED)
    for s in reg.sources:
        out[s.name] = OfficialSource(_PESTICIDE_TITLES.get(s.name, s.name), s.url, s.as_on)
    return out
