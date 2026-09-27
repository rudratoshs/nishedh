"""Listing readers, sweep and report on cached-shape SerpApi data; no network."""

import json

import pytest

from nishedh.listing import OTHER_STORE, from_google_shopping, from_google_web
from nishedh.registry.pesticides import load
from nishedh.search.client import SearchClient, params_hash
from nishedh.store import Store
from nishedh.sweep import AMAZON, QUERIES, Sweeper


def test_google_shopping_never_exposes_small_store_names():
    data = {"shopping_results": [
        {"title": "Weed killer", "source": "Tiny Agro Shop", "product_link": "https://www.google.co.in/search?x", "product_id": "1"},
        {"title": "Weed killer", "source": "amazon.in", "product_link": "https://www.google.co.in/search?y", "product_id": "2"},
        {"title": "Weed killer", "source": "Flipkart", "immersive_product_page_token": None, "product_id": None},
    ]}
    listings = from_google_shopping(data, "h")
    assert [x.marketplace for x in listings] == [OTHER_STORE, "Amazon.in", "Flipkart"]
    assert listings[0].merchant == "Tiny Agro Shop"            # kept privately, for the evidence store only


def test_google_web_skips_review_pages_and_merges_flipkart_links():
    data = {"organic_results": [
        {"title": "A", "link": "https://www.flipkart.com/x/product-reviews/itm1"},
        {"title": "B", "link": "https://dl.flipkart.com/dl/y/p/itm2"},
        {"title": "C", "link": "https://www.flipkart.com/y/p/itm2"},
    ]}
    listings = from_google_web(data, "h")
    assert [x.title for x in listings] == ["B", "C"] and listings[0].id == listings[1].id


@pytest.fixture()
def cache(tmp_path):
    """A cache holding one Amazon search, as the sweep would have stored it."""
    params = {**AMAZON, "k": "herbicide weed killer"}
    data = {"organic_results": [
        {"asin": "B0TEST0001", "title": "Herbicide Plus Bamboo Killer – 5% Active Formula", "link": "https://www.amazon.in/dp/B0TEST0001"},
        {"asin": "B0TEST0002", "title": "Bayer Roundup Herbicide – Glyphosate 41% SL", "link": "https://www.amazon.in/dp/B0TEST0002"},
        {"asin": "B0TEST0003", "title": "Garden Hose 20m", "link": "https://www.amazon.in/dp/B0TEST0003"},
    ]}
    path = tmp_path / "serpapi" / "amazon" / f"{params_hash(params)}.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"params": params, "fetched_at": "2026-09-27T00:00:00+00:00", "data": data}))
    return tmp_path


def test_offline_sweep_judges_cached_listings(cache, monkeypatch):
    monkeypatch.setitem(QUERIES, "pesticides", [{**AMAZON, "k": "herbicide weed killer"}])
    client = SearchClient(None, cache / "serpapi", offline=True)
    store = Store(cache / "nishedh.sqlite")
    r = Sweeper(client, store, load()).run("pesticides", max_live=0, max_details=0, max_lens=0)
    assert r.listings == 3 and r.judged == 2 and r.live == 0 and r.cached == 1
    by_id = {f["listing_id"]: f for f in store.findings(r.run_id)}
    assert by_id["amazon:B0TEST0001"]["reason"] == "information_missing"
    assert by_id["amazon:B0TEST0002"]["reason"] == "clear"
    assert all("merchant" not in f for f in by_id.values())
