from __future__ import annotations

from src.instrument_profile import build_instrument_profile


def test_merges_both_registers_when_available():
    fitrs = [
        {
            "isin": "GRS014003032",
            "instrument_name": "",
            "mic": "XATH",
            "liquidity_status": "Non liquid",
            "avg_daily_turnover": 3200,
            "avg_daily_transactions": 12,
            "cfi_code": "ESVUFR",
            "mifir_identifier": "SHRS",
            "calculation_date": "2026-01-15",
            "reference_period": "YEAR",
            "source_file_name": "esma_registers_fitrs_equities",
        }
    ]
    firds = [
        {
            "isin": "GRS014003032",
            "instrument_full_name": "Alpha Services and Holdings SA",
            "issuer_lei": "TESTLEI1",
            "cfi_code": "ESVUFR",
            "mic": "XATH",
            "admission_date": "2020-01-01",
            "termination_date": "",
            "source_file_name": "esma_registers_firds",
        }
    ]
    profile = build_instrument_profile("grs014003032", fitrs, firds)
    assert profile.isin == "GRS014003032"
    assert profile.instrument_name == "Alpha Services and Holdings SA"
    assert profile.instrument_name_source == "FIRDS"
    assert profile.issuer_lei == "TESTLEI1"
    assert profile.mic == "XATH"
    assert profile.liquidity_status == "Non liquid"
    assert profile.in_fitrs and profile.in_firds
    assert not any(n.level == "conflict" for n in profile.notices)


def test_falls_back_to_fitrs_name_when_firds_missing():
    fitrs = [{"isin": "X1", "instrument_name": "Fallback Name", "mic": "XATH", "avg_daily_turnover": 1}]
    profile = build_instrument_profile("X1", fitrs, [])
    assert profile.instrument_name == "Fallback Name"
    assert profile.instrument_name_source == "FITRS"
    assert profile.in_firds is False
    assert any(n.level == "gap" and "FIRDS" in n.message for n in profile.notices)


def test_flags_gap_when_fitrs_missing():
    firds = [{"isin": "X2", "instrument_full_name": "Only FIRDS SA", "mic": "XPAR"}]
    profile = build_instrument_profile("X2", [], firds)
    assert profile.in_fitrs is False
    assert profile.instrument_name == "Only FIRDS SA"
    assert any(n.level == "gap" and "FITRS" in n.message for n in profile.notices)


def test_flags_cfi_conflict_between_registers():
    fitrs = [{"isin": "X3", "mic": "XATH", "cfi_code": "ESVUFR", "avg_daily_turnover": 1}]
    firds = [{"isin": "X3", "mic": "XATH", "cfi_code": "ESNUFR"}]
    profile = build_instrument_profile("X3", fitrs, firds)
    assert profile.cfi_code == "ESNUFR"
    assert profile.cfi_source == "FIRDS"
    assert any(n.level == "conflict" and "CFI code" in n.message for n in profile.notices)


def test_flags_mic_conflict_between_registers():
    fitrs = [{"isin": "X4", "mic": "XATH", "avg_daily_turnover": 1}]
    firds = [{"isin": "X4", "mic": "XPAR"}]
    profile = build_instrument_profile("X4", fitrs, firds)
    assert profile.mic == "XATH"
    assert any(n.level == "conflict" and "most relevant market" in n.message for n in profile.notices)


def test_picks_highest_turnover_fitrs_venue_as_primary():
    fitrs = [
        {"isin": "X5", "mic": "XATH", "avg_daily_turnover": 100, "liquidity_status": "Liquid"},
        {"isin": "X5", "mic": "XPAR", "avg_daily_turnover": 900, "liquidity_status": "Non liquid"},
    ]
    profile = build_instrument_profile("X5", fitrs, [])
    assert profile.mic == "XPAR"
    assert profile.avg_daily_turnover == 900
    assert profile.fitrs_mics == ["XATH", "XPAR"]
    assert any("2 venues" in n.message for n in profile.notices)


def test_no_data_in_either_register():
    profile = build_instrument_profile("NOWHERE1", [], [])
    assert profile.instrument_name is None
    assert profile.in_fitrs is False and profile.in_firds is False
    gap_messages = [n.message for n in profile.notices if n.level == "gap"]
    assert any("FITRS" in m for m in gap_messages)
    assert any("FIRDS" in m for m in gap_messages)
