"""Live on-demand ESMA Solr search helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlencode

import pandas as pd

from .esma_sources import FIRDS, FITRS_EQUITIES, fetch_solr_facet, fetch_solr_page
from .schema_mapper import map_firds_records, map_fitrs_records
from .utils import normalize_upper, utc_now_iso


LIVE_PAGE_SIZE = 20

LIVE_FIRDS_DISPLAY_COLUMNS = {
    "isin": "Instrument identification code",
    "mic": "Trading venue",
    "instrument_full_name": "Instrument full name",
    "classification": "Instrument classification",
    "issuer_lei": "Issuer or operator of the trading venue identifier",
    "admission_date": "Date of admission to trading or date of first trade",
    "termination_date": "Termination date",
    "short_name": "Financial instrument short name",
    "request_for_admission_by_issuer": "Request for admission to trading by issuer",
    "rca_mic": "RCA MIC",
    "more_info": "More Info",
}

LIVE_FITRS_DISPLAY_COLUMNS = {
    "isin": "ISIN",
    "methodology": "Methodology",
    "calculation_period_from": "Calculation From Date",
    "calculation_period_to": "Calculation To Date",
    "liquidity_status": "Liquidity Flag",
    "avg_daily_turnover": "ADT",
    "mic": "MRMTL",
    "adnte_on_mrmtl": "ADNTE on MRMTL",
    "mifir_identifier": "Mifir Identifier",
    "cfi_code": "CFI Code",
    "more_info": "More Info",
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
    canonical: pd.DataFrame = field(default_factory=pd.DataFrame)
    fetched_at: str = ""

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


def build_fitrs_query(term: str, *, methodology: str | None = None, liquidity_flag: str | None = None) -> str:
    key = normalize_upper(term)
    if not key:
        base = "*:*"
    else:
        quoted = _escape_solr_term(key)
        wildcard = key.replace(" ", "\\ ")
        base = f'isin:{quoted} OR mrmtl:{quoted} OR cfi_code:{wildcard}* OR mifir_identifier:{wildcard}*'

    clauses = []
    if methodology:
        clauses.append(f"methodology:{_escape_solr_term(methodology)}")
    if liquidity_flag:
        clauses.append(f"liquidity_flag:{_escape_solr_term(liquidity_flag)}")
    if clauses:
        return f"({base}) AND " + " AND ".join(clauses)
    return base


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
    return LiveResult(pd.DataFrame(), 0, start, rows, query, source, error, fetched_at=utc_now_iso())


def _payload_total(payload: dict) -> int:
    return int(payload.get("response", {}).get("numFound", 0))


def _record_query(row: pd.Series) -> str:
    record_id = str(row.get("source_record_id") or "").strip()
    if record_id:
        return f'id:"{record_id}"'
    isin = str(row.get("isin") or "").strip()
    if isin:
        return f'isin:"{isin}"'
    mic = str(row.get("mic") or "").strip()
    if mic:
        return f'mic:"{mic}"'
    return "*:*"


def _display_frame(frame: pd.DataFrame, display_columns: dict[str, str], source) -> pd.DataFrame:
    display = frame.copy()
    if "more_info" in display_columns:
        display["more_info"] = [
            f"{source.solr_url}?{urlencode({'q': _record_query(row), 'wt': 'json', 'rows': 1})}"
            for _, row in display.iterrows()
        ]
    for column in display_columns:
        if column not in display.columns:
            display[column] = pd.NA
    return display[list(display_columns)].rename(columns=display_columns).copy()


def live_fitrs_search(
    term: str,
    *,
    start: int = 0,
    rows: int = LIVE_PAGE_SIZE,
    methodology: str | None = None,
    liquidity_flag: str | None = None,
) -> LiveResult:
    query = build_fitrs_query(term, methodology=methodology, liquidity_flag=liquidity_flag)
    try:
        payload = fetch_solr_page(FITRS_EQUITIES, start=start, rows=rows, query=query)
    except Exception as exc:
        return empty_live_result("FITRS equities", query, start, rows, str(exc))
    docs = payload.get("response", {}).get("docs", [])
    frame = map_fitrs_records(docs, source_file_name="live:esma_registers_fitrs_equities")
    display = _display_frame(frame, LIVE_FITRS_DISPLAY_COLUMNS, FITRS_EQUITIES)
    return LiveResult(
        display, _payload_total(payload), start, rows, query, "FITRS equities", canonical=frame, fetched_at=utc_now_iso()
    )


def live_firds_search(term: str, *, start: int = 0, rows: int = LIVE_PAGE_SIZE) -> LiveResult:
    query = build_firds_query(term)
    try:
        payload = fetch_solr_page(FIRDS, start=start, rows=rows, query=query)
    except Exception as exc:
        return empty_live_result("FIRDS", query, start, rows, str(exc))
    docs = payload.get("response", {}).get("docs", [])
    frame = map_firds_records(docs, source_file_name="live:esma_registers_firds")
    display = _display_frame(frame, LIVE_FIRDS_DISPLAY_COLUMNS, FIRDS)
    return LiveResult(
        display, _payload_total(payload), start, rows, query, "FIRDS", canonical=frame, fetched_at=utc_now_iso()
    )


def live_isin_bundle(isin: str, *, rows: int = LIVE_PAGE_SIZE) -> dict[str, LiveResult]:
    return {
        "fitrs": live_fitrs_search(isin, start=0, rows=rows),
        "firds": live_firds_search(isin, start=0, rows=rows),
    }


def live_fitrs_liquidity_breakdown(term: str) -> list[tuple[str, int]]:
    """Liquid/non-liquid split over the *full* live FITRS result set for this search term."""

    try:
        return fetch_solr_facet(FITRS_EQUITIES, query=build_fitrs_query(term), facet_field="liquidity_flag")
    except Exception:
        return []


def live_fitrs_methodology_breakdown(term: str) -> list[tuple[str, int]]:
    """Methodology split over the *full* live FITRS result set for this search term."""

    try:
        return fetch_solr_facet(FITRS_EQUITIES, query=build_fitrs_query(term), facet_field="methodology", limit=50)
    except Exception:
        return []


def live_fitrs_venue_breakdown(term: str, *, limit: int = 15) -> list[tuple[str, int]]:
    """Top venues (MRMTL) over the *full* live FITRS result set for this search term."""

    try:
        return fetch_solr_facet(FITRS_EQUITIES, query=build_fitrs_query(term), facet_field="mrmtl", limit=limit)
    except Exception:
        return []
