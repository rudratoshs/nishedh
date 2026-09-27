"""Read a marketplace listing and extract what it says about pesticide chemicals.

Three questions, each answered with the exact words and the field they came from:
1. Is this a pesticide product at all? (herbicide, weed killer, kharpatwar nashak, ...)
2. Which chemicals does it name, at what strength and in which formulation?
3. Does it claim an active strength ("5% Active Formula") without naming any chemical?

Chemicals are recognised against a vocabulary built from the official registry, so a name is
only called a chemical if an official list knows it. Every match resolves to one canonical key
(the official name without its bracket), so "DDVP" and "Dichlorvos (DDVP)" are the same chemical
as banned "Dichlorvos". An unknown word followed by a strength and a formulation code
("Cyclosinone 20% SC") is reported separately as an unrecognised claim.

Precision rules, each pinned by a "must not flag" test:
- a listing is only a pesticide product if it uses a pesticide word, names a chemical together
  with a strength, or names a known pesticide trade name; a chemical word alone ("Copper",
  "Thymol", "Tunic") never makes a water bottle, mouthwash or shirt a pesticide;
- tools, sprayers, fabrics, nets, books and services that mention pesticides are not pesticides;
- the first word of a registered name is only an alias when the rest of the name is a salt or
  ester ("Glufosinate" for "Glufosinate Ammonium", not "Copper" for "Copper Hydroxide").
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from rapidfuzz import fuzz, process

from nishedh.registry.names import clean, is_salt_suffix, key
from nishedh.registry.pesticides import REGISTRY_DIR, PesticideRegistry

# Formulation codes used on Indian pesticide labels and in the CIB&RC list.
FORM_CODES = (
    "WDG|WSL|WSP|ULV|RTU|EC|SL|SC|WP|WG|SG|GR|CS|EW|OD|DF|SP|ZC|SE|FS|ME|DS|WS|CG|TB|RB|AS|ES|"
    "SS|DP|GB|CB|FG|PA|LV|MG|G"
)
# "41% SL", "41 % w/w", "41%,", "(41% SL)", "250 g/l SC". Group 1 = number, 2 = "%" or "g/l", 3 = code.
_STRENGTH_AFTER = re.compile(
    rf"^[\s:(\-]*(\d+(?:\.\d+)?)\s*(%|g\s*/\s*l(?:itre)?)\s*(?:w/w|w/v)?\s*(?:\([^)]*\)\s*)?(?:({FORM_CODES})\b)?",
    re.IGNORECASE,
)
# "Fipronil 80 WG", "Carbofuran 3G": Indian labels often drop the % before the formulation code.
_STRENGTH_CODE_ONLY = re.compile(rf"^[\s:(\-]*(\d+(?:\.\d+)?)\s*({FORM_CODES})\b", re.IGNORECASE)
_STRENGTH_BEFORE = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*(?:w/w|w/v)?\s*$", re.IGNORECASE)
_UNDISCLOSED_STRENGTH = re.compile(
    r"(\d+(?:\.\d+)?)\s*%\s*(?:active\s*(?:formula|ingredients?|content)?|a\.?\s?i\.?\b)", re.IGNORECASE
)
_UNDISCLOSED_PHRASE = re.compile(r"\bactive\s+ingredients?\b|\bspecial\s+formula\b|\bsecret\s+formula\b", re.IGNORECASE)
_UNKNOWN_CLAIM = re.compile(
    rf"\b([A-Z][a-z]{{4,}}(?:[\s-][A-Z]?[a-z]+){{0,2}})\s+(\d+(?:\.\d+)?)\s*%\s*(?:w/w|w/v)?\s*({FORM_CODES})\b"
)
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9,\-.']*")
_GLUED = re.compile(r"(?<=[A-Za-z]{3})(?=\d+(?:\.\d+)?\s*%)")   # "Glyphosate41%" -> "Glyphosate 41%"

# Phrases that mark a pesticide product, in English and common Hindi transliteration.
PESTICIDE_TERMS = re.compile(
    r"herbicid\w*|weedicide|weed\w*\s+(?:and|&)\s+root|weeds?\s+(?:killer|remov\w*|control|destroyer)|"
    r"(?:grass|root|bamboo|brush|termite)\s+(?:killer|remover)|kharpat[wv]ar|insecticid\w*|pesticid\w*|"
    r"keet\s?nashak|fungicid\w*|phaphund\s?nashak|rodenticid\w*|nematicid\w*|pest\s+control",
    re.IGNORECASE,
)
# Products that mention pesticides but are not pesticides themselves.
NOT_A_PESTICIDE = re.compile(
    r"\bsprayers?\b|\bnozzles?\b|\btools?\b|\bweeders?\b|\bfabric\b|\bmat\b|\bnets?\b|\bknife\b|\btrimmer\b|"
    r"\bservices?\b|-free\b|\bfree\s+from\b|\btreated\b|\bbooks?\b|\btext\s?book\b|\bby\s+dr\.?\b|"
    r"\bdrain\s+cleaner\b|\bwire\s+brush\b|\bchopper\b|\bgloves?\b|\bgoggles?\b|\bpump\b",
    re.IGNORECASE,
)
# Generic words around a product name; not part of a chemical name.
_GENERIC = r"(?:herbicide|insecticide|weedicide|fungicide|pesticide|weed|killer|systemic|selective|contact|premium|organic)"
_TRAILING_GENERIC = re.compile(rf"(?:\s+{_GENERIC})+$", re.IGNORECASE)
_LEADING_GENERIC = re.compile(rf"^(?:{_GENERIC}\s+)+", re.IGNORECASE)
_NOT_CHEMICAL = {"formula", "active", "concentrate", "solution", "strength", "pure", "organic", "natural", "power"}
# First words of registered names that are elements or organisms, never an active on their own.
_GENERIC_HEADS = {
    "hydrogen", "aluminum", "magnesium", "bacillus", "ethylene", "dichloro", "potassium", "calcium",
    "ammonium", "trichoderma", "pseudomonas", "beauveria", "metarhizium", "verticillium", "paecilomyces",
    "ampelomyces", "lecanicillium", "sulfuryl", "tribasic", "nuclear", "gibberellic", "copper", "sodium",
}


@dataclass(frozen=True)
class Found:
    """Text found in a listing, with the field it came from."""
    field: str
    text: str


@dataclass(frozen=True)
class ChemicalClaim:
    official_name: str          # spelling in the official list it matched
    key: str                    # canonical key: the official name without its bracket
    match: str                  # "exact" | "fuzzy" | "brand"
    score: float                # 100 for exact and brand
    strength_pct: float | None  # % (w/w or w/v); g/l is converted to % w/v
    form_code: str | None
    evidence: Found


@dataclass
class Extraction:
    pesticide_terms: list[Found] = field(default_factory=list)
    chemicals: list[ChemicalClaim] = field(default_factory=list)
    unrecognised: list[Found] = field(default_factory=list)   # "Cyclosinone 20% SC": a name on no list
    undisclosed: list[Found] = field(default_factory=list)    # "5% Active Formula", "active ingredient"
    excluded: list[Found] = field(default_factory=list)       # "sprayer", "tool": why terms were ignored

    @property
    def is_pesticide(self) -> bool:
        with_strength = any(c.strength_pct is not None or c.match == "brand" for c in self.chemicals)
        return bool(self.pesticide_terms or with_strength or self.unrecognised)


@dataclass(frozen=True)
class Term:
    official_name: str
    canonical: str


def _canonical(name: str) -> str:
    base = key(name.split("(")[0])
    return base if len(base) >= 3 else key(name)


def build_vocabulary(reg: PesticideRegistry) -> dict[str, Term]:
    """{key: (official name, canonical key)} for every name any official list knows."""
    vocab: dict[str, Term] = {}
    for mapping in (reg.registered, reg.schedule):
        for k, name in mapping.items():
            vocab.setdefault(k, Term(name, _canonical(name)))
    for listed in (*reg.banned, *reg.export_only, *reg.withdrawn, *reg.refused, *reg.restricted):
        for k in listed.keys:
            vocab[k] = Term(listed.name, listed.key)   # listed entries win: they carry the legal status
    # A seller may write only the first word of a registered salt or ester name ("Glufosinate" for
    # "Glufosinate Ammonium"). The head word is an alias only when the rest of the name is a salt
    # or ester and the head is a chemical stem, not an element or organism.
    for name in reg.registered.values():
        words = clean(name.split("(")[0]).split()
        if len(words) >= 2:
            head = key(words[0])
            rest = key(" ".join(words[1:]))
            if len(head) >= 7 and head.isalpha() and head not in _GENERIC_HEADS and is_salt_suffix(rest):
                vocab.setdefault(head, Term(name, _canonical(name)))
    short = {k for k in vocab if 3 <= len(k) < 4 and k.isalpha()}   # official abbreviations: DDT, EDB
    listed_keys = {k for x in (*reg.banned, *reg.export_only, *reg.withdrawn, *reg.refused, *reg.restricted) for k in x.keys}
    return {k: v for k, v in vocab.items() if _long_enough(k) or (k in short and k in listed_keys)}


def _long_enough(k: str) -> bool:
    """Keys of 4+ characters, or 3 when they mix digits and letters ("24d" for 2,4-D)."""
    return len(k) >= 4 or (len(k) == 3 and any(c.isdigit() for c in k) and any(c.isalpha() for c in k))


def load_brands(path: Path = REGISTRY_DIR / "brands.json") -> dict[str, str]:
    """{brand key: active ingredient name} from the curated trade-name table."""
    return {key(b): chem for b, chem in json.loads(path.read_text())["brands"].items()}


class PesticideExtractor:
    def __init__(self, reg: PesticideRegistry, fuzzy_threshold: float = 92.0, banned_fuzzy_threshold: float = 88.0) -> None:
        self.vocab = build_vocabulary(reg)
        self._keys = list(self.vocab)
        listed = (*reg.banned, *reg.export_only, *reg.withdrawn, *reg.refused)
        self._banned_keys = [k for x in listed for k in x.keys if len(k) >= 8]
        self.brands = {b: self.vocab.get(key(c), Term(c, key(c))) for b, c in load_brands().items()}
        self.fuzzy_threshold = fuzzy_threshold
        self.banned_fuzzy_threshold = banned_fuzzy_threshold

    def extract(self, fields: dict[str, str]) -> Extraction:
        """`fields` maps a field name ("title", "description", "about_item", ...) to its text."""
        out = Extraction()
        terms: list[Found] = []
        for name, raw in fields.items():
            text = _GLUED.sub(" ", clean(raw or ""))
            if not text:
                continue
            terms.extend(Found(name, m.group(0)) for m in PESTICIDE_TERMS.finditer(text))
            if name == "title":
                out.excluded.extend(Found(name, m.group(0)) for m in NOT_A_PESTICIDE.finditer(text))
            claims, spans = self._chemicals(name, text)
            out.chemicals.extend(claims)
            for m in _UNKNOWN_CLAIM.finditer(text):
                word = _LEADING_GENERIC.sub("", _TRAILING_GENERIC.sub("", m.group(1))).strip()
                overlaps = any(m.start() < e and s < m.end() for s, e in spans)
                if (not overlaps and word and key(word) not in self.vocab and key(word) not in self.brands
                        and word.lower() not in _NOT_CHEMICAL):
                    out.unrecognised.append(Found(name, f"{word} {m.group(2)}% {m.group(3)}"))
            out.undisclosed.extend(Found(name, m.group(0).strip()) for m in _UNDISCLOSED_STRENGTH.finditer(text))
            out.undisclosed.extend(Found(name, m.group(0).strip()) for m in _UNDISCLOSED_PHRASE.finditer(text))
        # A sprayer, weeder, net or book that mentions herbicides is not itself a pesticide.
        out.pesticide_terms = [] if out.excluded else terms
        out.chemicals = _dedupe(out.chemicals)
        return out

    def _chemicals(self, field_name: str, text: str) -> tuple[list[ChemicalClaim], list[tuple[int, int]]]:
        """Chemical claims in one field, and the character spans (name plus its strength) they cover.

        Exact and trade-name matches are found everywhere first; fuzzy matching then runs only on
        the tokens left over, so "W/W Atrazine" never swallows an exact "Atrazine".
        """
        tokens = [(m.start(), m.end(), m.group(0)) for m in _TOKEN.finditer(text)]
        used = [False] * len(tokens)
        hits: list[tuple[int, int, Term, str, float]] = []
        for exact in (True, False):
            i = 0
            while i < len(tokens):
                if used[i]:
                    i += 1
                    continue
                hit = self._exact_match(tokens, i) if exact else self._fuzzy_match(tokens, i, used)
                if hit is None:
                    i += 1
                    continue
                n, term, match, score = hit
                hits.append((i, n, term, match, score))
                for j in range(i, i + n):
                    used[j] = True
                i += n
        claims: list[ChemicalClaim] = []
        spans: list[tuple[int, int]] = []
        for i, n, term, match, score in sorted(hits, key=lambda h: h[0]):
            start, end = tokens[i][0], tokens[i + n - 1][1]
            pct, code, span = _strength(text, start, end)
            spans.append(span)
            claims.append(ChemicalClaim(
                official_name=term.official_name, key=term.canonical, match=match, score=score,
                strength_pct=pct, form_code=code.upper() if code else None,
                evidence=Found(field_name, text[start:end]),
            ))
        return claims, spans

    def _exact_match(self, tokens: list[tuple[int, int, str]], i: int) -> tuple[int, Term, str, float] | None:
        for n in range(min(6, len(tokens) - i), 0, -1):
            k = key(" ".join(t[2] for t in tokens[i : i + n]))
            if k in self.vocab and (_long_enough(k) or len(k) == 3):
                return n, self.vocab[k], "exact", 100.0
        first = key(tokens[i][2])
        if first in self.brands:
            return 1, self.brands[first], "brand", 100.0
        return None

    def _fuzzy_match(self, tokens: list[tuple[int, int, str]], i: int, used: list[bool]) -> tuple[int, Term, str, float] | None:
        if not tokens[i][2][:1].isalpha():
            return None   # fuzzy phrases never start on a number ("50 Cypermethrin")
        for n in range(1, min(3, len(tokens) - i) + 1):
            if any(used[i : i + n]):
                break
            k = key(" ".join(t[2] for t in tokens[i : i + n]))
            if len(k) < 8 or not k.isalpha():
                continue
            best = process.extractOne(k, self._keys, scorer=fuzz.ratio, score_cutoff=self.fuzzy_threshold)
            if best:
                return n, self.vocab[best[0]], "fuzzy", float(best[1])
            banned = process.extractOne(k, self._banned_keys, scorer=fuzz.ratio, score_cutoff=self.banned_fuzzy_threshold)
            if banned:
                return n, self.vocab[banned[0]], "fuzzy", float(banned[1])
        return None


def _strength(text: str, start: int, end: int) -> tuple[float | None, str | None, tuple[int, int]]:
    """Strength (%), formulation code, and the exact span of name plus strength.

    "Glyphosate 41% SL" -> (41, SL); "Quinclorac 250 g/l SC" -> (25, SC) as % w/v;
    "18.92% Quinclorac" -> (18.92, None); "Fipronil 80 WG" -> (80, None).
    """
    after = _STRENGTH_AFTER.match(text[end : end + 40])
    if after:
        value = float(after.group(1))
        pct = value / 10 if after.group(2).lower().startswith("g") else value
        return pct, after.group(3), (start, end + after.end())
    code_only = _STRENGTH_CODE_ONLY.match(text[end : end + 20])
    if code_only and 0 < float(code_only.group(1)) <= 100:   # "500 G" is grams, not a strength
        # The code is not kept: without the % the label style is loose ("3G" for a registered 3% CG),
        # so only the strength is compared.
        return float(code_only.group(1)), None, (start, end + code_only.end())
    window = max(0, start - 16)
    before = _STRENGTH_BEFORE.search(text[window:start])
    if before:
        return float(before.group(1)), None, (window + before.start(), end)
    return None, None, (start, end)


def _dedupe(claims: list[ChemicalClaim]) -> list[ChemicalClaim]:
    """One claim per chemical, preferring the one with a strength, then an exact match."""
    best: dict[str, ChemicalClaim] = {}
    for c in claims:
        cur = best.get(c.key)
        rank = (c.strength_pct is not None, c.match == "exact", c.score)
        if cur is None or rank > (cur.strength_pct is not None, cur.match == "exact", cur.score):
            best[c.key] = c
    return list(best.values())
