"""Project configuration for the ESMA search application."""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
CACHE_DATA_DIR = DATA_DIR / "cache"
DATABASE_PATH = PROCESSED_DATA_DIR / "esma_search.duckdb"

DEFAULT_FITRS_LIMIT: int | None = None
DEFAULT_FIRDS_LIMIT = 50_000
DEFAULT_BATCH_SIZE = 5_000
DEFAULT_PAGE_SIZE = 100


def ensure_directories() -> None:
    for path in (RAW_DATA_DIR, PROCESSED_DATA_DIR, CACHE_DATA_DIR):
        path.mkdir(parents=True, exist_ok=True)
    for name in ("fitrs_equities", "firds"):
        (RAW_DATA_DIR / name).mkdir(parents=True, exist_ok=True)
        (CACHE_DATA_DIR / name).mkdir(parents=True, exist_ok=True)
