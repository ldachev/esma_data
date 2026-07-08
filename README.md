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
- **ISIN Explorer**: enter an ISIN and inspect live FITRS and FIRDS records.
- **Venue Explorer**: search a MIC such as `XATH` and page through live ESMA FITRS results 20 rows at a time.
- **Liquidity Screener**: filter by liquidity status, MIC, country, instrument type, calculation date, reference period, turnover, and transaction count when a local DuckDB cache is loaded.
- **Data Health**: inspect row counts, distinct ISINs/MICs, latest calculation date, source batches, and null rates.

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

## Known Limitations

- FIRDS is huge, so the default local command intentionally ingests a bounded slice.
- Some FITRS rows do not include an instrument name; FIRDS enrichment depends on matching loaded reference rows.
- MIC country and venue type fields are only as complete as the loaded FIRDS/venue metadata.
- ESMA schemas and field names vary across endpoints and publication formats; `src/schema_mapper.py` handles common aliases but may need extension for new file schemas.

## GitHub Pages

GitHub Pages can host the static overview under `docs/`, but it cannot run the Streamlit app. Deploy the interactive app to Streamlit Community Cloud or another Python app host.
