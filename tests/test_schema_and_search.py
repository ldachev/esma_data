from __future__ import annotations

import duckdb

from src.database import append_dataframe, initialize_schema, upsert_venues
from src.schema_mapper import map_firds_records, map_fitrs_records, map_venues_from_firds, map_venues_from_fitrs
from src.search_index import isin_fitrs, liquidity_screener, venue_instruments


def memory_conn():
    conn = duckdb.connect(":memory:")
    initialize_schema(conn)
    return conn


def load_fixture(conn):
    fitrs = map_fitrs_records(
        [
            {
                "ISIN": "grs014003032",
                "mrmtl": "xath",
                "liquidity_flag": "Non liquid",
                "adt": 3200,
                "adnte": 12,
                "mifir_identifier": "SHRS",
                "cfi_code": "ESVUFR",
                "calculation_time": "2026-01-15T00:00:00Z",
                "methodology": "YEAR",
            },
            {
                "isin": "NL0010273215",
                "mrmtl": "XAMS",
                "liquidity_flag": "Liquid",
                "adt": 500000,
                "adnte": 200,
                "mifir_identifier": "SHRS",
                "cfi_code": "ESVUFR",
                "calculation_time": "2026-01-15T00:00:00Z",
                "methodology": "YEAR",
            },
        ]
    )
    firds = map_firds_records(
        [
            {
                "isin": "GRS014003032",
                "mic": "XATH",
                "gnr_full_name": "Alpha Services and Holdings SA",
                "gnr_cfi_code": "ESVUFR",
                "lei": "TESTLEI1",
                "upcoming_rca": "GR",
            },
            {
                "isin": "FRONLYFIRDS1",
                "mic": "XPAR",
                "gnr_full_name": "Only FIRDS SA",
                "gnr_cfi_code": "ESVUFR",
            },
        ]
    )
    append_dataframe(conn, "fitrs_equity_results", fitrs)
    append_dataframe(conn, "firds_instruments", firds)
    upsert_venues(conn, map_venues_from_fitrs(fitrs))
    upsert_venues(conn, map_venues_from_firds(firds))


def test_schema_mapping_accepts_alternate_column_names():
    frame = map_fitrs_records([{"ISIN": "abc", "mrmtl": "xath", "adt": "123.4", "adnte": "5"}])
    assert frame.loc[0, "isin"] == "ABC"
    assert frame.loc[0, "mic"] == "XATH"
    assert frame.loc[0, "avg_daily_turnover"] == 123.4


def test_isin_search_is_case_insensitive():
    conn = memory_conn()
    load_fixture(conn)
    assert len(isin_fitrs(conn, "grs014003032")) == 1


def test_mic_search_is_case_insensitive():
    conn = memory_conn()
    load_fixture(conn)
    rows, total = venue_instruments(conn, "xath")
    assert total == 1
    assert rows.loc[0, "isin"] == "GRS014003032"


def test_venue_explorer_returns_non_top_venues():
    conn = memory_conn()
    load_fixture(conn)
    rows, total = venue_instruments(conn, "XATH")
    assert total == 1
    assert rows.loc[0, "mic"] == "XATH"


def test_liquidity_sorting_works():
    conn = memory_conn()
    load_fixture(conn)
    rows, _ = liquidity_screener(conn, {"sort_by": "avg_daily_turnover", "sort_desc": True}, limit=10, offset=0)
    assert rows.loc[0, "isin"] == "NL0010273215"


def test_fitrs_firds_join_does_not_drop_unmatched_records():
    conn = memory_conn()
    load_fixture(conn)
    rows, total = liquidity_screener(conn, {}, limit=10, offset=0)
    assert total == 2
    assert set(rows["isin"]) == {"GRS014003032", "NL0010273215"}


def test_app_queries_work_when_only_fitrs_loaded():
    conn = memory_conn()
    fitrs = map_fitrs_records([{"isin": "ONLYFITRS1", "mrmtl": "XAMS", "adt": 1}])
    append_dataframe(conn, "fitrs_equity_results", fitrs)
    rows, total = venue_instruments(conn, "XAMS")
    assert total == 1
    assert rows.loc[0, "isin"] == "ONLYFITRS1"


def test_app_queries_work_when_only_firds_loaded():
    conn = memory_conn()
    firds = map_firds_records([{"isin": "ONLYFIRDS1", "mic": "XPAR", "gnr_full_name": "Only FIRDS"}])
    append_dataframe(conn, "firds_instruments", firds)
    assert len(isin_fitrs(conn, "ONLYFIRDS1")) == 0
