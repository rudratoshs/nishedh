"""Turn what a listing says about pesticide chemicals into a reviewable finding.

A finding is never a legal conclusion. It records which official list was checked, what the
listing said and where, and one reason code:

    banned_item          a named chemical is on the banned or banned-for-use list
    not_in_registry      a named chemical is refused, withdrawn, scheduled but unregistered, or unknown
    information_missing  a pesticide product that names no chemical at all
    registry_mismatch    a registered chemical at a strength or formulation that is not registered
    clear                every named chemical and formulation is registered

The verdict is the most serious reason across all chemicals in the listing.
"""

from __future__ import annotations

import re

from nishedh.extract.pesticide import FORM_CODES, ChemicalClaim, Extraction
from nishedh.registry.names import is_salt_suffix
from nishedh.registry.pesticides import PesticideRegistry
from nishedh.verdict.base import (  # noqa: F401  (re-exported for callers of this module)
    CONFIDENCE_ORDER,
    SEVERITY,
    VERDICT_OF,
    Check,
    Finding,
    Reason,
    Verdict,
    finalize,
    with_extra,
)


class PesticideRules:
    def __init__(self, reg: PesticideRegistry) -> None:
        self.reg = reg
        # Every list is indexed by the entry's key and its synonyms (BHC, Gamma-HCH, DBCP, Disulfoton).
        self._banned = {k: x for x in reg.banned for k in x.keys}
        self._export_only = {k: x for x in reg.export_only for k in x.keys}
        self._refused = {k: x for x in reg.refused for k in x.keys}
        self._withdrawn = {k: x for x in reg.withdrawn for k in x.keys}
        self._restricted = {k: x for x in reg.restricted for k in x.keys}
        # component key -> [(strength %, formulation code)] from single-chemical registered formulations
        self._forms: dict[str, list[tuple[float | None, str | None]]] = {}
        for f in reg.formulations:
            if len(f.components) == 1:
                self._forms.setdefault(f.components[0], []).append(_strength_code(f.raw))
        self._combos = [f for f in reg.formulations if len(f.components) >= 2]

    def family(self, k: str) -> set[str]:
        """Keys that name the same active substance in another salt or ester form.

        "glyphosate" covers "glyphosateammoniumsalt"; "24d" covers "24daminesalt" and
        "24dethylester"; "glufosinate" covers "glufosinateammonium". Two keys are one family only
        when the longer is the shorter plus salt/ester words, so "sulfurylfluoride" is not "sulfur"
        and "copperhydroxide" is not "copper".
        """
        out = {k}
        if len(k) >= 5 or (any(c.isdigit() for c in k) and len(k) >= 3):
            for other in (*self.reg.registered, *self._forms):
                if other.startswith(k) and is_salt_suffix(other[len(k):]) or len(other) >= 5 and k.startswith(other) and is_salt_suffix(k[len(other):]):
                    out.add(other)
        return out

    def assess(self, ex: Extraction, title_only: bool = False) -> Finding | None:
        """None when the listing is not a pesticide product.

        `title_only`: only the search-result title was seen (no product page). A title that names no
        chemical is then a low-confidence prompt, since the product page may name it.
        """
        if not ex.is_pesticide:
            return None
        checks = [self._check_claim(c) for c in ex.chemicals]
        combo = self._registered_combination(ex.chemicals)
        if combo is not None:
            conf = "high" if all(c.match == "exact" for c in ex.chemicals) else "medium"
            checks = [
                Check(Reason.CLEAR, conf, f"Registered combination formulation: {combo}.", ch.evidence,
                      "registered_formulations")
                if ch.reason in (Reason.CLEAR, Reason.REGISTRY_MISMATCH) else ch
                for ch in checks
            ]
        # A name with a strength that no official list knows ("Cyclosinone 20% SC") may be a brand or
        # an unregistered chemical. It is ignored only when it repeats the strength and code of a
        # chemical the listing does name ("Roundup 41% SL ... Glyphosate 41% SL"): that is the brand.
        named = {(c.strength_pct, c.form_code) for c in ex.chemicals}
        for u in ex.unrecognised:
            m = re.search(r"(\d+(?:\.\d+)?)% (\S+)$", u.text)
            if m and (float(m.group(1)), m.group(2).upper()) in named:
                continue
            checks.append(Check(
                Reason.INFORMATION_MISSING, "medium",
                f'"{u.text}" names no chemical on any official list; it may be a brand name or an '
                "unregistered chemical, and no registered active ingredient is stated for it.",
                (u,), "schedule",
            ))
        if not ex.chemicals and not ex.unrecognised:
            with_strength = [u for u in ex.undisclosed if re.search(r"\d", u.text)]
            if with_strength:
                checks.append(Check(
                    Reason.INFORMATION_MISSING, "high",
                    "Claims an active strength but names no chemical; Rule 19 of the Insecticides Rules, 1971 "
                    "requires the label to state the active ingredient and its percentage.",
                    tuple(with_strength) + tuple(ex.pesticide_terms[:1]), "labelling_rule",
                ))
            elif ex.undisclosed:
                checks.append(Check(
                    Reason.INFORMATION_MISSING, "low" if title_only else "medium",
                    "Mentions an active ingredient but never names it; Rule 19 of the Insecticides Rules, 1971 "
                    "requires the label to state the active ingredient and its percentage.",
                    tuple(ex.undisclosed) + tuple(ex.pesticide_terms[:1]), "labelling_rule",
                ))
            else:
                checks.append(Check(
                    Reason.INFORMATION_MISSING, "low" if title_only else "medium",
                    "Sold as a pesticide product, but the title names no chemical (only the search-result title "
                    "was checked)." if title_only else
                    "Sold as a pesticide product but names no chemical anywhere in the listing text.",
                    tuple(ex.pesticide_terms[:2]), "labelling_rule",
                ))
        notes = [
            f"{self._restricted[c.key].name} is restricted in use: {self._restricted[c.key].note}"
            for c in ex.chemicals if c.key in self._restricted
        ]
        return finalize(checks, notes)

    def _check_claim(self, c: ChemicalClaim) -> Check:
        conf = "high" if c.match == "exact" else "medium"
        ev = (c.evidence,)
        k = c.key
        if k in self._banned:
            b = self._banned[k]
            partial = "only" in b.note.lower()   # e.g. Sodium Cyanide: banned for insecticidal purpose only
            return Check(Reason.BANNED_ITEM, "medium" if partial else conf,
                         f"{b.name} is on the list of pesticides banned for manufacture, import and use"
                         + (f" ({b.note})" if b.note else "") + ".", ev, "banned_refused_restricted")
        if k in self._export_only:
            b = self._export_only[k]
            return Check(Reason.BANNED_ITEM, conf, f"{b.name} is banned for use in India (manufacture for export only).",
                         ev, "banned_refused_restricted")
        if k in self._refused:
            return Check(Reason.NOT_IN_REGISTRY, conf, f"{self._refused[k].name} was refused registration in India.",
                         ev, "banned_refused_restricted")
        if k in self._withdrawn:
            return Check(Reason.NOT_IN_REGISTRY, conf, f"{self._withdrawn[k].name} is on the withdrawn list.",
                         ev, "banned_refused_restricted")
        if k not in self.reg.registered:
            fam = [f for f in self.family(k) if f in self.reg.registered]
            if not fam:
                return Check(Reason.NOT_IN_REGISTRY, "medium",
                             f"{c.official_name} is in the Schedule to the Insecticides Act but not registered for use.",
                             ev, "registered_molecules")
            conf = "medium"   # registered only in a specific salt or ester form the listing does not name
        return self._check_formulation(c, conf)

    def _registered_combination(self, claims: list[ChemicalClaim]) -> str | None:
        """The registered combination formulation containing every named chemical, if the listing names 2+."""
        if len(claims) < 2:
            return None
        families = [self.family(c.key) for c in claims]
        for f in self._combos:
            comps = set(f.components)
            if all(fam & comps for fam in families):
                return f.raw
        return None

    def _check_formulation(self, c: ChemicalClaim, conf: str) -> Check:
        fam = self.family(c.key)
        if c.key in self.reg.registered:
            name = self.reg.registered[c.key]
        else:
            forms_of = sorted({self.reg.registered[f] for f in fam if f in self.reg.registered})
            name = f"{c.official_name} (registered as {' / '.join(forms_of)})"
        if c.strength_pct is None:
            return Check(Reason.CLEAR, conf, f"{name} is registered; the listing states no strength to compare.",
                         (c.evidence,), "registered_molecules")
        forms = [sc for f in fam for sc in self._forms.get(f, [])]
        same = [
            (s, code) for s, code in forms
            if s is not None and abs(s - c.strength_pct) < 0.05
            and (c.form_code is None or code is None or code == c.form_code)   # an unstated code matches any
        ]
        if same:
            shown = f"{c.strength_pct:g}%" + (f" {c.form_code}" if c.form_code else "")
            return Check(Reason.CLEAR, conf, f"{name} {shown} matches a registered formulation.",
                         (c.evidence,), "registered_formulations")
        # Registered molecule, no single-chemical formulation at this strength/code. The formulation
        # PDF is irregular, so this is a low-confidence prompt for review, never a strong flag.
        shown = f"{c.strength_pct:g}%" + (f" {c.form_code}" if c.form_code else "")
        return Check(Reason.REGISTRY_MISMATCH, "low",
                     f"{name} is registered, but no registered single-chemical formulation matches {shown}.",
                     (c.evidence,), "registered_formulations")


def _strength_code(raw: str) -> tuple[float | None, str | None]:
    """Strength (%) and formulation code of a registered formulation string.

    "Glyphosate 41% SL" -> (41, "SL"); "Quinclorac 250 g/l SC" -> (25, "SC") as % w/v;
    "2,4-D Sodium Salt 80% min." -> (80, None).
    """
    m = re.search(
        rf"(\d+(?:\.\d+)?)\s*(%|g\s*/\s*l)\s*(?:w/w|w/v)?\s*(?:\([^)]*\)\s*)?(?:({FORM_CODES})\b)?", raw, re.IGNORECASE
    )
    if not m:
        return None, None
    value = float(m.group(1))
    pct = value / 10 if m.group(2).lower().startswith("g") else value
    return pct, (m.group(3) or "").upper() or None


