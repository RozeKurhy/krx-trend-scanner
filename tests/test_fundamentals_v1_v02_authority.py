from __future__ import annotations

from types import SimpleNamespace

from trend_scanner.fundamentals.opendart_contract import FilingRecord, FilingSelectionStatus, select_pit_filing
from trend_scanner.fundamentals.period_models import PeriodizationFact
from trend_scanner.fundamentals.periodization import (
    collapse_canonical_duplicate_periodization_facts,
)
from trend_scanner.reporting.fundamentals_report import _operating_income_yoy_status


def _filing(no: str, dt: str, *, correction: bool = False, chain: str = "2025:11011:annual") -> FilingRecord:
    return FilingRecord(
        ticker="000001", corp_code="001", bsns_year="2025", reprt_code="11011",
        report_nm=("[기재정정]" if correction else "") + "사업보고서 (2025.12)",
        rcept_no=no, rcept_dt=dt, filing_chain_key=chain, correction_flag=correction,
    )


def test_v02_same_day_original_and_correction_correction_wins():
    result = select_pit_filing([
        _filing("20260318000001", "2026-03-18"),
        _filing("20260318000002", "2026-03-18", correction=True),
    ], "2026-03-18", "2025", "11011")
    assert result.status == FilingSelectionStatus.READY.value
    assert result.selected is not None
    assert result.selected.rcept_no == "20260318000002"
    assert result.reason == "LATEST_EFFECTIVE_SAME_DAY_CORRECTION"


def test_v02_future_correction_is_not_selected():
    result = select_pit_filing([
        _filing("20260318000001", "2026-03-18"),
        _filing("20260602000001", "2026-06-02", correction=True),
    ], "2026-03-18", "2025", "11011")
    assert result.selected is not None
    assert result.selected.rcept_no == "20260318000001"
    assert result.future[0].correction_flag is True


def test_v02_independent_filing_chains_remain_ambiguous():
    result = select_pit_filing([
        _filing("20260318000001", "2026-03-18", chain="chain-a"),
        _filing("20260319000001", "2026-03-19", chain="chain-b"),
    ], "2026-06-01", "2025", "11011")
    assert result.status == FilingSelectionStatus.AMBIGUOUS.value
    assert result.selected is None
    assert result.reason == "MULTIPLE_FILING_CHAINS"


def _fact(value: int, *, account: str, raw: str, decimals: str) -> PeriodizationFact:
    return PeriodizationFact(
        ticker="000001", corp_code="001", company_family="NON_FINANCIAL",
        fiscal_year="2025", fiscal_year_start="2025-01-01", metric="revenue",
        value=value, currency="KRW", reprt_code="11011", report_type="ANNUAL",
        rcept_no="20260318000001", rcept_dt="2026-03-18", period_start="2025-01-01",
        period_end="2025-12-31", fs_div_used="CFS", source_sha256="sha",
        pit_available_from="2026-03-18", context_scope_fingerprint="same-context",
        account_id=account, raw_value=raw, decimals=decimals, unit_ref="KRW",
        context_ref="ctx-1",
    )


def test_v02_precision_equivalent_aliases_collapse_with_overlap():
    stats: dict[str, int] = {}
    result = collapse_canonical_duplicate_periodization_facts([
        _fact(1000, account="dart_OperatingIncomeLoss", raw="1000", decimals="-3"),
        _fact(1001, account="ifrs-full_ProfitLossFromOperatingActivities", raw="1001", decimals="-1"),
    ], stats=stats)
    assert len(result) == 1
    assert stats["precision_equivalent_group_count"] == 1
    assert stats["precision_equivalent_fact_removed_count"] == 1


def test_v02_true_value_conflict_is_preserved():
    stats: dict[str, int] = {}
    result = collapse_canonical_duplicate_periodization_facts([
        _fact(1000, account="dart_OperatingIncomeLoss", raw="1000", decimals="-3"),
        _fact(3000, account="ifrs-full_ProfitLossFromOperatingActivities", raw="3000", decimals="-3"),
    ], stats=stats)
    assert len(result) == 2
    assert stats["true_value_conflict_group_count"] == 1


def _yoy_index(current: int, prior: int):
    return {
        ("operating_income", "2025", "Q1"): (SimpleNamespace(resolution_status="READY", value=current),),
        ("operating_income", "2024", "Q1"): (SimpleNamespace(resolution_status="READY", value=prior),),
    }


def test_v02_positive_to_positive_uses_percent():
    assert _operating_income_yoy_status(_yoy_index(110, 100), "2025", "Q1", 10.0) == "PERCENT"


def test_v02_positive_to_negative_is_loss_transition():
    assert _operating_income_yoy_status(_yoy_index(-10, 100), "2025", "Q1", None) == "TURNED_TO_LOSS"


def test_v02_negative_to_positive_is_profit_transition():
    assert _operating_income_yoy_status(_yoy_index(10, -100), "2025", "Q1", None) == "TURNED_TO_PROFIT"


def test_v02_negative_to_negative_is_continued_loss():
    assert _operating_income_yoy_status(_yoy_index(-110, -100), "2025", "Q1", None) == "LOSS_CONTINUED"


def test_v02_zero_base_is_deterministic_without_infinity():
    assert _operating_income_yoy_status(_yoy_index(10, 0), "2025", "Q1", None) == "ZERO_BASE"
