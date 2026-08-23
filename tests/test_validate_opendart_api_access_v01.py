from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from scripts.validate_opendart_api_access_v01 import (
    EXPECTED_FINANCIAL_FIELDS,
    build_request_url,
    classify_status,
    map_tickers,
    parse_corp_code_zip,
    redact_url,
    _financial_summary,
    _company_summary,
)


def test_redact_url_never_keeps_open_dart_key():
    raw = build_request_url(
        "https://opendart.fss.or.kr/api/company.json",
        {"crtfc_key": "secret-value", "corp_code": "00123456"},
    )
    safe = redact_url(raw)
    assert "secret-value" not in safe
    assert "crtfc_key=%3CREDACTED%3E" in safe
    assert "corp_code=00123456" in safe


def test_corp_code_zip_parse_and_exact_mapping():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <result><list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name><stock_code>005930</stock_code><modify_date>20260821</modify_date></list>
    <list><corp_code>00238684</corp_code><corp_name>에스티팜</corp_name><stock_code>237690</stock_code><modify_date>20260821</modify_date></list></result>""".encode()
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("CORPCODE.xml", xml)
    records, info = parse_corp_code_zip(buffer.getvalue())
    mapping, errors = map_tickers(records, ("005930", "237690"))
    assert info["record_count"] == 2
    assert errors == []
    assert mapping["005930"]["corp_code"] == "00126380"
    assert mapping["237690"]["stock_code"] == "237690"


def test_status_code_classification_keeps_data_not_found_distinct():
    assert classify_status("000") == "PASS"
    assert classify_status("013") == "DATA_NOT_FOUND"
    assert classify_status("010") == "API_ACCESS_BLOCKED"
    assert classify_status("020") == "REQUEST_LIMIT_BLOCKED"
    assert classify_status("900") == "EXTERNAL_SERVICE_ERROR"


def test_financial_schema_summary_checks_fields_and_diagnostics():
    row = {field: "" for field in EXPECTED_FINANCIAL_FIELDS}
    row.update({
        "corp_code": "00126380",
        "sj_div": "IS",
        "sj_nm": "손익계산서",
        "account_id": "ifrs-full_Revenue",
        "account_nm": "매출액",
        "thstrm_amount": "100",
    })
    result = _financial_summary(
        {"status": "000", "message": "정상", "list": [row]},
        {"corp_code": "00126380"},
    )
    assert result["classification"] == "PASS"
    assert result["schema_status"] == "PASS"
    assert result["missing_expected_fields"] == []
    assert result["unique_sj_div"] == ["IS"]
    assert result["diagnostic_account_rows"][0]["account_id"] == "ifrs-full_Revenue"


def test_annual_report_optional_prior_quarter_fields_do_not_fail_schema():
    row = {field: "" for field in EXPECTED_FINANCIAL_FIELDS}
    row.pop("frmtrm_q_nm")
    row.pop("frmtrm_q_amount")
    row.pop("frmtrm_add_amount")
    row.update({"corp_code": "00126380", "sj_div": "IS", "account_nm": "매출액"})
    result = _financial_summary({"status": "000", "list": [row]}, {"corp_code": "00126380"})
    assert result["schema_status"] == "PASS"
    assert result["schema_required_missing_fields"] == []
    assert set(result["schema_optional_missing_fields"]) == {
        "frmtrm_q_nm", "frmtrm_q_amount", "frmtrm_add_amount"
    }


def test_company_identity_allows_legal_form_suffix_variation():
    result = _company_summary(
        {
            "status": "000",
            "corp_code": "00126380",
            "corp_name": "삼성전자(주)",
            "stock_code": "005930",
        },
        {"corp_code": "00126380", "corp_name": "삼성전자", "stock_code": "005930"},
    )
    assert result["corp_name_match_after_legal_suffix_normalization"] is True
    assert result["identity_consistency"] is True
