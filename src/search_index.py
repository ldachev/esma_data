"""DuckDB-backed search API for the Streamlit app and tests."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .database import count_query, query_df
from .utils import normalize_upper


FITRS_SORT_COLUMNS = {
    "isin": "isin_key",
    "mic": "mic_key",
    "instrument_name": "instrument_name",
    "liquidity_status": "liquidity_status",
    "avg_daily_turnover": "avg_daily_turnover",
    "avg_daily_transactions": "avg_daily_transactions",
    "calculation_date": "calculation_date",
}

VENUE_SORT_COLUMNS = {
    "isin": "isin_key",
    "instrument_name": "instrument_name",
    "liquidity_status": "liquidity_status",
    "avg_daily_turnover": "avg_daily_turnover",
    "avg_daily_transactions": "avg_daily_transactions",
}


def _order(sort_by: str, sort_desc: bool, allowed: dict[str, str], default: str) -> str:
    column = allowed.get(sort_by, allowed[default])
    direction = "DESC" if sort_desc else "ASC"
    return f"{column} {direction} NULLS LAST"


def global_search(conn, term: str, *, limit: int = 100, offset: int = 0) -> pd.DataFrame:
    key = normalize_upper(term)
    if not key:
        return pd.DataFrame()
    like = f"%{key}%"
    sql = """
        WITH firds_ref AS (
            SELECT isin_key, mic_key, MAX(instrument_full_name) AS instrument_full_name
            FROM firds_instruments
            GROUP BY isin_key, mic_key
        ),
        venue_ref AS (
            SELECT mic_key, MAX(venue_name) AS venue_name
            FROM trading_venues
            GROUP BY mic_key
        ),
        fitrs AS (
            SELECT
                'FITRS equity' AS dataset,
                f.isin,
                COALESCE(NULLIF(f.instrument_name, ''), fd.instrument_full_name) AS instrument_name,
                f.mic,
                COALESCE(NULLIF(f.venue_name, ''), tv.venue_name) AS venue_name,
                f.liquidity_status,
                f.avg_daily_turnover,
                f.avg_daily_transactions,
                f.calculation_date,
                f.reference_period
            FROM fitrs_equity_results f
            LEFT JOIN firds_ref fd ON fd.isin_key = f.isin_key AND fd.mic_key = f.mic_key
            LEFT JOIN venue_ref tv ON tv.mic_key = f.mic_key
            WHERE f.isin_key LIKE ?
               OR f.mic_key LIKE ?
               OR UPPER(COALESCE(f.instrument_name, fd.instrument_full_name, '')) LIKE ?
               OR UPPER(COALESCE(f.venue_name, tv.venue_name, '')) LIKE ?
        ),
        firds AS (
            SELECT
                'FIRDS' AS dataset,
                fd.isin,
                fd.instrument_full_name AS instrument_name,
                fd.mic,
                tv.venue_name,
                NULL AS liquidity_status,
                NULL AS avg_daily_turnover,
                NULL AS avg_daily_transactions,
                NULL AS calculation_date,
                NULL AS reference_period
            FROM firds_instruments fd
            LEFT JOIN venue_ref tv ON tv.mic_key = fd.mic_key
            WHERE fd.isin_key LIKE ?
               OR fd.mic_key LIKE ?
               OR fd.instrument_name_key LIKE ?
               OR UPPER(COALESCE(tv.venue_name, '')) LIKE ?
        )
        SELECT * FROM fitrs
        UNION ALL
        SELECT * FROM firds
        ORDER BY dataset, isin, mic
        LIMIT ? OFFSET ?
    """
    return query_df(conn, sql, [like, like, like, like, like, like, like, like, limit, offset])


def isin_fitrs(conn, isin: str) -> pd.DataFrame:
    key = normalize_upper(isin)
    return query_df(
        conn,
        """
        WITH firds_ref AS (
            SELECT isin_key, mic_key, MAX(instrument_full_name) AS instrument_full_name
            FROM firds_instruments
            GROUP BY isin_key, mic_key
        ),
        venue_ref AS (
            SELECT mic_key, MAX(venue_name) AS venue_name
            FROM trading_venues
            GROUP BY mic_key
        )
        SELECT
            f.isin,
            COALESCE(NULLIF(f.instrument_name, ''), fd.instrument_full_name) AS instrument_name,
            f.mic,
            COALESCE(NULLIF(f.venue_name, ''), tv.venue_name) AS venue_name,
            f.liquidity_status,
            f.avg_daily_turnover,
            f.avg_daily_transactions,
            f.mifir_identifier,
            f.cfi_code,
            f.instrument_type,
            f.calculation_date,
            f.reference_period,
            f.methodology,
            f.source_file_name
        FROM fitrs_equity_results f
        LEFT JOIN firds_ref fd ON fd.isin_key = f.isin_key AND fd.mic_key = f.mic_key
        LEFT JOIN venue_ref tv ON tv.mic_key = f.mic_key
        WHERE f.isin_key = ?
        ORDER BY f.avg_daily_turnover DESC NULLS LAST, f.mic_key
        """,
        [key],
    )


def isin_firds(conn, isin: str) -> pd.DataFrame:
    key = normalize_upper(isin)
    return query_df(
        conn,
        """
        SELECT
            isin,
            instrument_full_name,
            short_name,
            classification,
            cfi_code,
            issuer_lei,
            mic,
            country,
            venue_type,
            admission_date,
            termination_date,
            source_file_name
        FROM firds_instruments
        WHERE isin_key = ?
        ORDER BY mic_key, admission_date DESC NULLS LAST
        """,
        [key],
    )


def isin_venues(conn, isin: str) -> pd.DataFrame:
    key = normalize_upper(isin)
    return query_df(
        conn,
        """
        SELECT
            mic,
            MAX(venue_name) AS venue_name,
            MAX(country) AS country,
            MAX(venue_type) AS venue_type,
            BOOL_OR(in_fitrs) AS in_fitrs,
            BOOL_OR(in_firds) AS in_firds,
            MAX(avg_daily_turnover) AS max_avg_daily_turnover,
            MAX(avg_daily_transactions) AS max_avg_daily_transactions
        FROM (
            SELECT f.mic, tv.venue_name, tv.country, tv.venue_type, TRUE AS in_fitrs, FALSE AS in_firds,
                   f.avg_daily_turnover, f.avg_daily_transactions
            FROM fitrs_equity_results f
            LEFT JOIN trading_venues tv ON tv.mic_key = f.mic_key
            WHERE f.isin_key = ?
            UNION ALL
            SELECT fd.mic, tv.venue_name, fd.country, fd.venue_type, FALSE AS in_fitrs, TRUE AS in_firds,
                   NULL AS avg_daily_turnover, NULL AS avg_daily_transactions
            FROM firds_instruments fd
            LEFT JOIN trading_venues tv ON tv.mic_key = fd.mic_key
            WHERE fd.isin_key = ?
        )
        GROUP BY mic
        ORDER BY max_avg_daily_turnover DESC NULLS LAST, mic
        """,
        [key, key],
    )


def venue_lookup(conn, search: str = "", *, limit: int = 500) -> pd.DataFrame:
    key = normalize_upper(search)
    like = f"%{key}%"
    return query_df(
        conn,
        """
        SELECT
            mic_key AS mic,
            MAX(NULLIF(venue_name, '')) AS venue_name,
            MAX(NULLIF(country, '')) AS country,
            MAX(NULLIF(venue_type, '')) AS venue_type,
            COUNT(*) AS source_rows
        FROM trading_venues
        WHERE (? = '' OR mic_key LIKE ? OR venue_name_key LIKE ?)
        GROUP BY mic_key
        ORDER BY mic_key
        LIMIT ?
        """,
        [key, like, like, limit],
    )


def venue_instruments(
    conn,
    mic: str,
    *,
    limit: int = 100,
    offset: int = 0,
    sort_by: str = "avg_daily_turnover",
    sort_desc: bool = True,
) -> tuple[pd.DataFrame, int]:
    key = normalize_upper(mic)
    order = _order(sort_by, sort_desc, VENUE_SORT_COLUMNS, "avg_daily_turnover")
    base = """
        FROM fitrs_equity_results f
        LEFT JOIN (
            SELECT isin_key, mic_key, MAX(instrument_full_name) AS instrument_full_name
            FROM firds_instruments
            GROUP BY isin_key, mic_key
        ) fd ON fd.isin_key = f.isin_key AND fd.mic_key = f.mic_key
        WHERE f.mic_key = ?
    """
    total = count_query(conn, f"SELECT COUNT(*) {base}", [key])
    df = query_df(
        conn,
        f"""
        SELECT
            f.isin,
            COALESCE(NULLIF(f.instrument_name, ''), fd.instrument_full_name) AS instrument_name,
            f.mic,
            f.liquidity_status,
            f.avg_daily_turnover,
            f.avg_daily_transactions,
            f.instrument_type,
            f.cfi_code,
            f.calculation_date,
            f.reference_period
        {base}
        ORDER BY {order}
        LIMIT ? OFFSET ?
        """,
        [key, limit, offset],
    )
    return df, total


def liquidity_screener(conn, filters: dict[str, Any], *, limit: int = 100, offset: int = 0) -> tuple[pd.DataFrame, int]:
    where: list[str] = []
    params: list[Any] = []
    if filters.get("liquidity_status"):
        where.append("f.liquidity_status = ?")
        params.append(filters["liquidity_status"])
    if filters.get("mic"):
        where.append("f.mic_key = ?")
        params.append(normalize_upper(filters["mic"]))
    if filters.get("country"):
        where.append("fd.country = ?")
        params.append(normalize_upper(filters["country"]))
    if filters.get("instrument_type"):
        where.append("f.instrument_type = ?")
        params.append(filters["instrument_type"])
    if filters.get("reference_period"):
        where.append("f.reference_period = ?")
        params.append(filters["reference_period"])
    if filters.get("date_from"):
        where.append("f.calculation_date >= ?")
        params.append(str(filters["date_from"]))
    if filters.get("date_to"):
        where.append("f.calculation_date <= ?")
        params.append(str(filters["date_to"]))
    if filters.get("min_turnover") is not None:
        where.append("f.avg_daily_turnover >= ?")
        params.append(float(filters["min_turnover"]))
    if filters.get("min_transactions") is not None:
        where.append("f.avg_daily_transactions >= ?")
        params.append(float(filters["min_transactions"]))
    search = normalize_upper(filters.get("search") or "")
    if search:
        like = f"%{search}%"
        where.append("(f.isin_key LIKE ? OR f.mic_key LIKE ? OR UPPER(COALESCE(fd.instrument_full_name, f.instrument_name, '')) LIKE ?)")
        params.extend([like, like, like])

    where_sql = "WHERE " + " AND ".join(where) if where else ""
    base = f"""
        FROM fitrs_equity_results f
        LEFT JOIN (
            SELECT isin_key, mic_key, MAX(instrument_full_name) AS instrument_full_name, MAX(country) AS country
            FROM firds_instruments
            GROUP BY isin_key, mic_key
        ) fd ON fd.isin_key = f.isin_key AND fd.mic_key = f.mic_key
        {where_sql}
    """
    sort_by = filters.get("sort_by") or "avg_daily_turnover"
    sort_desc = bool(filters.get("sort_desc", True))
    order = _order(sort_by, sort_desc, FITRS_SORT_COLUMNS, "avg_daily_turnover")
    total = count_query(conn, f"SELECT COUNT(*) {base}", params)
    df_params = params + [limit, offset]
    df = query_df(
        conn,
        f"""
        SELECT
            f.isin,
            COALESCE(NULLIF(f.instrument_name, ''), fd.instrument_full_name) AS instrument_name,
            f.mic,
            fd.country,
            f.liquidity_status,
            f.avg_daily_turnover,
            f.avg_daily_transactions,
            f.instrument_type,
            f.cfi_code,
            f.calculation_date,
            f.reference_period,
            f.source_file_name
        {base}
        ORDER BY {order}
        LIMIT ? OFFSET ?
        """,
        df_params,
    )
    return df, total


def export_liquidity_screener(conn, filters: dict[str, Any], *, max_rows: int = 100_000) -> pd.DataFrame:
    df, _total = liquidity_screener(conn, filters, limit=max_rows, offset=0)
    return df
