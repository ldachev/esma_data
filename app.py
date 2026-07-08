from __future__ import annotations

import pandas as pd
import streamlit as st

from src.config import DATABASE_PATH, DEFAULT_PAGE_SIZE
from src.database import connect, data_health, diagnostics_for_isin, lookup_values, null_rates, source_files
from src.ingest_firds import ingest_firds
from src.ingest_fitrs_equities import ingest_fitrs_equities
from src.search_index import (
    export_liquidity_screener,
    global_search,
    isin_firds,
    isin_fitrs,
    isin_venues,
    liquidity_screener,
    venue_instruments,
    venue_lookup,
)
from src.ui_components import dataframe, empty_state, metric_row, pagination_controls, setup_instructions
from src.utils import normalize_upper


st.set_page_config(page_title="ESMA Equity Search", page_icon="EU", layout="wide")

st.markdown(
    """
    <style>
    .block-container { padding-top: 1.3rem; }
    .small-note { color: #64748b; font-size: 0.9rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def db_connection():
    return connect()


@st.cache_data(ttl=300)
def cached_lookup(kind: str) -> list[str]:
    with connect() as conn:
        return lookup_values(conn, kind)


def selected_row(event, frame: pd.DataFrame) -> pd.Series | None:
    try:
        rows = event.selection.rows
    except Exception:
        rows = []
    if not rows:
        return None
    return frame.iloc[rows[0]]


def render_table_with_selection(df: pd.DataFrame, key: str):
    return st.dataframe(
        df,
        width="stretch",
        hide_index=True,
        height=420,
        selection_mode="single-row",
        on_select="rerun",
        key=key,
    )


def bootstrap_starter_data() -> None:
    """Load a small official ESMA dataset suitable for first Streamlit Cloud run."""

    conn.close()
    db_connection.clear()
    cached_lookup.clear()
    ingest_fitrs_equities(limit=20_000, batch_size=5_000, reset=True)
    ingest_firds(limit=5_000, batch_size=1_000, reset=True)


conn = db_connection()
health = data_health(conn)

st.title("ESMA Equity Transparency and FIRDS Search")
st.caption(
    "Search ESMA Equity Transparency Calculation Results and connect them to FIRDS instrument reference data."
)

source_state = "No data loaded"
if health["fitrs_equity_results_rows"] or health["firds_instruments_rows"]:
    source_state = "Local DuckDB cache built from official ESMA register/Solr data"

st.markdown(
    f"<span class='small-note'>Database: {DATABASE_PATH} | Source state: {source_state}</span>",
    unsafe_allow_html=True,
)

if not health["fitrs_equity_results_rows"] and not health["firds_instruments_rows"]:
    setup_instructions()
    st.markdown("**Streamlit Cloud quick start**")
    st.write(
        "Click the button below to load a starter dataset from the official ESMA registers. "
        "This writes a local DuckDB file inside the Streamlit Cloud app container."
    )
    if st.button("Load starter ESMA dataset", type="primary"):
        with st.spinner("Loading official ESMA FITRS/FIRDS starter data. This can take a minute..."):
            try:
                bootstrap_starter_data()
            except Exception as exc:
                st.error(f"Starter ingestion failed: {exc}")
                st.stop()
        st.success("Starter ESMA data loaded. Reloading the app...")
        st.rerun()
    st.stop()

tabs = st.tabs(["Global Search", "ISIN Explorer", "Venue Explorer", "Liquidity Screener", "Data Health"])

with tabs[0]:
    st.subheader("Global Search")
    st.write("Search by ISIN, MIC, venue name, or instrument name across FITRS equities and FIRDS.")
    term = st.text_input("Search term", placeholder="Example: XATH, NL0010273215, Allianz, Euronext")
    col_a, col_b = st.columns([1, 3])
    with col_a:
        page_size = st.selectbox("Rows per page", [25, 50, 100, 250], index=2, key="global_size")
    offset = 0
    if term:
        results = global_search(conn, term, limit=page_size, offset=offset)
        if results.empty:
            empty_state("No results found. Try a broader ISIN, MIC, venue, or name search.")
        else:
            event = render_table_with_selection(results, "global_results")
            row = selected_row(event, results)
            if row is not None:
                st.markdown("**Selected result details**")
                isin = row.get("isin")
                mic = row.get("mic")
                detail_cols = st.columns(2)
                with detail_cols[0]:
                    st.write(f"ISIN: `{isin}`")
                    dataframe(isin_fitrs(conn, str(isin)), height=260)
                with detail_cols[1]:
                    st.write(f"Venue/MIC: `{mic}`")
                    venue_df, total = venue_instruments(conn, str(mic), limit=50, offset=0)
                    st.caption(f"{total:,} FITRS records for this MIC.")
                    dataframe(venue_df, height=260)

with tabs[1]:
    st.subheader("ISIN Explorer")
    isin = st.text_input("Enter ISIN", placeholder="Example: GRS014003032", key="isin_explorer").strip()
    if isin:
        isin_key = normalize_upper(isin)
        fitrs = isin_fitrs(conn, isin_key)
        firds = isin_firds(conn, isin_key)
        venues = isin_venues(conn, isin_key)
        metric_row(
            {
                "FITRS records": f"{len(fitrs):,}",
                "FIRDS records": f"{len(firds):,}",
                "Venues/MICs": f"{len(venues):,}",
            }
        )
        if fitrs.empty and firds.empty:
            st.warning("This ISIN was not found in the currently loaded data.")
            st.json(diagnostics_for_isin(conn, isin_key))
        else:
            st.markdown("**All venues where this ISIN appears**")
            dataframe(venues, height=260)
            st.markdown("**FITRS equity transparency records**")
            dataframe(fitrs, height=360)
            st.markdown("**FIRDS reference records**")
            dataframe(firds, height=360)

with tabs[2]:
    st.subheader("Venue Explorer")
    st.write("Browse the full loaded venue/MIC universe, including smaller venues.")
    venue_search_term = st.text_input("Search MIC or venue name", placeholder="Example: XATH", key="venue_search")
    venues = venue_lookup(conn, venue_search_term, limit=1000)
    if venues.empty:
        empty_state("No venues match that search in the loaded data.")
    else:
        venue_event = render_table_with_selection(venues, "venue_results")
        selected = selected_row(venue_event, venues)
        default_mic = str(selected["mic"]) if selected is not None else str(venues.iloc[0]["mic"])
        selected_mic = st.text_input("Selected MIC", value=default_mic, key="selected_mic").strip()
        sort_col, dir_col, size_col = st.columns(3)
        with sort_col:
            sort_by = st.selectbox(
                "Sort instruments by",
                ["avg_daily_turnover", "avg_daily_transactions", "instrument_name", "isin", "liquidity_status"],
                index=0,
            )
        with dir_col:
            sort_desc = st.checkbox("Descending", value=True, key="venue_sort_desc")
        with size_col:
            page_size = st.selectbox("Page size", [50, 100, 250, 500], index=1, key="venue_page_size")
        preview_df, total = venue_instruments(conn, selected_mic, limit=1, offset=0)
        limit, offset = pagination_controls("Venue instruments", total, page_size)
        instruments, total = venue_instruments(conn, selected_mic, limit=limit, offset=offset, sort_by=sort_by, sort_desc=sort_desc)
        if instruments.empty:
            empty_state("No FITRS equity instruments are loaded for this venue/MIC.")
        else:
            dataframe(instruments, height=520)

with tabs[3]:
    st.subheader("Liquidity Screener")
    st.write("Filter all loaded FITRS equity records with paginated DuckDB queries.")
    with st.sidebar:
        st.header("Screener Filters")
        search = st.text_input("ISIN, MIC, or name contains", key="screen_search")
        liquidity = st.selectbox("Liquidity status", [""] + cached_lookup("liquidity"))
        mic = st.selectbox("MIC", [""] + cached_lookup("mic"))
        country = st.selectbox("Country", [""] + cached_lookup("country"))
        instrument_type = st.selectbox("Instrument type", [""] + cached_lookup("instrument_type"))
        reference_period = st.selectbox("Reference period", [""] + cached_lookup("reference_period"))
        min_turnover = st.number_input("Minimum average daily turnover", min_value=0.0, value=0.0, step=1000.0)
        min_transactions = st.number_input("Minimum average daily transactions", min_value=0.0, value=0.0, step=1.0)
        date_range = st.date_input("Calculation date range", value=())
    sort_col, dir_col, size_col = st.columns(3)
    with sort_col:
        sort_by = st.selectbox(
            "Sort by",
            ["avg_daily_turnover", "avg_daily_transactions", "calculation_date", "instrument_name", "isin", "mic", "liquidity_status"],
            index=0,
        )
    with dir_col:
        sort_desc = st.checkbox("Descending", value=True, key="screen_sort_desc")
    with size_col:
        page_size = st.selectbox("Rows per page", [50, 100, 250, 500, 1000], index=1, key="screen_page_size")

    date_from = date_to = None
    if isinstance(date_range, tuple) and len(date_range) == 2:
        date_from, date_to = date_range
    filters = {
        "search": search,
        "liquidity_status": liquidity or None,
        "mic": mic or None,
        "country": country or None,
        "instrument_type": instrument_type or None,
        "reference_period": reference_period or None,
        "min_turnover": min_turnover if min_turnover else None,
        "min_transactions": min_transactions if min_transactions else None,
        "date_from": date_from,
        "date_to": date_to,
        "sort_by": sort_by,
        "sort_desc": sort_desc,
    }
    _first, total = liquidity_screener(conn, filters, limit=1, offset=0)
    limit, offset = pagination_controls("Screener", total, page_size)
    screen_df, total = liquidity_screener(conn, filters, limit=limit, offset=offset)
    if screen_df.empty:
        empty_state("No records match the current screener filters.")
        if search:
            st.json(diagnostics_for_isin(conn, search, {"mic": mic}))
    else:
        dataframe(screen_df, height=520)
        export_df = export_liquidity_screener(conn, filters)
        st.download_button(
            "Export filtered results as CSV",
            data=export_df.to_csv(index=False).encode("utf-8"),
            file_name="esma_liquidity_screener_export.csv",
            mime="text/csv",
        )

with tabs[4]:
    st.subheader("Data Health")
    metric_row(
        {
            "FITRS rows": f"{health['fitrs_equity_results_rows']:,}",
            "FIRDS rows": f"{health['firds_instruments_rows']:,}",
            "Distinct ISINs": f"{health['distinct_isins']:,}",
            "Distinct MICs": f"{health['distinct_mics']:,}",
            "Latest calculation date": health["latest_calculation_date"] or "N/A",
        }
    )
    st.markdown("**Source files / batches ingested**")
    dataframe(source_files(conn), height=300)
    st.markdown("**Missing/null rates for important fields**")
    dataframe(null_rates(conn), height=420)
