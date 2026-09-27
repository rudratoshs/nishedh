"""Dashboard: pages render, exports never include merchant names, complaint drafts are marked as drafts."""

import json

import pytest
from fastapi.testclient import TestClient

from nishedh.extract.pesticide import Found
from nishedh.listing import Listing
from nishedh.store import Store
from nishedh.verdict.base import Check, Finding, Reason, Verdict
from nishedh.web.app import create_app


@pytest.fixture()
def client(tmp_path):
    store = Store(tmp_path / "nishedh.sqlite")
    run = store.start_run("pesticides")
    listing = Listing(id="amazon:B0TEST0001", marketplace="Amazon.in", title="Bamboo Killer – 5% Active Formula",
                      url="https://www.amazon.in/dp/B0TEST0001", engine="amazon", search_id="ab" * 32,
                      price="₹399", merchant="SECRET SELLER PVT LTD")
    check = Check(Reason.INFORMATION_MISSING, "high", "Claims an active strength but names no chemical.",
                  (Found("title", "5% Active Formula"),), "labelling_rule")
    store.add(run, "pesticides", listing, Finding(Verdict.UNREGISTERED_OR_HIDDEN, Reason.INFORMATION_MISSING, "high", [check]))
    store.finish_run(run, live=0, cached=1)
    store.close()
    return TestClient(create_app(tmp_path))


def test_index_and_finding_pages(client):
    page = client.get("/?pack=pesticides")
    assert page.status_code == 200 and "Bamboo Killer" in page.text and "Information missing" in page.text
    detail = client.get("/finding/pesticides/amazon:B0TEST0001")
    assert detail.status_code == 200 and "Why was this flagged?" in detail.text and "Rule 19" in detail.text


def test_merchant_names_never_leave_the_store(client):
    for url in ("/?pack=pesticides", "/finding/pesticides/amazon:B0TEST0001", "/export/pesticides.csv",
                "/export/pesticides.json", "/complaint/pesticides/amazon:B0TEST0001"):
        assert "SECRET SELLER" not in client.get(url).text, url
    rows = json.loads(client.get("/export/pesticides.json").text)
    assert rows[0]["reason"] == "information_missing" and "merchant" not in rows[0]


def test_complaint_is_a_marked_draft_with_sources(client):
    text = client.get("/complaint/pesticides/amazon:B0TEST0001").text
    assert text.startswith("DRAFT") and "not a legal determination" in text
    assert "Insecticides Rules, 1971" in text and "https://" in text


def test_raw_viewer_rejects_path_tricks(client):
    assert client.get("/raw/amazon/..%2F..%2Fetc").status_code in (400, 404)
    assert client.get("/raw/amazon/" + "zz" * 32).status_code == 400


def test_unknown_finding_is_404(client):
    assert client.get("/finding/pesticides/amazon:NOPE").status_code == 404


def test_help_pages_render(client):
    assert "What the results mean" in client.get("/how-it-works").text
    faq = client.get("/faq").text
    assert "Does a flag mean the seller broke the law?" in faq and "1915" in faq


def test_filters_search_and_pagination(tmp_path):
    store = Store(tmp_path / "nishedh.sqlite")
    run = store.start_run("pesticides")
    check = Check(Reason.INFORMATION_MISSING, "low", "Sold as a pesticide product, but the title names no chemical.",
                  (Found("title", "Weed killer"),), "labelling_rule")
    for i in range(30):
        listing = Listing(id=f"amazon:B0{i:08d}", marketplace="Amazon.in", title=f"Weed killer {i:02d}",
                          url="https://www.amazon.in/", engine="amazon", search_id="ab" * 32, price=f"₹{100 + i}")
        store.add(run, "pesticides", listing, Finding(Verdict.UNREGISTERED_OR_HIDDEN, Reason.INFORMATION_MISSING, "low", [check]))
    store.finish_run(run, live=0, cached=1)
    store.close()
    c = TestClient(create_app(tmp_path))
    first, second = c.get("/?pack=pesticides").text, c.get("/?pack=pesticides&page=2").text
    assert "Showing <b>24</b> of <b>30</b>" in first and "Showing <b>6</b> of <b>30</b>" in second
    assert "Weed killer 07" in c.get("/?pack=pesticides&q=killer+07").text
    assert "Showing <b>1</b> of <b>1</b>" in c.get("/?pack=pesticides&q=killer+07").text
    assert "No products match" in c.get("/?pack=pesticides&confidence=high").text
    dearest = c.get("/?pack=pesticides&sort=price_high").text
    assert dearest.index("Weed killer 29") < dearest.index("Weed killer 10") and "Weed killer 00" not in dearest
    assert c.get("/?pack=pesticides&page=99").status_code == 200   # out-of-range page falls back to the last


def test_plain_headlines():
    from nishedh.web.app import headline

    def f(pack, reason, explanation, confidence="high"):
        return {"pack": pack, "reason": reason, "confidence": confidence,
                "checks": [{"reason": reason, "explanation": explanation, "evidence": []}]}

    booster = f("radio", "banned_item", "Listed as a mobile signal booster; ... boosters and wireless jammers.")
    assert headline(booster).startswith("Mobile signal boosters")
    lens = f("pesticides", "not_in_registry", 'The same product photo is sold on X as "Y". Cyclosinone is named in the CCPA orders')
    assert "Cyclosinone" in headline(lens)
    assert "chemical" in headline(f("pesticides", "information_missing", "Claims an active strength but names no chemical"))
    unknown = f("pesticides", "information_missing",
                '"Cyclosinone 20% SC" names no chemical on any official list; it may be a brand name or an unregistered chemical')
    assert headline(unknown).startswith('Names "Cyclosinone 20% SC", which is on no official list')


def test_store_name_appended_to_a_title_is_removed(tmp_path):
    from nishedh.listing import strip_seller

    assert strip_seller("Ultra Boost 3G & 4G Signal Amplifier | Mobile Signal Guru", "Mobile Signal Guru") == \
        "Ultra Boost 3G & 4G Signal Amplifier"
    assert strip_seller("Sarv Rog Nashak Kit - MahaGuru", "MahaGuru") == "Sarv Rog Nashak Kit"
    assert strip_seller("Elecbee 7Dbi Antenna", "Elecbee") == "Elecbee 7Dbi Antenna"          # a brand at the start stays
    assert strip_seller("Walkie Talkie | Amazon.in", "Amazon.in") == "Walkie Talkie | Amazon.in"   # marketplaces are public
    store = Store(tmp_path / "nishedh.sqlite")
    run = store.start_run("radio")
    listing = Listing(id="shopping:1", marketplace="another online store", url="https://example.com/p",
                      title="Signal Amplifier | Tiny Shop", engine="google_shopping", search_id="ab" * 32,
                      merchant="Tiny Shop")
    check = Check(Reason.BANNED_ITEM, "high", "Listed as a mobile signal booster.", (Found("title", "x"),), "ccpa_radio_guidelines_2025")
    store.add(run, "radio", listing, Finding(Verdict.BANNED, Reason.BANNED_ITEM, "high", [check]))
    store.finish_run(run, live=0, cached=1)
    store.close()
    c = TestClient(create_app(tmp_path))
    for url in ("/?pack=radio", "/finding/radio/shopping:1", "/export/radio.csv", "/complaint/radio/shopping:1"):
        assert "Tiny Shop" not in c.get(url).text, url


def test_odd_query_values_fall_back_to_defaults(client):
    for url in ("/?pack=zzz", "/?pack=pesticides&page=abc", "/?pack=pesticides&page=-1", "/?pack=pesticides&sort=zzz",
                "/?pack=pesticides&reason=zzz&confidence=zzz"):
        page = client.get(url)
        assert page.status_code == 200 and "Bamboo Killer" in page.text, url
    assert client.get("/export/zzz.csv").status_code == 404


def test_only_web_links_reach_the_page():
    from nishedh.web.app import web_url

    assert web_url("https://www.amazon.in/dp/B0") == "https://www.amazon.in/dp/B0"
    assert web_url("javascript:alert(1)") == "#" and web_url("data:text/html,x") == "#"


def test_logo_and_favicon_are_served(client):
    for name in ("mark.png", "mark-dark.png", "favicon.png"):
        r = client.get(f"/static/{name}")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png", name
    assert "/static/mark.png" in client.get("/faq").text
