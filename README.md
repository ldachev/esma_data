# ESMA Securities Liquidity Dashboard

Interactive Streamlit dashboard for exploring securities traded on regulated European trading venues using ESMA-style FIRDS, FITRS, and MIC/trading venue fields.

The project is structured as a GitHub-ready Python MVP. It starts with equities/shares and a small fallback dataset so the app runs offline, while leaving a clear ingestion path for larger production ESMA files.

## What It Does

- Search securities by ISIN and instrument name.
- Filter by asset class, MIC code, venue type, country, liquidity status, and calculation/reference date.
- View headline KPIs for instruments, venues, liquid instruments, and the top venue.
- Explore charts for top venues by instrument count, top venues by turnover, and asset class distribution.
- Sort and inspect an interactive table.
- Export filtered results to CSV.
- Cache raw ESMA files under `data/raw/` and processed data under `data/processed/`.
- Store processed data in DuckDB, with SQLite fallback if DuckDB is unavailable.

## ESMA Data Sources

The code is designed around these public ESMA datasets and concepts:

- **FIRDS**: Financial Instruments Reference Data System, used for instrument identifiers and reference attributes.
- **FITRS**: Financial Instruments Transparency System, used for transparency and liquidity calculations such as liquidity status, average daily turnover, and average daily number of transactions.
- **MiFID II trading venue metadata**: MIC code, trading venue name, venue type, and country where available.

The live ingestion helper queries ESMA public register indexes:

- `https://registers.esma.europa.eu/solr/esma_registers_firds_files/select`
- `https://registers.esma.europa.eu/solr/esma_registers_fitrs_files/select`

The project also detects the optional `esma_data_py` package when installed. It is not pinned in `requirements.txt` because the public distribution name can differ from the import name; install it from the official ESMA GitHub/package instructions for your environment, then the dashboard will report that it is available. The current MVP keeps that integration conservative because ESMA files can be large and schemas vary by file type.

## Project Structure

```text
.
├── app.py
├── requirements.txt
├── README.md
├── data/
│   ├── raw/
│   └── processed/
└── src/
    ├── __init__.py
    ├── config.py
    ├── database.py
    ├── data_processing.py
    └── esma_client.py
```

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
streamlit run app.py
```

The app starts with sample data if no processed ESMA data exists. In the sidebar, enable **Try live ESMA refresh** and click **Reload data** to attempt a small live ESMA download into `data/raw/`. Very large ESMA archives are skipped by default to keep the MVP responsive.

## GitHub Pages

GitHub Pages can display this repository's static project overview from `docs/index.html`, but it cannot run the interactive Streamlit dashboard because Pages only serves static files. For the live app, deploy to Streamlit Community Cloud or another Python app host.

## Data Pipeline

1. `src/esma_client.py` downloads or loads ESMA register-backed files.
2. Raw files are cached locally under `data/raw/firds/` and `data/raw/fitrs/`.
3. `src/data_processing.py` parses CSV, XML, JSON, Excel, or ZIP inputs where possible.
4. Column names are normalized through a schema mapping layer to reduce fragility across ESMA file variants.
5. FIRDS reference rows and FITRS liquidity rows are joined on ISIN and MIC code where available.
6. Processed data is saved to `data/processed/securities_liquidity.csv`.
7. `src/database.py` stores the processed dataset in DuckDB for fast filtering.

## Known Limitations

- The live ingestion path intentionally downloads only a small number of files by default and skips archives larger than 75 MB.
- Full FIRDS/FITRS production ingestion may require streaming XML parsing and dataset-specific schema handlers because ESMA files can be very large.
- Venue type and country are populated only when present in the source data or fallback sample.
- The bundled sample data is illustrative and should not be treated as official ESMA calculations.

## Future Improvements

- Add production-grade streaming parsers for large FIRDS and FITRS XML archives.
- Expand beyond shares/equities to bonds, derivatives, ETFs, and structured finance products.
- Add scheduled refresh jobs and incremental DuckDB loading.
- Add a dedicated MIC/trading venue reference ingestion source.
- Add tests for schema normalization and joins.
- Add deployment instructions for Streamlit Community Cloud or another hosting target.
