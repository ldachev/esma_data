"""Local DuckDB/SQLite storage and query helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

from .config import DATABASE_PATH, DEFAULT_TABLE_LIMIT, SQLITE_FALLBACK_PATH, ensure_directories


TABLE_NAME = "securities"


def duckdb_available() -> bool:
    try:
        import duckdb  # noqa: F401

        return True
    except Exception:
        return False


def initialize_database(df: pd.DataFrame, db_path: Path = DATABASE_PATH) -> str:
    """Persist the processed securities dataframe for fast local analytics."""

    ensure_directories()
    if duckdb_available():
        import duckdb

        with duckdb.connect(str(db_path)) as conn:
            conn.execute(f"DROP TABLE IF EXISTS {TABLE_NAME}")
            conn.register("securities_df", df)
            conn.execute(f"CREATE TABLE {TABLE_NAME} AS SELECT * FROM securities_df")
        return "duckdb"

    with sqlite3.connect(SQLITE_FALLBACK_PATH) as conn:
        df.to_sql(TABLE_NAME, conn, if_exists="replace", index=False)
    return "sqlite"


def _connection(db_path: Path = DATABASE_PATH) -> tuple[Any, str]:
    if duckdb_available() and db_path.exists():
        import duckdb

        return duckdb.connect(str(db_path)), "duckdb"
    return sqlite3.connect(SQLITE_FALLBACK_PATH), "sqlite"


def _add_in_filter(where: list[str], params: list[Any], column: str, values: list[str] | None) -> None:
    if not values:
        return
    placeholders = ", ".join(["?"] * len(values))
    where.append(f"{column} IN ({placeholders})")
    params.extend(values)


def query_securities(
    filters: dict[str, Any] | None = None,
    sort_by: str = "avg_daily_turnover",
    sort_desc: bool = True,
    limit: int = DEFAULT_TABLE_LIMIT,
) -> pd.DataFrame:
    """Query securities with optional dashboard filters."""

    filters = filters or {}
    where: list[str] = []
    params: list[Any] = []

    isin_search = str(filters.get("isin_search") or "").strip().upper()
    if isin_search:
        where.append("UPPER(COALESCE(isin, '')) LIKE ?")
        params.append(f"%{isin_search}%")

    name_search = str(filters.get("name_search") or "").strip().lower()
    if name_search:
        where.append("LOWER(COALESCE(instrument_name, '')) LIKE ?")
        params.append(f"%{name_search}%")

    _add_in_filter(where, params, "asset_class", filters.get("asset_classes"))
    _add_in_filter(where, params, "mic_code", filters.get("mic_codes"))
    _add_in_filter(where, params, "venue_type", filters.get("venue_types"))
    _add_in_filter(where, params, "country", filters.get("countries"))
    _add_in_filter(where, params, "liquidity_status", filters.get("liquidity_statuses"))

    date_range = filters.get("date_range")
    if date_range and len(date_range) == 2 and all(date_range):
        where.append("calculation_date BETWEEN ? AND ?")
        params.extend([str(date_range[0]), str(date_range[1])])

    valid_sort_columns = {
        "isin",
        "instrument_name",
        "asset_class",
        "trading_venue",
        "mic_code",
        "country",
        "liquidity_status",
        "avg_daily_turnover",
        "avg_daily_transactions",
        "calculation_date",
    }
    if sort_by not in valid_sort_columns:
        sort_by = "avg_daily_turnover"

    order = "DESC" if sort_desc else "ASC"
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    sql = f"""
        SELECT *
        FROM {TABLE_NAME}
        {where_sql}
        ORDER BY {sort_by} {order} NULLS LAST
        LIMIT ?
    """
    params.append(limit)

    conn, engine = _connection()
    try:
        if engine == "duckdb":
            return conn.execute(sql, params).df()
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()


def distinct_values(column: str) -> list[str]:
    """Return distinct non-empty values for sidebar filters."""

    allowed = {"asset_class", "mic_code", "venue_type", "country", "liquidity_status"}
    if column not in allowed:
        return []
    conn, engine = _connection()
    sql = f"""
        SELECT DISTINCT {column}
        FROM {TABLE_NAME}
        WHERE {column} IS NOT NULL AND {column} <> ''
        ORDER BY {column}
    """
    try:
        if engine == "duckdb":
            df = conn.execute(sql).df()
        else:
            df = pd.read_sql_query(sql, conn)
    finally:
        conn.close()
    return df[column].dropna().astype(str).tolist()
