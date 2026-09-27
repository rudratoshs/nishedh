"""Name normalisation for pesticide molecules.

Official lists and marketplace listings spell the same chemical differently ("2,4-D Amine salt",
"Alphacypermethrin10.00%", "Thiomethoxam" vs "Thiamethoxam"). Everything is compared through
`key()`, which maps to the ISO common-name spelling: misspellings found in the official CIB&RC
PDFs (in the registered list itself, in the formulations list, and in the banned list) are listed
in `ALIASES`, each against the standard name that marketplaces and labels use.
"""

import re
import unicodedata

# Official-PDF spelling (key form) -> ISO common name (key form). Where the registered list and the
# formulations list disagree, both map to the standard spelling, so the two lists agree with each
# other and with marketplace text. Generated from a diff of the three lists, then checked by hand.
ALIASES: dict[str, str] = {
    # misspelt in the registered-molecules list (31.03.2026)
    "thiomethoxam": "thiamethoxam",
    "profenophos": "profenofos",
    "propergite": "propargite",
    "primiphosmethyl": "pirimiphosmethyl",
    "chlorfenopyr": "chlorfenapyr",
    "anilophos": "anilofos",
    "dinotefuron": "dinotefuran",
    "ipflufenoqin": "ipflufenoquin",
    "fluoxametamide": "fluxametamide",
    "ethofenprox": "etofenprox",
    "sodiumparanitrophinolate": "sodiumparanitrophenolate",
    "nuclearpolyhyderosisvirusofhelicoverpaarmigera": "nuclearpolyhedrosisvirusofhelicoverpaarmigera",
    "nuclearpolyhyderosisvirusofspodopteralitura": "nuclearpolyhedrosisvirusofspodopteralitura",
    "pyroxasulfon": "pyroxasulfone",
    "pymetrozin": "pymetrozine",
    "buprimate": "bupirimate",
    "cyzofamide": "cyazofamid",
    "oxathiapipron": "oxathiapiprolin",
    "bacillussubtillus": "bacillussubtilis",
    # misspelt in the formulations list
    "allerthrin": "allethrin",
    "azoxytrobin": "azoxystrobin",
    "bacilliussubtilis": "bacillussubtilis",
    "buprofenzin": "buprofezin",
    "chlorantraniliporle": "chlorantraniliprole",
    "chlorantraniliprorle": "chlorantraniliprole",
    "chloropyriphos": "chlorpyrifos",
    "chlorpyriphos": "chlorpyrifos",
    "didinotefuran": "dinotefuran",
    "difenconazole": "difenoconazole",
    "ethofenoprox": "etofenprox",
    "fiproni": "fipronil",
    "fluazandolizine": "fluazaindolizine",
    "fluroxpyr": "fluroxypyr",
    "hexaconzole": "hexaconazole",
    "hydrogencynamide": "hydrogencyanamide",
    "imiprothroin": "imiprothrin",
    "nitepyram": "nitenpyram",
    "paclobutarzole": "paclobutrazol",
    "penoxasulam": "penoxsulam",
    "pseudomonasflourescens": "pseudomonasfluorescens",
    "pyrazusulfuronethyl": "pyrazosulfuronethyl",
    "pyrifluinazon": "pyrifluquinazon",
    "pyrirpoxyfen": "pyriproxyfen",
    "pyroclostrobin": "pyraclostrobin",
    "spinoteram": "spinetoram",
    "thiafluzamide": "thifluzamide",
    "tranfluthrin": "transfluthrin",
    "trichodermaressei": "trichodermareesei",
    "trifloxysrobin": "trifloxystrobin",
    # misspelt in the banned / refused list
    "endosulfron": "endosulfan",
    "dichlorovos": "dichlorvos",
    "nicotinsulfate": "nicotinesulfate",
    "dicohlrodiphenyltrichloroethane": "dichlorodiphenyltrichloroethane",
    # the same chemical under two official names: Schedule entry 10 "BHC" (benzene hexachloride)
    # and banned-list entry 4 "Benzene Hexachloride"
    "bhc": "benzenehexachloride",
    # near-duplicate spellings inside the official lists
    "ipovalicarb": "iprovalicarb",
    "mefentrifluaconazole": "mefentrifluconazole",
    "verticiliumlecanii": "verticilliumlecanii",
}

# Words that name a salt, ester or form of an active ingredient rather than a different chemical.
# "Glufosinate Ammonium" and "2,4-D Amine salt" are forms of glufosinate and 2,4-D; "Copper
# Hydroxide", "Sulfuryl fluoride" and "Methyl Bromide" are not forms of copper, sulfur or methyl.
SALT_WORDS = (
    "isopropylammonium", "isopropylamine", "dimethylammonium", "dimethylamine", "hydrochloride",
    "potassium", "ammonium", "trimesium", "dichloride", "propargyl", "isopropyl", "benzoate",
    "butotyl", "dimethyl", "sodium", "calcium", "chloride", "bromide", "sulfate", "esters", "ester",
    "methyl", "ethyl", "butyl", "propyl", "meptyl", "mexyl", "amine", "salts", "salt", "ipa",
    "acid", "technical", "tech", "min",
)


def is_salt_suffix(rest: str) -> bool:
    """True when `rest` (a key fragment) is made only of salt/ester words: "ammonium", "aminesalt",
    "isopropylaminesalt". Empty is not a suffix."""
    if not rest:
        return False
    i = 0
    while i < len(rest):
        word = next((w for w in SALT_WORDS if rest.startswith(w, i)), None)
        if word is None:
            return False
        i += len(word)
    return True

# Spelling variants applied inside every key (British/Indian vs ISO spelling).
_VARIANTS = (("sulph", "sulf"), ("aluminium", "aluminum"))


def clean(text: str) -> str:
    """Unicode-normalise, unify dashes and collapse whitespace; keeps the words readable."""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[‐-―−]", "-", text)
    return re.sub(r"\s+", " ", text).strip()


_PREFIX_ALIASES = sorted(((a, b) for a, b in ALIASES.items() if len(a) >= 8), key=lambda ab: -len(ab[0]))


def key(name: str) -> str:
    """Comparison key: lowercase letters and digits only, standard spelling, known misspellings fixed.

    A misspelling is also fixed at the start of a longer name, so "Chlorpyriphos methyl" becomes
    "chlorpyrifosmethyl" (only for misspellings of 8+ characters, which cannot be a fragment of
    another name).
    """
    k = re.sub(r"[^a-z0-9]+", "", clean(name).lower())
    for a, b in _VARIANTS:
        k = k.replace(a, b)
    if k in ALIASES:
        return ALIASES[k]
    for a, b in _PREFIX_ALIASES:
        # "pymetrozin" -> "pymetrozine": a correctly spelled name that starts with the misspelling
        # is left alone.
        if k.startswith(a) and not k.startswith(b):
            return b + k[len(a):]
    return k
