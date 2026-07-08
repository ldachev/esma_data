"""ESMA data access helpers.

The dashboard uses ESMA public register file indexes and can also detect the
optional ``esma_data_py`` package when it is installed in the environment.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd
import requests

from .config import (
    ESMA_DATASETS,
    MAX_RAW_DOWNLOAD_BYTES,
    PROCESSED_SECURITIES_PATH,
    RAW_DATA_DIR,
    ensure_directories,
)
from .data_processing import (
    join_reference_and_liquidity,
    load_cached_files,
    sample_securities_data,
)


@dataclass
class DatasetResult:
    """Processed dataset and user-facing status messages."""

    frame: pd.DataFrame
    messages: list[str]
    used_sample: bool


class ESMADataError(RuntimeError):
    """Raised when an ESMA download or parse operation fails."""


def esma_data_py_status() -> dict[str, Any]:
    """Return basic availability metadata for the optional esma_data_py package."""

    try:
        module = importlib.import_module("esma_data_py")
    except Exception as exc:
        return {
            "available": False,
            "version": None,
            "message": f"esma_data_py is not installed or could not be imported: {exc}",
        }

    exports = [name for name in dir(module) if not name.startswith("_")][:20]
    return {
        "available": True,
        "version": getattr(module, "__version__", "unknown"),
        "exports": exports,
        "message": "esma_data_py is available for future production ingestion hooks.",
    }


def list_register_files(dataset_key: str, rows: int | None = None) -> pd.DataFrame:
    """Fetch a public ESMA Solr register file index as a dataframe."""

    dataset = ESMA_DATASETS[dataset_key]
    params = {
        "q": "*:*",
        "wt": "json",
        "rows": rows or dataset.default_rows,
    }
    if dataset.sort_field:
        params["sort"] = f"{dataset.sort_field} desc"
    if dataset.solr_filter:
        params["fq"] = dataset.solr_filter
    response = requests.get(dataset.register_url, params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()
    docs = payload.get("response", {}).get("docs", [])
    return pd.DataFrame(docs)


def _find_url_in_doc(doc: dict[str, Any]) -> str | None:
    urlish_keys = (
        "download",
        "file",
        "url",
        "link",
        "path",
        "publications",
    )
    for key, value in doc.items():
        key_lower = str(key).lower()
        values = value if isinstance(value, list) else [value]
        for candidate in values:
            text = str(candidate)
            if text.startswith("http") and any(token in key_lower or token in text.lower() for token in urlish_keys):
                return text
    return None


def _safe_filename(url: str, fallback: str) -> str:
    parsed = urlparse(url)
    name = Path(parsed.path).name
    return name or fallback


def download_register_files(dataset_key: str, rows: int = 2, force: bool = False) -> list[Path]:
    """Download a small number of files from an ESMA register index."""

    ensure_directories()
    dataset = ESMA_DATASETS[dataset_key]
    target_dir = RAW_DATA_DIR / dataset.raw_subdir
    index = list_register_files(dataset_key, rows=rows)
    downloaded: list[Path] = []

    for i, doc in enumerate(index.to_dict(orient="records"), start=1):
        url = _find_url_in_doc(doc)
        if not url:
            continue
        filename = _safe_filename(url, f"{dataset_key}_{i}.dat")
        target = target_dir / filename
        if target.exists() and not force:
            downloaded.append(target)
            continue

        head = requests.head(url, allow_redirects=True, timeout=30)
        size_header = head.headers.get("content-length")
        if size_header and int(size_header) > MAX_RAW_DOWNLOAD_BYTES:
            continue

        response = requests.get(url, timeout=60, stream=True)
        response.raise_for_status()
        total = 0
        chunks: list[bytes] = []
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_RAW_DOWNLOAD_BYTES:
                chunks = []
                break
            chunks.append(chunk)
        if not chunks:
            continue
        target.write_bytes(b"".join(chunks))
        downloaded.append(target)

    return downloaded


def cached_raw_files(dataset_key: str) -> list[Path]:
    """Return locally cached raw files for a dataset."""

    dataset = ESMA_DATASETS[dataset_key]
    target_dir = RAW_DATA_DIR / dataset.raw_subdir
    if not target_dir.exists():
        return []
    return sorted(
        [
            path
            for path in target_dir.iterdir()
            if path.suffix.lower() in {".csv", ".xml", ".json", ".zip", ".xlsx", ".xls"}
        ]
    )


def load_cached_esma_data(max_rows_per_file: int = 5000) -> pd.DataFrame:
    """Load cached FIRDS/FITRS files and join them where possible."""

    firds = load_cached_files(cached_raw_files("firds"), "FIRDS", max_rows=max_rows_per_file)
    fitrs = load_cached_files(cached_raw_files("fitrs"), "FITRS", max_rows=max_rows_per_file)
    return join_reference_and_liquidity(firds, fitrs)


def load_or_build_dataset(try_live: bool = False, force_download: bool = False) -> DatasetResult:
    """Load processed data, attempt live refresh if requested, else use sample data."""

    ensure_directories()
    messages: list[str] = []

    if try_live:
        try:
            for dataset_key in ("firds", "fitrs"):
                files = download_register_files(dataset_key, rows=2, force=force_download)
                messages.append(f"{dataset_key.upper()}: cached {len(files)} file(s) from the ESMA register index.")
            frame = load_cached_esma_data()
            if not frame.empty:
                frame.to_csv(PROCESSED_SECURITIES_PATH, index=False)
                messages.append(f"Processed {len(frame):,} rows from cached ESMA files.")
                return DatasetResult(frame=frame, messages=messages, used_sample=False)
            messages.append("ESMA files were reached, but no parseable securities rows were found.")
        except Exception as exc:
            messages.append(f"Live ESMA refresh failed: {exc}")

    if PROCESSED_SECURITIES_PATH.exists():
        try:
            frame = pd.read_csv(PROCESSED_SECURITIES_PATH, parse_dates=["calculation_date"])
            if not frame.empty:
                is_sample_cache = bool(
                    "source_dataset" in frame
                    and frame["source_dataset"].astype(str).str.contains("Sample fallback", case=False, na=False).all()
                )
                messages.append(f"Loaded {len(frame):,} processed rows from {PROCESSED_SECURITIES_PATH}.")
                return DatasetResult(frame=frame, messages=messages, used_sample=is_sample_cache)
        except Exception as exc:
            messages.append(f"Processed cache could not be loaded: {exc}")

    frame = sample_securities_data()
    frame.to_csv(PROCESSED_SECURITIES_PATH, index=False)
    messages.append("Using bundled sample equities data so the dashboard remains available offline.")
    return DatasetResult(frame=frame, messages=messages, used_sample=True)
