"""Pure logic that reconciles FITRS and FIRDS records for a single ISIN.

Takes lists of plain dicts (as produced by ``schema_mapper.map_fitrs_records`` /
``map_firds_records``, or the equivalent local-cache query rows from
``search_index.isin_fitrs`` / ``isin_firds``, which share the same field
vocabulary for the columns used here) and returns a single structured
``InstrumentProfile``. Contains no Streamlit or I/O so it is unit-testable in
isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .utils import normalize_text, normalize_upper, to_float


@dataclass(frozen=True)
class ReconciliationNotice:
    level: str  # "gap" (a register has no data) or "conflict" (registers disagree)
    message: str


@dataclass(frozen=True)
class InstrumentProfile:
    isin: str
    instrument_name: str | None
    instrument_name_source: str | None
    issuer_lei: str | None
    cfi_code: str | None
    cfi_source: str | None
    mic: str | None
    mic_source: str | None
    fitrs_mics: list[str]
    firds_mics: list[str]
    liquidity_status: str | None
    avg_daily_turnover: float | None
    avg_daily_transactions: float | None
    calculation_date: str | None
    reference_period: str | None
    mifir_identifier: str | None
    admission_date: str | None
    termination_date: str | None
    fitrs_source_file: str | None
    firds_source_file: str | None
    in_fitrs: bool
    in_firds: bool
    fitrs_record_count: int
    firds_record_count: int
    notices: list[ReconciliationNotice] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return self.in_fitrs and self.in_firds

    def to_dict(self) -> dict[str, Any]:
        return {
            "ISIN": self.isin,
            "Instrument name": self.instrument_name,
            "Instrument name source": self.instrument_name_source,
            "Issuer LEI": self.issuer_lei,
            "CFI code": self.cfi_code,
            "CFI source": self.cfi_source,
            "Home/most relevant MIC": self.mic,
            "MIC source": self.mic_source,
            "Liquidity flag": self.liquidity_status,
            "Average daily turnover": self.avg_daily_turnover,
            "Average daily number of transactions": self.avg_daily_transactions,
            "Calculation date": self.calculation_date,
            "Reference period": self.reference_period,
            "MiFIR identifier": self.mifir_identifier,
            "Admission date": self.admission_date,
            "Termination date": self.termination_date,
            "In FITRS": self.in_fitrs,
            "In FIRDS": self.in_firds,
        }


def _primary_fitrs(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not records:
        return None
    return max(records, key=lambda r: to_float(r.get("avg_daily_turnover")) or -1.0)


def _primary_firds(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not records:
        return None
    with_admission = [r for r in records if normalize_text(r.get("admission_date"))]
    pool = with_admission or records
    return max(pool, key=lambda r: normalize_text(r.get("admission_date")))


def build_instrument_profile(
    isin: str,
    fitrs_records: list[dict[str, Any]] | None,
    firds_records: list[dict[str, Any]] | None,
) -> InstrumentProfile:
    isin_key = normalize_upper(isin)
    fitrs_records = fitrs_records or []
    firds_records = firds_records or []

    primary_fitrs = _primary_fitrs(fitrs_records)
    primary_firds = _primary_firds(firds_records)

    fitrs_mics = sorted({normalize_upper(r.get("mic")) for r in fitrs_records if normalize_text(r.get("mic"))})
    firds_mics = sorted({normalize_upper(r.get("mic")) for r in firds_records if normalize_text(r.get("mic"))})

    notices: list[ReconciliationNotice] = []

    firds_name = normalize_text(primary_firds.get("instrument_full_name")) if primary_firds else ""
    fitrs_name = normalize_text(primary_fitrs.get("instrument_name")) if primary_fitrs else ""
    if firds_name:
        instrument_name, instrument_name_source = firds_name, "FIRDS"
    elif fitrs_name:
        instrument_name, instrument_name_source = fitrs_name, "FITRS"
    else:
        instrument_name, instrument_name_source = None, None

    issuer_lei = normalize_text(primary_firds.get("issuer_lei")) if primary_firds else ""
    issuer_lei = issuer_lei or None

    firds_cfi = normalize_upper(primary_firds.get("cfi_code")) if primary_firds else ""
    fitrs_cfi = normalize_upper(primary_fitrs.get("cfi_code")) if primary_fitrs else ""
    if firds_cfi:
        cfi_code, cfi_source = firds_cfi, "FIRDS"
    elif fitrs_cfi:
        cfi_code, cfi_source = fitrs_cfi, "FITRS"
    else:
        cfi_code, cfi_source = None, None
    if firds_cfi and fitrs_cfi and firds_cfi != fitrs_cfi:
        notices.append(
            ReconciliationNotice(
                "conflict",
                f"FITRS CFI code ({fitrs_cfi}) differs from FIRDS CFI code ({firds_cfi}).",
            )
        )

    fitrs_mic = normalize_upper(primary_fitrs.get("mic")) if primary_fitrs else ""
    firds_mic = normalize_upper(primary_firds.get("mic")) if primary_firds else ""
    if fitrs_mic:
        mic, mic_source = fitrs_mic, "FITRS (most relevant market)"
    elif firds_mic:
        mic, mic_source = firds_mic, "FIRDS"
    else:
        mic, mic_source = None, None
    if fitrs_mic and firds_mics and fitrs_mic not in firds_mics:
        notices.append(
            ReconciliationNotice(
                "conflict",
                f"FITRS most relevant market ({fitrs_mic}) was not found among the FIRDS trading venues "
                f"loaded for this ISIN ({', '.join(firds_mics)}).",
            )
        )

    if len(fitrs_mics) > 1:
        notices.append(
            ReconciliationNotice(
                "gap",
                f"This ISIN has FITRS calculation results on {len(fitrs_mics)} venues: {', '.join(fitrs_mics)}. "
                "The card shows the venue with the highest average daily turnover.",
            )
        )

    if not fitrs_records:
        notices.append(
            ReconciliationNotice(
                "gap",
                "No FITRS equity transparency/liquidity calculation was found for this ISIN.",
            )
        )
    if not firds_records:
        notices.append(
            ReconciliationNotice(
                "gap",
                "No FIRDS reference data was found for this ISIN.",
            )
        )

    return InstrumentProfile(
        isin=isin_key,
        instrument_name=instrument_name,
        instrument_name_source=instrument_name_source,
        issuer_lei=issuer_lei,
        cfi_code=cfi_code,
        cfi_source=cfi_source,
        mic=mic,
        mic_source=mic_source,
        fitrs_mics=fitrs_mics,
        firds_mics=firds_mics,
        liquidity_status=normalize_text(primary_fitrs.get("liquidity_status")) if primary_fitrs else None,
        avg_daily_turnover=to_float(primary_fitrs.get("avg_daily_turnover")) if primary_fitrs else None,
        avg_daily_transactions=to_float(primary_fitrs.get("avg_daily_transactions")) if primary_fitrs else None,
        calculation_date=normalize_text(primary_fitrs.get("calculation_date")) or None if primary_fitrs else None,
        reference_period=normalize_text(primary_fitrs.get("reference_period")) or None if primary_fitrs else None,
        mifir_identifier=normalize_text(primary_fitrs.get("mifir_identifier")) or None if primary_fitrs else None,
        admission_date=normalize_text(primary_firds.get("admission_date")) or None if primary_firds else None,
        termination_date=normalize_text(primary_firds.get("termination_date")) or None if primary_firds else None,
        fitrs_source_file=normalize_text(primary_fitrs.get("source_file_name")) or None if primary_fitrs else None,
        firds_source_file=normalize_text(primary_firds.get("source_file_name")) or None if primary_firds else None,
        in_fitrs=bool(fitrs_records),
        in_firds=bool(firds_records),
        fitrs_record_count=len(fitrs_records),
        firds_record_count=len(firds_records),
        notices=notices,
    )
