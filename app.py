from __future__ import annotations

import pandas as pd
import streamlit as st

from src.config import DATABASE_PATH, DEFAULT_PAGE_SIZE
from src.database import connect, data_health, diagnostics_for_isin, lookup_values, null_rates, source_files
from src.ingest_firds import ingest_firds
from src.ingest_fitrs_equities import ingest_fitrs_equities
from src.instrument_profile import build_instrument_profile
from src.interpretations import decode_cfi, interpret_liquidity, interpret_reference_period
from src.live_esma import LIVE_PAGE_SIZE, live_firds_search, live_fitrs_search, live_isin_bundle
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
from src.ui_components import dataframe, empty_state, instrument_card, metric_row, pagination_controls, setup_instructions
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


@st.cache_data(ttl=120, show_spinner=False)
def cached_live_fitrs(term: str, start: int, rows: int):
    return live_fitrs_search(term, start=start, rows=rows)


@st.cache_data(ttl=120, show_spinner=False)
def cached_live_firds(term: str, start: int, rows: int):
    return live_firds_search(term, start=start, rows=rows)


@st.cache_data(ttl=120, show_spinner=False)
def cached_live_isin(isin: str, rows: int):
    return live_isin_bundle(isin, rows=rows)


def live_pager(source_key: str, total: int, rows: int = LIVE_PAGE_SIZE) -> int:
    state_key = f"{source_key}_start"
    if state_key not in st.session_state:
        st.session_state[state_key] = 0
    current = int(st.session_state[state_key])
    max_start = max(0, ((max(total, 1) - 1) // rows) * rows)
    current = min(max(current, 0), max_start)
    st.session_state[state_key] = current
    left, mid, right = st.columns([1, 2, 1])
    with left:
        if st.button("Previous 20", key=f"{source_key}_prev", disabled=current <= 0):
            st.session_state[state_key] = max(0, current - rows)
            st.rerun()
    with mid:
        end = min(current + rows, total)
        st.caption(f"Showing {current + 1 if total else 0:,}-{end:,} of {total:,} live ESMA rows.")
    with right:
        if st.button("Next 20", key=f"{source_key}_next", disabled=current + rows >= total):
            st.session_state[state_key] = current + rows
            st.rerun()
    return int(st.session_state[state_key])


def show_live_result(result, *, height: int = 360) -> None:
    if result.error:
        st.error(f"ESMA live query failed: {result.error}")
    elif result.frame.empty:
        empty_state(f"No live {result.source} results.")
    else:
        dataframe(result.frame, height=height)


conn = db_connection()
health = data_health(conn)

st.title("ESMA Equity Transparency and FIRDS Search")
st.caption(
    "Search ESMA Equity Transparency Calculation Results and connect them to FIRDS instrument reference data."
)

source_state = "No data loaded"
if health["fitrs_equity_results_rows"] or health["firds_instruments_rows"]:
    source_state = "Local DuckDB cache built from official ESMA register/Solr data"
else:
    source_state = "Live ESMA search mode; no local DuckDB cache loaded"

st.markdown(
    f"<span class='small-note'>Database: {DATABASE_PATH} | Source state: {source_state}</span>",
    unsafe_allow_html=True,
)

tabs = st.tabs(["Global Search", "ISIN Explorer", "Venue Explorer", "Liquidity Screener", "Data Health"])

with tabs[0]:
    st.subheader("Global Search")
    st.write("Search live ESMA FITRS equities and FIRDS. Results are fetched 20 rows at a time from ESMA.")
    term = st.text_input("Search term", placeholder="Example: XATH, NL0010273215, Allianz, Euronext")
    if term:
        fitrs_start = live_pager("global_fitrs", cached_live_fitrs(term, 0, LIVE_PAGE_SIZE).total)
        with st.spinner("Querying live ESMA FITRS equities..."):
            fitrs_live = cached_live_fitrs(term, fitrs_start, LIVE_PAGE_SIZE)
        st.markdown("**Live FITRS equity transparency results**")
        st.caption(f"ESMA query: `{fitrs_live.query}`")
        show_live_result(fitrs_live, height=360)

        firds_start = live_pager("global_firds", cached_live_firds(term, 0, LIVE_PAGE_SIZE).total)
        with st.spinner("Querying live ESMA FIRDS..."):
            firds_live = cached_live_firds(term, firds_start, LIVE_PAGE_SIZE)
        st.markdown("**Live FIRDS reference results**")
        st.caption(f"ESMA query: `{firds_live.query}`")
        show_live_result(firds_live, height=360)
    elif health["fitrs_equity_results_rows"] or health["firds_instruments_rows"]:
        st.info("Enter a term for live ESMA search, or use the other tabs to browse the local DuckDB cache.")
    else:
        st.info("Enter an ISIN or MIC to query ESMA live. No sample data is required.")

with tabs[1]:
    st.subheader("ISIN Explorer")
    isin = st.text_input("Enter ISIN", placeholder="Example: GRS014003032", key="isin_explorer").strip()
    if isin:
        isin_key = normalize_upper(isin)
        with st.spinner("Querying ESMA live for this ISIN..."):
            live = cached_live_isin(isin_key, LIVE_PAGE_SIZE)
        metric_row(
            {
                "Live FITRS matches": f"{live['fitrs'].total:,}",
                "Live FIRDS matches": f"{live['firds'].total:,}",
            }
        )

        fitrs_records = live["fitrs"].canonical.to_dict("records") if not live["fitrs"].canonical.empty else []
        firds_records = live["firds"].canonical.to_dict("records") if not live["firds"].canonical.empty else []
        local_loaded = bool(health["fitrs_equity_results_rows"] or health["firds_instruments_rows"])
        local_fitrs = local_firds = None
        if local_loaded:
            local_fitrs = isin_fitrs(conn, isin_key)
            local_firds = isin_firds(conn, isin_key)
            fitrs_records += local_fitrs.to_dict("records")
            firds_records += local_firds.to_dict("records")

        profile = build_instrument_profile(isin_key, fitrs_records, firds_records)
        cfi_decoding = decode_cfi(profile.cfi_code)
        st.markdown("#### Instrument card")
        instrument_card(
            profile.to_dict(),
            notices=[(n.level, n.message) for n in profile.notices],
            liquidity_text=interpret_liquidity(profile.liquidity_status),
            period_text=interpret_reference_period(profile.reference_period),
            cfi_text=cfi_decoding.description,
        )

        st.divider()
        st.markdown("**Live FITRS records for this ISIN**")
        show_live_result(live["fitrs"], height=360)
        st.markdown("**Live FIRDS records for this ISIN**")
        show_live_result(live["firds"], height=360)
        if local_loaded:
            st.markdown("**Local cache cross-check**")
            venues = isin_venues(conn, isin_key)
            st.caption(
                f"Local cache: {len(local_fitrs):,} FITRS rows, {len(local_firds):,} FIRDS rows, {len(venues):,} venues."
            )
            if not local_fitrs.empty:
                dataframe(local_fitrs, height=240)
            if not local_firds.empty:
                dataframe(local_firds, height=240)

with tabs[2]:
    st.subheader("Venue Explorer")
    st.write("Search a MIC live in ESMA FITRS. Results are returned 20 rows at a time.")
    venue_search_term = st.text_input("Search MIC or venue name", placeholder="Example: XATH", key="venue_search")
    if venue_search_term:
        venue_start = live_pager("venue_live_fitrs", cached_live_fitrs(venue_search_term, 0, LIVE_PAGE_SIZE).total)
        with st.spinner("Querying ESMA live for this venue/MIC..."):
            venue_live = cached_live_fitrs(venue_search_term, venue_start, LIVE_PAGE_SIZE)
        st.caption(f"ESMA query: `{venue_live.query}`")
        show_live_result(venue_live, height=520)
    elif health["fitrs_equity_results_rows"]:
        st.markdown("**Local cached venues**")
        venues = venue_lookup(conn, "", limit=1000)
        dataframe(venues, height=420)
    else:
        st.info("Enter a MIC such as `XATH` to query ESMA live.")

with tabs[3]:
    st.subheader("Liquidity Screener")
    if not health["fitrs_equity_results_rows"]:
        st.info("The screener uses local DuckDB data. Use Global Search, ISIN Explorer, or Venue Explorer for live ESMA 20-row searches without loading a local cache.")
    else:
        st.write("Filter all locally loaded FITRS equity records with paginated DuckDB queries.")
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
    if not health["fitrs_equity_results_rows"] and not health["firds_instruments_rows"]:
        st.info("No local DuckDB cache is loaded. The search pages still query ESMA live in 20-row pages.")
    else:
        st.markdown("**Source files / batches ingested**")
        dataframe(source_files(conn), height=300)
        st.markdown("**Missing/null rates for important fields**")
        dataframe(null_rates(conn), height=420)
