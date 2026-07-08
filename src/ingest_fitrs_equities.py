"""Ingest ESMA Equity Transparency Calculation Results into DuckDB.

Run:
    python -m src.ingest_fitrs_equities
"""

from __future__ import annotations

import argparse

from .config import DEFAULT_BATCH_SIZE, DEFAULT_FITRS_LIMIT, ensure_directories
from .database import append_dataframe, connect, reset_table, upsert_venues
from .esma_sources import FITRS_EQUITIES, add_common_ingest_args, default_limit, iter_solr_documents
from .schema_mapper import map_fitrs_records, map_venues_from_fitrs


def ingest_fitrs_equities(*, limit: int | None, batch_size: int, query: str | None = None, reset: bool = False) -> int:
    ensure_directories()
    total = 0
    with connect() as conn:
        if reset:
            reset_table(conn, "fitrs_equity_results")
        for docs, payload in iter_solr_documents(FITRS_EQUITIES, query=query, rows=batch_size, limit=limit):
            source_name = f"{FITRS_EQUITIES.core}:{payload.get('response', {}).get('start', 0)}"
            frame = map_fitrs_records(docs, source_file_name=source_name)
            total += append_dataframe(conn, "fitrs_equity_results", frame)
            upsert_venues(conn, map_venues_from_fitrs(frame))
        conn.execute("CHECKPOINT")
    return total


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest ESMA FITRS equity transparency results into DuckDB.")
    add_common_ingest_args(parser, DEFAULT_FITRS_LIMIT)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    limit = default_limit(args.limit, args.default_limit_rows)
    total = ingest_fitrs_equities(limit=limit, batch_size=args.batch_size or DEFAULT_BATCH_SIZE, query=args.query, reset=args.reset)
    print(f"Ingested {total:,} FITRS equity rows into DuckDB.")


if __name__ == "__main__":
    main()
