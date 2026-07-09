"""Plain-language MiFID II interpretations of raw FITRS/FIRDS field values.

Pure text-mapping functions, deliberately factual and derived only from the
field values passed in -- no speculation about instruments not covered by the
data. Kept separate from UI code so the mapping is easy to review and extend.
"""

from __future__ import annotations

from dataclasses import dataclass

from .utils import normalize_text, normalize_upper


def interpret_liquidity(liquidity_status: str | None) -> str:
    status = normalize_upper(liquidity_status)
    if not status:
        return "No liquidity flag is available for this instrument."
    if status.startswith("NON") or status in {"N", "FALSE", "0"}:
        return (
            "Flagged as **not liquid** under the FITRS calculation. Under MiFIR equity transparency rules, "
            "trading venues may apply pre-trade transparency waivers and defer post-trade publication for "
            "this instrument, since there is no liquid market obligation to publish quotes and trades in "
            "real time."
        )
    if status.startswith("LIQUID") or status in {"Y", "TRUE", "1"}:
        return (
            "Flagged as **liquid** under the FITRS calculation. Under MiFIR equity transparency rules, "
            "trading venues and investment firms trading this instrument must generally provide continuous "
            "pre-trade quotes and publish trades close to real time, with narrower scope for waivers/deferrals."
        )
    return f"Liquidity flag value is '{liquidity_status}', which does not match a recognized Liquid/Non-liquid value."


def interpret_reference_period(
    reference_period: str | None,
    calculation_period_from: str | None = None,
    calculation_period_to: str | None = None,
    methodology: str | None = None,
) -> str:
    period_from = normalize_text(calculation_period_from)
    period_to = normalize_text(calculation_period_to)
    method = normalize_text(methodology)
    if period_from or period_to:
        span = f"from {period_from or 'an unspecified start date'} to {period_to or 'an unspecified end date'}"
        method_note = f" using the '{method}' methodology" if method else ""
        return (
            f"This FITRS calculation covers trading activity {span}{method_note}. Liquidity and average "
            "daily turnover/transaction figures are computed by ESMA over this reference window under the "
            "MiFIR RTS equity transparency calculation methodology, and apply until the next periodic "
            "recalculation is published."
        )
    period = normalize_text(reference_period)
    if period:
        return (
            f"Reference period reported as '{period}'. This identifies which ESMA calculation cycle "
            "(e.g. annual, quarterly) the liquidity/turnover figures were computed over."
        )
    return "No reference/calculation period is available for this instrument."


@dataclass(frozen=True)
class CfiDecoding:
    code: str
    category_code: str | None
    category_label: str | None
    group_code: str | None
    group_label: str | None
    description: str


_CFI_CATEGORIES: dict[str, str] = {
    "E": "Equities",
    "D": "Debt Instruments",
    "R": "Entitlements (Rights)",
    "O": "Options",
    "F": "Futures",
    "S": "Swaps",
    "H": "Non-listed and complex listed options",
    "I": "Spot",
    "J": "Forwards",
    "K": "Strategies",
    "L": "Financing",
    "T": "Referential Instruments",
    "C": "Collective Investment Vehicles",
    "M": "Others / Miscellaneous",
}

_CFI_GROUPS: dict[str, dict[str, str]] = {
    "E": {
        "S": "Common / Ordinary Shares",
        "P": "Preferred / Preference Shares",
        "C": "Common / Ordinary Convertible Shares",
        "F": "Preferred Convertible Shares",
        "L": "Limited Partnership Units",
        "D": "Depositary Receipts on Equities",
        "Y": "Structured Instruments (Participation)",
        "M": "Miscellaneous Equities",
    },
    "C": {
        "I": "Standard (Vanilla) Investment Funds/Units - Income",
        "B": "Hedge Funds",
        "M": "Mixed Funds",
        "E": "Equity/REIT-Backed Funds",
    },
}


def decode_cfi(cfi_code: str | None) -> CfiDecoding:
    code = normalize_upper(cfi_code)
    if not code:
        return CfiDecoding(code="", category_code=None, category_label=None, group_code=None, group_label=None,
                            description="No CFI code is available for this instrument.")
    category_code = code[0]
    group_code = code[1] if len(code) > 1 else None
    category_label = _CFI_CATEGORIES.get(category_code)
    group_label = _CFI_GROUPS.get(category_code, {}).get(group_code) if group_code else None

    if not category_label:
        return CfiDecoding(
            code=code,
            category_code=category_code,
            category_label=None,
            group_code=group_code,
            group_label=None,
            description=f"CFI code '{code}' starts with an unrecognized category letter ('{category_code}').",
        )
    if group_label:
        description = f"{code}: {category_label} - {group_label} (ISO 10962 CFI category/group)."
    else:
        description = (
            f"{code}: {category_label} (ISO 10962 CFI category). The group letter '{group_code}' is not "
            "in the curated group mapping for this category, so only the category is decoded."
        )
    return CfiDecoding(
        code=code,
        category_code=category_code,
        category_label=category_label,
        group_code=group_code,
        group_label=group_label,
        description=description,
    )


def interpret_reconciliation_notice(level: str, message: str) -> str:
    prefix = "Data gap" if level == "gap" else "Register conflict"
    return f"{prefix}: {message}"
