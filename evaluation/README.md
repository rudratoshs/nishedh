# Blind evaluation

Unit tests check that each rule does what it says. This evaluation checks the rules on real listings. An independent reviewer labelled real listings from the 27 Sep 2026 run without seeing Nishedh's verdicts, and the two sets of answers were compared.

There are two parts. The **verdict evaluation** asks: for a listing in a category, is Nishedh's reason code right? The **scope evaluation** asks: does Nishedh recognise which listings belong to a category at all? A listing wrongly judged out of scope never reaches the rules, so the verdict evaluation alone cannot see that error.

## Verdict evaluation: reason codes on 52 sampled in-scope listings

| | Cases | Agree | Exact | False flag or overstated | Missed or understated |
| --- | --- | --- | --- | --- | --- |
| Pesticides | 38 | 38 | 36 | 0 | 0 |
| Radio equipment | 14 | 14 | 14 | 0 | 0 |
| **Total** | **52** | **52** | **50** | **0** | **0** |

"Agree" means Nishedh's **reason code** is the reviewer's expected code, or one the reviewer marked as equally defensible. Only reason codes are compared. On **confidence** (compare `nishedh_confidence` with `reviewer_confidence` in `results.json`), 19 of the 52 differ: in 17 Nishedh is more cautious than the reviewer (14 "good lead" where the reviewer said "strong evidence", 3 "weak signal" where it said "good lead"), and in 2 it is more confident ("strong evidence" where the reviewer said "good lead"). The two non-exact agreements:

| Case | Nishedh | Reviewer (and also acceptable) | Why it is ambiguous |
| --- | --- | --- | --- |
| 10 | information missing | not in registry (information missing) | Its only watchlist visual match is the misspelling "Cyclosinonie", 13th of 59. Nishedh matches the watchlist name exactly, so it did not treat this as a hit. |
| 28 | information missing | clear (information missing) | "Trichoderma bio fungicide": the genus is registered, but the species is not named. |

Per-case detail, including the reviewer's reasoning, is in [`results.json`](results.json).

## Scope evaluation: all 389 listings

The same kind of independent reviewer labelled **every** listing the searches surfaced ([`scope_cases.json`](scope_cases.json), [`scope_labels.json`](scope_labels.json)): is this product itself a pesticide, or radio equipment covered by the 2025 rules? [`scripts/evaluate_scope.py`](../scripts/evaluate_scope.py) compares that with Nishedh (a listing is in scope for Nishedh when it gets a finding).

| | Listings | In scope (reviewer) | Recall | Precision |
| --- | --- | --- | --- | --- |
| Pesticides | 233 | 161 | 99.4% (1 missed) | 97.0% (5 extra) |
| Radio equipment | 156 | 63 | 98.4% (1 missed) | 96.9% (2 extra) |

The 9 disagreements, in [`scope_results.json`](scope_results.json):

- **Missed (2):** an "organic" fungus remover that names no ingredient, and a walkie-talkie listed only as "Motorola T62".
- **Extra (7):**
  - Five are products that call themselves an insecticide or pest control but that the reviewer's brief put out of scope: tobacco dust, two neem or organic sprays, a "pest control solution" spray, and a household deltamethrin concentrate. Nishedh checks anything sold as a pesticide.
  - A book titled "The Baofeng Radio Revolution".
  - A truncated "walkie talkie" toy title.

  The rules were not tuned to these labels.

This evaluation was added after an external review found that scope was not measured. The same review found real misses, now fixed and pinned in `tests/test_scope_recall.py`: Syngenta Actara, Godrej Hitweed, Trichoderma, Beauveria and Metarhizium products, and five mobile signal boosters worded as "mobile phone signal booster", "Quad Band Signal Booster" or "Signal Booster For Cars … Cell Phones".

## Method

1. **Sample.** [`scripts/eval_cases.py`](../scripts/eval_cases.py) draws 52 listings from the demo replay with a fixed seed. It takes every pesticide finding above "weak signal", every registry mismatch, and random draws of weak signals, passes and radio findings. [`cases.json`](cases.json) holds only what a reviewer would see: the listing text, whether the product page was read, and the Google Lens visual-match titles. It does not include Nishedh's verdicts.
2. **Labels.** A separate AI model (Claude Fable, run as an independent reviewer) labelled each case. It had a written rulebook and the official registry data, and was barred from reading Nishedh's code, tests, cache or output. Its labels are in [`labels.json`](labels.json). It verified every chemical and strength against the parsed government lists.
3. **Compare.** [`scripts/evaluate.py`](../scripts/evaluate.py) compares the two and writes `results.json`.

Reproduce with `uv run nishedh demo --no-serve && uv run python scripts/evaluate.py && uv run python scripts/evaluate_scope.py`. The result above is for the current rules: after every change, the frozen set is re-scored.

## What this does and does not show

- **The reviewer is an AI model, not a human expert.** It was independent of Nishedh's code, but it is not a legal review.
- **It measures whether Nishedh applies its rulebook correctly to real listings**, not whether the rulebook matches the law in every case. The rulebook itself is sourced in the main README.
- **52 cases is a small sample, and not 52 independent scenarios.** Several are near-duplicates (the same product from different sellers, the same booster in several listings). It is weighted towards findings, because false flags are the most costly error, and every case is in scope, so it says nothing about scope. That is what the scope evaluation is for. It has no radio cases with an approval (ETA) number, because none of the radio listings stated one.
- **Found and fixed during this evaluation:**
  - The first export cut each listing's Lens matches to 15, which hid the Cyclosinone matches for case 2. The reviewer re-judged every Lens case with the full lists.
  - After labelling, five Lens titles in `cases.json` that were a seller's business-directory page ("Photos from …, Trader …") were replaced with a placeholder for privacy. They name no watchlist product, and no label depends on them.
  - Re-exporting the sample after later rule changes once reshuffled the case numbers against the labels. The set is now frozen: `eval_cases.py` refuses to overwrite it.
  - The reviewer noticed that some watchlist matches are weak: a few matches, ranked low. Nishedh now reports how many visual matches name the product and the rank of the best one. A weak match is a "weak signal", not a "good lead".
