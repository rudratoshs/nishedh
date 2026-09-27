"""A sweep: search the marketplaces for one product category, assess every listing, store the findings.

The query list per pack is fixed and versioned here, so a sweep is reproducible: rerunning it
offline replays the exact cached SerpApi responses. Live searches are spent in this order:
category searches first, then Amazon product pages for listings that were not cleared from their
title alone, up to `max_live` live searches in total.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from nishedh.extract.pesticide import PesticideExtractor
from nishedh.extract.radio import extract_radio
from nishedh.lens import lens_found, load_watchlist, read_lens
from nishedh.listing import (
    Listing,
    enrich_from_amazon_product,
    from_amazon_search,
    from_google_shopping,
    from_google_web,
)
from nishedh.registry.eta import EtaRegistry, EtaUnavailable
from nishedh.registry.pesticides import PesticideRegistry
from nishedh.search.client import (
    BudgetExceeded,
    CacheMiss,
    SearchClient,
    SearchError,
    params_hash,
)
from nishedh.store import Store
from nishedh.verdict.base import Check, Finding, Reason, with_extra
from nishedh.verdict.pesticide import PesticideRules
from nishedh.verdict.radio import assess_radio

SHOPPING = {"engine": "google_shopping", "gl": "in", "hl": "en", "google_domain": "google.co.in", "location": "India"}
AMAZON = {"engine": "amazon", "amazon_domain": "amazon.in"}
WEB = {"engine": "google", "gl": "in", "hl": "en", "google_domain": "google.co.in"}

QUERIES: dict[str, list[dict[str, str]]] = {
    "pesticides": [
        {**SHOPPING, "q": "weed killer herbicide"},
        {**AMAZON, "k": "herbicide weed killer"},
        {**AMAZON, "k": "weed and root remover"},
        {**AMAZON, "k": "insecticide for plants"},
        {**SHOPPING, "q": "kharpatwar nashak dawa"},
        {**WEB, "q": "site:flipkart.com herbicide weed killer"},
        {**WEB, "q": "site:jiomart.com herbicide"},
    ],
    "radio": [
        {**SHOPPING, "q": "walkie talkie"},
        {**AMAZON, "k": "walkie talkie"},
        {**AMAZON, "k": "walkie talkie long range"},
        {**SHOPPING, "q": "mobile signal booster"},
        {**AMAZON, "k": "mobile network signal booster"},
        {**WEB, "q": "site:flipkart.com walkie talkie"},
    ],
}
READERS: dict[str, Callable[..., list[Listing]]] = {
    "google_shopping": from_google_shopping, "amazon": from_amazon_search, "google": from_google_web,
}


@dataclass
class SweepResult:
    run_id: int
    listings: int = 0
    judged: int = 0
    live: int = 0
    cached: int = 0
    skipped_searches: list[str] = field(default_factory=list)
    by_reason: dict[str, int] = field(default_factory=dict)


class Sweeper:
    def __init__(self, client: SearchClient, store: Store, pesticides: PesticideRegistry,
                 eta: EtaRegistry | None = None) -> None:
        self.client = client
        self.store = store
        self.pesticides = pesticides
        self.extractor = PesticideExtractor(pesticides)
        self.rules = PesticideRules(pesticides)
        self.eta = eta
        self.watchlist = load_watchlist()
        self._offline = SearchClient(None, client.cache_dir, offline=True)

    def assess(self, pack: str, listing: Listing) -> Finding | None:
        """Judge one listing. Only the title was seen unless a product page was fetched."""
        title_only = not listing.fields
        if pack == "pesticides":
            return self.rules.assess(self.extractor.extract(listing.text_fields()), title_only=title_only)
        ex = extract_radio(listing.text_fields())
        certs = {}
        if self.eta is not None:
            for number in ex.eta_numbers:
                try:
                    cert = self.eta.lookup(number)
                except EtaUnavailable:
                    cert = None   # recorded as "certificate not checked"; never a verdict on its own
                if cert is not None:
                    certs[number] = cert
        return assess_radio(ex, certs, " ".join(listing.text_fields().values()), title_only=title_only)

    def _search(self, params: dict[str, str], result: SweepResult, max_live: int) -> dict | None:  # type: ignore[type-arg]
        try:
            if result.live >= max_live:
                r = self._offline.search(**params)
            else:
                r = self.client.search(**params)
        except (CacheMiss, BudgetExceeded, SearchError) as e:
            result.skipped_searches.append(f"{params.get('q') or params.get('k') or params.get('asin')}: {e}")
            return None
        if r.cached:
            result.cached += 1
        else:
            result.live += 1
        return r.data

    def label_check(self, listing: Listing, finding: Finding, result: SweepResult, max_live: int) -> Finding:
        """Google Lens on the listing's photo: what is the same product called elsewhere?"""
        params = {"engine": "google_lens", "url": listing.thumbnail, "country": "in", "hl": "en"}
        data = self._search(params, result, max_live)
        if data is None:
            return finding
        listing.lens_search_id = params_hash(params)
        ev = read_lens(data, listing.lens_search_id, self.extractor, self.watchlist)
        checks: list[Check] = []
        notes: list[str] = []
        for item, match in ev.watchlist_hits[:1]:
            checks.append(Check(
                Reason.NOT_IN_REGISTRY, "medium",
                f'The same product photo is sold on {match.site} as "{match.title}". {item.name} is named in the '
                f"{item.order}: {item.finding}. A matching photo is a lead for review, not proof.",
                lens_found(ev), item.source,
            ))
        if ev.chemicals_elsewhere and not ev.watchlist_hits:
            name, match = ev.chemicals_elsewhere[0]
            notes.append(f'The same photo is sold on {match.site} as "{match.title}", which names {name}; '
                         "this listing itself does not name it.")
        others = [site for site in ev.named_sites if site != listing.marketplace]
        small = len({m.link for m in ev.matches if m.site not in ev.named_sites})
        if others or small:
            where = ", ".join(others) + (f" and {small} other online stores" if small else "")
            notes.append(f"The same product photo also appears on {where.removeprefix(', ')}.")
        return with_extra(finding, checks, notes) if checks or notes else finding

    def run(self, pack: str, max_live: int = 40, max_details: int = 20, max_lens: int = 10) -> SweepResult:
        if pack not in QUERIES:
            raise ValueError(f"unknown pack {pack!r}; choose from {sorted(QUERIES)}")
        registry = ",".join(f"{s.name}@{s.as_on}" for s in self.pesticides.sources) if pack == "pesticides" else "ccpa_radio_2025"
        result = SweepResult(run_id=self.store.start_run(pack, registry))
        listings: dict[str, Listing] = {}
        for params in QUERIES[pack]:
            data = self._search(params, result, max_live)
            if data is None:
                continue
            for listing in READERS[params["engine"]](data, params_hash(params)):
                listings.setdefault(listing.id, listing)
        findings = {lid: self.assess(pack, lst) for lid, lst in listings.items()}
        # Product pages for Amazon listings not cleared from the title alone, most serious first.
        order = [Reason.BANNED_ITEM, Reason.NOT_IN_REGISTRY, Reason.INFORMATION_MISSING, Reason.REGISTRY_MISMATCH]
        candidates = sorted(
            (lid for lid, f in findings.items() if f is not None and f.reason is not Reason.CLEAR and lid.startswith("amazon:")),
            key=lambda lid: order.index(findings[lid].reason),  # type: ignore[union-attr]
        )[:max_details]
        for lid in candidates:
            asin = lid.split(":", 1)[1]
            params = {"engine": "amazon_product", "asin": asin, "amazon_domain": "amazon.in"}
            data = self._search(params, result, max_live)
            if data is not None:
                enrich_from_amazon_product(listings[lid], data, params_hash(params))
                findings[lid] = self.assess(pack, listings[lid])
        # Label check: Lens on the photos of pesticide listings that name no chemical, most serious first.
        if pack == "pesticides":
            nameless = [lid for lid, f in findings.items()
                        if f is not None and f.reason is Reason.INFORMATION_MISSING and listings[lid].thumbnail]
            nameless.sort(key=lambda lid: {"high": 0, "medium": 1, "low": 2}[findings[lid].confidence])  # type: ignore[union-attr]
            for lid in nameless[:max_lens]:
                findings[lid] = self.label_check(listings[lid], findings[lid], result, max_live)  # type: ignore[arg-type]
        for lid, listing in listings.items():
            f = findings[lid]
            self.store.add(result.run_id, pack, listing, f)
            if f is not None:
                result.judged += 1
                result.by_reason[f.reason.value] = result.by_reason.get(f.reason.value, 0) + 1
        result.listings = len(listings)
        self.store.finish_run(result.run_id, result.live, result.cached)
        return result
