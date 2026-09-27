"""Reduce a SerpApi response to the fields Nishedh reads, for anything shown outside the local store.

Raw responses hold far more than the listing readers use, including reviewers' names and
manufacturers' contact details. This allowlist keeps only what `nishedh.listing` and `nishedh.lens`
read, and replaces store and seller names with the marketplace display name, so small shops become
"another online store", exactly as the dashboard shows them. Used by the public demo snapshot
(`scripts/build_demo.py`) and the dashboard's raw-data view.
"""

from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import urlparse

from nishedh.listing import (
    MARKETPLACES,
    OTHER_STORE,
    display_site,
    marketplace_of,
    strip_seller,
)

ENGINES = ("google_shopping", "amazon", "google", "google_lens", "amazon_product")

SHOPPING = ("title", "product_id", "immersive_product_page_token", "product_link", "link", "price", "thumbnail")
AMAZON = ("asin", "title", "link_clean", "link", "price", "thumbnail")
WEB = ("link", "title", "snippet")
LENS = ("title", "link", "thumbnail")
PRODUCT_DETAILS_DROP = ("contact_information", "best_sellers_rank", "customer_reviews")


LINKS = ("link", "product_link", "link_clean")


def safe_link(url: str) -> str:
    """A small store's URL names the store, so it becomes a stable placeholder.

    Marketplace and Google links are kept. The placeholder keeps listings distinct (it hashes the
    URL) and still reads as "another online store" to `marketplace_of`.
    """
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    if not host or host.startswith("google.") or ".google." in host:
        return url
    # Marketplace product pages are kept; a seller's storefront inside a marketplace
    # ("indiamart.com/<company>/photos.html") names the seller.
    storefront = host == "indiamart.com" and not parsed.path.startswith(("/proddetail/", "/impcat/"))
    if marketplace_of(url) != OTHER_STORE and not storefront:
        return url
    return f"https://another-online-store.invalid/{hashlib.sha256(url.encode()).hexdigest()[:16]}"


def _pick(r: dict[str, Any], keep: tuple[str, ...]) -> dict[str, Any]:
    out = {k: r[k] for k in keep if k in r}
    for k in LINKS:
        if k in out:
            out[k] = safe_link(str(out[k]))
    if "title" in out and "source" in r:
        out["title"] = strip_seller(str(out["title"]), str(r["source"]))
    if "source" in r:
        out["source"] = display_site(str(r["source"]))
    return out


def sanitise(engine: str, data: dict[str, Any]) -> dict[str, Any]:
    if engine == "google_shopping":
        return {
            "shopping_results": [_pick(r, SHOPPING) for r in data.get("shopping_results") or []],
            "categorized_shopping_results": [
                {"shopping_results": [_pick(r, SHOPPING) for r in s.get("shopping_results") or []]}
                for s in data.get("categorized_shopping_results") or []
            ],
        }
    if engine == "amazon":
        return {"organic_results": [_pick(r, AMAZON) for r in data.get("organic_results") or []]}
    if engine == "google":
        # Only marketplace pages are read (`listing.from_google_web`); other results can name shops.
        keep = [r for r in data.get("organic_results") or []
                if marketplace_of(str(r.get("link", ""))) in MARKETPLACES.values()]
        return {"organic_results": [_pick(r, WEB) for r in keep]}
    if engine == "google_lens":
        return {"visual_matches": [_pick(r, LENS) for r in data.get("visual_matches") or []]}
    if engine == "amazon_product":
        pr = data.get("product_results") or {}
        details = {k: v for k, v in (data.get("product_details") or {}).items()
                   if not any(d in k for d in PRODUCT_DETAILS_DROP)}
        return {
            "product_results": {"description": pr.get("description", "")},
            "about_item": data.get("about_item") or [],
            "item_specifications": data.get("item_specifications") or {},
            "product_details": details,
        }
    raise ValueError(f"no demo allowlist for engine {engine!r}")
