"""The bundled demo snapshot replays the 27 Sep 2026 live run: the README's numbers, and nothing private."""

import json
import shutil
from collections import Counter
from pathlib import Path

import pytest

from nishedh.listing import MARKETPLACES, OTHER_STORE
from nishedh.registry.eta import EtaRegistry
from nishedh.registry.pesticides import load
from nishedh.search.client import SearchClient
from nishedh.store import Store
from nishedh.sweep import Sweeper

DEMO = Path(__file__).resolve().parents[1] / "demo"


@pytest.fixture(scope="module")
def replay(tmp_path_factory):
    cache = tmp_path_factory.mktemp("demo")
    shutil.copytree(DEMO / "serpapi", cache / "serpapi")
    store = Store(cache / "nishedh.sqlite")
    client = SearchClient(None, cache / "serpapi", offline=True)
    eta = EtaRegistry(cache / "eta", offline=True)
    sweeper = Sweeper(client, store, load(), eta)
    results = {pack: sweeper.run(pack, max_live=0) for pack in ("pesticides", "radio")}
    findings = {pack: store.findings(r.run_id) for pack, r in results.items()}
    client.close()
    eta.close()
    store.close()
    return results, findings


def test_pesticide_numbers_match_the_readme(replay):
    results, findings = replay
    assert (results["pesticides"].listings, results["pesticides"].judged) == (233, 165)
    counts = Counter((f["reason"], f["confidence"]) for f in findings["pesticides"])
    assert counts[("not_in_registry", "medium")] + counts[("not_in_registry", "low")] == 7
    assert counts[("information_missing", "high")] == 1 and counts[("information_missing", "medium")] == 11
    cyclosinone = [f for f in findings["pesticides"] if f["lens_search_id"] and "Cyclosinone" in f["checks"][0]["explanation"]]
    assert len(cyclosinone) == 5
    assert sum(f["confidence"] == "medium" for f in cyclosinone) == 4   # one is a weak visual match


def test_radio_numbers_match_the_readme(replay):
    results, findings = replay
    assert (results["radio"].listings, results["radio"].judged) == (156, 64)
    banned = [f for f in findings["radio"] if f["reason"] == "banned_item"]
    assert len(banned) == 20 and sum("booster" in f["checks"][0]["explanation"] for f in banned) == 18


def test_snapshot_links_never_name_a_small_store():
    import re
    from urllib.parse import urlparse

    allowed = ("amazon.in", "flipkart.com", "jiomart.com", "meesho.com", "indiamart.com", "snapdeal.com",
               "shopclues.com", "tatacliq.com", "myntra.com", "ebay.com", "tradeindia.com", "google.co.in",
               "google.com", "gstatic.com", "serpapi.com", "media-amazon.com", "another-online-store.invalid")
    for path in (DEMO / "serpapi").glob("*/*.json"):
        for url in re.findall(r'https?://[^"\s]+', path.read_text()):
            parsed = urlparse(url)
            host = parsed.netloc.lower().removeprefix("www.")
            assert any(host == d or host.endswith("." + d) for d in allowed), (path.name, url)
            if host == "indiamart.com":   # a seller's storefront page names the seller
                assert parsed.path.startswith(("/proddetail/", "/impcat/")), (path.name, url)


def test_snapshot_holds_only_allowlisted_fields():
    allowed = set(MARKETPLACES.values()) | {OTHER_STORE}
    for path in (DEMO / "serpapi").glob("*/*.json"):
        text = path.read_text()
        for field in ("author", "contact_information", "sold_by", "seller", "shipper_seller", "profile_name", "api_key"):
            assert f'"{field}' not in text, (path.name, field)   # as a JSON key ("seller.jiomart.com" in a URL is fine)

        def sources(o):
            if isinstance(o, dict):
                if "source" in o:
                    yield o["source"]
                for v in o.values():
                    yield from sources(v)
            elif isinstance(o, list):
                for v in o:
                    yield from sources(v)

        assert set(sources(json.loads(text))) <= allowed, path.name


def test_readme_numbers_come_from_the_snapshot(replay):
    """The README's results table is checked against the replay, so the prose cannot drift."""
    results, findings = replay
    readme = (DEMO.parent / "README.md").read_text()
    pest, radio = findings["pesticides"], findings["radio"]
    counts = Counter((f["reason"], f["confidence"]) for f in pest)
    lens = [f for f in pest if f["lens_search_id"] and "Cyclosinone" in f["checks"][0]["explanation"]]
    nir = sum(n for (r, _), n in counts.items() if r == "not_in_registry")
    banned = [f for f in radio if f["reason"] == "banned_item"]
    boosters = sum("booster" in f["checks"][0]["explanation"] for f in banned)
    expected = [
        f"{results['pesticides'].listings} listings, {results['pesticides'].judged} of them pesticides",
        f"{results['radio'].listings} listings, {results['radio'].judged} of them radio equipment",
        (f"**{nir}** not on the official list ({len(lens)} linked by photo to Cyclosinone, "
         f"{sum(f['confidence'] == 'medium' for f in lens)} of them strongly)"),
        f"**{counts[('information_missing', 'high')]}** claiming an \"active\" strength",
        f"**{counts[('information_missing', 'medium')]}** more naming no chemical",
        f"**{boosters}** mobile signal boosters detected",
        f"**{len(banned) - boosters}** walkie-talkies stating frequencies",
        f"The findings use {results['pesticides'].cached + results['radio'].cached} of them",
    ]
    for text in expected:
        assert text in readme, text
