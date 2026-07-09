"""Portfolio watchlist: ISIN validation, bulk parsing, and import/export.

Pure logic with no Streamlit dependency. ``InMemoryPortfolioStore`` wraps any
mutable mapping (the app uses ``st.session_state``) behind a small
load/save/add/remove interface, so a real per-user database backend can
implement the same interface later without touching the UI.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from typing import Protocol

from .utils import normalize_upper


ISIN_FORMAT_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def is_valid_isin_format(isin: str) -> bool:
    return bool(ISIN_FORMAT_RE.match(normalize_upper(isin)))


def _isin_letter_to_digits(char: str) -> str:
    if char.isdigit():
        return char
    return str(ord(char) - ord("A") + 10)


def isin_check_digit_valid(isin: str) -> bool:
    """Validate the ISO 6166 Luhn-style check digit (12th character)."""

    key = normalize_upper(isin)
    if not is_valid_isin_format(key):
        return False
    body, check = key[:11], key[11]
    digit_string = "".join(_isin_letter_to_digits(c) for c in body)
    n = len(digit_string)
    total = 0
    for i, ch in enumerate(digit_string):
        d = int(ch)
        if i % 2 != n % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    computed = (10 - (total % 10)) % 10
    return str(computed) == check


def is_valid_isin(isin: str) -> bool:
    return is_valid_isin_format(isin) and isin_check_digit_valid(isin)


def dedupe_isins(isins: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for isin in isins:
        key = normalize_upper(isin)
        if key and key not in seen:
            seen.add(key)
            result.append(key)
    return result


def parse_bulk_isins(text: str) -> tuple[list[str], list[str]]:
    """Split free-form pasted text into (valid, invalid) normalized ISIN candidates."""

    tokens = re.split(r"[\s,;]+", (text or "").strip())
    valid: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if not token:
            continue
        key = normalize_upper(token)
        if key in seen:
            continue
        seen.add(key)
        if is_valid_isin(key):
            valid.append(key)
        else:
            invalid.append(key)
    return valid, invalid


def portfolio_to_json(isins: list[str]) -> str:
    return json.dumps({"isins": dedupe_isins(isins)}, indent=2)


def portfolio_from_json(data: str | bytes) -> list[str]:
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    payload = json.loads(data)
    raw = payload if isinstance(payload, list) else payload.get("isins", [])
    return dedupe_isins([str(v) for v in raw])


def portfolio_to_csv(isins: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["isin"])
    for isin in dedupe_isins(isins):
        writer.writerow([isin])
    return buffer.getvalue()


def portfolio_from_csv(data: str | bytes) -> list[str]:
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    rows = list(csv.reader(io.StringIO(data)))
    if not rows:
        return []
    header = [c.strip().lower() for c in rows[0]]
    col_idx, start = 0, 0
    if "isin" in header:
        col_idx, start = header.index("isin"), 1
    isins = [row[col_idx].strip() for row in rows[start:] if len(row) > col_idx and row[col_idx].strip()]
    return dedupe_isins(isins)


class PortfolioStore(Protocol):
    def load(self) -> list[str]: ...

    def save(self, isins: list[str]) -> None: ...


@dataclass
class InMemoryPortfolioStore:
    state: dict
    key: str = "portfolio_isins"

    def load(self) -> list[str]:
        return list(self.state.get(self.key, []))

    def save(self, isins: list[str]) -> None:
        self.state[self.key] = dedupe_isins(isins)

    def add(self, isins: list[str]) -> list[str]:
        merged = dedupe_isins(self.load() + list(isins))
        self.save(merged)
        return merged

    def remove(self, isin: str) -> list[str]:
        key = normalize_upper(isin)
        remaining = [i for i in self.load() if i != key]
        self.save(remaining)
        return remaining
