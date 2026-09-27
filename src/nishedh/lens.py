"""Label check: what are visually matching product photos called elsewhere?

A listing that names no chemical can still be identified: Google Lens (through SerpApi) finds the
visually matching pack photos on other sites (Lens "visual matches": similar, not
necessarily identical, images), where another seller may have named the chemical, or named the
product as one a regulator has already acted on. This module reads Lens "visual matches" and
reports, for review:

- the other names visually matching photos are sold under, and on which sites;
- chemicals those other listings name (checked against the registry like any listing text);
- hits on the watchlist of products named in regulator orders (e.g. Cyclosinone).

A matching photo is a lead, not proof: a finding that uses it is never above medium confidence.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nishedh.extract.pesticide import Found, PesticideExtractor
from nishedh.listing import OTHER_STORE, marketplace_of
from nishedh.registry.pesticides import REGISTRY_DIR

STRONG_HITS = 3    # matches naming the watchlist product
STRONG_RANK = 15   # the best of them within the top matches


@dataclass(frozen=True)
class WatchItem:
    name: str
    finding: str
    order: str
    source: str


@dataclass(frozen=True)
class Match:
    title: str
    site: str
    link: str


@dataclass
class LensEvidence:
    search_id: str
    matches: list[Match] = field(default_factory=list)
    watchlist_hits: list[tuple[WatchItem, Match]] = field(default_factory=list)
    chemicals_elsewhere: list[tuple[str, Match]] = field(default_factory=list)   # (official name, where)

    def hit_strength(self, item: WatchItem) -> tuple[int, int, bool]:
        """(number of matches naming `item`, rank of the first one from 1, strong?).

        Lens ranks matches by visual similarity. A hit is strong when at least STRONG_HITS matches
        name the product and one is among the top STRONG_RANK; a few low-ranked hits are a weak lead.
        """
        ranks = [i for i, m in enumerate(self.matches, 1) if any(w is item for w, x in self.watchlist_hits if x is m)]
        if not ranks:
            return 0, 0, False
        return len(ranks), ranks[0], len(ranks) >= STRONG_HITS and ranks[0] <= STRONG_RANK

    @property
    def sites(self) -> list[str]:
        return sorted({m.site for m in self.matches})

    @property
    def named_sites(self) -> list[str]:
        """Marketplaces the photo appears on (small stores are counted, not named)."""
        return sorted({m.site for m in self.matches if m.site != OTHER_STORE})


def load_watchlist(path: Path = REGISTRY_DIR / "watchlist.json") -> list[WatchItem]:
    return [WatchItem(**p) for p in json.loads(path.read_text())["products"]]


def read_lens(data: dict[str, Any], search_id: str, extractor: PesticideExtractor,
              watchlist: list[WatchItem]) -> LensEvidence:
    ev = LensEvidence(search_id=search_id)
    for v in data.get("visual_matches") or []:
        link = str(v.get("link", ""))
        m = Match(title=str(v.get("title", "")), site=marketplace_of(link, str(v.get("source", ""))), link=link)
        ev.matches.append(m)
        for item in watchlist:
            if re.search(rf"\b{re.escape(item.name)}\b", m.title, re.IGNORECASE):
                ev.watchlist_hits.append((item, m))
        for c in extractor.extract({"lens_match": m.title}).chemicals:
            if c.strength_pct is not None or c.match == "exact":
                ev.chemicals_elsewhere.append((c.official_name, m))
    return ev


def lens_found(ev: LensEvidence, limit: int = 3) -> tuple[Found, ...]:
    """The matches to show as evidence: watchlist hits first, then matches naming a chemical."""
    chosen = [m for _, m in ev.watchlist_hits] + [m for _, m in ev.chemicals_elsewhere]
    seen: set[str] = set()
    out = []
    for m in chosen:
        if m.link not in seen:
            seen.add(m.link)
            out.append(Found(f"visual match on {m.site}", m.title))
    return tuple(out[:limit])
