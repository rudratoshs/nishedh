"""Build the public demo snapshot in `demo/` from the local SerpApi cache.

The demo lets anyone replay the 27 Sep 2026 live run without an API key (`nishedh demo`). Raw
SerpApi responses hold far more than Nishedh reads, including reviewers' names and manufacturers'
contact details, so this keeps an allowlist: only the fields the listing readers use
(`nishedh.listing`, `nishedh.lens`). Store and seller names are replaced by the marketplace display
name, so small shops become "another online store", exactly as the dashboard shows them.

Run: uv run python scripts/build_demo.py   (then check `uv run pytest tests/test_demo.py`)
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from nishedh.listing import display_site, strip_seller

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / ".cache"
OUT = ROOT / "demo"

SHOPPING = ("title", "product_id", "immersive_product_page_token", "product_link", "link", "price", "thumbnail")
AMAZON = ("asin", "title", "link_clean", "link", "price", "thumbnail")
WEB = ("link", "title", "snippet")
LENS = ("title", "link", "thumbnail")
PRODUCT_DETAILS_DROP = ("contact_information", "best_sellers_rank", "customer_reviews")


def _pick(r: dict[str, Any], keep: tuple[str, ...]) -> dict[str, Any]:
    out = {k: r[k] for k in keep if k in r}
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
        return {"organic_results": [_pick(r, WEB) for r in data.get("organic_results") or []]}
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


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    n = 0
    for path in sorted((SRC / "serpapi").glob("*/*.json")):
        engine = path.parent.name
        stored = json.loads(path.read_text())
        target = OUT / "serpapi" / engine / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        clean = {"params": stored["params"], "fetched_at": stored["fetched_at"], "data": sanitise(engine, stored["data"])}
        target.write_text(json.dumps(clean, ensure_ascii=False, indent=1) + "\n")
        n += 1
    if (SRC / "eta").exists():
        shutil.copytree(SRC / "eta", OUT / "eta")
    print(f"wrote {n} sanitised SerpApi responses to {OUT.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
