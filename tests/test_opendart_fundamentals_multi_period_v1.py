from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from trend_scanner.fundamentals.multi_period import (
    MultiPeriodFundamentalsProvider,
    build_multi_period_result,
)
from trend_scanner.fundamentals.period_models import PeriodizationResult, PeriodizedFinancialObservation


METRICS = ("revenue", "operating_income", "net_income", "operating_cash_flow", "equity", "liabilities")


def _obs(year: int, period: str, metric: str, *, status: str = "READY", family: str = "NON_FINANCIAL",
         receipt: str | None = None, basis: str | None = "CFS",
         currency: str | None = "KRW") -> PeriodizedFinancialObservation:
    code = {"Q1": "11013", "Q2": "11012", "Q3": "11014", "Q4": "11011", "FY": "11011"}[period]
    receipt = receipt or f"{year}-12-31"
    return PeriodizedFinancialObservation(
        ticker="TEST", corp_code="00000001", company_family=family,
        fiscal_year=str(year), fiscal_year_start=f"{year}-01-01", fiscal_period=period,
        period_semantics="FULL_YEAR" if period == "FY" else "STANDALONE_QUARTER",
        period_start=f"{year}-01-01", period_end=f"{year}-12-31", metric=metric,
        value=100, currency=currency, method="DIRECT_ONLY", anchor_report_type="ANNUAL",
        anchor_reprt_code=code, anchor_rcept_no=f"{year}-{period}-{metric}",
        anchor_rcept_dt=receipt, source_rcept_nos=(f"{year}-{period}-{metric}",),
        source_rcept_dts=(receipt,), source_sha256s=(f"sha-{year}-{period}",),
        resolution_status=status, pit_available_from=receipt, fs_div_used=basis,
    )


def _canonical(*, missing: tuple[int, int] | None = None, ambiguous: tuple[int, int] | None = None,
               include_future: bool = False):
    rows = []
    for year in range(2021, 2025):
        for quarter in range(1, 5):
            if missing == (year, quarter):
                continue
            status = "PERIOD_AMBIGUOUS" if ambiguous == (year, quarter) else "READY"
            for metric in METRICS:
                rows.append(_obs(year, f"Q{quarter}", metric, status=status))
    for year in range(2019, 2025):
        for metric in METRICS:
            rows.append(_obs(year, "FY", metric))
    if include_future:
        rows.append(_obs(2025, "Q1", "revenue", receipt="2025-05-15"))
    return rows


def test_16q_and_6fy_windows_are_explicit_and_display_windows_are_extractable():
    result = build_multi_period_result(
        ticker="TEST", requested_as_of="2024-12-31", observations=_canonical()
    )
    assert len(result.quarter_slots) == 16
    assert len(result.annual_slots) == 6
    assert result.has_16q_comparison_window is True
    assert result.has_12q_display_window is True
    assert result.has_6fy_comparison_window is True
    assert result.has_5y_display_window is True
    assert result.display_quarters[0].identity == "2022Q1"
    assert result.display_annuals[0].identity == "2020"
    assert result.quarter_coverage["quarter_requested_count"] == 16
    assert result.annual_coverage["annual_requested_count"] == 6


def test_missing_quarter_is_preserved_without_silent_compression():
    result = build_multi_period_result(
        ticker="TEST", requested_as_of="2024-12-31", observations=_canonical(missing=(2023, 2))
    )
    slot = next(item for item in result.quarter_slots if item.identity == "2023Q2")
    assert slot.status == "DATA_UNAVAILABLE"
    assert result.has_16q_comparison_window is False
    assert len(result.quarter_slots) == 16
    assert [item.identity for item in result.quarter_slots].count("2023Q2") == 1


def test_required_quarter_metric_missing_blocks_slot_and_windows():
    rows = [
        item for item in _canonical()
        if not (item.fiscal_year == "2023" and item.fiscal_period == "Q2"
                and item.metric == "operating_cash_flow")
    ]
    result = build_multi_period_result(
        ticker="TEST", requested_as_of="2024-12-31", observations=rows
    )
    slot = next(item for item in result.quarter_slots if item.identity == "2023Q2")
    assert slot.status == "DATA_UNAVAILABLE"
    assert slot.reason == "REQUIRED_METRIC_MISSING"
    assert slot.missing_metrics == ("operating_cash_flow",)
    assert result.has_16q_comparison_window is False
    assert result.has_12q_display_window is False
    assert any(item.get("missing_metrics") == ["operating_cash_flow"] for item in result.diagnostics)


def test_required_annual_metric_missing_blocks_year_but_optional_ocf_does_not():
    rows = [
        item for item in _canonical()
        if not (item.fiscal_year == "2022" and item.fiscal_period == "FY"
                and item.metric == "liabilities")
    ]
    result = build_multi_period_result(
        ticker="TEST", requested_as_of="2024-12-31", observations=rows
    )
    year = next(item for item in result.annual_slots if item.identity == "2022")
    assert year.status == "DATA_UNAVAILABLE"
    assert year.missing_metrics == ("liabilities",)
    assert result.has_6fy_comparison_window is False
    assert result.has_5y_display_window is False

    optional_rows = [
        item for item in _canonical()
        if not (item.fiscal_period == "FY" and item.metric == "operating_cash_flow")
    ]
    optional_result = build_multi_period_result(
        ticker="TEST", requested_as_of="2024-12-31", observations=optional_rows
    )
    assert all(item.status == "READY" for item in optional_result.annual_slots)
    assert optional_result.has_6fy_comparison_window is True


def test_ambiguous_and_future_observations_fail_closed():
    result = build_multi_period_result(
        ticker="TEST", requested_as_of="2024-12-31",
        observations=_canonical(ambiguous=(2023, 2), include_future=True),
    )
    slot = next(item for item in result.quarter_slots if item.identity == "2023Q2")
    assert slot.status == "PERIOD_AMBIGUOUS"
    assert result.has_16q_comparison_window is False
    assert any(item["type"] == "FUTURE_OR_UNAVAILABLE_SOURCE_EXCLUDED" for item in result.diagnostics)


def test_latest_selection_does_not_merge_different_period_semantics():
    rows = _canonical()
    standalone = next(
        item for item in rows
        if item.fiscal_year == "2023" and item.fiscal_period == "Q2" and item.metric == "revenue"
    )
    rows.append(replace(
        standalone,
        value=999,
        anchor_rcept_no="2024-Q2-revenue-cumulative",
        anchor_rcept_dt="2024-06-30",
        source_rcept_nos=("2024-Q2-revenue-cumulative",),
        source_rcept_dts=("2024-06-30",),
        period_semantics="CUMULATIVE_YTD",
        period_start="2023-01-01",
        pit_available_from="2024-06-30",
    ))
    result = build_multi_period_result(
        ticker="TEST", requested_as_of="2024-12-31", observations=rows
    )
    slot = next(item for item in result.quarter_slots if item.identity == "2023Q2")
    assert slot.status == "PERIOD_AMBIGUOUS"
    assert "AUTHORITY_SIGNATURE_CONFLICT:revenue" in (slot.reason or "")
    values = [
        item.value for item in result.quarters
        if item.fiscal_year == "2023" and item.fiscal_period == "Q2" and item.metric == "revenue"
    ]
    assert sorted(values) == [100, 999]


def test_basis_and_currency_mismatch_disable_comparison_window():
    rows = _canonical()
    rows[0] = _obs(2021, "Q1", "revenue", basis="OFS")
    rows[1] = _obs(2021, "Q1", "operating_income", currency="USD")
    result = build_multi_period_result(
        ticker="TEST", requested_as_of="2024-12-31", observations=rows
    )
    assert result.has_16q_comparison_window is False
    assert result.quarter_coverage["basis_consistent"] is False
    assert result.quarter_coverage["currency_consistent"] is False
    assert any(item["type"] == "BASIS_MISMATCH_WINDOW" for item in result.diagnostics)
    assert any(item["type"] == "CURRENCY_MISMATCH_WINDOW" for item in result.diagnostics)


def test_financial_family_keeps_general_series_not_applicable():
    result = build_multi_period_result(
        ticker="086790", requested_as_of="2024-12-31",
        observations=[_obs(2024, "Q4", "net_income", family="FINANCIAL")],
        company_family="FINANCIAL",
    )
    assert result.quarters == ()
    assert result.annuals == ()
    assert result.quarter_coverage["not_applicable"] is True
    assert all(item.status == "NOT_APPLICABLE" for item in result.quarter_slots)


def test_provider_builds_each_requested_year_once_and_reuses_periodization_authority():
    calls: list[str] = []

    class StubPeriodizationProvider:
        def build(self, ticker, fiscal_year, requested_as_of, **kwargs):
            calls.append(str(fiscal_year))
            rows = tuple(_obs(int(fiscal_year), "Q1", metric) for metric in METRICS)
            return SimpleNamespace(
                company_family="NON_FINANCIAL", facts=rows,
                result=PeriodizationResult(rows), skipped_anchors=(), fiscal_year=str(fiscal_year),
            )

    provider = MultiPeriodFundamentalsProvider(StubPeriodizationProvider())
    result = provider.build("TEST", "2024-12-31", fiscal_years=["2024", "2024", "2023"])
    assert calls == ["2024", "2023"]
    assert result.corp_code == "00000001"
    assert result.requested_as_of == "2024-12-31"


def test_provider_anchors_annual_window_to_latest_available_fy_and_builds_only_missing_history():
    calls: list[str] = []

    class AnnualStub:
        def build(self, ticker, fiscal_year, requested_as_of, **kwargs):
            calls.append(str(fiscal_year))
            rows = ()
            if str(fiscal_year) in {"2020", "2021", "2022", "2023", "2024", "2025"}:
                rows = tuple(_obs(int(fiscal_year), "FY", metric) for metric in METRICS)
            return SimpleNamespace(
                company_family="NON_FINANCIAL", facts=rows,
                result=PeriodizationResult(rows), skipped_anchors=(), fiscal_year=str(fiscal_year),
            )

    provider = MultiPeriodFundamentalsProvider(AnnualStub())
    result = provider.build(
        "TEST", "2026-09-07", fiscal_years=("2021", "2022", "2023", "2024", "2025", "2026")
    )
    assert calls == ["2021", "2022", "2023", "2024", "2025", "2026", "2020"]
    assert result.latest_fy == "2025"
    assert result.annual_slots[0].identity == "2020"
    assert result.has_6fy_comparison_window is True
    assert result.has_5y_display_window is True


def test_provider_does_not_add_older_history_when_current_fy_is_available():
    calls: list[str] = []

    class CurrentStub:
        def build(self, ticker, fiscal_year, requested_as_of, **kwargs):
            calls.append(str(fiscal_year))
            rows = tuple(_obs(int(fiscal_year), "FY", metric) for metric in METRICS) \
                if str(fiscal_year) == "2026" else ()
            return SimpleNamespace(
                company_family="NON_FINANCIAL", facts=rows,
                result=PeriodizationResult(rows), skipped_anchors=(), fiscal_year=str(fiscal_year),
            )

    provider = MultiPeriodFundamentalsProvider(CurrentStub())
    result = provider.build(
        "TEST", "2026-12-31", fiscal_years=("2021", "2022", "2023", "2024", "2025", "2026")
    )
    assert calls == ["2021", "2022", "2023", "2024", "2025", "2026"]
    assert result.latest_fy == "2026"


def _annual_rows(year: int, *, missing: str | None = None, status: str = "READY"):
    return tuple(
        _obs(year, "FY", metric, status=status)
        for metric in METRICS
        if metric != missing
    )


def test_provider_anchors_to_latest_usable_fy_when_latest_fy_is_incomplete():
    calls: list[str] = []

    class IncompleteLatestStub:
        def build(self, ticker, fiscal_year, requested_as_of, **kwargs):
            calls.append(str(fiscal_year))
            year = int(fiscal_year)
            if year == 2026:
                rows = _annual_rows(year, missing="liabilities")
            elif year == 2020 or 2021 <= year <= 2025:
                rows = _annual_rows(year)
            else:
                rows = ()
            return SimpleNamespace(
                company_family="NON_FINANCIAL", facts=rows,
                result=PeriodizationResult(rows), skipped_anchors=(), fiscal_year=str(fiscal_year),
            )

    result = MultiPeriodFundamentalsProvider(IncompleteLatestStub()).build(
        "TEST", "2026-12-31", fiscal_years=("2021", "2022", "2023", "2024", "2025", "2026")
    )
    assert calls == ["2021", "2022", "2023", "2024", "2025", "2026", "2020"]
    assert result.latest_fy == "2025"
    assert [item.identity for item in result.annual_slots] == ["2020", "2021", "2022", "2023", "2024", "2025"]
    anchor = next(item for item in result.diagnostics if item["type"] == "ANNUAL_FY_ANCHOR")
    assert anchor["latest_available_fy"] == "2026"
    assert anchor["latest_usable_fy"] == "2025"


def test_provider_anchors_to_latest_usable_fy_when_latest_fy_is_ambiguous():
    calls: list[str] = []

    class AmbiguousLatestStub:
        def build(self, ticker, fiscal_year, requested_as_of, **kwargs):
            calls.append(str(fiscal_year))
            year = int(fiscal_year)
            rows = _annual_rows(year, status="PERIOD_AMBIGUOUS") if year == 2026 else _annual_rows(year)
            return SimpleNamespace(
                company_family="NON_FINANCIAL", facts=rows,
                result=PeriodizationResult(rows), skipped_anchors=(), fiscal_year=str(fiscal_year),
            )

    result = MultiPeriodFundamentalsProvider(AmbiguousLatestStub()).build(
        "TEST", "2026-12-31", fiscal_years=("2021", "2022", "2023", "2024", "2025", "2026")
    )
    assert calls == ["2021", "2022", "2023", "2024", "2025", "2026", "2020"]
    assert result.latest_fy == "2025"
    assert result.has_6fy_comparison_window is True


def test_provider_does_not_backfill_when_no_usable_fy_exists():
    calls: list[str] = []

    class NoUsableFYStub:
        def build(self, ticker, fiscal_year, requested_as_of, **kwargs):
            calls.append(str(fiscal_year))
            rows = (_obs(int(fiscal_year), "FY", "revenue"),)
            return SimpleNamespace(
                company_family="NON_FINANCIAL", facts=rows,
                result=PeriodizationResult(rows), skipped_anchors=(), fiscal_year=str(fiscal_year),
            )

    result = MultiPeriodFundamentalsProvider(NoUsableFYStub()).build(
        "TEST", "2026-12-31", fiscal_years=("2021", "2022", "2023", "2024", "2025", "2026")
    )
    assert calls == ["2021", "2022", "2023", "2024", "2025", "2026"]
    assert result.latest_fy is None
    assert result.has_6fy_comparison_window is False
    anchor = next(item for item in result.diagnostics if item["type"] == "ANNUAL_FY_ANCHOR")
    assert anchor["latest_available_fy"] == "2026"
    assert anchor["latest_usable_fy"] is None


def test_optional_annual_ocf_basis_mismatch_does_not_block_window():
    rows = [
        _obs(2022, "FY", "operating_cash_flow", basis="OFS")
        if item.fiscal_year == "2022" and item.fiscal_period == "FY" and item.metric == "operating_cash_flow"
        else item
        for item in _canonical()
    ]
    result = build_multi_period_result(ticker="TEST", requested_as_of="2024-12-31", observations=rows)
    assert result.has_6fy_comparison_window is True
    assert result.annual_coverage["basis_consistent"] is True
    assert any(item["type"] == "OPTIONAL_BASIS_MISMATCH" for item in result.diagnostics)


def test_optional_annual_ocf_currency_mismatch_does_not_block_window():
    rows = [
        _obs(2022, "FY", "operating_cash_flow", currency="USD")
        if item.fiscal_year == "2022" and item.fiscal_period == "FY" and item.metric == "operating_cash_flow"
        else item
        for item in _canonical()
    ]
    result = build_multi_period_result(ticker="TEST", requested_as_of="2024-12-31", observations=rows)
    assert result.has_6fy_comparison_window is True
    assert result.annual_coverage["currency_consistent"] is True
    assert any(item["type"] == "OPTIONAL_CURRENCY_MISMATCH" for item in result.diagnostics)


def test_optional_quarter_equity_basis_mismatch_does_not_block_window():
    rows = [
        _obs(2022, "Q1", "equity", basis="OFS")
        if item.fiscal_year == "2022" and item.fiscal_period == "Q1" and item.metric == "equity"
        else item
        for item in _canonical()
    ]
    result = build_multi_period_result(ticker="TEST", requested_as_of="2024-12-31", observations=rows)
    assert result.has_16q_comparison_window is True
    assert result.quarter_coverage["basis_consistent"] is True
    assert any(item["type"] == "OPTIONAL_BASIS_MISMATCH" and item["metric"] == "equity" for item in result.diagnostics)


def test_optional_quarter_liabilities_currency_mismatch_does_not_block_window():
    rows = [
        _obs(2022, "Q1", "liabilities", currency="USD")
        if item.fiscal_year == "2022" and item.fiscal_period == "Q1" and item.metric == "liabilities"
        else item
        for item in _canonical()
    ]
    result = build_multi_period_result(ticker="TEST", requested_as_of="2024-12-31", observations=rows)
    assert result.has_16q_comparison_window is True
    assert result.quarter_coverage["currency_consistent"] is True
    assert any(item["type"] == "OPTIONAL_CURRENCY_MISMATCH" and item["metric"] == "liabilities" for item in result.diagnostics)


def test_required_metric_mismatch_still_blocks_window():
    rows = [
        _obs(2022, "Q1", "net_income", currency="USD")
        if item.fiscal_year == "2022" and item.fiscal_period == "Q1" and item.metric == "net_income"
        else item
        for item in _canonical()
    ]
    result = build_multi_period_result(ticker="TEST", requested_as_of="2024-12-31", observations=rows)
    assert result.has_16q_comparison_window is False
    assert result.quarter_coverage["currency_consistent"] is False
    assert any(item["type"] == "CURRENCY_MISMATCH_WINDOW" and item["metric"] == "net_income" for item in result.diagnostics)
