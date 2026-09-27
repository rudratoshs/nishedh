"""Compare Nishedh's scope decisions with blind labels on every listing of the demo replay.

Inputs: evaluation/scope_cases.json (all listings) and evaluation/scope_labels.json (labelled
without seeing Nishedh's code or output). A listing is in scope for Nishedh when it got a finding.
Writes evaluation/scope_results.json and prints precision and recall per category.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    cases = {c["case"]: c for c in json.loads((ROOT / "evaluation" / "scope_cases.json").read_text())}
    labels = {x["case"]: x for x in json.loads((ROOT / "evaluation" / "scope_labels.json").read_text())}
    db = sqlite3.connect(ROOT / ".cache" / "demo" / "nishedh.sqlite")
    judged = set(db.execute(
        "SELECT pack, listing_id FROM findings WHERE run_id IN (SELECT max(id) FROM runs GROUP BY pack)"
    ).fetchall())
    rows, summary = [], {}
    for n, c in sorted(cases.items()):
        want, got = labels[n]["in_scope"], (c["pack"], c["listing_id"]) in judged
        kind = {(True, True): "tp", (False, False): "tn", (False, True): "fp", (True, False): "fn"}[(want, got)]
        s = summary.setdefault(c["pack"], {"tp": 0, "tn": 0, "fp": 0, "fn": 0})
        s[kind] += 1
        rows.append({"case": n, "pack": c["pack"], "title": c["title"][:120], "reviewer_in_scope": want,
                     "nishedh_in_scope": got, "outcome": kind, "category": labels[n].get("category", ""),
                     "note": labels[n].get("note", "")})
    (ROOT / "evaluation" / "scope_results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n")
    for pack, s in summary.items():
        precision = s["tp"] / max(1, s["tp"] + s["fp"])
        recall = s["tp"] / max(1, s["tp"] + s["fn"])
        print(f"{pack}: {sum(s.values())} listings; in scope per reviewer {s['tp'] + s['fn']}; "
              f"precision {precision:.1%} ({s['fp']} extra), recall {recall:.1%} ({s['fn']} missed)")
    for r in rows:
        if r["outcome"] in ("fp", "fn"):
            print(f"  [{r['outcome']}] {r['pack']} #{r['case']} ({r['category']}): {r['title'][:90]}  {r['note'][:90]}")


if __name__ == "__main__":
    main()
