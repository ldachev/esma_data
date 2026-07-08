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


def setup_instructions() -> None:
    st.warning("No ESMA data has been loaded into DuckDB yet.")
    st.markdown(
        """
Run ingestion from the project directory:

```bash
python -m src.ingest_fitrs_equities --reset
python -m src.ingest_firds --reset
streamlit run app.py
```

FIRDS is very large, so the default FIRDS command loads a bounded equity slice. Use
`--limit 0` only for an intentional production-scale ingest.
        """
    )
