"""Flexible ESMA schema mapping into canonical search tables."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .utils import first_present, json_dumps, normalize_text, normalize_upper, parse_date, parse_timestamp, to_float, utc_now_iso


FITRS_COLUMNS = [
    "isin",
    "isin_key",
    "instrument_name",
    "mic",
    "mic_key",
    "venue_name",
    "venue_name_key",
    "liquidity_status",
    "avg_daily_turnover",
    "avg_daily_transactions",
    "mifir_identifier",
    "cfi_code",
    "instrument_type",
    "calculation_date",
    "reference_period",
    "calculation_period_from",
    "calculation_period_to",
    "methodology",
    "source_file_name",
    "source_record_id",
    "ingestion_timestamp",
    "raw_payload",
]

FIRDS_COLUMNS = [
    "isin",
    "isin_key",
    "instrument_full_name",
    "instrument_name_key",
    "short_name",
    "classification",
    "cfi_code",
    "issuer_lei",
    "mic",
    "mic_key",
    "admission_date",
    "termination_date",
    "notional_currency_1",
    "rca_mic",
    "regulated_market",
    "country",
    "venue_type",
    "source_file_name",
    "source_record_id",
    "ingestion_timestamp",
    "raw_payload",
]

VENUE_COLUMNS = [
    "mic",
    "mic_key",
    "venue_name",
    "venue_name_key",
    "country",
    "venue_type",
    "source",
    "ingestion_timestamp",
]


FITRS_SYNONYMS: dict[str, list[str]] = {
    "isin": ["isin", "ISIN", "FinInstrmGnlAttrbts.Id"],
    "mic": ["mrmtl", "mic", "trading_venue", "venue_mic", "TradgVn"],
    "venue_name": ["venue_name", "trading_venue_name", "market_name"],
    "liquidity_status": ["liquidity_flag", "liquidity_status", "liquid", "liq"],
    "avg_daily_turnover": ["adt", "avg_daily_turnover", "average_daily_turnover", "AvrgDalyTrnovr"],
    "avg_daily_transactions": ["adnte", "avg_daily_transactions", "average_daily_number_of_transactions", "AvrgDalyNbOfTx"],
    "mifir_identifier": ["mifir_identifier", "asset_class", "MiFIRId"],
    "cfi_code": ["cfi_code", "classification", "FinInstrmGnlAttrbts.ClssfctnTp"],
    "calculation_time": ["calculation_time", "calculation_date", "publication_date"],
    "calculation_period_from": ["calculation_period_from", "reference_period_from"],
    "calculation_period_to": ["calculation_period_to", "reference_period_to"],
    "methodology": ["methodology", "reference_period", "period"],
}

FIRDS_SYNONYMS: dict[str, list[str]] = {
    "isin": ["isin", "ISIN", "fininstrmgnlattrbts_id"],
    "mic": ["mic", "trading_venue", "venue_mic", "tradg_vn"],
    "instrument_full_name": ["gnr_full_name", "instrument_full_name", "full_name", "fininstrmgnlattrbts_fullnm"],
    "short_name": ["gnr_short_name", "short_name", "fininstrmgnlattrbts_shrtnm"],
    "classification": ["gnr_cfi_code", "classification", "cfi_code"],
    "cfi_code": ["gnr_cfi_code", "cfi_code", "classification"],
    "issuer_lei": ["lei", "issuer_lei", "issuer"],
    "admission_date": ["mrkt_trdng_start_date", "admission_date", "admission_to_trading_date"],
    "termination_date": ["mrkt_trdng_trmination_date", "termination_date"],
    "notional_currency_1": ["gnr_notional_curr_code", "notional_currency_1", "notional_curr_code"],
    "rca_mic": ["rca_mic", "relevant_competent_authority_mic"],
    "regulated_market": ["regulated_market", "rmkt", "mrkt_issr_trdng_rqst_flag"],
    "country": ["upcoming_rca", "country", "country_code"],
    "venue_type": ["venue_type", "market_type"],
}


def _value(row: dict[str, Any], synonyms: dict[str, list[str]], canonical: str) -> Any:
    return first_present(row, synonyms.get(canonical, [canonical]))


def instrument_type_from_cfi(cfi_code: object, mifir_identifier: object = None) -> str:
    mifir = normalize_upper(mifir_identifier)
    cfi = normalize_upper(cfi_code)
    if mifir == "SHRS" or cfi.startswith("ES"):
        return "Share"
    if mifir == "ETFS" or cfi.startswith("CE"):
        return "ETF"
    if cfi.startswith("DB"):
        return "Bond"
    if cfi.startswith("R"):
        return "Derivative / warrant"
    return mifir or cfi[:2] or "Unknown"


def map_fitrs_records(records: list[dict[str, Any]], source_file_name: str = "esma_registers_fitrs_equities") -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    ts = utc_now_iso()
    for record in records:
        isin = normalize_upper(_value(record, FITRS_SYNONYMS, "isin"))
        mic = normalize_upper(_value(record, FITRS_SYNONYMS, "mic"))
        cfi = normalize_upper(_value(record, FITRS_SYNONYMS, "cfi_code"))
        mifir = normalize_upper(_value(record, FITRS_SYNONYMS, "mifir_identifier"))
        period_from = parse_date(_value(record, FITRS_SYNONYMS, "calculation_period_from"))
        period_to = parse_date(_value(record, FITRS_SYNONYMS, "calculation_period_to"))
        methodology = normalize_text(_value(record, FITRS_SYNONYMS, "methodology"))
        reference_period = methodology
        if period_from or period_to:
            reference_period = f"{methodology} {period_from or ''} to {period_to or ''}".strip()
        rows.append(
            {
                "isin": isin,
                "isin_key": isin,
                "instrument_name": normalize_text(record.get("instrument_name")),
                "mic": mic,
                "mic_key": mic,
                "venue_name": normalize_text(_value(record, FITRS_SYNONYMS, "venue_name")),
                "venue_name_key": normalize_upper(_value(record, FITRS_SYNONYMS, "venue_name")),
                "liquidity_status": normalize_text(_value(record, FITRS_SYNONYMS, "liquidity_status")) or "Unknown",
                "avg_daily_turnover": to_float(_value(record, FITRS_SYNONYMS, "avg_daily_turnover")),
                "avg_daily_transactions": to_float(_value(record, FITRS_SYNONYMS, "avg_daily_transactions")),
                "mifir_identifier": mifir,
                "cfi_code": cfi,
                "instrument_type": instrument_type_from_cfi(cfi, mifir),
                "calculation_date": parse_date(_value(record, FITRS_SYNONYMS, "calculation_time")),
                "reference_period": reference_period,
                "calculation_period_from": period_from,
                "calculation_period_to": period_to,
                "methodology": methodology,
                "source_file_name": source_file_name,
                "source_record_id": normalize_text(record.get("id") or record.get("_root_")),
                "ingestion_timestamp": ts,
                "raw_payload": json_dumps(record),
            }
        )
    return pd.DataFrame(rows, columns=FITRS_COLUMNS)


def map_firds_records(records: list[dict[str, Any]], source_file_name: str = "esma_registers_firds") -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    ts = utc_now_iso()
    for record in records:
        isin = normalize_upper(_value(record, FIRDS_SYNONYMS, "isin"))
        mic = normalize_upper(_value(record, FIRDS_SYNONYMS, "mic"))
        full_name = normalize_text(_value(record, FIRDS_SYNONYMS, "instrument_full_name"))
        cfi = normalize_upper(_value(record, FIRDS_SYNONYMS, "cfi_code"))
        rows.append(
            {
                "isin": isin,
                "isin_key": isin,
                "instrument_full_name": full_name,
                "instrument_name_key": normalize_upper(full_name),
                "short_name": normalize_text(_value(record, FIRDS_SYNONYMS, "short_name")),
                "classification": normalize_text(_value(record, FIRDS_SYNONYMS, "classification")),
                "cfi_code": cfi,
                "issuer_lei": normalize_upper(_value(record, FIRDS_SYNONYMS, "issuer_lei")),
                "mic": mic,
                "mic_key": mic,
                "admission_date": parse_timestamp(_value(record, FIRDS_SYNONYMS, "admission_date")),
                "termination_date": parse_timestamp(_value(record, FIRDS_SYNONYMS, "termination_date")),
                "notional_currency_1": normalize_upper(_value(record, FIRDS_SYNONYMS, "notional_currency_1")),
                "rca_mic": normalize_upper(_value(record, FIRDS_SYNONYMS, "rca_mic")),
                "regulated_market": normalize_text(_value(record, FIRDS_SYNONYMS, "regulated_market")),
                "country": normalize_upper(_value(record, FIRDS_SYNONYMS, "country")),
                "venue_type": normalize_upper(_value(record, FIRDS_SYNONYMS, "venue_type")),
                "source_file_name": source_file_name,
                "source_record_id": normalize_text(record.get("id") or record.get("_root_")),
                "ingestion_timestamp": ts,
                "raw_payload": json_dumps(record),
            }
        )
    return pd.DataFrame(rows, columns=FIRDS_COLUMNS)


def map_venues_from_fitrs(fitrs_df: pd.DataFrame) -> pd.DataFrame:
    if fitrs_df.empty:
        return pd.DataFrame(columns=VENUE_COLUMNS)
    venues = fitrs_df[["mic", "mic_key", "venue_name", "venue_name_key", "ingestion_timestamp"]].drop_duplicates()
    venues["country"] = ""
    venues["venue_type"] = ""
    venues["source"] = "FITRS equities"
    return venues[VENUE_COLUMNS]


def map_venues_from_firds(firds_df: pd.DataFrame) -> pd.DataFrame:
    if firds_df.empty:
        return pd.DataFrame(columns=VENUE_COLUMNS)
    venues = firds_df[["mic", "mic_key", "country", "venue_type", "ingestion_timestamp"]].drop_duplicates()
    venues["venue_name"] = ""
    venues["venue_name_key"] = ""
    venues["source"] = "FIRDS"
    return venues[VENUE_COLUMNS]
