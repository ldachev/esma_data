"""Ingest ESMA FIRDS reference data into DuckDB.

FIRDS is very large. The default command ingests a bounded latest slice; use
``--limit 0`` only when you intentionally want an unbounded production ingest.

Run:
    python -m src.ingest_firds
"""

from __future__ import annotations

import argparse

from .config import DEFAULT_BATCH_SIZE, DEFAULT_FIRDS_LIMIT, ensure_directories
from .database import append_dataframe, connect, reset_table, upsert_venues
from .esma_sources import FIRDS, add_common_ingest_args, default_limit, iter_solr_documents
from .schema_mapper import map_firds_records, map_venues_from_firds


DEFAULT_FIRDS_QUERY = "type_s:parent"


def ingest_firds(*, limit: int | None, batch_size: int, query: str | None = None, reset: bool = False) -> int:
    ensure_directories()
    total = 0
    with connect() as conn:
        if reset:
            reset_table(conn, "firds_instruments")
        for docs, payload in iter_solr_documents(FIRDS, query=query or DEFAULT_FIRDS_QUERY, rows=batch_size, limit=limit):
            source_name = f"{FIRDS.core}:{payload.get('response', {}).get('start', 0)}"
            frame = map_firds_records(docs, source_file_name=source_name)
            total += append_dataframe(conn, "firds_instruments", frame)
            upsert_venues(conn, map_venues_from_firds(frame))
        conn.execute("CHECKPOINT")
    return total


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest ESMA FIRDS reference records into DuckDB.")
    add_common_ingest_args(parser, DEFAULT_FIRDS_LIMIT)
    parser.set_defaults(query=DEFAULT_FIRDS_QUERY)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    limit = default_limit(args.limit, args.default_limit_rows)
    total = ingest_firds(limit=limit, batch_size=args.batch_size or DEFAULT_BATCH_SIZE, query=args.query, reset=args.reset)
    print(f"Ingested {total:,} FIRDS rows into DuckDB.")


if __name__ == "__main__":
    main()
