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
from dataclasses import dataclass

from nishedh.extract.pesticide import FORM_CODES, ChemicalClaim, Extraction
from nishedh.registry.names import is_salt_suffix, key
from nishedh.registry.pesticides import PesticideRegistry, _component_name
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
        # component key -> [(strength %, formulation code, stated in g/l?)] from single-chemical formulations
        self._forms: dict[str, list[tuple[float | None, str | None, bool]]] = {}
        for f in reg.formulations:
            if len(f.components) == 1:
                pct, code = _strength_code(f.raw)
                self._forms.setdefault(f.components[0], []).append((pct, _code(code), _is_gl(f.raw)))
        # Registered combinations, parsed component by component (see _combo_variants).
        known = set(reg.registered) | set(self._forms)
        self._combos = [(f, comps, code, clean) for f in reg.formulations if len(f.components) >= 2
                        for comps, code, clean in _combo_variants(f.raw, known)]

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
        combo = self._combination_check(ex.chemicals)
        if combo is not None:
            # One check for the whole combination replaces the per-chemical formulation checks
            # (banned, refused and other serious checks stay).
            serious = [ch for ch in checks if ch.reason not in (Reason.CLEAR, Reason.REGISTRY_MISMATCH)]
            checks = serious + [combo]
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
                    "Claims an active strength but names no chemical: "
                    "the online listing does not show the active ingredient, which Rule 19 of the Insecticides Rules, 1971 "
                    "requires on the product label; check the physical label before concluding anything.",
                    tuple(with_strength) + tuple(ex.pesticide_terms[:1]), "labelling_rule",
                ))
            elif ex.undisclosed:
                checks.append(Check(
                    Reason.INFORMATION_MISSING, "low" if title_only else "medium",
                    "Mentions an active ingredient but never names it: "
                    "the online listing does not show the active ingredient, which Rule 19 of the Insecticides Rules, 1971 "
                    "requires on the product label; check the physical label before concluding anything.",
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

    def _combination_check(self, claims: list[ChemicalClaim]) -> Check | None:
        """Compare a listing naming 2+ chemicals with the registered combination formulations.

        A registered combination with exactly the listing's chemicals is compared component by
        component: each stated strength and the formulation code. The registry PDF is irregular
        (typos, strengths given twice, names glued to digits), so a registry value that cannot be
        read cleanly can confirm a match but never causes a mismatch. Returns None when no
        registered combination has these chemicals (each chemical is then judged on its own).
        """
        if len(claims) < 2:
            return None
        families = [self.family(c.key) for c in claims]
        evidence = tuple(c.evidence for c in claims)
        conf = "high" if all(c.match == "exact" for c in claims) else "medium"
        codes = {x for c in claims if (x := _code(c.form_code))}
        matched: str | None = None
        matched_conf = conf
        uncertain: str | None = None
        differ: list[str] = []
        for f, comps, code, clean in self._combos:
            order = _assign(families, [c.key for c in comps])
            if order is None:
                continue
            states = [_compare(c.strength_pct, comps[i]) for c, i in zip(claims, order, strict=True)]
            if code is not None and codes:
                states.append("match" if codes == {code} else "differ")
            if not clean:
                states = ["unknown" if st == "differ" else st for st in states]
            if "differ" in states:
                differ.append(f.raw)
            elif all(st == "match" for st in states) and all(c.strength_pct is not None for c in claims):
                if matched is None or (matched_conf == "medium" and clean and all(x.certain for x in comps)):
                    matched = f.raw
                    matched_conf = conf if clean and all(comps[i].certain for i in order) else "medium"
            else:
                uncertain = uncertain or f.raw
        if matched:
            return Check(Reason.CLEAR, matched_conf, f"Matches the registered combination formulation {matched}.",
                         evidence, "registered_formulations")
        if uncertain:
            return Check(Reason.CLEAR, "medium",
                         f"These chemicals are registered together as {uncertain}; not every strength could be "
                         "compared (unstated in the listing, or unclear in the registry).", evidence,
                         "registered_formulations")
        if not differ:
            return None
        shown = " + ".join(
            f"{c.official_name}" + (f" {c.strength_pct:g}%" if c.strength_pct is not None else "") for c in claims
        ) + "".join(f" {x}" for x in sorted(codes))
        return Check(Reason.REGISTRY_MISMATCH, "low",
                     f"{shown} does not match a registered combination. These chemicals are registered together "
                     f"only as: {'; '.join(dict.fromkeys(differ[:3]))}.", evidence, "registered_formulations")

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
        stated_code = _code(c.form_code)
        code_ok = [(s, gl) for s, code, gl in forms
                   if s is not None and (stated_code is None or code is None or code == stated_code)]
        shown = f"{c.strength_pct:g}%" + (f" {c.form_code}" if c.form_code else "")
        if any(abs(s - c.strength_pct) < 0.05 for s, _ in code_ok):
            return Check(Reason.CLEAR, conf, f"{name} {shown} matches a registered formulation.",
                         (c.evidence,), "registered_formulations")
        near = [s for s, gl in code_ok if gl and _density_ratio(s, c.strength_pct)]
        if near:
            return Check(Reason.CLEAR, "medium",
                         f"{name} is registered at {near[0] * 10:g} g/l; the listing's {shown} may be the same "
                         "product measured by weight, so the strengths could not be compared exactly.",
                         (c.evidence,), "registered_formulations")
        # Registered molecule, no single-chemical formulation at this strength/code. The formulation
        # PDF is irregular, so this is a low-confidence prompt for review, never a strong flag.
        return Check(Reason.REGISTRY_MISMATCH, "low",
                     f"{name} is registered, but no registered single-chemical formulation matches {shown}.",
                     (c.evidence,), "registered_formulations")


CODE_SYNONYMS = {"WDG": "WG", "DF": "WG"}   # water-dispersible granules are written three ways


def _code(code: str | None) -> str | None:
    return CODE_SYNONYMS.get(code.upper(), code.upper()) if code else None


def _is_gl(raw: str) -> bool:
    return re.search(r"\d\s*g\s*/\s*l", raw, re.IGNORECASE) is not None


def _density_ratio(registered_wv: float, stated: float) -> bool:
    """A % w/v (from g/l) and a % w/w of the same product differ by the liquid's density, 0.8-1.3."""
    return stated > 0 and 0.8 <= registered_wv / stated <= 1.3


@dataclass(frozen=True)
class _Comp:
    key: str
    values: tuple[float, ...]   # every strength the registry gives for it (w/w and w/v), in %
    gl: bool                    # stated in g/l
    certain: bool               # False: the registry text is garbled here; a difference is not a mismatch


def _compare(stated: float | None, comp: _Comp) -> str:
    """"match", "differ" or "unknown" for one listing strength against one registered component."""
    if stated is None or not comp.values:
        return "unknown"
    if any(abs(v - stated) < 0.05 for v in comp.values):
        return "match"
    if not comp.certain or (comp.gl and any(_density_ratio(v, stated) for v in comp.values)):
        return "unknown"
    return "differ"


def _assign(families: list[set[str]], components: list[str]) -> list[int] | None:
    """Pair each listing chemical (by its family of keys) with a distinct combination component.

    Returns, for each chemical, the index of its component; None unless the combination has
    exactly these chemicals.
    """
    if len(families) != len(components):
        return None
    order: list[int] = []
    for fam in families:
        i = next((j for j, k in enumerate(components) if k in fam and j not in order), None)
        if i is None:
            return None
        order.append(i)
    return order


def _resolve(k: str, known: set[str]) -> tuple[str | None, bool]:
    """The registry key a garbled combination component stands for, and whether it was clean.

    The PDF glues digits to names ("Imidacloprid1 9.81%" is 19.81%), truncates or misspells names
    ("Iprodion", "MEtribuzine"), prefixes trade codes ("CF-1020 (Fluopicolide") and splits esters
    ("Fluroxpyr + (Meptyl 20%)"). Returns (None, False) for a component that is not a chemical.
    """
    if k in known:
        return k, True
    if k.endswith("1") and k[:-1] in known:
        return k[:-1], False
    salt = [x for x in known if k.startswith(x) and len(x) >= 5 and is_salt_suffix(k[len(x):])]
    ester = [x for x in known if x.startswith(k) and len(k) >= 5 and is_salt_suffix(x[len(k):])]
    if ester and not salt:   # "Fluroxypyr" split from its ester "(Meptyl ...)": the registered form
        return min(ester, key=len), False
    if salt:
        return max(salt, key=len), True
    near = [x for x in known if len(k) >= 6 and (x.startswith(k) or k.startswith(x)) and abs(len(x) - len(k)) <= 2]
    if near:
        return min(near, key=lambda x: abs(len(x) - len(k))), True
    suffix = [x for x in known if len(x) >= 6 and k.endswith(x)]
    if suffix:
        return max(suffix, key=len), True
    return None, False


def _combo_variants(raw: str, known: set[str]) -> list[tuple[list[_Comp], str | None, bool]]:
    """Parse a registered combination into components with strengths, its code, and whether it is clean.

    "Acephate 25%+ Fenvalerate 3% EC" -> [acephate 25, fenvalerate 3], "EC". A row that gives the
    whole combination twice ("A 6.89% + B 11.49% SC (A 7.5% + B 12.5% SC)", w/w then w/v) yields
    both. A row with a component that is not a chemical, or a garbled strength, is not clean.
    """
    texts = [raw]
    m = re.search(r"\(([^)]*\+[^)]*)\)", raw)
    if m:
        texts = [raw[: m.start()] + raw[m.end():], m.group(1)]
    out = []
    for text in texts:
        comps: list[_Comp] = []
        clean = True
        parts = [p.strip() for p in text.split("+") if p.strip()]
        for part in parts:
            name = _component_name(part.strip("() "))
            if not name or not re.search(r"[A-Za-z]{3}", name):
                clean = False
                continue
            k, ok = _resolve(key(name), known)
            if k is None:
                clean = False
                continue
            if not ok and k + "1" == key(name):            # "Imidacloprid1 9.81%": the 1 is the strength's
                part = re.sub(r"1\s+(?=\d)", " 1", part, count=1)
            # "Ethoxysulfuron l0%": a letter typed for a digit (10 or 0?) is not guessed. "Fiproni l5%"
            # is Fipronil 5%: the letter ends the name, which is not a typo.
            lm = re.search(r"\s([lIO])(?=\d)", part)
            typo = lm is not None and key(part[: lm.start()] + lm.group(1)) != k
            values = tuple(float(v) / (10 if u.lower().startswith("g") else 1)
                           for v, u in re.findall(r"(\d+(?:\.\d+)?)\s*(%|g\s*/\s*l)", part, re.IGNORECASE))
            garbled_unit = re.search(r"(\d+(?:\.\d+)?)\s*%\s*g\s*/\s*l", part, re.IGNORECASE)
            if garbled_unit:   # "Pyraclostrobin 40% g/l": % or g/l? Both readings, neither certain.
                values = (*values, float(garbled_unit.group(1)) / 10)
                ok = False
            if not values and not typo:   # "Hexythiazox 3.5 + ...": a strength without "%"
                bare = re.match(r"\s*(\d+(?:\.\d+)?)\s*(?:w/w\s*%?)?\s*(?:[A-Z]{1,3})?\s*$", part[len(name):])
                values = (float(bare.group(1)),) if bare else ()
            comps.append(_Comp(k, () if typo else values, _is_gl(part), ok and not typo))
        code = None
        if parts:
            last = parts[-1]
            code = _strength_code(last)[1]
            if code is None:
                cm = re.search(rf"(?<![A-Za-z])({FORM_CODES})\s*\)?\s*$", last)
                code = cm.group(1) if cm else None
        if len(comps) >= 2:
            out.append((comps, _code(code), clean))
    return out


def _strength_code(raw: str) -> tuple[float | None, str | None]:
    """Strength (%) and formulation code of a registered formulation string.

    "Glyphosate 41% SL" -> (41, "SL"); "Quinclorac 250 g/l SC" -> (25, "SC") as % w/v;
    "2,4-D Sodium Salt 80% min." -> (80, None).
    """
    m = re.search(
        rf"(\d+(?:\.\d+)?)\s*(%|g\s*/\s*l)\s*(?:w/w|w/v)?\s*(?:\([^)]*\)\s*)?(?:({FORM_CODES})\b(?!\s*/))?", raw, re.IGNORECASE
    )
    if not m:
        return None, None
    value = float(m.group(1))
    pct = value / 10 if m.group(2).lower().startswith("g") else value
    return pct, (m.group(3) or "").upper() or None


