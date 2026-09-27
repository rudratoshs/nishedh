"""Export a blind evaluation set from the demo replay: listing text only, no Nishedh verdicts.

Sample (fixed seed): every pesticide finding above "weak signal", the registry mismatches, and a
random draw of weak signals, passes and radio findings. Run after `nishedh demo --no-serve`.

The set in evaluation/cases.json was drawn once (27 Sep 2026) and labelled against those case
numbers; redrawing after the rules change reshuffles the sample. So this refuses to overwrite it
unless given --force (which also means the labels must be redone).
"""

from __future__ import annotations

import json
import random
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / ".cache" / "demo" / "nishedh.sqlite"
LENS = ROOT / "demo" / "serpapi" / "google_lens"


def main() -> None:
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    rows = db.execute(
        """SELECT f.pack, f.reason, f.confidence, l.listing_id, l.title, l.marketplace, l.fields, l.lens_search_id
           FROM findings f JOIN listings l USING (run_id, listing_id)
           WHERE f.run_id IN (SELECT max(id) FROM runs GROUP BY pack) ORDER BY l.listing_id"""
    ).fetchall()
    rng = random.Random(27)

    def pick(pack: str, cond, n: int | None = None) -> list[sqlite3.Row]:
        pool = [r for r in rows if r["pack"] == pack and cond(r)]
        return pool if n is None else rng.sample(pool, min(n, len(pool)))

    chosen = (
        pick("pesticides", lambda r: r["reason"] != "clear" and r["confidence"] != "low")
        + pick("pesticides", lambda r: r["reason"] == "registry_mismatch")
        + pick("pesticides", lambda r: r["reason"] == "information_missing" and r["confidence"] == "low", 8)
        + pick("pesticides", lambda r: r["reason"] == "clear", 10)
        + pick("radio", lambda r: r["reason"] == "banned_item", 8)
        + pick("radio", lambda r: r["reason"] != "banned_item", 6)
    )
    cases = []
    for i, r in enumerate(chosen, 1):
        lens = []
        if r["lens_search_id"]:
            data = json.loads((LENS / f"{r['lens_search_id']}.json").read_text())["data"]
            lens = [v.get("title", "") for v in data.get("visual_matches") or []]
        cases.append({
            "case": i, "pack": r["pack"], "listing_id": r["listing_id"], "marketplace": r["marketplace"],
            "title": r["title"], "fields": json.loads(r["fields"] or "{}"), "lens_visual_match_titles": lens,
            "product_page_read": bool(json.loads(r["fields"] or "{}")),
        })
    out = ROOT / "evaluation" / "cases.json"
    if out.exists() and "--force" not in sys.argv:
        raise SystemExit(f"{out.relative_to(ROOT)} exists and is labelled; use --force to redraw (and relabel)")
    out.write_text(json.dumps(cases, ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {len(cases)} cases to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
