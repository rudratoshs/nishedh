"""Export every listing of the demo replay for a blind scope review: is it a pesticide / radio product?

Unlike evaluation/cases.json (a sample of findings), this covers all 389 listings the searches
surfaced, including those Nishedh judged out of scope, so scope recall can be measured. Nishedh's
decisions are not included. Refuses to overwrite a labelled set unless given --force.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    out = ROOT / "evaluation" / "scope_cases.json"
    if out.exists() and "--force" not in sys.argv:
        raise SystemExit(f"{out.relative_to(ROOT)} exists; use --force to redraw (and relabel)")
    db = sqlite3.connect(ROOT / ".cache" / "demo" / "nishedh.sqlite")
    rows = db.execute(
        "SELECT r.pack, l.listing_id, l.title, l.fields FROM listings l JOIN runs r ON r.id = l.run_id "
        "WHERE l.run_id IN (SELECT max(id) FROM runs GROUP BY pack) ORDER BY r.pack, l.listing_id"
    ).fetchall()
    cases = []
    for i, (pack, lid, title, fields) in enumerate(rows, 1):
        f = {k: v[:300] for k, v in json.loads(fields or "{}").items()}
        cases.append({"case": i, "pack": pack, "listing_id": lid, "title": title, "fields": f})
    out.write_text(json.dumps(cases, ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {len(cases)} listings to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
