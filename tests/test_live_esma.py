from __future__ import annotations

from src.live_esma import build_fitrs_query, live_firds_search, live_fitrs_search


def test_build_fitrs_query_combines_methodology_and_liquidity_filters():
    query = build_fitrs_query("XATH", methodology="YEAR", liquidity_flag="Non liquid")

    assert '(isin:"XATH" OR mrmtl:"XATH"' in query
    assert 'methodology:"YEAR"' in query
    assert 'liquidity_flag:"Non liquid"' in query
    assert ") AND " in query


def test_live_fitrs_display_columns_are_in_requested_order(monkeypatch):
    calls = []

    def fake_fetch(source, *, start, rows, query, sort=None, extra_params=None):
        calls.append(query)
        return {
            "response": {
                "numFound": 1,
                "docs": [
                    {
                        "id": "fitrs-1",
                        "isin": "NL0010273215",
                        "mrmtl": "XAMS",
                        "methodology": "YEAR",
                        "calculation_period_from": "2026-01-01",
                        "calculation_period_to": "2026-12-31",
                        "liquidity_flag": "Liquid",
                        "adt": 12345.67,
                        "mrmtl_adnte": 42,
                        "mifir_identifier": "SHRS",
                        "cfi_code": "ESVUFR",
                    }
                ],
            }
        }

    monkeypatch.setattr("src.live_esma.fetch_solr_page", fake_fetch)

    result = live_fitrs_search("NL0010273215", methodology="YEAR", liquidity_flag="Liquid")

    assert 'methodology:"YEAR"' in calls[0]
    assert 'liquidity_flag:"Liquid"' in calls[0]
    assert list(result.frame.columns) == [
        "ISIN",
        "Methodology",
        "Calculation From Date",
        "Calculation To Date",
        "Liquidity Flag",
        "ADT",
        "MRMTL",
        "ADNTE on MRMTL",
        "Mifir Identifier",
        "CFI Code",
        "More Info",
    ]
    assert result.frame.loc[0, "ADT"] == 12345.67
    assert result.frame.loc[0, "More Info"].endswith("publication/searchRegister?core=esma_registers_fitrs_equities")


def test_live_firds_display_columns_are_in_requested_order(monkeypatch):
    def fake_fetch(source, *, start, rows, query, sort=None, extra_params=None):
        return {
            "response": {
                "numFound": 1,
                "docs": [
                    {
                        "id": "firds-1",
                        "isin": "GRS014003032",
                        "mic": "XATH",
                        "gnr_full_name": "Alpha Services and Holdings SA",
                        "gnr_cfi_code": "ESVUFR",
                        "lei": "TESTLEI1",
                        "mrkt_trdng_start_date": "2026-01-01T00:00:00Z",
                        "mrkt_trdng_trmination_date": "2027-01-01T00:00:00Z",
                        "gnr_short_name": "ALPHA",
                        "mrkt_issr_trdng_rqst_flag": "true",
                        "rca_mic": "XATH",
                    }
                ],
            }
        }

    monkeypatch.setattr("src.live_esma.fetch_solr_page", fake_fetch)

    result = live_firds_search("GRS014003032")

    assert list(result.frame.columns) == [
        "Instrument identification code",
        "Trading venue",
        "Instrument full name",
        "Instrument classification",
        "Issuer or operator of the trading venue identifier",
        "Date of admission to trading or date of first trade",
        "Termination date",
        "Financial instrument short name",
        "Request for admission to trading by issuer",
        "RCA MIC",
        "More Info",
    ]
    assert result.frame.loc[0, "Request for admission to trading by issuer"] == "true"
    assert result.frame.loc[0, "More Info"].endswith("publication/searchRegister?core=esma_registers_firds")
