"""Live on-demand ESMA Solr search helpers."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .esma_sources import FIRDS, FITRS_EQUITIES, fetch_solr_page
from .schema_mapper import map_firds_records, map_fitrs_records
from .utils import normalize_upper


LIVE_PAGE_SIZE = 20

LIVE_FIRDS_DISPLAY_COLUMNS = {
    "isin": "Instrument identification code",
    "mic": "Trading venue",
    "instrument_full_name": "Instrument Full name",
    "classification": "Instrument classification",
    "issuer_lei": "Issuer or operator of the trading venue identifier",
    "admission_date": "Date of admission to trading or date of first trade",
    "termination_date": "Termination date",
    "notional_currency_1": "Notional currency 1",
    "short_name": "Financial instrument short name",
    "rca_mic": "RCA MIC",
    "regulated_market": "Regulated market",
    "country": "Country",
}


@dataclass(frozen=True)
class LiveResult:
    frame: pd.DataFrame
    total: int
    start: int
    rows: int
    query: str
    source: str
    error: str | None = None

    @property
    def next_start(self) -> int | None:
        candidate = self.start + self.rows
        return candidate if candidate < self.total else None

    @property
    def previous_start(self) -> int | None:
        candidate = max(0, self.start - self.rows)
        return candidate if self.start > 0 else None


def _escape_solr_term(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def build_fitrs_query(term: str) -> str:
    key = normalize_upper(term)
    if not key:
        return "*:*"
    quoted = _escape_solr_term(key)
    wildcard = key.replace(" ", "\\ ")
    return f'isin:{quoted} OR mrmtl:{quoted} OR cfi_code:{wildcard}* OR mifir_identifier:{wildcard}*'


def build_firds_query(term: str) -> str:
    key = normalize_upper(term)
    if not key:
        return "type_s:parent"
    quoted = _escape_solr_term(key)
    wildcard = key.replace(" ", "\\ ")
    if len(key) == 12 and key.isalnum():
        return f"type_s:parent AND isin:{quoted}"
    if len(key) == 4 and key.isalnum():
        return f"type_s:parent AND mic:{quoted}"
    if key.startswith("LEI:"):
        return f"type_s:parent AND lei:{_escape_solr_term(key.removeprefix('LEI:'))}"
    return (
        "type_s:parent AND "
        f"(isin:{quoted} OR mic:{quoted} OR gnr_full_name:*{wildcard}* "
        f"OR gnr_short_name:*{wildcard}* OR lei:{quoted})"
    )


def empty_live_result(source: str, query: str, start: int, rows: int, error: str) -> LiveResult:
    return LiveResult(pd.DataFrame(), 0, start, rows, query, source, error)


def _payload_total(payload: dict) -> int:
    return int(payload.get("response", {}).get("numFound", 0))


def live_fitrs_search(term: str, *, start: int = 0, rows: int = LIVE_PAGE_SIZE) -> LiveResult:
    query = build_fitrs_query(term)
    try:
        payload = fetch_solr_page(FITRS_EQUITIES, start=start, rows=rows, query=query)
    except Exception as exc:
        return empty_live_result("FITRS equities", query, start, rows, str(exc))
    docs = payload.get("response", {}).get("docs", [])
    frame = map_fitrs_records(docs, source_file_name="live:esma_registers_fitrs_equities")
    display = frame[
        [
            "isin",
            "mic",
            "liquidity_status",
            "avg_daily_turnover",
            "avg_daily_transactions",
            "mifir_identifier",
            "cfi_code",
            "instrument_type",
            "calculation_date",
            "reference_period",
            "source_record_id",
        ]
    ].copy()
    return LiveResult(display, _payload_total(payload), start, rows, query, "FITRS equities")


def live_firds_search(term: str, *, start: int = 0, rows: int = LIVE_PAGE_SIZE) -> LiveResult:
    query = build_firds_query(term)
    try:
        payload = fetch_solr_page(FIRDS, start=start, rows=rows, query=query)
    except Exception as exc:
        return empty_live_result("FIRDS", query, start, rows, str(exc))
    docs = payload.get("response", {}).get("docs", [])
    frame = map_firds_records(docs, source_file_name="live:esma_registers_firds")
    display = frame[list(LIVE_FIRDS_DISPLAY_COLUMNS)].rename(columns=LIVE_FIRDS_DISPLAY_COLUMNS).copy()
    return LiveResult(display, _payload_total(payload), start, rows, query, "FIRDS")


def live_isin_bundle(isin: str, *, rows: int = LIVE_PAGE_SIZE) -> dict[str, LiveResult]:
    return {
        "fitrs": live_fitrs_search(isin, start=0, rows=rows),
        "firds": live_firds_search(isin, start=0, rows=rows),
    }
