"""Parsing, cleaning, and normalization utilities for ESMA-style datasets."""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Iterable

import pandas as pd

from .config import CANONICAL_COLUMNS


COLUMN_SYNONYMS: dict[str, tuple[str, ...]] = {
    "isin": (
        "isin",
        "isin_code",
        "fininstrmgnlattrbts_id",
        "fin_instrm_gnl_attrbts_id",
        "id",
        "instrument_isin",
    ),
    "instrument_name": (
        "instrument_name",
        "name",
        "fullnm",
        "full_name",
        "fininstrmgnlattrbts_fullnm",
        "fin_instrm_gnl_attrbts_full_nm",
        "instrm_full_nm",
    ),
    "asset_class": (
        "asset_class",
        "assetclass",
        "asset_clss",
        "fininstrmclssfctn",
        "classification_type",
        "cfi_code",
        "instrument_classification",
    ),
    "instrument_type": (
        "instrument_type",
        "instrumenttype",
        "type",
        "fininstrmgnlattrbts_clssfctntp",
        "classification_type",
        "cfi_group",
    ),
    "trading_venue": (
        "trading_venue",
        "venue",
        "venue_name",
        "tradingvenue",
        "trading_venue_name",
        "mkt_nm",
        "market_name",
    ),
    "mic_code": (
        "mic_code",
        "mic",
        "venue_mic",
        "trading_venue_mic",
        "tradg_vn",
        "tradingvenueid",
        "venue_id",
        "mkt_id_cd",
    ),
    "venue_type": (
        "venue_type",
        "venuetype",
        "market_type",
        "trading_venue_type",
        "organised_trading_venue_type",
    ),
    "country": (
        "country",
        "ctry",
        "country_code",
        "issuer_country",
        "authority_country",
        "competent_authority_country",
    ),
    "liquidity_status": (
        "liquidity_status",
        "liquid",
        "liquidity",
        "liq",
        "liquidity_flag",
        "is_liquid",
        "liqdty",
    ),
    "avg_daily_turnover": (
        "avg_daily_turnover",
        "average_daily_turnover",
        "adturnover",
        "adt",
        "avrg_daly_turnover",
        "avrgdlytrnovr",
        "average_daily_notional_amount",
    ),
    "avg_daily_transactions": (
        "avg_daily_transactions",
        "average_daily_transactions",
        "adnt",
        "adn_transactions",
        "avrg_daly_nb_of_tx",
        "avrgdlynbroftrades",
        "average_daily_number_of_transactions",
    ),
    "calculation_date": (
        "calculation_date",
        "calc_date",
        "calculationdate",
        "publication_date",
        "pub_date",
        "tech_rcrd_id",
    ),
    "reference_period": (
        "reference_period",
        "referenceperiod",
        "ref_period",
        "period",
        "from_to_date",
        "applicable_from",
    ),
}


def normalize_column_name(column: object) -> str:
    """Normalize arbitrary ESMA XML/CSV column names into comparable tokens."""

    cleaned = re.sub(r"[^0-9a-zA-Z]+", "_", str(column)).strip("_").lower()
    return re.sub(r"_+", "_", cleaned)


def _synonym_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}
    for canonical, synonyms in COLUMN_SYNONYMS.items():
        lookup[normalize_column_name(canonical)] = canonical
        for synonym in synonyms:
            lookup[normalize_column_name(synonym)] = canonical
    return lookup


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename known ESMA schema variants to the dashboard's canonical names."""

    lookup = _synonym_lookup()
    rename_map: dict[object, str] = {}
    used: set[str] = set()

    for column in df.columns:
        normalized = normalize_column_name(column)
        canonical = lookup.get(normalized)
        if canonical and canonical not in used:
            rename_map[column] = canonical
            used.add(canonical)
        elif normalized and normalized not in used:
            rename_map[column] = normalized
            used.add(normalized)

    return df.rename(columns=rename_map)


def ensure_canonical_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add missing canonical fields so downstream code can be schema-tolerant."""

    result = df.copy()
    for column in CANONICAL_COLUMNS:
        if column not in result.columns:
            result[column] = pd.NA
    return result


def _coerce_liquidity(value: object) -> str:
    if pd.isna(value):
        return "Unknown"
    text = str(value).strip().lower()
    if text in {"true", "t", "1", "y", "yes", "liquid", "liq", "l"}:
        return "Liquid"
    if text in {"false", "f", "0", "n", "no", "not liquid", "illiquid", "i"}:
        return "Not liquid"
    return str(value).strip().title() or "Unknown"


def _infer_asset_class(row: pd.Series) -> str:
    raw = row.get("asset_class")
    instrument_type = row.get("instrument_type")
    text = f"{raw or ''} {instrument_type or ''}".upper()
    if "SHR" in text or text.startswith("ES"):
        return "Shares"
    if "ETF" in text:
        return "Exchange-traded funds"
    if "BOND" in text or text.startswith("DB"):
        return "Bonds"
    if "DERV" in text or "FUT" in text or "OPT" in text:
        return "Derivatives"
    if raw and not pd.isna(raw):
        return str(raw).strip()
    return "Unknown"


def clean_securities_frame(df: pd.DataFrame, source_dataset: str = "unknown") -> pd.DataFrame:
    """Return a normalized securities dataframe suitable for storage/querying."""

    if df.empty:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)

    result = normalize_columns(df)
    result = ensure_canonical_columns(result)

    result["isin"] = result["isin"].astype("string").str.strip().str.upper()
    result["instrument_name"] = result["instrument_name"].astype("string").str.strip()
    result["mic_code"] = result["mic_code"].astype("string").str.strip().str.upper()
    result["trading_venue"] = result["trading_venue"].astype("string").str.strip()
    result["venue_type"] = result["venue_type"].astype("string").str.strip().str.upper()
    result["country"] = result["country"].astype("string").str.strip().str.upper()
    result["liquidity_status"] = result["liquidity_status"].map(_coerce_liquidity)
    result["avg_daily_turnover"] = pd.to_numeric(result["avg_daily_turnover"], errors="coerce")
    result["avg_daily_transactions"] = pd.to_numeric(result["avg_daily_transactions"], errors="coerce")
    result["calculation_date"] = pd.to_datetime(result["calculation_date"], errors="coerce").dt.date
    result["reference_period"] = result["reference_period"].astype("string").str.strip()
    result["source_dataset"] = result["source_dataset"].fillna(source_dataset)
    result.loc[result["source_dataset"].isna(), "source_dataset"] = source_dataset
    result["asset_class"] = result.apply(_infer_asset_class, axis=1)

    result = result[result["isin"].notna() | result["mic_code"].notna()].copy()
    result = result.drop_duplicates(subset=["isin", "mic_code", "calculation_date"], keep="first")
    return result[CANONICAL_COLUMNS].reset_index(drop=True)


def coalesce_columns(df: pd.DataFrame, base: str) -> pd.Series:
    """Coalesce a column that may have merge suffixes."""

    candidates = [base, f"{base}_x", f"{base}_y", f"{base}_firds", f"{base}_fitrs", f"{base}_venue"]
    series = pd.Series(pd.NA, index=df.index)
    for candidate in candidates:
        if candidate in df.columns:
            series = series.combine_first(df[candidate])
    return series


def join_reference_and_liquidity(
    firds_df: pd.DataFrame | None,
    fitrs_df: pd.DataFrame | None,
    venues_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Join FIRDS reference rows with FITRS liquidity rows where keys overlap."""

    frames = {
        "firds": clean_securities_frame(firds_df, "FIRDS") if firds_df is not None else pd.DataFrame(),
        "fitrs": clean_securities_frame(fitrs_df, "FITRS") if fitrs_df is not None else pd.DataFrame(),
        "venues": clean_securities_frame(venues_df, "Venue reference") if venues_df is not None else pd.DataFrame(),
    }

    firds = frames["firds"]
    fitrs = frames["fitrs"]
    venues = frames["venues"]

    if firds.empty and fitrs.empty:
        combined = venues
    elif firds.empty:
        combined = fitrs
    elif fitrs.empty:
        combined = firds
    else:
        keys = [key for key in ("isin", "mic_code") if firds[key].notna().any() and fitrs[key].notna().any()]
        if not keys:
            combined = pd.concat([firds, fitrs], ignore_index=True)
        else:
            merged = firds.merge(fitrs, on=keys, how="outer", suffixes=("_firds", "_fitrs"))
            combined = pd.DataFrame({column: coalesce_columns(merged, column) for column in CANONICAL_COLUMNS})

    if not venues.empty and not combined.empty and "mic_code" in combined:
        venue_cols = ["mic_code", "trading_venue", "venue_type", "country"]
        venue_ref = venues[venue_cols].dropna(subset=["mic_code"]).drop_duplicates("mic_code")
        merged = combined.merge(venue_ref, on="mic_code", how="left", suffixes=("", "_venue"))
        for column in ("trading_venue", "venue_type", "country"):
            merged[column] = merged[column].combine_first(merged.get(f"{column}_venue"))
        combined = merged[CANONICAL_COLUMNS]

    return clean_securities_frame(combined, "Combined")


def read_tabular_file(path: Path, max_rows: int | None = None) -> pd.DataFrame:
    """Read common ESMA-delivered tabular or XML files into a dataframe."""

    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, nrows=max_rows)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path, nrows=max_rows)
    if suffix == ".json":
        return pd.read_json(path)
    if suffix == ".xml":
        return pd.read_xml(path, parser="lxml")
    if suffix == ".zip":
        return read_zip_file(path, max_rows=max_rows)
    raise ValueError(f"Unsupported file type: {path.suffix}")


def read_zip_file(path: Path, max_rows: int | None = None) -> pd.DataFrame:
    """Read the first supported file inside a ZIP archive."""

    with zipfile.ZipFile(path) as archive:
        for member in archive.namelist():
            member_suffix = Path(member).suffix.lower()
            if member_suffix not in {".csv", ".xml", ".json"}:
                continue
            with archive.open(member) as handle:
                payload = handle.read()
            if member_suffix == ".csv":
                return pd.read_csv(io.BytesIO(payload), nrows=max_rows)
            if member_suffix == ".json":
                return pd.read_json(io.BytesIO(payload))
            return pd.read_xml(io.BytesIO(payload), parser="lxml")
    raise ValueError(f"No supported CSV, JSON, or XML file found in {path}")


def load_cached_files(paths: Iterable[Path], source_dataset: str, max_rows: int | None = 5000) -> pd.DataFrame:
    """Load and normalize cached raw files, skipping files that fail to parse."""

    frames: list[pd.DataFrame] = []
    for path in paths:
        try:
            frames.append(clean_securities_frame(read_tabular_file(path, max_rows=max_rows), source_dataset))
        except Exception:
            continue
    if not frames:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)
    return pd.concat(frames, ignore_index=True).drop_duplicates()


def sample_securities_data() -> pd.DataFrame:
    """Small, realistic fallback dataset so the dashboard always runs."""

    rows = [
        {
            "isin": "DE0008404005",
            "instrument_name": "Allianz SE Registered Shares",
            "asset_class": "Shares",
            "instrument_type": "Equity share",
            "trading_venue": "Xetra",
            "mic_code": "XETR",
            "venue_type": "RM",
            "country": "DE",
            "liquidity_status": "Liquid",
            "avg_daily_turnover": 286_500_000,
            "avg_daily_transactions": 42_300,
            "calculation_date": "2026-06-30",
            "reference_period": "2026-Q2",
            "source_dataset": "Sample fallback",
        },
        {
            "isin": "FR0000120271",
            "instrument_name": "TotalEnergies SE",
            "asset_class": "Shares",
            "instrument_type": "Equity share",
            "trading_venue": "Euronext Paris",
            "mic_code": "XPAR",
            "venue_type": "RM",
            "country": "FR",
            "liquidity_status": "Liquid",
            "avg_daily_turnover": 241_200_000,
            "avg_daily_transactions": 38_900,
            "calculation_date": "2026-06-30",
            "reference_period": "2026-Q2",
            "source_dataset": "Sample fallback",
        },
        {
            "isin": "NL0010273215",
            "instrument_name": "ASML Holding NV",
            "asset_class": "Shares",
            "instrument_type": "Equity share",
            "trading_venue": "Euronext Amsterdam",
            "mic_code": "XAMS",
            "venue_type": "RM",
            "country": "NL",
            "liquidity_status": "Liquid",
            "avg_daily_turnover": 512_800_000,
            "avg_daily_transactions": 45_800,
            "calculation_date": "2026-06-30",
            "reference_period": "2026-Q2",
            "source_dataset": "Sample fallback",
        },
        {
            "isin": "ES0178430E18",
            "instrument_name": "Telefonica SA",
            "asset_class": "Shares",
            "instrument_type": "Equity share",
            "trading_venue": "Bolsa de Madrid",
            "mic_code": "XMAD",
            "venue_type": "RM",
            "country": "ES",
            "liquidity_status": "Liquid",
            "avg_daily_turnover": 86_700_000,
            "avg_daily_transactions": 17_250,
            "calculation_date": "2026-06-30",
            "reference_period": "2026-Q2",
            "source_dataset": "Sample fallback",
        },
        {
            "isin": "IT0005239360",
            "instrument_name": "UniCredit SpA",
            "asset_class": "Shares",
            "instrument_type": "Equity share",
            "trading_venue": "Borsa Italiana",
            "mic_code": "XMIL",
            "venue_type": "RM",
            "country": "IT",
            "liquidity_status": "Liquid",
            "avg_daily_turnover": 193_400_000,
            "avg_daily_transactions": 29_400,
            "calculation_date": "2026-06-30",
            "reference_period": "2026-Q2",
            "source_dataset": "Sample fallback",
        },
        {
            "isin": "BE0974293251",
            "instrument_name": "Anheuser-Busch InBev SA/NV",
            "asset_class": "Shares",
            "instrument_type": "Equity share",
            "trading_venue": "Euronext Brussels",
            "mic_code": "XBRU",
            "venue_type": "RM",
            "country": "BE",
            "liquidity_status": "Liquid",
            "avg_daily_turnover": 49_100_000,
            "avg_daily_transactions": 8_450,
            "calculation_date": "2026-06-30",
            "reference_period": "2026-Q2",
            "source_dataset": "Sample fallback",
        },
        {
            "isin": "FI0009000681",
            "instrument_name": "Nokia Oyj",
            "asset_class": "Shares",
            "instrument_type": "Equity share",
            "trading_venue": "Nasdaq Helsinki",
            "mic_code": "XHEL",
            "venue_type": "RM",
            "country": "FI",
            "liquidity_status": "Liquid",
            "avg_daily_turnover": 34_500_000,
            "avg_daily_transactions": 7_800,
            "calculation_date": "2026-06-30",
            "reference_period": "2026-Q2",
            "source_dataset": "Sample fallback",
        },
        {
            "isin": "AT0000652011",
            "instrument_name": "Erste Group Bank AG",
            "asset_class": "Shares",
            "instrument_type": "Equity share",
            "trading_venue": "Vienna Stock Exchange",
            "mic_code": "XWBO",
            "venue_type": "RM",
            "country": "AT",
            "liquidity_status": "Liquid",
            "avg_daily_turnover": 22_700_000,
            "avg_daily_transactions": 4_600,
            "calculation_date": "2026-06-30",
            "reference_period": "2026-Q2",
            "source_dataset": "Sample fallback",
        },
        {
            "isin": "PTEDP0AM0009",
            "instrument_name": "EDP Energias de Portugal SA",
            "asset_class": "Shares",
            "instrument_type": "Equity share",
            "trading_venue": "Euronext Lisbon",
            "mic_code": "XLIS",
            "venue_type": "RM",
            "country": "PT",
            "liquidity_status": "Liquid",
            "avg_daily_turnover": 18_300_000,
            "avg_daily_transactions": 3_950,
            "calculation_date": "2026-06-30",
            "reference_period": "2026-Q2",
            "source_dataset": "Sample fallback",
        },
        {
            "isin": "IE00B4BNMY34",
            "instrument_name": "iShares Core MSCI World UCITS ETF",
            "asset_class": "Exchange-traded funds",
            "instrument_type": "ETF",
            "trading_venue": "Euronext Dublin",
            "mic_code": "XDUB",
            "venue_type": "RM",
            "country": "IE",
            "liquidity_status": "Liquid",
            "avg_daily_turnover": 61_000_000,
            "avg_daily_transactions": 6_300,
            "calculation_date": "2026-06-30",
            "reference_period": "2026-Q2",
            "source_dataset": "Sample fallback",
        },
        {
            "isin": "SE0000108656",
            "instrument_name": "Telefonaktiebolaget LM Ericsson B",
            "asset_class": "Shares",
            "instrument_type": "Equity share",
            "trading_venue": "Nasdaq Stockholm",
            "mic_code": "XSTO",
            "venue_type": "RM",
            "country": "SE",
            "liquidity_status": "Liquid",
            "avg_daily_turnover": 28_900_000,
            "avg_daily_transactions": 5_850,
            "calculation_date": "2026-06-30",
            "reference_period": "2026-Q2",
            "source_dataset": "Sample fallback",
        },
        {
            "isin": "GRS014003032",
            "instrument_name": "Alpha Services and Holdings SA",
            "asset_class": "Shares",
            "instrument_type": "Equity share",
            "trading_venue": "Athens Exchange",
            "mic_code": "XATH",
            "venue_type": "RM",
            "country": "GR",
            "liquidity_status": "Not liquid",
            "avg_daily_turnover": 3_250_000,
            "avg_daily_transactions": 1_200,
            "calculation_date": "2026-06-30",
            "reference_period": "2026-Q2",
            "source_dataset": "Sample fallback",
        },
    ]
    return clean_securities_frame(pd.DataFrame(rows), "Sample fallback")
