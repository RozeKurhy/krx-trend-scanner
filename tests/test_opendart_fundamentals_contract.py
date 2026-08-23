from __future__ import annotations

from trend_scanner.fundamentals.opendart_contract import (
    AccountResolutionStatus,
    CompanyFamily,
    FilingSelectionStatus,
    StatementFamily,
    map_statement_family,
    redact_url,
    resolve_core_account,
    select_pit_filing,
    select_statement_basis,
)


def _filing(rcept_no: str, rcept_dt: str, report_nm: str = "사업보고서", chain: str = "annual") -> dict[str, str]:
    return {
        "ticker": "237690",
        "corp_code": "00871833",
        "bsns_year": "2025",
        "reprt_code": "11011",
        "report_nm": report_nm,
        "rcept_no": rcept_no,
        "rcept_dt": rcept_dt,
        "filing_chain_key": chain,
    }


def test_same_day_filing_is_available_at_eod():
    result = select_pit_filing([_filing("100", "2025-03-20")], "2025-03-20", "2025", "11011")
    assert result.status == FilingSelectionStatus.READY.value
    assert result.availability == "AVAILABLE_AT_EOD"


def test_future_filing_is_rejected():
    result = select_pit_filing([_filing("100", "2025-03-20")], "2025-03-19", "2025", "11011")
    assert result.status == FilingSelectionStatus.FUTURE_FORBIDDEN.value
    assert result.selected is None


def test_latest_eligible_correction_is_selected():
    filings = [
        _filing("100", "2025-03-20"),
        _filing("200", "2025-05-10", "[기재정정]사업보고서"),
    ]
    result = select_pit_filing(filings, "2025-06-01", "2025", "11011")
    assert result.selected is not None
    assert result.selected.rcept_no == "200"


def test_future_correction_does_not_replace_original():
    filings = [
        _filing("100", "2025-03-20"),
        _filing("200", "2025-05-10", "[기재정정]사업보고서"),
    ]
    result = select_pit_filing(filings, "2025-04-01", "2025", "11011")
    assert result.selected is not None
    assert result.selected.rcept_no == "100"


def test_ambiguous_chain_fails_closed():
    filings = [_filing("100", "2025-03-20", chain="chain-a"), _filing("200", "2025-03-21", chain="chain-b")]
    result = select_pit_filing(filings, "2025-04-01", "2025", "11011")
    assert result.status == FilingSelectionStatus.AMBIGUOUS.value
    assert result.selected is None


def test_statement_family_maps_is_and_cis_to_income_statement():
    assert map_statement_family("IS") == StatementFamily.INCOME_STATEMENT.value
    assert map_statement_family("CIS") == StatementFamily.INCOME_STATEMENT.value
    assert map_statement_family("SCE") == StatementFamily.EQUITY_CHANGES.value


def test_sce_equity_does_not_pollute_balance_sheet_equity_resolution():
    rows = [
        {"account_id": "ifrs-full_Equity", "account_nm": "자본총계", "sj_div": "SCE", "thstrm_amount": "10"},
        {"account_id": "ifrs-full_Equity", "account_nm": "자본총계", "sj_div": "BS", "thstrm_amount": "20"},
    ]
    result = resolve_core_account(rows, "equity", CompanyFamily.NON_FINANCIAL.value)
    assert result["resolution_status"] == AccountResolutionStatus.RESOLVED.value
    assert result["raw_sj_div"] == "BS"
    assert result["thstrm_amount"] == "20"


def test_cfs_is_atomic_and_preferred_over_ofs():
    result = select_statement_basis("000", [{"account_id": "x"}], "000", [{"account_id": "y"}])
    assert result.fs_div_used == "CFS"
    assert result.fallback_used is False


def test_cfs_data_not_found_allows_ofs_fallback():
    result = select_statement_basis("013", [], "000", [{"account_id": "y"}])
    assert result.fs_div_used == "OFS"
    assert result.fallback_used is True


def test_cfs_api_error_does_not_silently_fallback_to_ofs():
    result = select_statement_basis("900", [], "000", [{"account_id": "y"}])
    assert result.fs_div_used is None
    assert result.fallback_used is False
    assert "NO_SILENT_OFS_FALLBACK" in result.reason


def test_financial_family_marks_nonfinancial_metric_not_applicable():
    result = resolve_core_account([], "revenue", CompanyFamily.FINANCIAL.value)
    assert result["resolution_status"] == AccountResolutionStatus.NOT_APPLICABLE.value


def test_account_resolution_uses_cis_when_is_is_absent():
    rows = [{
        "account_id": "ifrs-full_Revenue",
        "account_nm": "매출",
        "sj_div": "CIS",
        "thstrm_amount": "331",
    }]
    result = resolve_core_account(rows, "revenue", CompanyFamily.NON_FINANCIAL.value)
    assert result["resolution_status"] == AccountResolutionStatus.RESOLVED.value
    assert result["canonical_statement_family"] == StatementFamily.INCOME_STATEMENT.value
    assert result["raw_sj_div"] == "CIS"


def test_tied_same_context_accounts_fail_closed_instead_of_first_match():
    rows = [
        {"account_id": "ifrs-full_ProfitLoss", "account_nm": "당기순이익", "sj_div": "IS", "thstrm_amount": "1"},
        {"account_id": "ifrs-full_ProfitLoss", "account_nm": "당기순이익", "sj_div": "IS", "thstrm_amount": "2"},
    ]
    result = resolve_core_account(rows, "net_income", CompanyFamily.NON_FINANCIAL.value)
    assert result["resolution_status"] == AccountResolutionStatus.AMBIGUOUS.value


def test_secret_redaction_never_keeps_api_key():
    raw = "https://opendart.fss.or.kr/api/fnlttXbrl.xml?crtfc_key=secret-value&rcept_no=123"
    safe = redact_url(raw)
    assert "secret-value" not in safe
    assert "crtfc_key=%3CREDACTED%3E" in safe
    assert "rcept_no=123" in safe
