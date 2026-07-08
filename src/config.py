"""Project configuration for the ESMA dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
PROCESSED_SECURITIES_PATH = PROCESSED_DATA_DIR / "securities_liquidity.csv"
DATABASE_PATH = PROCESSED_DATA_DIR / "esma_securities.duckdb"
SQLITE_FALLBACK_PATH = PROCESSED_DATA_DIR / "esma_securities.sqlite"


@dataclass(frozen=True)
class EsmaDataset:
    """Metadata for ESMA register-backed file indexes."""

    name: str
    register_url: str
    description: str
    raw_subdir: str
    default_rows: int = 20
    sort_field: str | None = None
    solr_filter: str | None = None


ESMA_DATASETS = {
    "firds": EsmaDataset(
        name="firds",
        register_url="https://registers.esma.europa.eu/solr/esma_registers_firds_files/select",
        description="FIRDS instrument reference data file index",
        raw_subdir="firds",
        sort_field="publication_date",
        solr_filter="file_type:FULINS",
    ),
    "fitrs": EsmaDataset(
        name="fitrs",
        register_url="https://registers.esma.europa.eu/solr/esma_registers_fitrs_files/select",
        description="FITRS transparency and liquidity calculation file index",
        raw_subdir="fitrs",
        sort_field="creation_date",
        solr_filter='instrument_type:"Equity Instruments"',
    ),
}


CANONICAL_COLUMNS = [
    "isin",
    "instrument_name",
    "asset_class",
    "instrument_type",
    "trading_venue",
    "mic_code",
    "venue_type",
    "country",
    "liquidity_status",
    "avg_daily_turnover",
    "avg_daily_transactions",
    "calculation_date",
    "reference_period",
    "source_dataset",
]


DEFAULT_SORT_COLUMN = "avg_daily_turnover"
DEFAULT_TABLE_LIMIT = 2500
MAX_RAW_DOWNLOAD_BYTES = 75 * 1024 * 1024


ASSET_CLASS_LABELS = {
    "SHRS": "Shares",
    "ETFS": "Exchange-traded funds",
    "BOND": "Bonds",
    "DERV": "Derivatives",
    "SFP": "Structured finance products",
    "OTHR": "Other",
}


VENUE_TYPE_LABELS = {
    "RM": "Regulated Market",
    "MTF": "Multilateral Trading Facility",
    "OTF": "Organised Trading Facility",
    "SI": "Systematic Internaliser",
    "APA": "Approved Publication Arrangement",
    "CTP": "Consolidated Tape Provider",
    "UNKNOWN": "Unknown",
}


def ensure_directories() -> None:
    """Create local data directories used by the dashboard."""

    for path in (RAW_DATA_DIR, PROCESSED_DATA_DIR):
        path.mkdir(parents=True, exist_ok=True)
    for dataset in ESMA_DATASETS.values():
        (RAW_DATA_DIR / dataset.raw_subdir).mkdir(parents=True, exist_ok=True)
