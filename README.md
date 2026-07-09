# ESMA Equity Transparency and FIRDS Search

Production-style local Streamlit application for searching ESMA equity transparency calculation results and connecting them to FIRDS instrument reference data.

This is not a leaderboard dashboard. It is a DuckDB-backed search and browsing wrapper over official ESMA register/Solr data.

## What It Uses

### ESMA FITRS Equities

ESMA Equity Transparency Calculation Results are published through the FITRS equities register:

`https://registers.esma.europa.eu/publication/searchRegister?core=esma_registers_fitrs_equities`

These records include equity transparency and liquidity calculation fields such as:

- ISIN
- MIC / most relevant market
- MiFIR identifier
- CFI code
- liquidity flag
- average daily turnover
- average daily number of transactions
- calculation date
- reference/calculation period

### ESMA FIRDS

FIRDS is the Financial Instruments Reference Data System:

`https://registers.esma.europa.eu/publication/searchRegister?core=esma_registers_firds`

FIRDS contains instrument reference records such as:

- ISIN
- full and short instrument names
- CFI/classification
- issuer LEI
- MIC / trading venue
- admission and termination dates
- reference country / RCA fields where available

## How FITRS and FIRDS Relate

FITRS gives transparency and liquidity calculations. FIRDS gives instrument reference attributes. The app joins them where possible on `ISIN` and `MIC`, but it deliberately does not drop unmatched records.

Some ISINs can appear in FITRS but not in the loaded FIRDS slice, and vice versa. Reasons include:

- FIRDS is vastly larger than FITRS and may be ingested only as a bounded local slice.
- ESMA publishes different registers on different schedules.
- FITRS equity calculations are specific to transparency calculations, while FIRDS is broader reference data.
- MIC or instrument identifiers can differ across historical records.

## Project Structure

```text
.
├── app.py
├── src/
│   ├── esma_sources.py
│   ├── ingest_fitrs_equities.py
│   ├── ingest_firds.py
│   ├── schema_mapper.py
│   ├── search_index.py
│   ├── database.py
│   ├── live_esma.py
│   ├── instrument_profile.py
│   ├── interpretations.py
│   ├── portfolio.py
│   ├── ui_components.py
│   └── utils.py
├── data/
│   ├── raw/
│   ├── processed/
│   └── cache/
├── tests/
├── requirements.txt
└── README.md
```

- `src/instrument_profile.py` — pure logic that merges FITRS + FIRDS records for one ISIN into a
  single `InstrumentProfile`, with explicit gap/conflict reconciliation notices when a register is
  missing or the two registers disagree (e.g. different CFI code or most-relevant MIC).
- `src/interpretations.py` — plain-language MiFID II context for raw field values: what the
  liquidity flag means for transparency obligations, what the reference/calculation period covers,
  and a curated ISO 10962 CFI code decoder. Kept separate from UI code so the mapping is easy to
  review and extend.
- `src/portfolio.py` — ISIN watchlist logic: ISO 6166 format + Luhn check-digit validation,
  bulk-paste parsing, JSON/CSV import/export, and an `InMemoryPortfolioStore` that wraps a mutable
  mapping (the app uses `st.session_state`) behind a `load`/`save`/`add`/`remove` interface, so a
  real per-user database backend could be swapped in later without touching the UI.

## Install

```bash
pip install -r requirements.txt
```

## Ingest Data

Load all currently available ESMA FITRS equity transparency results:

```bash
python -m src.ingest_fitrs_equities
```

Load a bounded FIRDS reference slice:

```bash
python -m src.ingest_firds
```

FIRDS is extremely large. The default FIRDS command loads a bounded slice so the local app remains practical. To change this:

```bash
python -m src.ingest_firds --limit 100000
python -m src.ingest_firds --limit 0
```

Use `--limit 0` only when you intentionally want an unbounded production-scale ingest.

Useful options:

```bash
python -m src.ingest_fitrs_equities --reset --batch-size 10000
python -m src.ingest_firds --reset --limit 50000 --batch-size 1000
python -m src.ingest_firds --query "type_s:parent AND isin:GRS014003032"
```

## Run

```bash
streamlit run app.py
```

If no local DuckDB data is loaded, the app still works in live ESMA search mode. Global Search, ISIN Explorer, and Venue Explorer query ESMA directly and return 20 rows at a time.

## Streamlit Cloud First Run

Streamlit Cloud does not receive your local DuckDB file. That is fine: the deployed app now starts in **live ESMA search mode**.

In live mode:

- Search results are fetched directly from ESMA public Solr/register endpoints.
- The app shows the first 20 rows.
- Use **Next 20** and **Previous 20** to page through more ESMA results.
- No sample or fake data is required.

The local DuckDB ingestion commands are still available for heavier local analytics and the Liquidity Screener.

## App Pages

- **Global Search**: live search ISIN/MIC fields against FITRS and FIRDS, 20 ESMA rows at a time.
  Above the pager, a total-match count and liquidity/venue distribution charts summarize the *full*
  live result set (via ESMA Solr faceting), not just the visible page. Each result block has a CSV
  export and a live/cached provenance badge with an "as of" timestamp.
- **ISIN Explorer**: enter an ISIN and see a synthesized **instrument card** above the existing raw
  FITRS/FIRDS tables (which are unchanged). The card reconciles both registers — preferring the
  FIRDS name/CFI code and the FITRS most-relevant-market MIC — and surfaces explicit reconciliation
  notices when a register has no match or the two registers disagree. An expander decodes the
  liquidity flag, reference period, and CFI code into plain-language MiFID II context. Works from
  live data alone and cross-checks the local cache when one is loaded. Raw tables and local
  cross-check rows each have CSV export.
- **Venue Explorer**: search a MIC such as `XATH` and page through live ESMA FITRS results 20 rows
  at a time, with a total-match count, a liquidity split chart over the full result set, and CSV
  export.
- **Liquidity Screener**: filter by liquidity status, MIC, country, instrument type, calculation
  date, reference period, turnover, and transaction count when a local DuckDB cache is loaded. A
  "full result set overview" above the page grid shows totals plus charts for liquid/non-liquid
  split, turnover distribution, venue/country breakdown, and calculation-date coverage by month —
  computed via SQL aggregates over all matching rows, not just the current page. Export as CSV or
  Excel.
- **Portfolio**: save ISINs to a watchlist (single entry or bulk paste, both ISO 6166
  format/check-digit validated), persisted in the browser session and importable/exportable as
  JSON or CSV so a list can be saved and reloaded. Each saved ISIN is enriched with the same
  instrument-profile logic as the ISIN Explorer (name, venue, liquidity, turnover, transactions,
  calculation date), with a portfolio-level summary (liquid/non-liquid split, venue breakdown,
  mean turnover) and CSV/Excel export of the enriched table. Row actions let you open an ISIN in
  the ISIN Explorer or remove it from the list.
- **Data Health**: inspect row counts, distinct ISINs/MICs, latest calculation date, per-table last
  ingestion timestamp, source batches, and null rates.

## Instrument Card & Interpretation Layer

The ISIN Explorer's instrument card (`src/instrument_profile.py` + `src/interpretations.py`) is the
one place in the app that answers "what is this instrument and is it liquid, in plain terms?"
without you having to cross-reference two raw registers by hand. It never drops or hides unmatched
data: if FITRS has no calculation for the ISIN, or FIRDS has no reference row, or the two registers
disagree on CFI code or MIC, that is shown as an explicit notice rather than silently picking one
side.

## Portfolio Tracker

The Portfolio tab is a lightweight watchlist, not a brokerage account: it stores a list of ISINs in
`st.session_state` for the current browser session, with JSON/CSV import/export so you can save and
reload a list across sessions (Streamlit Cloud has no per-user database). The storage layer
(`src/portfolio.py`) is written behind a small `load`/`save`/`add`/`remove` interface so a real
per-user backend could replace `InMemoryPortfolioStore` later without changing the Portfolio tab UI.
Bulk enrichment of many ISINs reuses the same `@st.cache_data`-wrapped live lookup as the ISIN
Explorer, so adding 50 ISINs only fires uncached live ESMA calls once per ISIN per cache window
(120s), not on every rerun.

## Shareable Links

Global Search term, ISIN Explorer ISIN, Venue Explorer MIC, and Liquidity Screener filters
(search/liquidity/MIC/country/instrument type/reference period/sort) are synced to the URL via
`st.query_params`, so a specific view can be bookmarked or shared and is restored on load. Visiting
the app with no query params behaves exactly as before. Streamlit does not support switching the
active tab programmatically, so a deep link restores the *state* of a tab; you still click the tab
to view it.

## Provenance & Freshness

Every result view — Global Search, ISIN Explorer, Venue Explorer, Liquidity Screener, and
Portfolio, not just Data Health — shows a `LIVE` or `CACHED` badge alongside the source register
and an "as of" timestamp. For live results this is the time of the actual ESMA request (accurate
under the existing cache TTLs); for local-cache results it is the most recent ingestion timestamp
for that table, also now surfaced as explicit metrics on the Data Health tab.

## Searching

Search is case-insensitive for ISIN and MIC fields. Examples:

```text
XATH
GRS014003032
NL0010273215
```

Partial text search is supported for venue and instrument names where those names are loaded from FIRDS or available in FITRS.

## Local Database

The app stores normalized data in:

```text
data/processed/esma_search.duckdb
```

Logical tables:

- `fitrs_equity_results`
- `firds_instruments`
- `trading_venues`

The app queries DuckDB directly using SQL with `LIMIT` / `OFFSET` pagination and avoids loading the full dataset into Streamlit memory.

## Tests

```bash
python -m pytest -q
```

Tests cover:

- alternate ESMA column-name mapping
- case-insensitive ISIN and MIC search
- non-top venue browsing
- liquidity sorting
- FITRS/FIRDS joins without dropping unmatched records
- operation when only FITRS or only FIRDS is loaded
- full-result-set screener aggregates (`screener_summary`)
- Solr facet-pair parsing (`parse_facet_pairs`)
- instrument profile merge/reconcile logic, including gap and conflict notices
- MiFID II interpretation text (liquidity flag, reference period, CFI decoding)
- ISIN format/check-digit validation, bulk parsing, and portfolio JSON/CSV import-export

## Dependencies

No new third-party dependencies were added for this work; `requirements.txt` is unchanged. Excel
export (Liquidity Screener, Portfolio) uses `openpyxl`, which was already a dependency. Live
aggregate summaries use the ESMA Solr endpoints' existing faceting support via plain HTTP
(`requests`, already a dependency) — no new client library required.

## Known Limitations

- FIRDS is huge, so the default local command intentionally ingests a bounded slice.
- Some FITRS rows do not include an instrument name; FIRDS enrichment depends on matching loaded reference rows.
- MIC country and venue type fields are only as complete as the loaded FIRDS/venue metadata.
- ESMA schemas and field names vary across endpoints and publication formats; `src/schema_mapper.py` handles common aliases but may need extension for new file schemas.
- The CFI code decoder in `src/interpretations.py` covers a curated subset of ISO 10962
  category/group letters (enough for the equity/CIV instruments this app deals with); codes outside
  that subset are labeled as unrecognized rather than guessed.
- Screener deep links cover the categorical filters and sort order; the minimum turnover/transaction
  thresholds and the calculation-date range are not synced to the URL.
- Streamlit cannot switch the active tab programmatically, so opening a deep link or an "Open in
  ISIN Explorer" portfolio action preloads that tab's state, but you still click the tab to view it.
- The Portfolio watchlist lives in `st.session_state` for the current browser session only; use the
  JSON/CSV export to persist it across sessions or share it.

## GitHub Pages

GitHub Pages can host the static overview under `docs/`, but it cannot run the Streamlit app. Deploy the interactive app to Streamlit Community Cloud or another Python app host.
