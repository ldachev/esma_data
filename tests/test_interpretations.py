from __future__ import annotations

from src.interpretations import classify_liquidity, decode_cfi, interpret_liquidity, interpret_reconciliation_notice, interpret_reference_period


def test_classify_liquidity():
    assert classify_liquidity("Liquid") == "liquid"
    assert classify_liquidity("Non liquid") == "non_liquid"
    assert classify_liquidity("") == "unknown"
    assert classify_liquidity("Maybe") == "unknown"


def test_interpret_liquidity_non_liquid():
    text = interpret_liquidity("Non liquid")
    assert "not liquid" in text
    assert "waivers" in text.lower() or "waiver" in text.lower()


def test_interpret_liquidity_liquid():
    text = interpret_liquidity("Liquid")
    assert "liquid" in text.lower()
    assert "continuous" in text.lower()


def test_interpret_liquidity_missing():
    assert "No liquidity flag" in interpret_liquidity(None)
    assert "No liquidity flag" in interpret_liquidity("")


def test_interpret_liquidity_unrecognized_value():
    text = interpret_liquidity("Maybe")
    assert "does not match" in text


def test_interpret_reference_period_with_dates():
    text = interpret_reference_period("YEAR", "2025-01-01", "2025-12-31", "YEAR")
    assert "2025-01-01" in text and "2025-12-31" in text
    assert "YEAR" in text


def test_interpret_reference_period_label_only():
    text = interpret_reference_period("Q4 2025")
    assert "Q4 2025" in text


def test_interpret_reference_period_missing():
    assert "No reference/calculation period" in interpret_reference_period(None)


def test_decode_cfi_known_category_and_group():
    decoding = decode_cfi("ESVUFR")
    assert decoding.category_code == "E"
    assert decoding.category_label == "Equities"
    assert decoding.group_code == "S"
    assert decoding.group_label == "Common / Ordinary Shares"
    assert "Equities" in decoding.description


def test_decode_cfi_known_category_unknown_group():
    decoding = decode_cfi("EZVUFR")
    assert decoding.category_label == "Equities"
    assert decoding.group_label is None
    assert "not in the curated group mapping" in decoding.description


def test_decode_cfi_unrecognized_category():
    decoding = decode_cfi("ZZVUFR")
    assert decoding.category_label is None
    assert "unrecognized category" in decoding.description


def test_decode_cfi_empty():
    decoding = decode_cfi(None)
    assert decoding.code == ""
    assert "No CFI code" in decoding.description


def test_interpret_reconciliation_notice_prefixes():
    assert interpret_reconciliation_notice("gap", "msg").startswith("Data gap:")
    assert interpret_reconciliation_notice("conflict", "msg").startswith("Register conflict:")
