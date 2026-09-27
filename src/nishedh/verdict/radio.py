"""Turn what a listing says about radio equipment into a reviewable finding.

Rules come from the CCPA's radio-equipment listing guidelines (2025) and the PIB release on the
16 Jan 2026 penalties:

    R1  mobile signal booster or jammer listed          -> banned_item, high     (para 4(i)(b))
    R2  a band used by licensed handheld radios         -> banned_item, high     (para 4(i)(a))
        (VHF 136-174, UHF 400-520, FRS/GMRS 462-468 MHz); a band that is neither licensed nor
        exempt -> registry_mismatch, low ("band needs review")
    R3  R2 plus a "licence-free" / "100% legal" claim   -> adds a misleading-claim note
    R4  no frequency stated                             -> information_missing  (para 4(ii)(B))
    R5  no Equipment Type Approval (ETA) number stated  -> information_missing  (para 4(ii)(A))
        a stated ETA number is checked against its public DoT certificate.

Exempt bands (no R2): PMR446 446.0-446.2 MHz; CB 26.957-27.283 MHz; 2.4 GHz and 5.8 GHz
delicensed bands. An ETA is still required for these.

R4/R5 are medium confidence when the product page was read, low when only the search-result title
was seen (the tool then says "the title does not state ...").
"""

from __future__ import annotations

import re

from nishedh.extract.pesticide import Found
from nishedh.extract.radio import Band, RadioExtraction
from nishedh.registry.eta import EtaCertificate
from nishedh.verdict.base import Check, Finding, Reason, finalize

PMR446 = (446.0, 446.2)
EXEMPT_BANDS = (PMR446, (26.957, 27.283), (2400.0, 2483.5), (5725.0, 5875.0))
# Bands where handheld radios need a frequency assignment in India: marine/business VHF, UHF
# business and amateur, and US FRS/GMRS channels sold on imported radios.
LICENSED_BANDS = ((136.0, 174.0), (400.0, 520.0), (462.0, 468.0))
SOURCE = "ccpa_radio_guidelines_2025"
EPS = 1e-6


def _within(b: tuple[float, float], band: tuple[float, float]) -> bool:
    return b[0] >= band[0] - EPS and b[1] <= band[1] + EPS


def _exempt(b: Band) -> bool:
    return any(_within((b.low_mhz, b.high_mhz), band) for band in EXEMPT_BANDS)


def _overlaps_licensed(b: Band) -> bool:
    return any(b.low_mhz <= hi and b.high_mhz >= lo for lo, hi in LICENSED_BANDS)


def _norm_model(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _model_named(model: str, listing_text: str) -> bool:
    """True when any of the certificate's models ("T82", "T82 / T82E") appears in the listing,
    ignoring hyphens and spaces ("BF-888S" = "BF888S"). Models under 3 characters never match."""
    haystack = _norm_model(listing_text)
    for part in re.split(r"[/,;]|\band\b", model):
        m = _norm_model(part)
        if len(m) >= 3 and m in haystack:
            return True
    return False


def _eta_check(number: str, cert: EtaCertificate | None, listing_text: str, stated_in_band: bool) -> Check:
    """Compare a stated ETA number with its public certificate."""
    ev = (Found("eta", number),)
    if cert is None:
        return Check(Reason.CLEAR if stated_in_band else Reason.INFORMATION_MISSING, "low",
                     f"States ETA {number}; its certificate has not been checked yet.", ev, "wpc_eta")
    if not cert.found:
        return Check(Reason.NOT_IN_REGISTRY, "high",
                     f"ETA {number} does not resolve to any certificate on the Department of Telecommunications' "
                     f"public register ({cert.url}).", ev, "wpc_eta")
    if not cert.bands_mhz:
        return Check(Reason.REGISTRY_MISMATCH, "low",
                     f"ETA {number} ({cert.make} {cert.model}) exists, but its frequency range could not be read; "
                     f"check the certificate by hand ({cert.url}).", ev, "wpc_eta")
    outside = [b for b in cert.bands_mhz if not any(_within(b, band) for band in EXEMPT_BANDS)]
    if outside:
        lo, hi = outside[0]
        return Check(Reason.REGISTRY_MISMATCH, "medium",
                     f"ETA {number} ({cert.make} {cert.model}) certifies {lo:g}–{hi:g} MHz, outside the "
                     "licence-exempt bands; a self-declared ETA does not make a licensed band licence-free "
                     f"({cert.url}).", ev, "wpc_eta")
    if not _model_named(cert.model, listing_text):
        return Check(Reason.REGISTRY_MISMATCH, "medium",
                     f"ETA {number} is for model {cert.model or '(none)'} by {cert.make or '(unknown)'}, which the "
                     f"listing does not name; the approval may belong to a different product ({cert.url}).",
                     ev, "wpc_eta")
    bands = ", ".join(f"{lo:g}-{hi:g} MHz" for lo, hi in cert.bands_mhz)
    return Check(Reason.CLEAR, "high", f"ETA {number} is a valid certificate for {cert.make} {cert.model}, {bands} ({cert.url}).",
                 ev, "wpc_eta")


def assess_radio(
    ex: RadioExtraction,
    certificates: dict[str, EtaCertificate] | None = None,
    listing_text: str = "",
    title_only: bool = False,
) -> Finding | None:
    """None when the listing is not radio equipment (accessories and other products included).

    `certificates` maps ETA numbers stated in the listing to their looked-up certificates;
    `listing_text` (all listing text) is used to check the certificate's model is the one sold;
    `title_only` is True when only the search-result title was seen, not the product page.
    """
    if not ex.is_radio_equipment:
        return None
    checks: list[Check] = []
    notes: list[str] = []
    if ex.booster or ex.jammer:
        kind = "jammer" if ex.jammer else "mobile signal booster"
        checks.append(Check(
            Reason.BANNED_ITEM, "high",
            f"Listed as a {kind}; the 2025 guidelines (para 4(i)(b)) say platforms shall not allow listing "
            "or sale of mobile signal boosters and wireless jammers.",
            tuple(ex.jammer or ex.booster), SOURCE,
        ))
    outside = [b for b in ex.bands if not _exempt(b)]
    for b in outside:
        shown = f"{b.low_mhz:g} MHz" if b.low_mhz == b.high_mhz else f"{b.low_mhz:g}–{b.high_mhz:g} MHz"
        if _overlaps_licensed(b):
            checks.append(Check(
                Reason.BANNED_ITEM, "high",
                f"States {shown}, a band used by licensed handheld radios. Radios needing a frequency assignment "
                "may not be listed on e-commerce platforms (para 4(i)(a)); walkie-talkies are licence-exempt only "
                "in 446.0–446.2 MHz (PMR446).",
                (b.evidence,), SOURCE,
            ))
        else:
            checks.append(Check(
                Reason.REGISTRY_MISMATCH, "low",
                f"States {shown}, which is neither PMR446 nor a common licensed handheld band; the band needs review.",
                (b.evidence,), SOURCE,
            ))
    if any(_overlaps_licensed(b) for b in outside) and ex.licence_free_claims:
        notes.append(
            f'Also claims "{ex.licence_free_claims[0].text}" while stating a licensed band; the 16 Jan 2026 '
            "orders called such claims misleading."
        )
    if not ex.booster and not ex.jammer:
        seen = "The title does not state" if title_only else "The listing does not state"
        conf = "low" if title_only else "medium"
        only = " (only the search-result title was checked)" if title_only else ""
        if not ex.bands:
            words = ", ".join(sorted({w.text.upper() for w in ex.band_words}))
            checks.append(Check(
                Reason.INFORMATION_MISSING, conf,
                f"{seen} an operating frequency{only}; the guidelines (para 4(ii)(B)) say listings lacking frequency "
                "information shall be taken down." + (f" It mentions {words} without numbers." if words else ""),
                tuple(ex.band_words[:1]) or tuple(ex.device[:1]), SOURCE,
            ))
        if not ex.eta_numbers:
            claim = f' It says "{ex.eta_claims[0].text}" without a number.' if ex.eta_claims else ""
            checks.append(Check(
                Reason.INFORMATION_MISSING, conf,
                f"{seen} an Equipment Type Approval (ETA) number{only}, as para 4(ii)(A) requires.{claim}",
                tuple(ex.eta_claims[:1]) or tuple(ex.device[:1]), SOURCE,
            ))
        else:
            for number in ex.eta_numbers:
                cert = (certificates or {}).get(number)
                checks.append(_eta_check(number, cert, listing_text, stated_in_band=bool(ex.bands) and not outside))
    if ex.toy:
        notes.append("Sold as a toy; toy walkie-talkies were among the listings penalised on 16 Jan 2026.")
    return finalize(checks, notes)
