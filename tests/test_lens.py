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
    assert found[0].text.startswith("Cyclosinone") and found[0].field == "visual match on another online store"


def test_no_matches(ex):
    ev = read_lens({}, "id", ex, load_watchlist())
    assert not ev.matches and not ev.watchlist_hits and not lens_found(ev)


def test_hit_strength_counts_and_ranks_watchlist_matches():
    from nishedh.lens import LensEvidence, Match, WatchItem

    item = WatchItem("Cyclosinone", "f", "o", "ccpa_orders")
    other = [Match(f"Weed killer {i}", "another online store", f"https://x/{i}") for i in range(20)]
    hit = [Match(f"Cyclosinone Herbicide {i}", "another online store", f"https://y/{i}") for i in range(4)]
    strong = LensEvidence("a", matches=hit[:1] + other[:5] + hit[1:], watchlist_hits=[(item, m) for m in hit])
    assert strong.hit_strength(item) == (4, 1, True)
    weak = LensEvidence("b", matches=other[:16] + hit, watchlist_hits=[(item, m) for m in hit])
    assert weak.hit_strength(item) == (4, 17, False)


def test_directory_title_is_hidden_but_still_matched():
    from nishedh.lens import DIRECTORY_TITLE, WatchItem, read_lens

    class NoChemicals:
        def extract(self, fields):
            from nishedh.extract.pesticide import Extraction
            return Extraction()

    item = WatchItem("Cyclosinone", "f", "o", "ccpa_orders")
    data = {"visual_matches": [{"title": "Cyclosinone 20% SC - Wholesaler in Pune", "link": "https://x.in/p", "source": "x"}]}
    ev = read_lens(data, "s", NoChemicals(), [item])
    assert ev.matches[0].title == DIRECTORY_TITLE and len(ev.watchlist_hits) == 1


def test_other_stores_note_has_no_leading_gap_or_plural_error():
    from nishedh.sweep import _other_stores_note

    assert _other_stores_note([], 1) == "Visually matching photos also appear on 1 other online store."
    assert _other_stores_note([], 2) == "Visually matching photos also appear on 2 other online stores."
    assert _other_stores_note(["Flipkart"], 2) == \
        "Visually matching photos also appear on Flipkart and 2 other online stores."
    assert " on  and" not in _other_stores_note([], 3)
    assert _other_stores_note([], 0) == ""
