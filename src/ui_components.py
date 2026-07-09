"""Reusable Streamlit UI helpers."""

from __future__ import annotations

import math

import pandas as pd
import streamlit as st


def metric_row(metrics: dict[str, object]) -> None:
    cols = st.columns(len(metrics))
    for col, (label, value) in zip(cols, metrics.items(), strict=False):
        col.metric(label, "" if value is None else str(value))


def pagination_controls(prefix: str, total: int, page_size: int) -> tuple[int, int]:
    pages = max(1, math.ceil(total / page_size))
    page = st.number_input(
        f"{prefix} page",
        min_value=1,
        max_value=pages,
        value=1,
        step=1,
        help=f"{total:,} rows total",
    )
    offset = (int(page) - 1) * page_size
    st.caption(f"Showing page {int(page):,} of {pages:,}; {total:,} total rows.")
    return page_size, offset


def dataframe(df: pd.DataFrame, *, height: int = 420) -> None:
    st.dataframe(df, width="stretch", hide_index=True, height=height)


def empty_state(message: str) -> None:
    st.info(message)


def provenance_line(*, mode: str, source: str, as_of: object) -> None:
    """Show a live-vs-cached badge plus source register and 'as of' freshness."""

    label = "LIVE" if mode == "live" else "CACHED"
    as_of_text = str(as_of) if as_of else "unknown"
    st.caption(f"`{label}` · source: {source} · as of: {as_of_text}")


def csv_download_button(df: pd.DataFrame, *, label: str, file_name: str, key: str | None = None) -> None:
    st.download_button(
        label,
        data=df.to_csv(index=False).encode("utf-8"),
        file_name=file_name,
        mime="text/csv",
        disabled=df.empty,
        key=key,
    )


def facet_bar_chart(pairs: list[tuple[str, int]], *, label: str) -> None:
    """Render a bar chart from (value, count) pairs covering the full result set."""

    if not pairs:
        st.caption(f"No {label} breakdown available for the full result set.")
        return
    series = pd.Series({k: v for k, v in pairs}, name="count")
    st.bar_chart(series)


def _fmt_number(value: object) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def instrument_card(
    profile: dict[str, object],
    *,
    notices: list[tuple[str, str]],
    liquidity_text: str,
    period_text: str,
    cfi_text: str,
) -> None:
    """Render a synthesized single-instrument summary card.

    ``profile`` is the dict from ``InstrumentProfile.to_dict()``. ``notices``
    is a list of ``(level, message)`` tuples from reconciliation.
    """

    name = profile.get("Instrument name") or profile.get("ISIN")
    name_source = profile.get("Instrument name source")
    title = f"{name}" + (f" ({name_source})" if name_source else "")
    st.markdown(f"### {title}")
    st.caption(f"ISIN: {profile.get('ISIN')}")

    metric_row(
        {
            "Liquidity flag": profile.get("Liquidity flag") or "N/A",
            "Avg. daily turnover": _fmt_number(profile.get("Average daily turnover")),
            "Avg. daily transactions": _fmt_number(profile.get("Average daily number of transactions")),
            "Calculation date": profile.get("Calculation date") or "N/A",
        }
    )

    left, right = st.columns(2)
    with left:
        st.markdown(f"**Issuer LEI:** {profile.get('Issuer LEI') or 'N/A'}")
        st.markdown(
            f"**CFI code:** {profile.get('CFI code') or 'N/A'}"
            + (f" (source: {profile.get('CFI source')})" if profile.get("CFI source") else "")
        )
        st.markdown(
            f"**Home/most relevant MIC:** {profile.get('Home/most relevant MIC') or 'N/A'}"
            + (f" (source: {profile.get('MIC source')})" if profile.get("MIC source") else "")
        )
        st.markdown(f"**MiFIR identifier:** {profile.get('MiFIR identifier') or 'N/A'}")
    with right:
        st.markdown(f"**Reference period:** {profile.get('Reference period') or 'N/A'}")
        st.markdown(f"**Admission date:** {profile.get('Admission date') or 'N/A'}")
        st.markdown(f"**Termination date:** {profile.get('Termination date') or 'N/A'}")
        st.markdown(
            f"**Registers matched:** FITRS {'yes' if profile.get('In FITRS') else 'no'} / "
            f"FIRDS {'yes' if profile.get('In FIRDS') else 'no'}"
        )

    for level, message in notices:
        if level == "conflict":
            st.warning(message)
        else:
            st.info(message)

    with st.expander("What do these fields mean? (MiFID II interpretation)"):
        st.markdown(f"**Liquidity flag:** {liquidity_text}")
        st.markdown(f"**Reference/calculation period:** {period_text}")
        st.markdown(f"**CFI code:** {cfi_text}")


def setup_instructions() -> None:
    st.warning("No ESMA data has been loaded into DuckDB yet.")
    st.markdown(
        """
On Streamlit Cloud, use the **Load starter ESMA dataset** button below.

For local development, run ingestion from the project directory:

```bash
python -m src.ingest_fitrs_equities --reset
python -m src.ingest_firds --reset
streamlit run app.py
```

FIRDS is very large, so the app's starter loader uses a small official ESMA slice.
Use `--limit 0` only for an intentional production-scale local ingest.
        """
    )
