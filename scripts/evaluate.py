"""Compare Nishedh's verdicts on the blind evaluation set with independent labels.

Inputs: evaluation/cases.json (listing text, from scripts/eval_cases.py) and evaluation/labels.json
(labels written without seeing Nishedh's code or output). Nishedh's verdicts come from the demo
replay (`nishedh demo --no-serve`). Writes evaluation/results.json and prints a summary.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / ".cache" / "demo" / "nishedh.sqlite"
SEVERITY = ["banned_item", "not_in_registry", "information_missing", "registry_mismatch", "clear"]


def main() -> None:
    cases = {c["case"]: c for c in json.loads((ROOT / "evaluation" / "cases.json").read_text())}
    labels = {x["case"]: x for x in json.loads((ROOT / "evaluation" / "labels.json").read_text())}
    db = sqlite3.connect(DB)
    got = {
        (pack, lid): (reason, conf)
        for pack, lid, reason, conf in db.execute(
            "SELECT pack, listing_id, reason, confidence FROM findings "
            "WHERE run_id IN (SELECT max(id) FROM runs GROUP BY pack)"
        )
    }
    rows = []
    for n, case in sorted(cases.items()):
        label = labels[n]
        reason, conf = got.get((case["pack"], case["listing_id"]), ("out_of_scope", ""))
        exact = reason == label["expected_reason"]
        acceptable = reason in label.get("acceptable_reasons", [label["expected_reason"]]) or exact
        expected = label["expected_reason"]
        # A flag the reviewer did not expect, or one more serious than expected, is a false flag;
        # a pass (or a milder reason) where the reviewer expected a flag is a missed flag.
        if acceptable:
            kind = "agree"
        elif expected in ("clear", "out_of_scope") or (
            reason in SEVERITY and expected in SEVERITY and SEVERITY.index(reason) < SEVERITY.index(expected)
        ):
            kind = "false_flag_or_overstated"
        else:
            kind = "missed_or_understated"
        rows.append({
            "case": n, "pack": case["pack"], "title": case["title"][:120], "nishedh": reason,
            "nishedh_confidence": conf, "reviewer": expected, "reviewer_acceptable": label.get("acceptable_reasons"),
            "exact": exact, "outcome": kind, "reviewer_rationale": label.get("rationale", ""),
        })
    (ROOT / "evaluation" / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n")
    c = Counter(r["outcome"] for r in rows)
    print(f"{len(rows)} cases: {c['agree']} agree ({sum(r['exact'] for r in rows)} exact), "
          f"{c['false_flag_or_overstated']} false flag or overstated, {c['missed_or_understated']} missed or understated")
    for r in rows:
        if r["outcome"] != "agree":
            print(f"  #{r['case']} [{r['outcome']}] nishedh={r['nishedh']} reviewer={r['reviewer']}: {r['title'][:80]}")
            print(f"      reviewer: {r['reviewer_rationale'][:220]}")


if __name__ == "__main__":
    main()
