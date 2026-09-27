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
    assert (results["pesticides"].listings, results["pesticides"].judged) == (233, 160)
    counts = Counter((f["reason"], f["confidence"]) for f in findings["pesticides"])
    assert counts[("not_in_registry", "medium")] == 7
    assert counts[("information_missing", "high")] == 1
    cyclosinone = [f for f in findings["pesticides"] if f["lens_search_id"] and "Cyclosinone" in f["checks"][0]["explanation"]]
    assert len(cyclosinone) == 5


def test_radio_numbers_match_the_readme(replay):
    results, findings = replay
    assert (results["radio"].listings, results["radio"].judged) == (156, 59)
    banned = [f for f in findings["radio"] if f["reason"] == "banned_item"]
    assert len(banned) == 15 and sum("booster" in f["checks"][0]["explanation"] for f in banned) == 13


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
