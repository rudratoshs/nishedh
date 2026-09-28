"""One-off: move the 27 Sep 2026 pilot searches into the SerpApi cache and budget ledger.

The 8 pilot searches were run before the cache existed. Writing them under the exact parameters the
sweep uses means they are reused instead of paid for again, and the ledger counts them against the
monthly budget.
"""

import json
from pathlib import Path

from nishedh.search.client import params_hash

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache" / "serpapi"
SHOPPING = {"engine": "google_shopping", "gl": "in", "hl": "en", "google_domain": "google.co.in", "location": "India"}
AMAZON = {"engine": "amazon", "amazon_domain": "amazon.in"}
WEB = {"engine": "google", "gl": "in", "hl": "en", "google_domain": "google.co.in"}
PILOT = {
    "shop_herbicide": {**SHOPPING, "q": "weed killer herbicide"},
    "amz_herbicide": {**AMAZON, "k": "herbicide weed killer"},
    "g_flipkart_herbicide": {**WEB, "q": "site:flipkart.com herbicide weed killer"},
    "g_jiomart_herbicide": {**WEB, "q": "site:jiomart.com herbicide"},
    "shop_walkie": {**SHOPPING, "q": "walkie talkie"},
    "amz_walkie": {**AMAZON, "k": "walkie talkie"},
    "g_flipkart_walkie": {**WEB, "q": "site:flipkart.com walkie talkie"},
    "amz_product_B0HJW9JXXN": {"engine": "amazon_product", "asin": "B0HJW9JXXN", "amazon_domain": "amazon.in"},
}

ledger = []
for name, params in PILOT.items():
    data = json.loads((ROOT / "pilot" / f"{name}.json").read_text())
    fetched = data.get("search_metadata", {}).get("created_at", "2026-09-27 09:50:00 UTC")
    fetched_iso = fetched.replace(" UTC", "+00:00").replace(" ", "T")
    h = params_hash(params)
    path = CACHE / params["engine"] / f"{h}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"params": params, "fetched_at": fetched_iso, "data": data}, ensure_ascii=False))
    ledger.append(json.dumps({"t": fetched_iso, "engine": params["engine"], "id": h}))
    print("imported", name, "->", path.relative_to(ROOT))
# Merge into the ledger by id: never clobber real searches recorded since (re-running is then safe).
ledger_path = CACHE / "ledger.jsonl"
existing = {}
if ledger_path.exists():
    for line in ledger_path.read_text().splitlines():
        if line.strip():
            existing[json.loads(line)["id"]] = line
for line in ledger:
    existing[json.loads(line)["id"]] = line
ledger_path.write_text("\n".join(existing.values()) + "\n")
print("ledger:", len(ledger), "pilot searches;", len(existing), "total in ledger")
