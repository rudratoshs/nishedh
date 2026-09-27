"""SearchClient: cache, budget, retries and key hygiene, with a fake HTTP transport (no real searches)."""

import json
from datetime import UTC, datetime

import httpx
import pytest

from nishedh.search.client import (
    BudgetExceeded,
    CacheMiss,
    SearchClient,
    SearchError,
    params_hash,
)

KEY = "k" * 64


def transport(responses):
    """Serve the given (status, body) pairs in order and record every request."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        status, body = responses[min(len(calls) - 1, len(responses) - 1)]
        return httpx.Response(status, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def client(tmp_path, responses, **kw):
    http, calls = transport(responses)
    return SearchClient(KEY, tmp_path, http=http, **kw), calls


def test_live_search_is_cached_and_counted(tmp_path):
    c, calls = client(tmp_path, [(200, {"shopping_results": [{"title": "x"}]})])
    first = c.search(engine="google_shopping", q="weed killer", gl="in")
    second = c.search(q="weed killer", gl="in", engine="google_shopping")  # same params, other order
    assert not first.cached and second.cached and len(calls) == 1
    assert second.data == first.data
    assert c.used_this_month() == 1
    assert calls[0].url.params["api_key"] == KEY


def test_api_key_never_reaches_disk(tmp_path):
    c, _ = client(tmp_path, [(200, {"organic_results": []})])
    c.search(engine="google", q="site:flipkart.com herbicide")
    for f in tmp_path.rglob("*"):
        if f.is_file():
            assert KEY not in f.read_text()


def test_a_response_echoing_the_key_is_redacted_not_refused(tmp_path):
    c, calls = client(tmp_path, [(200, {"search_metadata": {"url": f"https://x?api_key={KEY}"}})])
    r = c.search(engine="google", q="x")
    assert KEY not in json.dumps(r.data) and "[REDACTED]" in json.dumps(r.data)
    assert c.search(engine="google", q="x").cached and len(calls) == 1   # not paid for twice
    for f in tmp_path.rglob("*.json"):
        assert KEY not in f.read_text()


def test_httpx_request_logging_never_shows_the_key(tmp_path, caplog):
    import logging
    caplog.set_level(logging.INFO)
    c, _ = client(tmp_path, [(200, {})])
    c.search(engine="google", q="logged")
    assert KEY not in caplog.text


def test_network_errors_are_retried_and_never_carry_the_key(tmp_path, monkeypatch):
    monkeypatch.setattr("nishedh.search.client.time.sleep", lambda s: None)
    attempts = []

    def handler(request):
        attempts.append(request)
        raise httpx.ConnectError("boom", request=request)

    c = SearchClient(KEY, tmp_path, http=httpx.Client(transport=httpx.MockTransport(handler)), max_retries=2)
    with pytest.raises(SearchError) as info:
        c.search(engine="google", q="x")
    assert len(attempts) == 3 and KEY not in str(info.value) and info.value.__cause__ is None
    assert c.used_this_month() == 0


def test_non_dict_json_is_a_search_error(tmp_path):
    c, _ = client(tmp_path, [(200, ["not", "a", "dict"])])
    with pytest.raises(SearchError, match="unexpected response shape"):
        c.search(engine="google", q="x")


def test_engine_name_cannot_escape_the_cache(tmp_path):
    c, calls = client(tmp_path, [(200, {})])
    for bad in ("../../escaped", "google/../x", ""):
        with pytest.raises(ValueError):
            c.search(engine=bad, q="x")
    assert calls == []


def test_no_results_answer_is_cached_and_counted(tmp_path):
    body = {"error": "Google hasn't returned any results for this query."}
    c, calls = client(tmp_path, [(200, body)])
    assert c.search(engine="google", q="nothing").data == body
    assert c.search(engine="google", q="nothing").cached and len(calls) == 1 and c.used_this_month() == 1


def test_ledger_without_trailing_newline_still_counts(tmp_path):
    now = datetime.now(UTC).isoformat()
    (tmp_path / "ledger.jsonl").write_text(json.dumps({"t": now, "engine": "google", "id": "a"}))  # no newline
    c, _ = client(tmp_path, [(200, {})], monthly_cap=5)
    c.search(engine="google", q="second")
    assert c.used_this_month() == 2   # read back: both lines parse


def test_cap_boundary(tmp_path):
    c, calls = client(tmp_path, [(200, {})], monthly_cap=2)
    c.search(engine="google", q="1")
    c.search(engine="google", q="2")          # cap - 1 used before this call: allowed
    with pytest.raises(BudgetExceeded):
        c.search(engine="google", q="3")      # cap reached
    assert len(calls) == 2


def test_client_closes_its_own_http_client(tmp_path):
    with SearchClient(KEY, tmp_path) as c:
        http = c._http
    assert http.is_closed


def test_budget_cap_blocks_before_any_request(tmp_path):
    c, calls = client(tmp_path, [(200, {})], monthly_cap=2)
    now = datetime.now(UTC).isoformat()
    (tmp_path / "ledger.jsonl").write_text("\n".join(json.dumps({"t": now, "engine": "google", "id": str(i)}) for i in range(2)))
    with pytest.raises(BudgetExceeded):
        c.search(engine="google", q="new query")
    assert calls == []


def test_last_months_usage_does_not_count(tmp_path):
    c, _ = client(tmp_path, [(200, {})], monthly_cap=1)
    (tmp_path / "ledger.jsonl").write_text(json.dumps({"t": "2020-01-15T00:00:00+00:00", "engine": "google", "id": "x"}) + "\n")
    assert c.used_this_month() == 0
    c.search(engine="google", q="fine")
    assert c.used_this_month() == 1


def test_offline_mode_serves_cache_only(tmp_path):
    live, _ = client(tmp_path, [(200, {"a": 1})])
    live.search(engine="google", q="cached")
    off = SearchClient(None, tmp_path, offline=True)
    assert off.search(engine="google", q="cached").data == {"a": 1}
    with pytest.raises(CacheMiss):
        off.search(engine="google", q="not cached")


def test_retries_rate_limit_then_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr("nishedh.search.client.time.sleep", lambda s: None)
    c, calls = client(tmp_path, [(429, {"error": "slow down"}), (200, {"ok": True})])
    assert c.search(engine="google", q="x").data == {"ok": True}
    assert len(calls) == 2 and c.used_this_month() == 1


def test_api_error_is_raised_and_not_cached(tmp_path):
    c, _ = client(tmp_path, [(400, {"error": "Invalid engine"})])
    with pytest.raises(SearchError, match="Invalid engine"):
        c.search(engine="nope", q="x")
    assert c.used_this_month() == 0 and not list(tmp_path.rglob("*.json"))


def test_key_must_not_be_a_search_parameter(tmp_path):
    c, _ = client(tmp_path, [(200, {})])
    with pytest.raises(ValueError):
        c.search(engine="google", q="x", api_key="leak")


def test_params_hash_ignores_key_and_order():
    assert params_hash({"q": "a", "engine": "google"}) == params_hash({"engine": "google", "q": "a", "api_key": "z"})
    assert params_hash({"q": "a"}) != params_hash({"q": "b"})
