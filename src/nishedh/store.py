"""Evidence store: every sweep, listing and finding in one SQLite file.

A finding row keeps its checks (reason, confidence, explanation, the exact text that triggered it
and the field it came from, the official source) and the ids of the cached SerpApi responses the
listing came from, so any finding can be re-verified from the raw data later.

The store lives under `.cache/` (git-ignored): it holds seller and merchant names, which the public
repository does not publish. `findings()` (used by the dashboard, exports and reports) never
returns them, and removes a store name that a search engine appended to a listing's title.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nishedh.listing import Listing, strip_seller
from nishedh.verdict.base import Finding

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    pack TEXT NOT NULL,
    live_searches INTEGER NOT NULL DEFAULT 0,
    cached_searches INTEGER NOT NULL DEFAULT 0,
    registry TEXT NOT NULL DEFAULT '',
    data_as_of TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS listings (
    run_id INTEGER NOT NULL REFERENCES runs(id),
    listing_id TEXT NOT NULL,
    marketplace TEXT, title TEXT, url TEXT, engine TEXT, price TEXT, merchant TEXT, thumbnail TEXT,
    search_id TEXT, details_search_id TEXT, lens_search_id TEXT, fields TEXT,
    PRIMARY KEY (run_id, listing_id)
);
CREATE TABLE IF NOT EXISTS findings (
    run_id INTEGER NOT NULL REFERENCES runs(id),
    listing_id TEXT NOT NULL,
    pack TEXT NOT NULL,
    verdict TEXT NOT NULL, reason TEXT NOT NULL, confidence TEXT NOT NULL,
    checks TEXT NOT NULL, notes TEXT NOT NULL,
    PRIMARY KEY (run_id, listing_id, pack)
);
"""


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        columns = {r["name"] for r in self.db.execute("PRAGMA table_info(runs)")}
        if "data_as_of" not in columns:   # stores created before the column existed
            self.db.execute("ALTER TABLE runs ADD COLUMN data_as_of TEXT NOT NULL DEFAULT ''")

    def close(self) -> None:
        self.db.close()

    def start_run(self, pack: str, registry: str = "") -> int:
        cur = self.db.execute(
            "INSERT INTO runs (started_at, pack, registry) VALUES (?, ?, ?)",
            (datetime.now(UTC).isoformat(), pack, registry),
        )
        self.db.commit()
        return int(cur.lastrowid or 0)

    def finish_run(self, run_id: int, live: int, cached: int, data_as_of: str = "") -> None:
        self.db.execute("UPDATE runs SET live_searches = ?, cached_searches = ?, data_as_of = ? WHERE id = ?",
                        (live, cached, data_as_of, run_id))
        self.db.commit()

    def add(self, run_id: int, pack: str, listing: Listing, finding: Finding | None) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO listings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, listing.id, listing.marketplace, listing.title, listing.url, listing.engine, listing.price,
             listing.merchant, listing.thumbnail, listing.search_id, listing.details_search_id,
             listing.lens_search_id, json.dumps(listing.fields, ensure_ascii=False)),
        )
        if finding is not None:
            self.db.execute(
                "INSERT OR REPLACE INTO findings VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, listing.id, pack, finding.verdict.value, finding.reason.value, finding.confidence,
                 json.dumps([_check(c) for c in finding.checks], ensure_ascii=False),
                 json.dumps(finding.notes, ensure_ascii=False)),
            )
        self.db.commit()

    def findings(self, run_id: int) -> list[dict[str, Any]]:
        rows = self.db.execute(
            """SELECT f.*, l.marketplace, l.title, l.url, l.engine, l.price, l.thumbnail, l.merchant,
                      l.search_id, l.details_search_id, l.lens_search_id
               FROM findings f JOIN listings l USING (run_id, listing_id) WHERE f.run_id = ?""",
            (run_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["checks"], d["notes"] = json.loads(d["checks"]), json.loads(d["notes"])
            d["title"] = strip_seller(d["title"], d.pop("merchant") or "")
            out.append(d)
        return out

    def latest_run(self, pack: str | None = None) -> int | None:
        q = "SELECT id FROM runs" + (" WHERE pack = ?" if pack else "") + " ORDER BY id DESC LIMIT 1"
        row = self.db.execute(q, (pack,) if pack else ()).fetchone()
        return int(row["id"]) if row else None


def _check(c: Any) -> dict[str, Any]:
    d = asdict(c)
    d["reason"] = c.reason.value
    d["evidence"] = [{"field": e.field, "text": e.text} for e in c.evidence]
    return d
