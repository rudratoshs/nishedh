"""The official source behind every check, as shown to a reviewer: title, URL and as-of date.

Pesticide sources come from `data/registry/sources.json` (the exact PDFs parsed, with their hashes);
the rest are fixed. Every URL here was checked to resolve on 27 Sep 2026.
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
        "Insecticides Rules, 1971 – Rule 19 (label must state active ingredient and registration number)",
        "https://nhsrcindia.org/sites/default/files/2021-05/The%20Insecticides%20rules%201971.pdf",
    ),
    "ccpa_radio_guidelines_2025": OfficialSource(
        "CCPA Guidelines on listing radio equipment incl. walkie-talkies, 2025 (PIB release)",
        "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2132575", "2025-05-30",
    ),
    "ccpa_radio_orders_2026": OfficialSource(
        "CCPA penalties on walkie-talkie listings, 16 Jan 2026 (PIB release)",
        "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2215261", "2026-01-16",
    ),
    "wpc_eta": OfficialSource(
        "Department of Telecommunications – Equipment Type Approval certificate",
        "https://saralsanchar.gov.in/",
    ),
    "ccpa_orders": OfficialSource("CCPA orders (incl. Cyclosinone, Sep 2026)", "https://ccpa.doca.gov.in/"),
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
