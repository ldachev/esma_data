from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from src.config import DATABASE_PATH, DEFAULT_PAGE_SIZE
from src.database import connect, data_health, diagnostics_for_isin, lookup_values, null_rates, source_files
from src.ingest_firds import ingest_firds
from src.ingest_fitrs_equities import ingest_fitrs_equities
from src.instrument_profile import build_instrument_profile
from src.interpretations import classify_liquidity, decode_cfi, interpret_liquidity, interpret_reference_period
from src.live_esma import (
    LIVE_PAGE_SIZE,
    live_firds_search,
    live_fitrs_liquidity_breakdown,
    live_fitrs_search,
    live_fitrs_venue_breakdown,
    live_isin_bundle,
)
from src.portfolio import (
    InMemoryPortfolioStore,
    is_valid_isin,
    parse_bulk_isins,
    portfolio_from_csv,
    portfolio_from_json,
    portfolio_to_csv,
    portfolio_to_json,
)
from src.search_index import (
    export_liquidity_screener,
    global_search,
    isin_firds,
    isin_fitrs,
    isin_venues,
    liquidity_screener,
    screener_summary,
    venue_instruments,
    venue_lookup,
)
from src.ui_components import (
    csv_download_button,
    dataframe,
    empty_state,
    facet_bar_chart,
    instrument_card,
    metric_row,
    pagination_controls,
    setup_instructions,
)
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


@st.cache_data(ttl=120, show_spinner=False)
def cached_fitrs_liquidity_breakdown(term: str):
    return live_fitrs_liquidity_breakdown(term)


@st.cache_data(ttl=120, show_spinner=False)
def cached_fitrs_venue_breakdown(term: str):
    return live_fitrs_venue_breakdown(term)


@st.cache_data(ttl=120, show_spinner=False)
def cached_isin_profile(isin_key: str, use_local: bool) -> dict:
    live = cached_live_isin(isin_key, LIVE_PAGE_SIZE)
    fitrs_records = live["fitrs"].canonical.to_dict("records") if not live["fitrs"].canonical.empty else []
    firds_records = live["firds"].canonical.to_dict("records") if not live["firds"].canonical.empty else []
    if use_local:
        with connect() as local_conn:
            fitrs_records += isin_fitrs(local_conn, isin_key).to_dict("records")
            firds_records += isin_firds(local_conn, isin_key).to_dict("records")
    return build_instrument_profile(isin_key, fitrs_records, firds_records).to_dict()


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


def set_query_param(param: str, value: str | None) -> None:
    """Write (or clear) a URL query param so the current view is bookmarkable/shareable."""

    if value:
        st.query_params[param] = value
    elif param in st.query_params:
        del st.query_params[param]


def seed_text_state(session_key: str, param: str) -> None:
    """Seed a text widget's session_state from a URL query param, but only before it exists
    (i.e. on first load of this browser session) so later user edits always win."""

    if session_key not in st.session_state and param in query_params:
        st.session_state[session_key] = query_params[param]


def seed_choice_state(session_key: str, param: str, *, options: list, default) -> None:
    if session_key in st.session_state:
        return
    value = query_params.get(param)
    st.session_state[session_key] = value if value in options else default


conn = db_connection()
health = data_health(conn)
query_params = st.query_params

if "portfolio_open_isin_request" in st.session_state:
    st.session_state["isin_explorer"] = st.session_state.pop("portfolio_open_isin_request")
else:
    seed_text_state("isin_explorer", "isin")
seed_text_state("venue_search", "mic")
seed_text_state("global_search_term", "q")

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

tabs = st.tabs(["Global Search", "ISIN Explorer", "Venue Explorer", "Liquidity Screener", "Portfolio", "Data Health"])

with tabs[0]:
    st.subheader("Global Search")
    st.write("Search live ESMA FITRS equities and FIRDS. Results are fetched 20 rows at a time from ESMA.")
    term = st.text_input(
        "Search term", placeholder="Example: XATH, NL0010273215, Allianz, Euronext", key="global_search_term"
    )
    set_query_param("q", term)
    if term:
        fitrs_total = cached_live_fitrs(term, 0, LIVE_PAGE_SIZE).total
        st.markdown("**Live FITRS equity transparency results**")
        metric_row({"Total FITRS matches": f"{fitrs_total:,}"})
        agg_col1, agg_col2 = st.columns(2)
        with agg_col1:
            st.caption("Liquidity split across all matches")
            facet_bar_chart(cached_fitrs_liquidity_breakdown(term), label="liquidity")
        with agg_col2:
            st.caption("Top venues across all matches")
            facet_bar_chart(cached_fitrs_venue_breakdown(term), label="venue")
        fitrs_start = live_pager("global_fitrs", fitrs_total)
        with st.spinner("Querying live ESMA FITRS equities..."):
            fitrs_live = cached_live_fitrs(term, fitrs_start, LIVE_PAGE_SIZE)
        st.caption(f"ESMA query: `{fitrs_live.query}`")
        show_live_result(fitrs_live, height=360)
        csv_download_button(
            fitrs_live.frame, label="Export this page (20 rows) as CSV", file_name="esma_fitrs_global_search.csv", key="global_fitrs_csv"
        )

        firds_total = cached_live_firds(term, 0, LIVE_PAGE_SIZE).total
        st.markdown("**Live FIRDS reference results**")
        metric_row({"Total FIRDS matches": f"{firds_total:,}"})
        firds_start = live_pager("global_firds", firds_total)
        with st.spinner("Querying live ESMA FIRDS..."):
            firds_live = cached_live_firds(term, firds_start, LIVE_PAGE_SIZE)
        st.caption(f"ESMA query: `{firds_live.query}`")
        show_live_result(firds_live, height=360)
        csv_download_button(
            firds_live.frame, label="Export this page (20 rows) as CSV", file_name="esma_firds_global_search.csv", key="global_firds_csv"
        )
    elif health["fitrs_equity_results_rows"] or health["firds_instruments_rows"]:
        st.info("Enter a term for live ESMA search, or use the other tabs to browse the local DuckDB cache.")
    else:
        st.info("Enter an ISIN or MIC to query ESMA live. No sample data is required.")

with tabs[1]:
    st.subheader("ISIN Explorer")
    isin = st.text_input("Enter ISIN", placeholder="Example: GRS014003032", key="isin_explorer").strip()
    set_query_param("isin", isin)
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
        csv_download_button(live["fitrs"].frame, label="Export as CSV", file_name=f"esma_fitrs_{isin_key}.csv", key="isin_fitrs_csv")
        st.markdown("**Live FIRDS records for this ISIN**")
        show_live_result(live["firds"], height=360)
        csv_download_button(live["firds"].frame, label="Export as CSV", file_name=f"esma_firds_{isin_key}.csv", key="isin_firds_csv")
        if local_loaded:
            st.markdown("**Local cache cross-check**")
            venues = isin_venues(conn, isin_key)
            st.caption(
                f"Local cache: {len(local_fitrs):,} FITRS rows, {len(local_firds):,} FIRDS rows, {len(venues):,} venues."
            )
            if not local_fitrs.empty:
                dataframe(local_fitrs, height=240)
                csv_download_button(
                    local_fitrs, label="Export local FITRS rows as CSV", file_name=f"local_fitrs_{isin_key}.csv", key="isin_local_fitrs_csv"
                )
            if not local_firds.empty:
                dataframe(local_firds, height=240)
                csv_download_button(
                    local_firds, label="Export local FIRDS rows as CSV", file_name=f"local_firds_{isin_key}.csv", key="isin_local_firds_csv"
                )

with tabs[2]:
    st.subheader("Venue Explorer")
    st.write("Search a MIC live in ESMA FITRS. Results are returned 20 rows at a time.")
    venue_search_term = st.text_input("Search MIC or venue name", placeholder="Example: XATH", key="venue_search")
    set_query_param("mic", venue_search_term)
    if venue_search_term:
        venue_total = cached_live_fitrs(venue_search_term, 0, LIVE_PAGE_SIZE).total
        metric_row({"Total matches": f"{venue_total:,}"})
        st.caption("Liquidity split across all matches")
        facet_bar_chart(cached_fitrs_liquidity_breakdown(venue_search_term), label="liquidity")
        venue_start = live_pager("venue_live_fitrs", venue_total)
        with st.spinner("Querying ESMA live for this venue/MIC..."):
            venue_live = cached_live_fitrs(venue_search_term, venue_start, LIVE_PAGE_SIZE)
        st.caption(f"ESMA query: `{venue_live.query}`")
        show_live_result(venue_live, height=520)
        csv_download_button(
            venue_live.frame, label="Export this page (20 rows) as CSV", file_name="esma_venue_explorer.csv", key="venue_live_csv"
        )
    elif health["fitrs_equity_results_rows"]:
        st.markdown("**Local cached venues**")
        venues = venue_lookup(conn, "", limit=1000)
        dataframe(venues, height=420)
        csv_download_button(venues, label="Export as CSV", file_name="esma_local_venues.csv", key="venue_local_csv")
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
            seed_text_state("screen_search", "scr_search")
            search = st.text_input("ISIN, MIC, or name contains", key="screen_search")

            liquidity_options = [""] + cached_lookup("liquidity")
            seed_choice_state("screen_liquidity", "scr_liquidity", options=liquidity_options, default="")
            liquidity = st.selectbox("Liquidity status", liquidity_options, key="screen_liquidity")

            mic_options = [""] + cached_lookup("mic")
            seed_choice_state("screen_mic", "scr_mic", options=mic_options, default="")
            mic = st.selectbox("MIC", mic_options, key="screen_mic")

            country_options = [""] + cached_lookup("country")
            seed_choice_state("screen_country", "scr_country", options=country_options, default="")
            country = st.selectbox("Country", country_options, key="screen_country")

            type_options = [""] + cached_lookup("instrument_type")
            seed_choice_state("screen_type", "scr_type", options=type_options, default="")
            instrument_type = st.selectbox("Instrument type", type_options, key="screen_type")

            period_options = [""] + cached_lookup("reference_period")
            seed_choice_state("screen_period", "scr_period", options=period_options, default="")
            reference_period = st.selectbox("Reference period", period_options, key="screen_period")

            min_turnover = st.number_input("Minimum average daily turnover", min_value=0.0, value=0.0, step=1000.0)
            min_transactions = st.number_input("Minimum average daily transactions", min_value=0.0, value=0.0, step=1.0)
            date_range = st.date_input("Calculation date range", value=())
        sort_col, dir_col, size_col = st.columns(3)
        sort_options = [
            "avg_daily_turnover",
            "avg_daily_transactions",
            "calculation_date",
            "instrument_name",
            "isin",
            "mic",
            "liquidity_status",
        ]
        with sort_col:
            seed_choice_state("screen_sort_by", "scr_sort", options=sort_options, default="avg_daily_turnover")
            sort_by = st.selectbox("Sort by", sort_options, key="screen_sort_by")
        with dir_col:
            if "screen_sort_desc" not in st.session_state:
                st.session_state["screen_sort_desc"] = query_params.get("scr_desc", "true") != "false"
            sort_desc = st.checkbox("Descending", key="screen_sort_desc")
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
        set_query_param("scr_search", search)
        set_query_param("scr_liquidity", liquidity)
        set_query_param("scr_mic", mic)
        set_query_param("scr_country", country)
        set_query_param("scr_type", instrument_type)
        set_query_param("scr_period", reference_period)
        set_query_param("scr_sort", sort_by)
        set_query_param("scr_desc", "true" if sort_desc else "false")
        summary = screener_summary(conn, filters)
        total = summary["total"]

        st.markdown("**Full result set overview** (covers all matching rows, not just the page below)")
        metric_row(
            {
                "Total matches": f"{total:,}",
                "Sum avg. daily turnover": f"{summary['sum_turnover']:,.0f}" if summary["sum_turnover"] else "N/A",
                "Mean avg. daily turnover": f"{summary['mean_turnover']:,.0f}" if summary["mean_turnover"] else "N/A",
            }
        )
        chart_col1, chart_col2 = st.columns(2)
        with chart_col1:
            st.caption("Liquid vs. non-liquid split")
            facet_bar_chart(list(zip(summary["liquidity_breakdown"]["liquidity_status"], summary["liquidity_breakdown"]["count"])), label="liquidity")
            st.caption("Turnover distribution")
            facet_bar_chart(list(zip(summary["turnover_buckets"]["bucket"], summary["turnover_buckets"]["count"])), label="turnover")
        with chart_col2:
            st.caption("Top venues (MIC) by row count")
            facet_bar_chart(list(zip(summary["venue_breakdown"]["mic"], summary["venue_breakdown"]["count"])), label="venue")
            st.caption("Top countries by row count")
            facet_bar_chart(list(zip(summary["country_breakdown"]["country"], summary["country_breakdown"]["count"])), label="country")
        st.caption("Calculation date coverage (by month)")
        facet_bar_chart(
            list(zip(summary["date_coverage"]["period"], summary["date_coverage"]["count"])),
            label="calculation date",
        )

        limit, offset = pagination_controls("Screener", total, page_size)
        screen_df, _total_page = liquidity_screener(conn, filters, limit=limit, offset=offset)
        if screen_df.empty:
            empty_state("No records match the current screener filters.")
            if search:
                st.json(diagnostics_for_isin(conn, search, {"mic": mic}))
        else:
            dataframe(screen_df, height=520)
            export_col1, export_col2 = st.columns(2)
            export_df = export_liquidity_screener(conn, filters)
            with export_col1:
                csv_download_button(
                    export_df, label="Export filtered results as CSV", file_name="esma_liquidity_screener_export.csv", key="screener_csv"
                )
            with export_col2:
                xlsx_buffer = io.BytesIO()
                export_df.to_excel(xlsx_buffer, index=False, engine="openpyxl")
                st.download_button(
                    "Export filtered results as Excel",
                    data=xlsx_buffer.getvalue(),
                    file_name="esma_liquidity_screener_export.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

with tabs[4]:
    st.subheader("Portfolio")
    st.write(
        "Save ISINs to a personal watchlist and monitor them together. The list is kept for this browser "
        "session; use export/import below to save it to a file and reload it later."
    )

    store = InMemoryPortfolioStore(st.session_state, key="portfolio_isins")

    add_col, button_col = st.columns([3, 1])
    with add_col:
        new_isin = st.text_input("Add a single ISIN", key="portfolio_add_isin", placeholder="Example: NL0010273215")
    with button_col:
        st.write("")
        st.write("")
        if st.button("Add ISIN", key="portfolio_add_single_btn"):
            candidate = normalize_upper(new_isin)
            if not candidate:
                st.warning("Enter an ISIN first.")
            elif not is_valid_isin(candidate):
                st.error(f"'{candidate}' does not look like a valid ISIN (format or check digit failed).")
            else:
                store.add([candidate])
                st.rerun()

    with st.expander("Bulk add (paste many ISINs)"):
        bulk_text = st.text_area(
            "One ISIN per line, or comma/space separated", key="portfolio_bulk_text", height=120
        )
        if st.button("Add all", key="portfolio_add_bulk_btn"):
            valid_isins, invalid_isins = parse_bulk_isins(bulk_text)
            if valid_isins:
                store.add(valid_isins)
                st.success(f"Added {len(valid_isins)} ISIN(s).")
            if invalid_isins:
                st.warning(f"Skipped {len(invalid_isins)} value(s) that are not valid ISINs: {', '.join(invalid_isins)}")
            if valid_isins:
                st.rerun()

    watchlist = store.load()

    st.markdown("**Import / export watchlist**")
    exp_json_col, exp_csv_col, import_col = st.columns(3)
    with exp_json_col:
        st.download_button(
            "Export as JSON",
            data=portfolio_to_json(watchlist),
            file_name="esma_portfolio.json",
            mime="application/json",
            disabled=not watchlist,
        )
    with exp_csv_col:
        st.download_button(
            "Export as CSV",
            data=portfolio_to_csv(watchlist),
            file_name="esma_portfolio.csv",
            mime="text/csv",
            disabled=not watchlist,
        )
    with import_col:
        uploaded = st.file_uploader("Import watchlist", type=["json", "csv"], key="portfolio_uploader")
        if uploaded is not None:
            try:
                raw = uploaded.getvalue()
                imported = portfolio_from_json(raw) if uploaded.name.lower().endswith(".json") else portfolio_from_csv(raw)
            except Exception as exc:
                imported = []
                st.error(f"Could not parse uploaded file: {exc}")
            if imported:
                store.add(imported)
                st.success(f"Imported {len(imported)} ISIN(s).")
                st.rerun()

    watchlist = store.load()
    if not watchlist:
        empty_state("Your portfolio is empty. Add an ISIN above to get started.")
    else:
        use_local = bool(health["fitrs_equity_results_rows"] or health["firds_instruments_rows"])
        with st.spinner(f"Enriching {len(watchlist)} portfolio ISIN(s)..."):
            profiles = [cached_isin_profile(item, use_local) for item in watchlist]
        profile_df = pd.DataFrame(profiles)

        liquidity_categories = [classify_liquidity(p.get("Liquidity flag")) for p in profiles]
        liquid_count = liquidity_categories.count("liquid")
        non_liquid_count = liquidity_categories.count("non_liquid")
        turnovers = [p["Average daily turnover"] for p in profiles if p.get("Average daily turnover") is not None]

        st.markdown("**Portfolio summary**")
        metric_row(
            {
                "Instruments": f"{len(profiles):,}",
                "Liquid": f"{liquid_count:,}",
                "Non-liquid": f"{non_liquid_count:,}",
                "Unknown liquidity": f"{len(profiles) - liquid_count - non_liquid_count:,}",
                "Mean avg. daily turnover": f"{(sum(turnovers) / len(turnovers)):,.0f}" if turnovers else "N/A",
            }
        )

        venue_counts = profile_df["Home/most relevant MIC"].fillna("Unknown").value_counts()
        if not venue_counts.empty:
            st.markdown("**Venue breakdown**")
            st.bar_chart(venue_counts)

        st.markdown("**Portfolio holdings**")
        display_cols = [
            "ISIN",
            "Instrument name",
            "Home/most relevant MIC",
            "Liquidity flag",
            "Average daily turnover",
            "Average daily number of transactions",
            "Calculation date",
            "In FITRS",
            "In FIRDS",
        ]
        dataframe(profile_df[display_cols], height=360)

        export_col1, export_col2 = st.columns(2)
        with export_col1:
            st.download_button(
                "Export enriched portfolio as CSV",
                data=profile_df.to_csv(index=False).encode("utf-8"),
                file_name="esma_portfolio_enriched.csv",
                mime="text/csv",
            )
        with export_col2:
            xlsx_buffer = io.BytesIO()
            profile_df.to_excel(xlsx_buffer, index=False, engine="openpyxl")
            st.download_button(
                "Export enriched portfolio as Excel",
                data=xlsx_buffer.getvalue(),
                file_name="esma_portfolio_enriched.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        st.markdown("**Row actions**")
        for item in watchlist:
            profile_row = next((p for p in profiles if p["ISIN"] == item), {})
            row_name_col, row_open_col, row_remove_col = st.columns([3, 1, 1])
            with row_name_col:
                st.write(f"**{item}** - {profile_row.get('Instrument name') or 'Unknown name'}")
            with row_open_col:
                if st.button("Open in ISIN Explorer", key=f"portfolio_open_{item}"):
                    st.session_state["portfolio_open_isin_request"] = item
                    st.rerun()
            with row_remove_col:
                if st.button("Remove", key=f"portfolio_remove_{item}"):
                    store.remove(item)
                    st.rerun()

with tabs[5]:
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
