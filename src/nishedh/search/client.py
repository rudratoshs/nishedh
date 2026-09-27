"""SerpApi access with a disk cache and a hard monthly budget.

The free plan allows 250 searches a month, so every response is cached by its parameters and
never paid for twice, and live calls stop at a configurable cap below the plan limit.

The API key is sent only in the request. It is never written to the cache or the ledger, never
included in an exception message, and httpx's request logging (which prints full URLs, key
included) is silenced for this module's client.

Single-process use: the ledger is not locked, so two concurrent sweeps could both pass the cap check.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Self

import httpx

ENDPOINT = "https://serpapi.com/search.json"
RETRY_STATUS = {429, 500, 502, 503, 504}
ENGINE = re.compile(r"^[a-z0-9_]+$")
# A 200 response that SerpApi reports as an "error" but that is a real, billed answer: no results.
NO_RESULTS = re.compile(r"hasn't returned any results|no results", re.IGNORECASE)

# httpx logs "HTTP Request: GET <full url>" at INFO, and the URL carries the API key.
logging.getLogger("httpx").setLevel(logging.WARNING)


class BudgetExceeded(RuntimeError):
    """A live search would take this month's usage past the cap."""


class CacheMiss(RuntimeError):
    """Offline mode was asked for a search that is not cached."""


class SearchError(RuntimeError):
    """SerpApi returned an error for this search, or could not be reached."""


@dataclass(frozen=True)
class SearchResult:
    params: dict[str, str]
    data: dict[str, Any]
    fetched_at: str
    cached: bool


def params_hash(params: dict[str, str]) -> str:
    """Stable id for a search: SHA-256 of its parameters, sorted, without the API key."""
    clean = {k: str(v) for k, v in sorted(params.items()) if k != "api_key"}
    return hashlib.sha256(json.dumps(clean, sort_keys=True).encode()).hexdigest()


class SearchClient:
    def __init__(
        self,
        api_key: str | None,
        cache_dir: Path,
        monthly_cap: int = 230,
        offline: bool = False,
        http: httpx.Client | None = None,
        max_retries: int = 3,
    ) -> None:
        if not offline and not api_key:
            raise ValueError("SERPAPI_API_KEY is required unless offline=True")
        self._key = api_key
        self.cache_dir = cache_dir
        self.monthly_cap = monthly_cap
        self.offline = offline
        self._owns_http = http is None
        self._http = http or httpx.Client(timeout=120)
        self._max_retries = max_retries
        cache_dir.mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, t: type[BaseException] | None, e: BaseException | None, tb: TracebackType | None) -> None:
        self.close()

    # -- ledger ---------------------------------------------------------------------------

    @property
    def _ledger(self) -> Path:
        return self.cache_dir / "ledger.jsonl"

    def used_this_month(self, now: datetime | None = None) -> int:
        """Live searches recorded in the current UTC calendar month.

        SerpApi's own counter resets on the plan's billing date, which may differ; the default
        cap (230 of 250) leaves room for that difference.
        """
        month = (now or datetime.now(UTC)).strftime("%Y-%m")
        if not self._ledger.exists():
            return 0
        lines = (line for line in self._ledger.read_text().splitlines() if line.strip())
        return sum(1 for line in lines if json.loads(line)["t"].startswith(month))

    def _record(self, engine: str, h: str) -> None:
        entry = json.dumps({"t": datetime.now(UTC).isoformat(), "engine": engine, "id": h})
        needs_newline = self._ledger.exists() and not self._ledger.read_text().endswith("\n") and self._ledger.stat().st_size
        with self._ledger.open("a") as f:
            f.write(("\n" if needs_newline else "") + entry + "\n")

    # -- search ---------------------------------------------------------------------------

    def _path(self, params: dict[str, str]) -> Path:
        engine = params.get("engine", "google")
        if not ENGINE.fullmatch(engine):
            raise ValueError(f"invalid engine name: {engine!r}")
        return self.cache_dir / engine / f"{params_hash(params)}.json"

    def search(self, **params: str) -> SearchResult:
        """Return the cached result for these parameters, or run one live search and cache it."""
        if "api_key" in params:
            raise ValueError("pass the API key to SearchClient, not as a search parameter")
        path = self._path(params)
        if path.exists():
            stored = json.loads(path.read_text())
            return SearchResult(params=stored["params"], data=stored["data"], fetched_at=stored["fetched_at"], cached=True)
        if self.offline:
            raise CacheMiss(f"not cached: {params}")
        if self.used_this_month() >= self.monthly_cap:
            raise BudgetExceeded(f"monthly cap of {self.monthly_cap} live searches reached")
        data = self._fetch(params)
        self._record(params.get("engine", "google"), path.stem)
        fetched_at = datetime.now(UTC).isoformat()
        text = json.dumps({"params": params, "fetched_at": fetched_at, "data": data}, ensure_ascii=False)
        if self._key and self._key in text:
            # Redact rather than refuse: the credit is already spent, and a refusal would spend it again.
            text = text.replace(self._key, "[REDACTED]")
            data = json.loads(text)["data"]
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text)
        tmp.replace(path)
        return SearchResult(params=params, data=data, fetched_at=fetched_at, cached=False)

    def _fetch(self, params: dict[str, str]) -> dict[str, Any]:
        """One live search. Retries rate limits, server errors and network failures with backoff."""
        for attempt in range(self._max_retries + 1):
            last = attempt == self._max_retries
            try:
                resp = self._http.get(ENDPOINT, params={**params, "api_key": self._key})
            except httpx.TransportError as e:
                # The exception's request URL carries the key; report only the error type.
                if last:
                    raise SearchError(f"SerpApi unreachable after {attempt + 1} attempts: {type(e).__name__}") from None
                time.sleep(2 ** attempt)
                continue
            if resp.status_code in RETRY_STATUS and not last:
                time.sleep(2 ** attempt)
                continue
            try:
                data = resp.json()
            except ValueError:
                raise SearchError(f"HTTP {resp.status_code}: response is not JSON") from None
            if not isinstance(data, dict):
                raise SearchError(f"HTTP {resp.status_code}: unexpected response shape ({type(data).__name__})")
            error = data.get("error")
            if resp.status_code == 200 and isinstance(error, str) and NO_RESULTS.search(error):
                return data    # a real, billed answer with no results: cache it so it is never paid for again
            if resp.status_code != 200 or error:
                raise SearchError(f"HTTP {resp.status_code}: {error or 'unknown error'}")
            return data
        raise SearchError("retries exhausted")
