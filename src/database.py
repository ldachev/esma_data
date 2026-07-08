"""DuckDB schema, ingestion writes, and paginated search queries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from .config import DATABASE_PATH, ensure_directories
from .schema_mapper import FIRDS_COLUMNS, FITRS_COLUMNS, VENUE_COLUMNS
from .utils import normalize_upper


def connect(db_path: Path = DATABASE_PATH) -> duckdb.DuckDBPyConnection:
    ensure_directories()
    conn = duckdb.connect(str(db_path))
    initialize_schema(conn)
    return conn


def initialize_schema(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS fitrs_equity_results (
            isin VARCHAR,
            isin_key VARCHAR,
            instrument_name VARCHAR,
            mic VARCHAR,
            mic_key VARCHAR,
            venue_name VARCHAR,
            venue_name_key VARCHAR,
            liquidity_status VARCHAR,
            avg_daily_turnover DOUBLE,
            avg_daily_transactions DOUBLE,
            mifir_identifier VARCHAR,
            cfi_code VARCHAR,
            instrument_type VARCHAR,
            calculation_date DATE,
            reference_period VARCHAR,
            calculation_period_from DATE,
            calculation_period_to DATE,
            methodology VARCHAR,
            source_file_name VARCHAR,
            source_record_id VARCHAR,
            ingestion_timestamp TIMESTAMP,
            raw_payload JSON
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS firds_instruments (
            isin VARCHAR,
            isin_key VARCHAR,
            instrument_full_name VARCHAR,
            instrument_name_key VARCHAR,
            short_name VARCHAR,
            classification VARCHAR,
            cfi_code VARCHAR,
            issuer_lei VARCHAR,
            mic VARCHAR,
            mic_key VARCHAR,
            admission_date TIMESTAMP,
            termination_date TIMESTAMP,
            notional_currency_1 VARCHAR,
            rca_mic VARCHAR,
            regulated_market VARCHAR,
            country VARCHAR,
            venue_type VARCHAR,
            source_file_name VARCHAR,
            source_record_id VARCHAR,
            ingestion_timestamp TIMESTAMP,
            raw_payload JSON
        )
        """
    )
    for statement in (
        "ALTER TABLE firds_instruments ADD COLUMN IF NOT EXISTS notional_currency_1 VARCHAR",
        "ALTER TABLE firds_instruments ADD COLUMN IF NOT EXISTS rca_mic VARCHAR",
        "ALTER TABLE firds_instruments ADD COLUMN IF NOT EXISTS regulated_market VARCHAR",
    ):
        conn.execute(statement)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trading_venues (
            mic VARCHAR,
            mic_key VARCHAR,
            venue_name VARCHAR,
            venue_name_key VARCHAR,
            country VARCHAR,
            venue_type VARCHAR,
            source VARCHAR,
            ingestion_timestamp TIMESTAMP
        )
        """
    )
    create_indexes(conn)


def create_indexes(conn: duckdb.DuckDBPyConnection) -> None:
    index_statements = [
        "CREATE INDEX IF NOT EXISTS idx_fitrs_isin ON fitrs_equity_results(isin_key)",
        "CREATE INDEX IF NOT EXISTS idx_fitrs_mic ON fitrs_equity_results(mic_key)",
        "CREATE INDEX IF NOT EXISTS idx_fitrs_liquidity ON fitrs_equity_results(liquidity_status)",
        "CREATE INDEX IF NOT EXISTS idx_firds_isin ON firds_instruments(isin_key)",
        "CREATE INDEX IF NOT EXISTS idx_firds_mic ON firds_instruments(mic_key)",
        "CREATE INDEX IF NOT EXISTS idx_venues_mic ON trading_venues(mic_key)",
    ]
    for statement in index_statements:
        try:
            conn.execute(statement)
        except duckdb.Error:
            pass


def reset_table(conn: duckdb.DuckDBPyConnection, table: str) -> None:
    if table not in {"fitrs_equity_results", "firds_instruments", "trading_venues"}:
        raise ValueError(f"Unknown table: {table}")
    conn.execute(f"DELETE FROM {table}")


def append_dataframe(conn: duckdb.DuckDBPyConnection, table: str, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    expected = {
        "fitrs_equity_results": FITRS_COLUMNS,
        "firds_instruments": FIRDS_COLUMNS,
        "trading_venues": VENUE_COLUMNS,
    }[table]
    before = count_query(conn, f"SELECT COUNT(*) FROM {table}")
    frame = df.reindex(columns=expected)
    conn.register("incoming_df", frame)
    if table in {"fitrs_equity_results", "firds_instruments"} and "source_record_id" in frame.columns:
        conn.execute(
            f"""
            INSERT INTO {table}
            SELECT i.*
            FROM incoming_df i
            WHERE COALESCE(i.source_record_id, '') = ''
               OR NOT EXISTS (
                   SELECT 1
                   FROM {table} t
                   WHERE t.source_record_id = i.source_record_id
               )
            """
        )
    else:
        conn.execute(f"INSERT INTO {table} SELECT * FROM incoming_df")
    conn.unregister("incoming_df")
    after = count_query(conn, f"SELECT COUNT(*) FROM {table}")
    return after - before


def upsert_venues(conn: duckdb.DuckDBPyConnection, venues: pd.DataFrame) -> int:
    if venues.empty:
        return 0
    conn.register("incoming_venues", venues.reindex(columns=VENUE_COLUMNS))
    conn.execute(
        """
        INSERT INTO trading_venues
        SELECT i.*
        FROM incoming_venues i
        WHERE COALESCE(i.mic_key, '') <> ''
          AND NOT EXISTS (
              SELECT 1 FROM trading_venues v
              WHERE v.mic_key = i.mic_key
                AND COALESCE(v.venue_name_key, '') = COALESCE(i.venue_name_key, '')
                AND COALESCE(v.source, '') = COALESCE(i.source, '')
          )
        """
    )
    count = conn.execute("SELECT COUNT(*) FROM incoming_venues").fetchone()[0]
    conn.unregister("incoming_venues")
    return int(count)


def table_exists_with_rows(conn: duckdb.DuckDBPyConnection, table: str) -> bool:
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > 0
    except duckdb.Error:
        return False


def query_df(conn: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None) -> pd.DataFrame:
    return conn.execute(sql, params or []).df()


def count_query(conn: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None) -> int:
    return int(conn.execute(sql, params or []).fetchone()[0])


def data_health(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for table in ("fitrs_equity_results", "firds_instruments", "trading_venues"):
        result[f"{table}_rows"] = count_query(conn, f"SELECT COUNT(*) FROM {table}")
    result["distinct_isins"] = count_query(
        conn,
        """
        SELECT COUNT(DISTINCT isin_key)
        FROM (
            SELECT isin_key FROM fitrs_equity_results WHERE isin_key <> ''
            UNION ALL
            SELECT isin_key FROM firds_instruments WHERE isin_key <> ''
        )
        """,
    )
    result["distinct_mics"] = count_query(
        conn,
        """
        SELECT COUNT(DISTINCT mic_key)
        FROM (
            SELECT mic_key FROM fitrs_equity_results WHERE mic_key <> ''
            UNION ALL
            SELECT mic_key FROM firds_instruments WHERE mic_key <> ''
            UNION ALL
            SELECT mic_key FROM trading_venues WHERE mic_key <> ''
        )
        """,
    )
    result["latest_calculation_date"] = conn.execute("SELECT MAX(calculation_date) FROM fitrs_equity_results").fetchone()[0]
    return result


def source_files(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return query_df(
        conn,
        """
        SELECT 'FITRS equities' AS dataset, source_file_name, COUNT(*) AS rows_loaded, MAX(ingestion_timestamp) AS last_ingested
        FROM fitrs_equity_results
        GROUP BY source_file_name
        UNION ALL
        SELECT 'FIRDS' AS dataset, source_file_name, COUNT(*) AS rows_loaded, MAX(ingestion_timestamp) AS last_ingested
        FROM firds_instruments
        GROUP BY source_file_name
        ORDER BY last_ingested DESC NULLS LAST
        """,
    )


def null_rates(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    rows = []
    checks = {
        "fitrs_equity_results": ["isin", "mic", "liquidity_status", "avg_daily_turnover", "avg_daily_transactions", "calculation_date"],
        "firds_instruments": ["isin", "mic", "instrument_full_name", "cfi_code", "issuer_lei", "admission_date"],
    }
    for table, columns in checks.items():
        total = count_query(conn, f"SELECT COUNT(*) FROM {table}")
        for column in columns:
            missing = count_query(conn, f"SELECT COUNT(*) FROM {table} WHERE {column} IS NULL OR CAST({column} AS VARCHAR) = ''")
            rows.append({"table": table, "field": column, "missing_rows": missing, "total_rows": total, "missing_rate": missing / total if total else None})
    return pd.DataFrame(rows)


def lookup_values(conn: duckdb.DuckDBPyConnection, kind: str, limit: int = 10000) -> list[str]:
    sql_map = {
        "mic": """
            SELECT mic_key AS value FROM (
                SELECT mic_key FROM trading_venues
                UNION SELECT mic_key FROM fitrs_equity_results
                UNION SELECT mic_key FROM firds_instruments
            ) WHERE value <> '' ORDER BY value LIMIT ?
        """,
        "liquidity": "SELECT DISTINCT liquidity_status AS value FROM fitrs_equity_results WHERE liquidity_status <> '' ORDER BY value LIMIT ?",
        "country": "SELECT DISTINCT country AS value FROM firds_instruments WHERE country <> '' ORDER BY value LIMIT ?",
        "instrument_type": "SELECT DISTINCT instrument_type AS value FROM fitrs_equity_results WHERE instrument_type <> '' ORDER BY value LIMIT ?",
        "reference_period": "SELECT DISTINCT reference_period AS value FROM fitrs_equity_results WHERE reference_period <> '' ORDER BY value DESC LIMIT ?",
    }
    if kind not in sql_map:
        return []
    df = query_df(conn, sql_map[kind], [limit])
    return df["value"].dropna().astype(str).tolist()


def diagnostics_for_isin(conn: duckdb.DuckDBPyConnection, isin: str, active_filters: dict[str, Any] | None = None) -> dict[str, Any]:
    key = normalize_upper(isin)
    mic = normalize_upper((active_filters or {}).get("mic") or "")
    return {
        "isin": key,
        "exists_in_fitrs_equities": count_query(conn, "SELECT COUNT(*) FROM fitrs_equity_results WHERE isin_key = ?", [key]) > 0,
        "exists_in_firds": count_query(conn, "SELECT COUNT(*) FROM firds_instruments WHERE isin_key = ?", [key]) > 0,
        "xath_exists_in_venues": count_query(
            conn,
            """
            SELECT COUNT(*) FROM (
                SELECT mic_key FROM trading_venues
                UNION ALL SELECT mic_key FROM fitrs_equity_results
                UNION ALL SELECT mic_key FROM firds_instruments
            ) WHERE mic_key = 'XATH'
            """,
        )
        > 0,
        "active_mic_filter": mic,
        "active_mic_filter_has_isin": bool(mic)
        and count_query(conn, "SELECT COUNT(*) FROM fitrs_equity_results WHERE isin_key = ? AND mic_key = ?", [key, mic]) > 0,
    }
