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
