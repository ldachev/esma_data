"""Official ESMA source discovery and batch retrieval helpers."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from .config import CACHE_DATA_DIR, RAW_DATA_DIR, ensure_directories
from .utils import write_json


ESMA_SOLR_BASE = "https://registers.esma.europa.eu/solr"
ESMA_PUBLICATION_BASE = "https://registers.esma.europa.eu/publication/searchRegister"


@dataclass(frozen=True)
class EsmaSource:
    name: str
    core: str
    description: str
    default_query: str = "*:*"
    default_sort: str | None = "id asc"

    @property
    def solr_url(self) -> str:
        return f"{ESMA_SOLR_BASE}/{self.core}/select"

    @property
    def publication_url(self) -> str:
        return f"{ESMA_PUBLICATION_BASE}?core={self.core}"


FITRS_EQUITIES = EsmaSource(
    name="fitrs_equities",
    core="esma_registers_fitrs_equities",
    description="ESMA Equity Transparency Calculation Results",
    default_sort="isin asc,id asc",
)

FIRDS = EsmaSource(
    name="firds",
    core="esma_registers_firds",
    description="ESMA Financial Instruments Reference Data System",
    default_sort=None,
)


def fetch_solr_page(source: EsmaSource, *, start: int, rows: int, query: str | None = None, sort: str | None = None) -> dict[str, Any]:
    params = {
        "q": query or source.default_query,
        "wt": "json",
        "rows": rows,
        "start": start,
    }
    sort_value = sort if sort is not None else source.default_sort
    if sort_value:
        params["sort"] = sort_value
    response = requests.get(source.solr_url, params=params, timeout=60)
    response.raise_for_status()
    return response.json()


def iter_solr_documents(
    source: EsmaSource,
    *,
    query: str | None = None,
    rows: int = 5000,
    limit: int | None = None,
    cache_pages: bool = True,
) -> Iterator[tuple[list[dict[str, Any]], dict[str, Any]]]:
    """Yield Solr documents in bounded pages without loading the full source."""

    ensure_directories()
    start = 0
    remaining = limit
    while True:
        page_rows = rows if remaining is None else min(rows, remaining)
        if page_rows <= 0:
            break
        payload = fetch_solr_page(source, start=start, rows=page_rows, query=query)
        docs = payload.get("response", {}).get("docs", [])
        if cache_pages:
            cache_path = CACHE_DATA_DIR / source.name / f"page_{start}_{len(docs)}.json"
            write_json(cache_path, payload)
        if not docs:
            break
        yield docs, payload
        start += len(docs)
        if remaining is not None:
            remaining -= len(docs)
            if remaining <= 0:
                break
        total = payload.get("response", {}).get("numFound", 0)
        if start >= total:
            break


def discover_publication_files(source: EsmaSource, *, rows: int = 100) -> list[dict[str, Any]]:
    """Return raw publication/register rows for the source when file metadata exists."""

    payload = fetch_solr_page(source, start=0, rows=rows)
    return payload.get("response", {}).get("docs", [])


def default_limit(value: str | None, fallback: int | None) -> int | None:
    if value is None or value == "":
        return fallback
    if value.lower() in {"none", "all", "full", "0"}:
        return None
    return int(value)


def add_common_ingest_args(parser: argparse.ArgumentParser, default_limit_rows: int | None) -> None:
    parser.add_argument("--limit", type=str, default=None, help="Maximum Solr rows to ingest. Use 0/all/full for no limit.")
    parser.add_argument("--batch-size", type=int, default=5000, help="Solr rows to fetch per batch.")
    parser.add_argument("--query", default=None, help="Optional Solr query override.")
    parser.add_argument("--reset", action="store_true", help="Replace the target table before ingesting.")
    parser.set_defaults(default_limit_rows=default_limit_rows)


def raw_file_path(source_name: str, filename: str) -> Path:
    ensure_directories()
    path = RAW_DATA_DIR / source_name / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
