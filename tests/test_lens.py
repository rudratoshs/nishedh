"""Label check with Google Lens, on a synthetic response shaped like SerpApi's google_lens output."""

import pytest

from nishedh.extract.pesticide import PesticideExtractor
from nishedh.lens import lens_found, load_watchlist, read_lens
from nishedh.registry import pesticides as P

LENS = {"visual_matches": [
    {"title": "Cyclosinone Herbicide Granules LIMITED OFFER", "source": "Shopstore", "link": "https://shop.example/p/1"},
    {"title": "Weed Control Granules 100g", "source": "Flipkart", "link": "https://www.flipkart.com/x/p/itm1"},
    {"title": "Glyphosate 41% SL Herbicide 1L", "source": "AgriShop", "link": "https://agri.example/p/2"},
    {"title": "Garden gloves", "source": "Amazon.in", "link": "https://www.amazon.in/dp/B0X"},
]}


@pytest.fixture(scope="module")
def ex():
    return PesticideExtractor(P.load())


def test_watchlist_hit(ex):
    ev = read_lens(LENS, "id", ex, load_watchlist())
    assert [item.name for item, _ in ev.watchlist_hits] == ["Cyclosinone"]
    assert ev.named_sites == ["Amazon.in", "Flipkart"]            # small shops are never named
    assert "another online store" in ev.sites


def test_chemicals_named_elsewhere(ex):
    ev = read_lens(LENS, "id", ex, load_watchlist())
    assert [name for name, _ in ev.chemicals_elsewhere] == ["Glyphosate (IPA Salt)"]


def test_evidence_puts_watchlist_first(ex):
    ev = read_lens(LENS, "id", ex, load_watchlist())
    found = lens_found(ev)
    assert found[0].text.startswith("Cyclosinone") and found[0].field == "same photo on another online store"


def test_no_matches(ex):
    ev = read_lens({}, "id", ex, load_watchlist())
    assert not ev.matches and not ev.watchlist_hits and not lens_found(ev)
