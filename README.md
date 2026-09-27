# Nishedh (निषेध)

**Nishedh checks what India's online marketplaces are selling against the government's own registries, and hands a human reviewer the evidence.**

In September 2026 India's consumer regulator (CCPA) fined Amazon and Flipkart ₹10 lakh each, and JioMart ₹5 lakh, for selling "Cyclosinone Herbicide", a weed killer whose chemical exists in no official list. Flipkart alone had sold 5.47 lakh units (₹11.58 crore) since January 2024, some listed under "Plant Seed" and "Bathing Bars & Soaps". The regulator ordered all three marketplaces to audit their catalogues within 15 days and said that relying on seller self-declarations was "gross negligence" ([CCPA orders](https://ccpa.doca.gov.in/)).

Nishedh is that audit, run from the outside with live search data from [SerpApi](https://serpapi.com).

![Dashboard: listings flagged for review](docs/dashboard.png)

## What it found on its first live run (27 Sep 2026)

| Pack | Listings found | In scope | Flagged for review (high/medium) | Searches used |
| --- | --- | --- | --- | --- |
| Pesticides | 233 | 160 | 7 not in registry, 1 missing information (high), 12 missing information (medium) | 31 |
| Radio equipment | 156 | 59 | 13 mobile signal boosters, 2 radios on licensed bands | 4 |

- **Five Amazon.in listings sold without any chemical named** ("5% Active Formula", "organic herbicide") use a product photo that Google Lens finds elsewhere under the name **"Cyclosinone"**, the product the regulator penalised days earlier.
- **13 mobile signal boosters** are listed for sale, although the regulator's 2025 guidelines say platforms "shall not allow listing or sale of mobile signal boosters and wireless jammers" ([PIB](https://www.pib.gov.in/PressReleasePage.aspx?PRID=2132575)).
- **Baofeng radios stating 136–174 and 400–470 MHz**, bands that need a licence; walkie-talkies are licence-exempt only in 446.0–446.2 MHz.

Every result is a prompt for human review, never a legal finding. A matching photo is a lead, not proof.

## Why SerpApi is essential

Nishedh cannot see a single listing without SerpApi: there is no Flipkart or JioMart API, and Amazon.in blocks direct requests.

| SerpApi engine | What Nishedh uses it for |
| --- | --- |
| Google Shopping (`gl=in`) | Offers across Indian stores for each product category |
| Amazon Search + Amazon Product (`amazon.in`) | Listing titles, then full descriptions, bullet points and specifications for suspicious listings |
| Google Search (`site:flipkart.com`, `site:jiomart.com`) | Flipkart and JioMart product pages |
| Google Lens | The label check: what is the same product photo called elsewhere? |

## How it works

1. **Sweep** a product category through SerpApi, merge duplicates, and fetch product pages for listings not cleared by their title.
2. **Read** each listing: which chemicals it names (exact, fuzzy, trade-name and abbreviation matching against the official vocabulary), strengths and formulation codes, "5% active formula" claims with no chemical; or, for radios, frequencies, approval numbers and "licence-free" claims.
3. **Check** against the official source:
   - CIB&RC lists (registered molecules and formulations, banned, refused, withdrawn, restricted) and the Schedule to the Insecticides Act, parsed from the [government PDFs](https://ppqs.gov.in/divisions/cib-rc/registered-products), each verified by SHA-256;
   - the CCPA radio-equipment guidelines (2025) and the Department of Telecommunications' public Equipment Type Approval certificates, which catch approval numbers borrowed from another product.
4. **Label check** with Google Lens for listings that name no chemical, plus a watchlist of products named in regulator orders.
5. **Review** in a local dashboard: every finding opens as a "why was this flagged?" chain from the listing, to the exact words and where they appeared, to the official source with its link, to the result, with links to the raw SerpApi responses. Findings export to CSV/JSON and to a draft request for review.

![Why was this flagged?](docs/why-flagged.png)

Each finding carries one reason code: `banned_item`, `not_in_registry`, `information_missing`, `registry_mismatch` or `clear`, with a confidence level. A finding based only on a search-result title is low confidence and says so.

## Run it

```bash
uv sync
echo "SERPAPI_API_KEY=your_key" > .env        # free plan: 250 searches/month
uv run nishedh sweep pesticides --live --max-live 40
uv run nishedh sweep radio --live --max-live 30
uv run nishedh serve                           # dashboard at http://127.0.0.1:8787
uv run nishedh report pesticides --format csv  # or json
uv run nishedh budget                          # searches used this month
```

Without `--live`, a sweep replays cached SerpApi responses and costs nothing.

## Engineering

- **Budget-safe SerpApi client**: every response is cached by its parameters and never paid for twice; a monthly cap stops live calls; retries with backoff; the API key never reaches disk, logs or error messages.
- **Registry parsing**: the official PDFs silently skip serial numbers, repeat others, and misspell 56 chemical names (including in the registered list itself); each case is handled and pinned by tests against the real PDFs.
- **Precision first**: three independent code reviews focused on wrong flags. Ordinary products (a copper water bottle, a cotton tunic, a football jersey, a mouthwash, Wi-Fi extenders, phone cases, a book) are pinned as "must not flag" tests.
- **Privacy**: seller and small-store names stay in the local evidence store; the dashboard, exports and complaint drafts name only major marketplaces.
- 166 tests, `ruff`, `mypy --strict`, CI on every push.

```
src/nishedh/
  search/client.py      SerpApi access: cache, budget, retries
  registry/             official pesticide lists, ETA certificates, name normalisation
  extract/              what a listing says (pesticides, radio equipment)
  verdict/              rules and reason codes
  lens.py               Google Lens label check
  sweep.py, store.py    pipeline and evidence store
  web/                  review dashboard
```

## Limits

- Only what a listing shows can be checked; a label printed only on a product photo needs the Lens check or a person.
- Flipkart and JioMart are reached through Google and appear less often than Amazon.in.
- The registries are snapshots (dates in `data/registry/sources.json`); a newly registered product can look unregistered until the list is refreshed.
- Findings are leads for review. They are not legal determinations, and nothing here should be read as an accusation against any seller.

## AI tools

Built with Claude Code (Anthropic) as a coding assistant: research, implementation, tests and independent code reviews.

## License

MIT
