# Blind evaluation

Unit tests check that each rule does what it says. This evaluation checks the whole pipeline on real listings. An independent reviewer labelled real listings from the 27 Sep 2026 run without seeing Nishedh's verdicts, and the two sets of answers were compared.

## Result

| | Cases | Agree | Exact | False flag or overstated | Missed or understated |
| --- | --- | --- | --- | --- | --- |
| Pesticides | 38 | 38 | 36 | 0 | 0 |
| Radio equipment | 14 | 14 | 14 | 0 | 0 |
| **Total** | **52** | **52** | **50** | **0** | **0** |

"Agree" means Nishedh's reason code is the reviewer's expected code, or one the reviewer marked as equally defensible. The two non-exact agreements:

| Case | Nishedh | Reviewer (and also acceptable) | Why it is ambiguous |
| --- | --- | --- | --- |
| 10 | information missing | not in registry (information missing) | Its only watchlist visual match is the misspelling "Cyclosinonie", 13th of 59. Nishedh matches the watchlist name exactly, so it did not treat this as a hit. |
| 28 | information missing | clear (information missing) | "Trichoderma bio fungicide": the genus is registered, but the species is not named. |

Per-case detail, including the reviewer's reasoning, is in [`results.json`](results.json).

## Method

1. **Sample.** [`scripts/eval_cases.py`](../scripts/eval_cases.py) draws 52 listings from the demo replay with a fixed seed. It takes every pesticide finding above "weak signal", every registry mismatch, and random draws of weak signals, passes and radio findings. [`cases.json`](cases.json) holds only what a reviewer would see: the listing text, whether the product page was read, and the Google Lens visual-match titles. It does not include Nishedh's verdicts.
2. **Labels.** A separate AI model (Claude Fable, run as an independent reviewer) labelled each case. It had a written rulebook and the official registry data, and was barred from reading Nishedh's code, tests, cache or output. Its labels are in [`labels.json`](labels.json). It verified every chemical and strength against the parsed government lists.
3. **Compare.** [`scripts/evaluate.py`](../scripts/evaluate.py) compares the two and writes `results.json`.

Reproduce with `uv run nishedh demo --no-serve && uv run python scripts/evaluate.py`. The result above is for the current rules: after every change, the frozen set is re-scored.

## What this does and does not show

- **The reviewer is an AI model, not a human expert.** It was independent of Nishedh's code, but it is not a legal review.
- **It measures whether Nishedh applies its rulebook correctly to real listings**, not whether the rulebook matches the law in every case. The rulebook itself is sourced in the main README.
- **52 cases is a small sample.** It is weighted towards findings, because false flags are the most costly error. It has no radio cases with an approval (ETA) number, because none of the 59 radio listings stated one.
- **Found and fixed during this evaluation:**
  - The first export cut each listing's Lens matches to 15, which hid the Cyclosinone matches for case 2. The reviewer re-judged every Lens case with the full lists.
  - Re-exporting the sample after later rule changes once reshuffled the case numbers against the labels. The set is now frozen: `eval_cases.py` refuses to overwrite it.
  - The reviewer noticed that some watchlist matches are weak: a few matches, ranked low. Nishedh now reports how many visual matches name the product and the rank of the best one. A weak match is a "weak signal", not a "good lead".
