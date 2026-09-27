"""One marketplace listing, normalised from any SerpApi engine.

Each engine returns listings in its own shape; these readers turn them into `Listing`, keeping the
text fields that the extractors read (title, description, bullet points, specifications) and a
pointer to the cached search result the listing came from, so every finding can be traced back to
the exact SerpApi response.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

# Marketplaces shown by name. Any other store or seller is shown as OTHER_STORE: the public
# outputs (dashboard, exports, complaint drafts) never name individual sellers or small shops.
MARKETPLACES = {
    "amazon.in": "Amazon.in", "flipkart.com": "Flipkart", "jiomart.com": "JioMart",
    "meesho.com": "Meesho", "indiamart.com": "IndiaMART", "snapdeal.com": "Snapdeal",
    "shopclues.com": "Shopclues", "tatacliq.com": "Tata CLiQ", "myntra.com": "Myntra",
    "ebay.com": "eBay", "tradeindia.com": "TradeIndia",
}
OTHER_STORE = "another online store"


@dataclass
class Listing:
    id: str                       # stable: "amazon:<ASIN>", "shopping:<product_id>", "web:<url>"
    marketplace: str              # "Amazon.in", "Flipkart", ... or OTHER_STORE; never a seller's name
    title: str
    url: str
    engine: str                   # SerpApi engine it came from
    search_id: str                # params hash of the cached search result
    price: str = ""
    merchant: str = ""
    thumbnail: str = ""
    fields: dict[str, str] = field(default_factory=dict)   # extra text: description, about_item, specifications
    details_search_id: str = ""   # params hash of a product-details search, when one was fetched
    snippet: str = ""             # search-engine snippet, for display only
    lens_search_id: str = ""      # params hash of a Google Lens search on the listing's photo

    def text_fields(self) -> dict[str, str]:
        return {"title": self.title, **self.fields}


def display_site(name: str) -> str:
    """A marketplace's display name ("amazon.in", "Amazon.in" -> "Amazon.in"), else OTHER_STORE."""
    low = name.lower().strip().removeprefix("www.")
    for domain, pretty in MARKETPLACES.items():
        if low in (domain, pretty.lower()) or low.endswith("." + domain):
            return pretty
    return OTHER_STORE


def strip_seller(title: str, merchant: str) -> str:
    """Remove a small store's name that Google Shopping appends to a title ("... | Mobile Signal Guru").

    Marketplace names are public and kept; only a trailing store name after a separator is removed,
    so a brand at the start of a title (which may equal the store's name) stays.
    """
    if not merchant or display_site(merchant) != OTHER_STORE:
        return title
    return re.sub(rf"\s*[|\-–—:,]\s*(?:by\s+|from\s+)?{re.escape(merchant.strip())}\s*$", "", title, flags=re.IGNORECASE)


def marketplace_of(url: str, fallback: str = "") -> str:
    """Display name for where a URL points; a Google redirect falls back to the store name given."""
    host = urlparse(url).netloc.lower().removeprefix("www.").removeprefix("dl.")
    for domain, name in MARKETPLACES.items():
        if host == domain or host.endswith("." + domain):
            return name
    return display_site(fallback or host)


def from_google_shopping(data: dict[str, Any], search_id: str) -> list[Listing]:
    out = []
    results = list(data.get("shopping_results") or [])
    for section in data.get("categorized_shopping_results") or []:
        results.extend(section.get("shopping_results") or [])
    for r in results:
        token = str(r.get("immersive_product_page_token") or "")[:40]
        pid = str(r.get("product_id") or token or r.get("title", ""))
        link = str(r.get("product_link") or r.get("link") or "")
        merchant = str(r.get("source") or "")
        out.append(Listing(
            id=f"shopping:{pid}", marketplace=marketplace_of(link, merchant),
            title=str(r.get("title", "")), url=link, engine="google_shopping", search_id=search_id,
            price=str(r.get("price", "")), merchant=merchant, thumbnail=str(r.get("thumbnail", "")),
        ))
    return out


def from_amazon_search(data: dict[str, Any], search_id: str) -> list[Listing]:
    out = []
    for r in data.get("organic_results") or []:
        asin = str(r.get("asin", ""))
        if not asin:
            continue
        out.append(Listing(
            id=f"amazon:{asin}", marketplace="Amazon.in", title=str(r.get("title", "")),
            url=str(r.get("link_clean") or r.get("link") or f"https://www.amazon.in/dp/{asin}"),
            engine="amazon", search_id=search_id, price=str(r.get("price", "")), thumbnail=str(r.get("thumbnail", "")),
        ))
    return out


def from_google_web(data: dict[str, Any], search_id: str) -> list[Listing]:
    """`site:flipkart.com ...` style searches: only product pages count, with the snippet as extra text."""
    out = []
    for r in data.get("organic_results") or []:
        link = str(r.get("link", ""))
        if not re.search(r"/p/|/dp/|/prd?/|/product(?!-reviews)", link) or "review" in link:
            continue
        # dl.flipkart.com/dl/<path> is the same page as www.flipkart.com/<path>
        link = re.sub(r"^https?://dl\.flipkart\.com/dl/", "https://www.flipkart.com/", link)
        # Google's snippet can stitch in text from other products on the page, so only the title
        # is listing text; the snippet is kept for display, never read by the rules.
        out.append(Listing(
            id=f"web:{link.split('?')[0]}", marketplace=marketplace_of(link), title=str(r.get("title", "")),
            url=link, engine="google", search_id=search_id, snippet=str(r.get("snippet", "")),
        ))
    return out


def enrich_from_amazon_product(listing: Listing, data: dict[str, Any], search_id: str) -> None:
    """Add a product page's description, bullet points and specifications to the listing's text."""
    pr = data.get("product_results") or {}
    fields = {
        "description": str(pr.get("description") or ""),
        "about_item": " | ".join(str(x) for x in data.get("about_item") or []),
        "specifications": _flatten(data.get("item_specifications")),
        "product_details": _flatten(data.get("product_details"), skip={"best_sellers_rank", "customer_reviews"}),
    }
    listing.fields.update({k: v for k, v in fields.items() if v})
    listing.details_search_id = search_id


def _flatten(obj: Any, skip: set[str] | None = None) -> str:
    if not isinstance(obj, dict):
        return ""
    parts = []
    for k, v in obj.items():
        if skip and k in skip:
            continue
        parts.append(f"{k.replace('_', ' ')}: {v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)}")
    return " | ".join(parts)
