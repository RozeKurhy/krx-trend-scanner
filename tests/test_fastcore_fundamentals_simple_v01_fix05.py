"""Focused FIX05 tests for failure classification and coverage exclusion."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from scripts import run_fastcore_fundamentals_simple_v01 as runner
from trend_scanner.fundamentals.opendart_client import OpenDartError
from trend_scanner.fundamentals.filing_registry import FilingRegistryApiError


class _CorpRepo:
    def get_record(self, ticker: str) -> SimpleNamespace:
        return SimpleNamespace(corp_code="00126380")


def _candidate() -> dict[str, str]:
    return {
        "candidate_id": "005930|KR7005930003|KOSPI|2020-01-03",
        "ticker": "005930",
        "isu_cd": "KR7005930003",
        "market": "KOSPI",
        "name": "Example",
        "candidate_signal_date": "2020-01-03",
        "entry_signal_information_date": "2020-01-03",
    }


def _f4(status: str, reasons: tuple[str, ...] = ()) -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        reasons=reasons,
        annual_revenue=None,
        quarterly_avg_revenue=None,
        ttm_operating_income=None,
        ttm_net_income=None,
        latest_fy="2019",
        latest_quarter="2019Q3",
    )


def test_transport_exception_is_evaluation_error(monkeypatch):
    monkeypatch.setattr(
        runner,
        "classify_company_family",
        lambda *_args: {"company_family": runner.CompanyFamily.NON_FINANCIAL.value},
    )
    monkeypatch.setattr(runner, "_company", lambda *_args: {"selected_fields": {}})

    def raise_transport(*_args, **_kwargs):
        raise OpenDartError("redacted", classification="SERVICE")

    monkeypatch.setattr(runner, "_bounded_f2", raise_transport)
    row = runner.evaluate_one_candidate(
        _candidate(), corp_repo=_CorpRepo(), period_provider=SimpleNamespace(), live=True,
        client=runner.OpenDartClient(api_key=""),
    )

    assert row["fundamentals_status"] == runner.EVALUATION_ERROR
    assert row["failure_classification"] == runner.EVALUATION_ERROR
    assert row["failure_category"] == "OpenDartError:SERVICE"
    assert not row["evaluable"]


def test_genuine_no_data_remains_true_data_unavailable(monkeypatch):
    monkeypatch.setattr(
        runner,
        "classify_company_family",
        lambda *_args: {"company_family": runner.CompanyFamily.NON_FINANCIAL.value},
    )
    monkeypatch.setattr(runner, "_company", lambda *_args: {"selected_fields": {}})
    monkeypatch.setattr(
        runner,
        "_bounded_f2",
        lambda *_args, **_kwargs: SimpleNamespace(canonical_observations=(), periodization_builds=()),
    )
    monkeypatch.setattr(runner.DerivedMetricsEngine, "derive", lambda *_args, **_kwargs: SimpleNamespace())
    monkeypatch.setattr(
        runner.FundamentalsFilter,
        "evaluate",
        lambda *_args, **_kwargs: _f4(runner.DATA_UNAVAILABLE, ("NO_PIT_DATA",)),
    )
    row = runner.evaluate_one_candidate(
        _candidate(), corp_repo=_CorpRepo(), period_provider=SimpleNamespace(), live=False,
    )

    assert row["fundamentals_status"] == runner.DATA_UNAVAILABLE
    assert row["failure_classification"] == runner.TRUE_DATA_UNAVAILABLE
    assert row["failure_category"] == runner.DATA_UNAVAILABLE
    assert not row["evaluable"]


def test_normal_opendart_data_not_found_remains_true_data_unavailable(monkeypatch):
    monkeypatch.setattr(
        runner,
        "classify_company_family",
        lambda *_args: {"company_family": runner.CompanyFamily.NON_FINANCIAL.value},
    )
    monkeypatch.setattr(runner, "_company", lambda *_args: {"selected_fields": {}})
    monkeypatch.setattr(
        runner,
        "_bounded_f2",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            FilingRegistryApiError("no data", status="013", classification="DATA_NOT_FOUND", http_status=200)
        ),
    )
    row = runner.evaluate_one_candidate(
        _candidate(), corp_repo=_CorpRepo(), period_provider=SimpleNamespace(), live=True,
    )

    assert row["fundamentals_status"] == runner.DATA_UNAVAILABLE
    assert row["failure_classification"] == runner.TRUE_DATA_UNAVAILABLE
    assert row["failure_category"] == "API_DATA_NOT_FOUND"


def test_successful_pit_fixture_is_evaluable_and_keeps_as_of(monkeypatch):
    monkeypatch.setattr(
        runner,
        "classify_company_family",
        lambda *_args: {"company_family": runner.CompanyFamily.NON_FINANCIAL.value},
    )
    monkeypatch.setattr(runner, "_company", lambda *_args: {"selected_fields": {}})
    monkeypatch.setattr(
        runner,
        "_bounded_f2",
        lambda *_args, **_kwargs: SimpleNamespace(canonical_observations=(), periodization_builds=()),
    )
    monkeypatch.setattr(runner.DerivedMetricsEngine, "derive", lambda *_args, **_kwargs: SimpleNamespace())
    monkeypatch.setattr(
        runner.FundamentalsFilter,
        "evaluate",
        lambda *_args, **_kwargs: _f4(runner.PASS),
    )
    row = runner.evaluate_one_candidate(
        _candidate(), corp_repo=_CorpRepo(), period_provider=SimpleNamespace(), live=False,
    )
    artifact_row = runner._coverage_candidate_row({
        **row,
        "selected_filing_receipt_dates": ["2020-01-02"],
    })

    assert row["fundamentals_as_of"] == "2020-01-03"
    assert row["fundamentals_status"] == runner.PASS
    assert row["failure_classification"] == runner.EVALUABLE
    assert artifact_row["entry_signal_information_date"] == "2020-01-03"
    assert artifact_row["fundamentals_as_of"] == "2020-01-03"
    assert artifact_row["filing_references"] == '["2020-01-02"]'


def test_coverage_excludes_evaluation_errors_from_rate_and_qualification():
    decisions = pd.DataFrame([
        {
            "candidate_id": "A", "entry_signal_information_date": "2020-01-10",
            "company_family": "NON_FINANCIAL", "fundamentals_status": runner.PASS,
            "evaluable": True, "failure_classification": runner.EVALUABLE,
        },
        {
            "candidate_id": "B", "entry_signal_information_date": "2020-02-10",
            "company_family": "NON_FINANCIAL", "fundamentals_status": runner.DATA_UNAVAILABLE,
            "evaluable": False, "failure_classification": runner.TRUE_DATA_UNAVAILABLE,
        },
        {
            "candidate_id": "C", "entry_signal_information_date": "2020-03-10",
            "company_family": "NON_FINANCIAL", "fundamentals_status": runner.EVALUATION_ERROR,
            "evaluable": False, "failure_classification": runner.EVALUATION_ERROR,
        },
    ])
    coverage = runner._coverage_rows(decisions)
    row = coverage.iloc[0]

    assert int(row["nonfinancial_candidates"]) == 3
    assert int(row["coverage_eligible_candidates"]) == 2
    assert int(row["evaluation_error_nonfinancial_candidates"]) == 1
    assert float(row["evaluable_rate"]) == 50.0
    assert not bool(row["qualifies_90_percent"])
