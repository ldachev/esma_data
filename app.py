from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from src.config import DEFAULT_SORT_COLUMN
from src.database import distinct_values, initialize_database, query_securities
from src.esma_client import DatasetResult, esma_data_py_status, load_or_build_dataset


st.set_page_config(
    page_title="ESMA Securities Liquidity Dashboard",
    page_icon="EU",
    layout="wide",
)


st.markdown(
    """
    <style>
    .block-container { padding-top: 1.5rem; }
    .metric-card {
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        padding: 1rem;
        background: #ffffff;
    }
    .metric-label {
        color: #64748b;
        font-size: 0.85rem;
        margin-bottom: 0.35rem;
    }
    .metric-value {
        color: #0f172a;
        font-size: 1.6rem;
        font-weight: 700;
    }
    .small-muted { color: #64748b; font-size: 0.9rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner="Loading ESMA dashboard data...")
def load_dashboard_data(try_live: bool, force_download: bool) -> DatasetResult:
    return load_or_build_dataset(try_live=try_live, force_download=force_download)


def metric_card(label: str, value: str) -> None:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def multiselect_filter(label: str, column: str, help_text: str) -> list[str]:
    values = distinct_values(column)
    return st.sidebar.multiselect(label, values, help=help_text)


def date_bounds(frame: pd.DataFrame) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    if "calculation_date" not in frame:
        return None, None
    dates = pd.to_datetime(frame["calculation_date"], errors="coerce").dropna()
    if dates.empty:
        return None, None
    return dates.min(), dates.max()


st.title("ESMA Securities Liquidity and Trading Venue Dashboard")
st.caption(
    "Explore European securities using ESMA-style FIRDS instrument reference fields, "
    "FITRS transparency/liquidity metrics, and trading venue MIC metadata."
)

with st.sidebar:
    st.header("Data")
    try_live = st.toggle(
        "Try live ESMA refresh",
        value=False,
        help=(
            "Downloads a small sample of public FIRDS/FITRS register files from ESMA and caches "
            "them under data/raw. If this fails, the app falls back to sample data."
        ),
    )
    force_download = st.checkbox("Force re-download cached files", value=False)
    if st.button("Reload data"):
        load_dashboard_data.clear()
        st.rerun()


dataset = load_dashboard_data(try_live=try_live, force_download=force_download)
engine = initialize_database(dataset.frame)

with st.sidebar:
    st.header("Filters")
    isin_search = st.text_input("ISIN search", help="Find a full or partial International Securities Identification Number.")
    name_search = st.text_input("Instrument name search", help="Search by issuer or instrument name.")
    asset_classes = multiselect_filter("Asset class", "asset_class", "Filter by shares, ETFs, bonds, derivatives, or other classes.")
    mic_codes = multiselect_filter("Venue / MIC code", "mic_code", "Market Identifier Code for the trading venue.")
    venue_types = multiselect_filter("Venue type", "venue_type", "Examples include RM, MTF, OTF, and SI where available.")
    countries = multiselect_filter("Country", "country", "Country code associated with the venue or competent authority.")
    liquidity_statuses = multiselect_filter("Liquidity status", "liquidity_status", "FITRS-style liquidity classification where available.")

    min_date, max_date = date_bounds(dataset.frame)
    selected_dates = None
    if min_date is not None and max_date is not None:
        selected_dates = st.date_input(
            "Calculation date / reference period",
            value=(min_date.date(), max_date.date()),
            min_value=min_date.date(),
            max_value=max_date.date(),
            help="Calculation or publication date after ESMA schema normalization.",
        )

    st.header("Sorting")
    sort_by = st.selectbox(
        "Default sort",
        [
            "avg_daily_turnover",
            "avg_daily_transactions",
            "calculation_date",
            "instrument_name",
            "mic_code",
            "country",
        ],
        index=0,
        help="The interactive table remains sortable after loading.",
    )
    sort_desc = st.checkbox("Descending", value=True)
    table_limit = st.slider("Maximum rows", min_value=100, max_value=10000, value=2500, step=100)


filters = {
    "isin_search": isin_search,
    "name_search": name_search,
    "asset_classes": asset_classes,
    "mic_codes": mic_codes,
    "venue_types": venue_types,
    "countries": countries,
    "liquidity_statuses": liquidity_statuses,
    "date_range": selected_dates if isinstance(selected_dates, tuple) and len(selected_dates) == 2 else None,
}

filtered = query_securities(
    filters=filters,
    sort_by=sort_by or DEFAULT_SORT_COLUMN,
    sort_desc=sort_desc,
    limit=table_limit,
)

status = esma_data_py_status()
source_note = "Sample fallback data" if dataset.used_sample else "Processed ESMA cache"
st.markdown(
    f"<span class='small-muted'>Storage engine: {engine.upper()} | Source: {source_note} | "
    f"esma_data_py: {'available' if status['available'] else 'not installed'}</span>",
    unsafe_allow_html=True,
)

with st.expander("Data loading notes", expanded=dataset.used_sample):
    for message in dataset.messages:
        st.write(f"- {message}")
    st.write(
        "FIRDS is ESMA's Financial Instruments Reference Data System. "
        "FITRS is ESMA's Financial Instruments Transparency System, which includes transparency "
        "and liquidity calculations used by MiFID II/MiFIR workflows."
    )

total_instruments = filtered["isin"].nunique() if not filtered.empty else 0
venue_count = filtered["mic_code"].nunique() if not filtered.empty else 0
liquid_count = (
    filtered.loc[filtered["liquidity_status"].str.lower().eq("liquid"), "isin"].nunique()
    if not filtered.empty and "liquidity_status" in filtered
    else 0
)
top_venue = "N/A"
if not filtered.empty:
    venue_counts = filtered.dropna(subset=["mic_code"]).groupby("mic_code")["isin"].nunique().sort_values(ascending=False)
    if not venue_counts.empty:
        top_venue = f"{venue_counts.index[0]} ({venue_counts.iloc[0]:,})"

cols = st.columns(4)
with cols[0]:
    metric_card("Total instruments", f"{total_instruments:,}")
with cols[1]:
    metric_card("Trading venues", f"{venue_count:,}")
with cols[2]:
    metric_card("Liquid instruments", f"{liquid_count:,}")
with cols[3]:
    metric_card("Top venue", top_venue)

st.divider()

if filtered.empty:
    st.info("No instruments match the current filters. Try broadening the search or clearing a sidebar filter.")
    st.stop()

chart_left, chart_right = st.columns(2)

with chart_left:
    top_venues = (
        filtered.groupby(["mic_code", "trading_venue"], dropna=False)["isin"]
        .nunique()
        .reset_index(name="instrument_count")
        .sort_values("instrument_count", ascending=False)
        .head(10)
    )
    top_venues["venue_label"] = top_venues["mic_code"].fillna("UNKNOWN") + " - " + top_venues["trading_venue"].fillna("")
    fig = px.bar(
        top_venues,
        x="instrument_count",
        y="venue_label",
        orientation="h",
        title="Top 10 venues by number of instruments",
        labels={"instrument_count": "Instruments", "venue_label": "Venue"},
    )
    fig.update_layout(yaxis={"categoryorder": "total ascending"}, height=380, margin=dict(l=10, r=10, t=50, b=10))
    st.plotly_chart(fig, width="stretch")

with chart_right:
    venue_turnover = (
        filtered.groupby(["mic_code", "trading_venue"], dropna=False)["avg_daily_turnover"]
        .sum(min_count=1)
        .reset_index()
        .sort_values("avg_daily_turnover", ascending=False)
        .head(10)
    )
    venue_turnover["venue_label"] = venue_turnover["mic_code"].fillna("UNKNOWN") + " - " + venue_turnover["trading_venue"].fillna("")
    fig = px.bar(
        venue_turnover,
        x="avg_daily_turnover",
        y="venue_label",
        orientation="h",
        title="Top 10 venues by average daily turnover",
        labels={"avg_daily_turnover": "Average daily turnover", "venue_label": "Venue"},
    )
    fig.update_layout(yaxis={"categoryorder": "total ascending"}, height=380, margin=dict(l=10, r=10, t=50, b=10))
    st.plotly_chart(fig, width="stretch")

asset_counts = filtered.groupby("asset_class", dropna=False)["isin"].nunique().reset_index(name="instrument_count")
fig = px.pie(
    asset_counts,
    names="asset_class",
    values="instrument_count",
    title="Asset class distribution",
    hole=0.42,
)
fig.update_layout(height=360, margin=dict(l=10, r=10, t=50, b=10))
st.plotly_chart(fig, width="stretch")

st.subheader("Filtered securities")
display_columns = [
    "isin",
    "instrument_name",
    "asset_class",
    "trading_venue",
    "mic_code",
    "venue_type",
    "country",
    "liquidity_status",
    "avg_daily_turnover",
    "avg_daily_transactions",
    "calculation_date",
    "reference_period",
]
st.dataframe(
    filtered[display_columns],
    width="stretch",
    hide_index=True,
    column_config={
        "avg_daily_turnover": st.column_config.NumberColumn("Avg daily turnover", format="%.0f"),
        "avg_daily_transactions": st.column_config.NumberColumn("Avg daily transactions", format="%.0f"),
        "calculation_date": st.column_config.DateColumn("Calculation date"),
    },
)

csv = filtered.to_csv(index=False).encode("utf-8")
st.download_button(
    "Download filtered results as CSV",
    data=csv,
    file_name="esma_filtered_securities.csv",
    mime="text/csv",
)
