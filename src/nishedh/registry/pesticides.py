"""Load India's official pesticide lists (CIB&RC, Insecticides Act 1968) into one registry.

Sources are the PDFs published at https://ppqs.gov.in/divisions/cib-rc/registered-products,
downloaded unmodified into `data/registry/raw/` and described in `data/registry/sources.json`
(URL, "as on" date, SHA-256). Parsing is deterministic; the only hand-transcribed part is the
restricted-use list, whose PDF layout interleaves names and conditions across columns
(`data/registry/restricted_pesticides.json`, checked entry by entry against the PDF).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pdfplumber

from nishedh.registry.names import clean, key

REGISTRY_DIR = Path(__file__).resolve().parents[3] / "data" / "registry"

ITEM = re.compile(r"^(\d+)\.\s*(.+)$")


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    file: str
    as_on: str
    sha256: str


@dataclass(frozen=True)
class Listed:
    """One entry on a banned / withdrawn / refused / restricted list.

    `synonyms` are extra keys for the same chemical given in the entry itself:
    "Lindane (Gamma-HCH)" -> ("gammahch",), "Thiodemeton / Disulfoton" -> ("thiodemeton", "disulfoton").
    """
    name: str
    key: str
    note: str = ""
    synonyms: tuple[str, ...] = ()

    @property
    def keys(self) -> tuple[str, ...]:
        return (self.key, *self.synonyms)


@dataclass(frozen=True)
class Formulation:
    """One registered formulation, e.g. "Acephate 50%+ Imidacloprid 1.8% SP"."""
    serial: int
    raw: str
    category: str
    components: tuple[str, ...]  # molecule keys, in the order written


@dataclass
class PesticideRegistry:
    sources: list[Source]
    registered: dict[str, str]            # key -> official spelling (section 9(3) molecules)
    schedule: dict[str, str]              # key -> official spelling (Schedule to the Act)
    formulations: list[Formulation]
    banned: list[Listed]                  # banned for manufacture, import and use
    export_only: list[Listed]             # banned for use, manufacture for export allowed
    withdrawn: list[Listed]
    refused: list[Listed]
    restricted: list[Listed] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=1, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> PesticideRegistry:
        d = json.loads(text)
        return cls(
            sources=[Source(**s) for s in d["sources"]],
            registered=d["registered"],
            schedule=d["schedule"],
            formulations=[Formulation(**{**f, "components": tuple(f["components"])}) for f in d["formulations"]],
            banned=[_listed(x) for x in d["banned"]],
            export_only=[_listed(x) for x in d["export_only"]],
            withdrawn=[_listed(x) for x in d["withdrawn"]],
            refused=[_listed(x) for x in d["refused"]],
            restricted=[_listed(x) for x in d["restricted"]],
        )


def _listed(d: dict[str, object]) -> Listed:
    return Listed(**{**d, "synonyms": tuple(d.get("synonyms", ()))})  # type: ignore[arg-type]


def _table_rows(pdf_path: Path) -> list[list[str]]:
    rows: list[list[str]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    rows.append([clean(c or "") for c in row])
    return rows


_TEXT_ITEM = re.compile(r"^(\d{1,4})\.?\s+([A-Za-z0-9(].*)$")


def _serial_items(pdf_path: Path) -> dict[int, str]:
    """{serial: first-column text} for a numbered list, read from tables AND page text.

    pdfplumber's table reader silently drops a few rows (e.g. serial 36 "Beflubutamid" in the
    31.03.2026 molecule list), so page-text lines of the form "36. Name" / "36 Name" fill the
    gaps. Text lines only count when their serial is within the table's range, which rejects
    wrapped continuation lines such as "14245 IU/ml min.". The official lists also skip some
    serials outright (276 is followed by 278), so the count is not the last serial.
    """
    items: dict[int, str] = {}
    for row in _table_rows(pdf_path):
        if len(row) >= 2 and re.fullmatch(r"\d+\.?", row[0]) and row[1]:
            items.setdefault(int(row[0].rstrip(".")), row[1])
    if not items:
        return items
    top = max(items)
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for line in (page.extract_text() or "").splitlines():
                m = _TEXT_ITEM.match(clean(line))
                if m and int(m.group(1)) <= top and int(m.group(1)) not in items:
                    items[int(m.group(1))] = m.group(2)
    return items


# Words that make a bracketed phrase a description, not a synonym ("IPA Salt", "Neem Products").
_NOT_SYNONYM = (
    "salt", "product", "mixture", "isomer", "technical", "fungus", "vitamin", "oil", "acid", "ester", "cide",
    # descriptions in Schedule brackets: "(Bacteria)", "(non pathogenic)", "(for groundnut)",
    # "(tribasic)", "(Hairpin protein)"
    "bacteri", "virus", "protein", "pathogen", "groundnut", "tribasic",
)


def _is_synonym(text: str) -> bool:
    """A bracketed phrase counts as another name for the chemical only if it looks like one:
    one or two words, letters only, at least 6 letters, no descriptive word. "Decamethrin" and
    "Gamma-HCH" pass; "IPA Salt", "Neem Products", "fungus" and "1R isomer" do not.
    """
    k = key(text)
    words = clean(text).split()
    return (
        1 <= len(words) <= 2 and k.isalpha() and len(k) >= 6
        and not any(w in k for w in _NOT_SYNONYM)
    ) or (k.isalpha() and 3 <= len(k) <= 5 and text.strip().isupper())   # abbreviations: DDT, BHC, DBCP


def _index(names: list[str]) -> dict[str, str]:
    """{key: official name}, also keyed by the name without its bracket and by a bracketed synonym.

    "Deltamethrin (Decamethrin)" is reachable as "deltamethrin" and "decamethrin";
    "Azadirachtin (Neem Products)" only as "azadirachtin".
    """
    out: dict[str, str] = {}
    for name in names:
        out.setdefault(key(name), name)
        m = re.match(r"^(.*?)\s*\((.*?)\)", name)
        if m:
            if len(key(m.group(1))) >= 4:
                out.setdefault(key(m.group(1)), name)
            if _is_synonym(m.group(2)):
                out.setdefault(key(m.group(2)), name)
    return out


def parse_registered(pdf_path: Path) -> dict[str, str]:
    """Molecules registered under section 9(3): 371 entries as on 31.03.2026 (last serial 372)."""
    return _index(list(_serial_items(pdf_path).values()))


def parse_schedule(pdf_path: Path) -> dict[str, str]:
    """Common names in the Schedule to the Insecticides Act: 1,025 entries as on 31.07.2026 (last serial 1,027).

    Text-recovered Schedule lines carry the chemical name after the common name; only the table
    rows split the two columns, so text lines are indexed by their full text.
    """
    return _index(list(_serial_items(pdf_path).values()))


_PERCENT = re.compile(r"\d+(?:\.\d+)?\s*%|\d+(?:\.\d+)?\s*g\s*/\s*l", re.IGNORECASE)
_DIGIT = re.compile(r"\d")


def _component_name(part: str) -> str:
    """Molecule name from one component: the text before its strength.

    "Acephate 50%" -> "Acephate"; "2,4-D Amine Salt 58% SL" -> "2,4-D Amine Salt" (the name itself
    starts with digits, so the cut is at the percentage, not the first digit); "Pyraclostrobin
    133g/l" -> "Pyraclostrobin". A component with no strength ("Surfactant") keeps its whole text.
    """
    part = part.strip()
    m = _PERCENT.search(part)
    if m:
        name = part[: m.start()]
    else:
        d = _DIGIT.search(part)
        name = part[: d.start()] if d and d.start() > 0 else part
    # "Fiproni l5%": the PDF split "Fipronil 5%" as "Fiproni l5%"; drop a lone trailing letter.
    name = re.sub(r"\s+[A-Za-z]$", "", name.strip())
    return name.strip(" -,")


def _components(raw: str) -> tuple[str, ...]:
    parts = [p for p in raw.split("+") if p.strip()]
    return tuple(key(_component_name(p)) for p in parts if _component_name(p))


def parse_formulations(pdf_path: Path) -> list[Formulation]:
    """Registered formulations, each split into its molecule components.

    1,164 entries as on 31.03.2026 (last serial 1,177; the list skips some serials). The
    category of a row is the section heading above it (e.g. "B. HERBICIDES"); a row recovered
    from page text takes the category of the nearest lower serial.
    """
    # The PDF prints a few serials twice for different formulations (774, 904, 1093), so every
    # distinct (serial, text) row is kept.
    by_serial: dict[int, list[tuple[str, str]]] = {}
    category = ""
    for row in _table_rows(pdf_path):
        cells = [c for c in row if c]
        if not cells:
            continue
        heading = next((c for c in cells if re.fullmatch(r"[A-Z]\.\s.+", c)), None)
        if heading and not cells[0].rstrip(".").isdigit():
            category = _category(heading)
            continue
        if len(cells) >= 2 and cells[0].rstrip(".").isdigit():
            rows = by_serial.setdefault(int(cells[0].rstrip(".")), [])
            if all(raw != cells[-1] for raw, _ in rows):
                rows.append((cells[-1], category))
    for serial, text in _serial_items(pdf_path).items():
        if serial not in by_serial:
            lower = [s for s in by_serial if s < serial]
            by_serial[serial] = [(text, by_serial[max(lower)][0][1] if lower else "")]
    return [
        Formulation(serial=s, raw=raw, category=cat, components=_components(raw))
        for s, rows in sorted(by_serial.items()) for raw, cat in rows
    ]


def _category(heading: str) -> str:
    """"B. HERBICIDES" and "C. HERBICIDES" -> "HERBICIDES"; fixes the PDF's "GROTH" typo."""
    return re.sub(r"^[A-Z]\.\s*", "", heading).replace("GROTH", "GROWTH").strip()


_SECTIONS = (
    ("banned", re.compile(r"Pesticides Banned for manufacture, import and use", re.IGNORECASE)),
    ("export_only", re.compile(r"banned for use but continued to manufacture for", re.IGNORECASE)),
    ("withdrawn", re.compile(r"^Pesticides Withdrawn", re.IGNORECASE)),
    ("refused", re.compile(r"PESTICIDES REFUSED REGISTRATION", re.IGNORECASE)),
    ("end", re.compile(r"PESTICIDES RESTRICTED FOR USE", re.IGNORECASE)),
)


_NOTIFICATION = re.compile(r"S\.\s?O|G\.S\.R|dated|order|Petition|banned for|Supreme Court", re.IGNORECASE)


def _split_entry(text: str) -> tuple[str, tuple[str, ...], str]:
    """(name, synonym keys, note) from a banned-list entry.

    "Dibromochloropropane (DBCP) ( S.O. 569 (E) dated 25th July 1989)" -> name
    "Dibromochloropropane", synonyms ("dbcp",), note "S.O. 569 (E) dated 25th July 1989".
    "Thiodemeton / Disulfoton" -> name "Thiodemeton / Disulfoton", synonyms ("thiodemeton", "disulfoton").
    """
    text = text.rstrip("*").strip()
    groups: list[str] = []
    depth, start = 0, -1
    for i, ch in enumerate(text):          # top-level bracket groups, allowing "(E)" inside a note
        if ch == "(":
            if depth == 0:
                start = i
            depth += 1
        elif ch == ")" and depth:
            depth -= 1
            if depth == 0:
                groups.append(text[start + 1 : i].strip())
    first = text.find("(")
    name = (text[:first] if first > 0 else text).strip()
    notes = [g for g in groups if _NOTIFICATION.search(g)]
    synonyms = [key(g) for g in groups if not _NOTIFICATION.search(g) and _is_synonym(g)]
    if " / " in name:
        synonyms += [key(part) for part in name.split(" / ")]
    return name, tuple(dict.fromkeys(s for s in synonyms if s != key(name))), "; ".join(notes)


def parse_banned(pdf_path: Path) -> dict[str, list[Listed]]:
    """Banned, export-only, withdrawn and refused lists from the 'banned / refused / restricted' PDF."""
    with pdfplumber.open(pdf_path) as pdf:
        lines = [clean(line) for p in pdf.pages for line in (p.extract_text() or "").splitlines()]
    lists: dict[str, list[list[str]]] = {"banned": [], "export_only": [], "withdrawn": [], "refused": []}
    section: str | None = None
    for line in lines:
        if not line:
            continue
        hit = next((name for name, rx in _SECTIONS if rx.search(line)), None)
        if hit == "end":
            break
        if hit:
            section = hit
            continue
        if section is None or line.startswith("*") or re.fullmatch(r"[A-Z]\.", line):
            continue
        m = ITEM.match(line)
        if m:
            lists[section].append([m.group(2)])
        elif lists[section] and section != "refused":
            lists[section][-1].append(line)  # wrapped continuation of the previous entry
    result: dict[str, list[Listed]] = {}
    for name, items in lists.items():
        entries = []
        for parts in items:
            n, synonyms, note = _split_entry(" ".join(parts))
            entries.append(Listed(name=n, key=key(n), note=note, synonyms=synonyms))
        result[name] = entries
    return result


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(registry_dir: Path = REGISTRY_DIR) -> PesticideRegistry:
    """Parse every source PDF, verifying each file against its recorded SHA-256 first."""
    meta = json.loads((registry_dir / "sources.json").read_text())
    sources = [Source(**s) for s in meta["pesticides"]]
    by_name = {s.name: s for s in sources}
    for s in sources:
        actual = _sha256(registry_dir / "raw" / s.file)
        if actual != s.sha256:
            raise ValueError(f"{s.file}: SHA-256 {actual} does not match sources.json; re-check the download")
    raw = registry_dir / "raw"
    lists = parse_banned(raw / by_name["banned_refused_restricted"].file)
    restricted = [
        Listed(name=r["name"], key=key(r["name"]), note=r["restriction"])
        for r in json.loads((registry_dir / "restricted_pesticides.json").read_text())["entries"]
    ]
    return PesticideRegistry(
        sources=sources,
        registered=parse_registered(raw / by_name["registered_molecules"].file),
        schedule=parse_schedule(raw / by_name["schedule"].file),
        formulations=parse_formulations(raw / by_name["registered_formulations"].file),
        banned=lists["banned"],
        export_only=lists["export_only"],
        withdrawn=lists["withdrawn"],
        refused=lists["refused"],
        restricted=restricted,
    )


SNAPSHOT = REGISTRY_DIR / "pesticides.snapshot.json"


def load(registry_dir: Path = REGISTRY_DIR) -> PesticideRegistry:
    """The parsed registry, from a snapshot when it was built from exactly the current source files.

    The snapshot records the SHA-256 of every source PDF it was parsed from; if sources.json lists
    different files or hashes, the PDFs are parsed again and the snapshot rewritten.
    """
    snapshot = registry_dir / SNAPSHOT.name
    wanted = [Source(**s) for s in json.loads((registry_dir / "sources.json").read_text())["pesticides"]]
    if snapshot.exists():
        reg = PesticideRegistry.from_json(snapshot.read_text())
        if reg.sources == wanted:
            return reg
    reg = build(registry_dir)
    snapshot.write_text(reg.to_json())
    return reg
