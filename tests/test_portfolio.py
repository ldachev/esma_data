from __future__ import annotations

import pytest

from src.portfolio import (
    InMemoryPortfolioStore,
    dedupe_isins,
    is_valid_isin,
    is_valid_isin_format,
    parse_bulk_isins,
    portfolio_from_csv,
    portfolio_from_json,
    portfolio_to_csv,
    portfolio_to_json,
)


@pytest.mark.parametrize("isin", ["US0378331005", "GRS014003032", "NL0010273215"])
def test_valid_isins_pass_checksum(isin):
    assert is_valid_isin(isin)


@pytest.mark.parametrize("isin", ["US0378331004", "GRS014003031", "NOTANISIN00"])
def test_invalid_checksum_or_format_rejected(isin):
    assert not is_valid_isin(isin)


def test_format_check_rejects_wrong_length_and_lowercase_ok_after_normalize():
    assert not is_valid_isin_format("US037833100")  # too short
    assert is_valid_isin_format("us0378331005")  # normalized upper


def test_dedupe_isins_preserves_order_and_normalizes_case():
    assert dedupe_isins(["us0378331005", "US0378331005", "GRS014003032"]) == ["US0378331005", "GRS014003032"]


def test_parse_bulk_isins_splits_valid_and_invalid():
    text = "US0378331005, GRS014003032\nNOTVALID123\n  NL0010273215  "
    valid, invalid = parse_bulk_isins(text)
    assert valid == ["US0378331005", "GRS014003032", "NL0010273215"]
    assert invalid == ["NOTVALID123"]


def test_parse_bulk_isins_dedupes_within_input():
    valid, invalid = parse_bulk_isins("US0378331005 US0378331005")
    assert valid == ["US0378331005"]
    assert invalid == []


def test_json_roundtrip():
    isins = ["US0378331005", "GRS014003032"]
    payload = portfolio_to_json(isins)
    assert portfolio_from_json(payload) == isins


def test_json_import_accepts_bare_list():
    assert portfolio_from_json('["US0378331005", "us0378331005"]') == ["US0378331005"]


def test_csv_roundtrip():
    isins = ["US0378331005", "GRS014003032"]
    payload = portfolio_to_csv(isins)
    assert "isin" in payload.splitlines()[0]
    assert portfolio_from_csv(payload) == isins


def test_csv_import_without_header():
    assert portfolio_from_csv("US0378331005\nGRS014003032\n") == ["US0378331005", "GRS014003032"]


def test_in_memory_store_add_and_remove():
    state: dict = {}
    store = InMemoryPortfolioStore(state)
    assert store.load() == []
    store.add(["us0378331005", "GRS014003032"])
    assert store.load() == ["US0378331005", "GRS014003032"]
    store.add(["US0378331005"])  # no duplicate
    assert store.load() == ["US0378331005", "GRS014003032"]
    store.remove("grs014003032")
    assert store.load() == ["US0378331005"]
