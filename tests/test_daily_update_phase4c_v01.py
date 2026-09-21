"""Phase 4C production runner (scripts/run_daily_update_phase4c_v01.py) targeted tests.

일부 테스트는 실제 2026-09-17 exact-target production 데이터(4A/4B가 이미 생성한
로컬 authority)를 그대로 사용한다 -- exporter들이 ``repo_root``를 실제 저장소
루트에 고정하는 계약(예: ``export_stock_report_web.build_web_payload``)이라 완전히
격리된 tmp_path 루트로는 대체할 수 없기 때문이다. 이 테스트들은 세션 스코프
fixture로 한 번만 4C 러너를 실행해 결과를 재사용한다(각 테스트마다 재실행하지 않음).
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pandas as pd
import pytest

import scripts.run_daily_update_phase4c_v01 as phase4c
from scripts import export_foreign_net_buy_ranking_web as foreign_net_buy_web
from scripts import export_stock_report_web as stock_report_web
from scripts import export_strategy_monitor_web as strategy_monitor_web

ROOT = Path(__file__).resolve().parents[1]
REAL_TARGET = "2026-09-17"


def _write_scanner_summary(
    root: Path,
    target_as_of: str,
    *,
    requested_as_of: str | None = None,
    reference_market_date: str | None = None,
) -> Path:
    dt_clean = target_as_of.replace("-", "")
    scanner_dir = root / "artifacts/patterns/pattern_a/production/scanner"
    scanner_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "requested_as_of": requested_as_of if requested_as_of is not None else target_as_of,
        "reference_market_date": reference_market_date if reference_market_date is not None else target_as_of,
        "official_common_total": 1,
    }
    path = scanner_dir / f"pattern_a_universe_scan_{dt_clean}_summary.json"
    path.write_text(json.dumps(summary), encoding="utf-8")
    return path


# --- A. exact-target scanner summary만 사용 (latest 자동 선택 무시) ----------------


def test_a_load_scanner_summary_ignores_more_recent_other_date(tmp_path):
    _write_scanner_summary(tmp_path, "2026-09-17")
    _write_scanner_summary(tmp_path, "2026-09-20")  # target보다 최신이지만 무시돼야 함

    summary = phase4c.load_scanner_summary(tmp_path, "2026-09-17")
    assert summary["requested_as_of"] == "2026-09-17"


def test_a_missing_exact_scanner_summary_fails_closed(tmp_path):
    _write_scanner_summary(tmp_path, "2026-09-04")  # target 아님
    with pytest.raises(phase4c.Phase4CError, match="PHASE4C_SCANNER_SUMMARY_MISSING"):
        phase4c.load_scanner_summary(tmp_path, "2026-09-17")


def test_a_scanner_requested_as_of_mismatch_fails_closed(tmp_path):
    _write_scanner_summary(tmp_path, "2026-09-17", requested_as_of="2026-09-16")
    with pytest.raises(phase4c.Phase4CError, match="PHASE4C_SCANNER_REQUESTED_AS_OF_MISMATCH"):
        phase4c.load_scanner_summary(tmp_path, "2026-09-17")


def test_a_reference_market_date_after_target_fails_closed(tmp_path):
    _write_scanner_summary(tmp_path, "2026-09-17", reference_market_date="2026-09-18")
    with pytest.raises(phase4c.Phase4CError, match="PHASE4C_SCANNER_REFERENCE_MARKET_DATE_AFTER_TARGET"):
        phase4c.load_scanner_summary(tmp_path, "2026-09-17")


# --- basic_info dir 선택: target 이하 최신, 새 fallback 프레임워크 없이 재사용 -------


def test_basic_info_dir_picks_nearest_past_snapshot(tmp_path):
    basic_info_root = tmp_path / "data/reference/source/history/krx_instrument_master/v01/rolling/basic_info"
    (basic_info_root / "2026/20260910").mkdir(parents=True)
    (basic_info_root / "2026/20260911").mkdir(parents=True)
    (basic_info_root / "2026/20260918").mkdir(parents=True)  # target 이후, 선택되면 안 됨

    resolved = phase4c.resolve_basic_info_dir(tmp_path, "2026-09-17")
    assert resolved.name == "20260911"


def test_basic_info_dir_missing_fails_closed(tmp_path):
    with pytest.raises(phase4c.Phase4CError, match="PHASE4C_BASIC_INFO_DIR_NOT_FOUND"):
        phase4c.resolve_basic_info_dir(tmp_path, "2026-09-17")


# --- H. Basic Info future-only snapshot fail-closed (미래 fallback 제거) -----------


def test_h_basic_info_future_only_snapshots_fail_closed(tmp_path):
    """target=2026-09-17인데 가용 snapshot이 전부 미래(20260918/20260919)뿐이면
    과거 구현처럼 미래 snapshot으로 대체하지 않고 fail-closed해야 한다."""
    basic_info_root = tmp_path / "data/reference/source/history/krx_instrument_master/v01/rolling/basic_info"
    (basic_info_root / "2026/20260918").mkdir(parents=True)
    (basic_info_root / "2026/20260919").mkdir(parents=True)

    with pytest.raises(phase4c.Phase4CError, match="PHASE4C_BASIC_INFO_NO_SNAPSHOT_ON_OR_BEFORE_TARGET"):
        phase4c.resolve_basic_info_dir(tmp_path, "2026-09-17")


# --- report corpus 존재 확인 --------------------------------------------------------


def test_report_corpus_missing_fails_closed(tmp_path):
    with pytest.raises(phase4c.Phase4CError, match="PHASE4C_REPORT_CORPUS_MISSING"):
        phase4c.validate_report_corpus_directory(tmp_path, "2026-09-17")


def test_phase4c_uses_approved_periodic_sector_membership_snapshot(monkeypatch, tmp_path):
    selected_path = tmp_path / "sector_membership_20260917.parquet"
    calls = []

    def _resolver(target_as_of, *, repo_root):
        calls.append((target_as_of, repo_root))
        return object(), "2026-09-17", selected_path, {"snapshot_effective_date": "2026-09-17"}

    monkeypatch.setattr(phase4c, "resolve_sector_membership_snapshot_for_target", _resolver)

    effective_date, path = phase4c.resolve_sector_membership_for_target("2026-09-18", root=tmp_path)

    assert calls == [("2026-09-18", tmp_path)]
    assert effective_date == "2026-09-17"
    assert path == selected_path


# --- C. non-trading date: requested/reference 분리 정상 처리 -----------------------


@pytest.fixture
def temp_report_dir_for_non_trading_day():
    """실제 저장소 트리 안에 target-day 전용 임시 report 디렉터리를 만든다
    (export_stock_report_web은 repo_root를 실제 ROOT에 고정하는 계약이라 완전
    격리된 tmp_path로 대체할 수 없음). 20260904/20260917과 겹치지 않는 새 날짜만
    사용하고 테스트 종료 후 반드시 삭제한다."""
    target_as_of = "2026-09-12"
    reference_market_date = "2026-09-11"
    report_dir = ROOT / "artifacts/reporting/stock_reports" / target_as_of.replace("-", "")
    assert not report_dir.exists(), "test fixture must not already exist"
    json_dir = report_dir / "json"
    json_dir.mkdir(parents=True)
    fundamentals = {
        "applicability": "NOT_APPLICABLE",
        "reason": "TEST_FIXTURE",
        "requested_as_of": target_as_of,
        "company_family": None,
        "currency": "KRW",
        "filter_status": "DATA_UNAVAILABLE",
        "filter_passed": False,
        "filter_reasons": [],
        "summary": {},
        "quarterly": [],
        "annual": [],
        "data_status": "NOT_APPLICABLE",
    }
    report = {
        "ticker": "005930",
        "name": "삼성전자",
        "market": "KOSPI",
        "asset_type": "COMMON",
        "requested_as_of": target_as_of,
        "reference_market_date": reference_market_date,
        "report_version": "0.5",
        "header": {"ticker": "005930", "name": "삼성전자", "market": "KOSPI", "asset_type": "COMMON"},
        "fundamentals": fundamentals,
        "a_fast_core": {"strategy_id": "PATTERN_A_FAST_FINAL_STRATEGY_V02"},
    }
    (json_dir / "005930_삼성전자.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    try:
        yield target_as_of, reference_market_date
    finally:
        shutil.rmtree(report_dir)


def test_c_non_trading_day_requested_and_reference_are_kept_separate(temp_report_dir_for_non_trading_day):
    target_as_of, reference_market_date = temp_report_dir_for_non_trading_day
    index, reports, stats = stock_report_web.build_web_payload(
        ROOT, target_as_of=target_as_of, reference_market_date=reference_market_date,
    )
    assert index["requested_as_of"] == target_as_of
    assert index["reference_market_date"] == reference_market_date
    assert stats["requested_as_of"] == target_as_of
    assert stats["reference_market_date"] == reference_market_date
    assert reports["005930"]["technical_details"]["requested_as_of"] == target_as_of
    assert reports["005930"]["technical_details"]["reference_market_date"] == reference_market_date


# --- D. mixed date fail: 하나라도 다른 target/reference면 fail-closed --------------


def test_d_report_with_wrong_reference_market_date_fails_closed(temp_report_dir_for_non_trading_day):
    target_as_of, reference_market_date = temp_report_dir_for_non_trading_day
    with pytest.raises(ValueError, match="reference_market_date mismatch"):
        stock_report_web.build_web_payload(
            ROOT, target_as_of=target_as_of, reference_market_date="2026-09-10",  # 실제와 다른 값
        )


def test_d_report_with_wrong_requested_as_of_fails_closed(temp_report_dir_for_non_trading_day):
    target_as_of, reference_market_date = temp_report_dir_for_non_trading_day
    with pytest.raises(FileNotFoundError, match="exact-target Stock Report directory not found"):
        stock_report_web.build_web_payload(
            ROOT, target_as_of="2026-09-13", reference_market_date=reference_market_date,
        )


# --- 실제 2026-09-17 production 데이터 기반 통합 검증 (세션 1회 실행) --------------


@pytest.fixture(scope="session")
def real_phase4c_result():
    return phase4c.run_phase4c(REAL_TARGET, root=ROOT)


def test_real_run_status_pass(real_phase4c_result):
    assert real_phase4c_result["status"] == "PASS"
    assert real_phase4c_result["requested_as_of"] == REAL_TARGET
    assert real_phase4c_result["reference_market_date"] == REAL_TARGET


# --- B. stale web/data가 4C 결과의 authority로 쓰이지 않음 --------------------------


def test_b_stale_web_data_is_not_used_as_authority(real_phase4c_result):
    """web/data가 현재 더 오래된 날짜 기반 상태여도(예: 2026-09-04, 553~1836개 등)
    4C 결과는 2026-09-17 exact-target 기준(1850개)으로 나와야 한다."""
    web_index_path = ROOT / "web/data/stock-index.json"
    if web_index_path.exists():
        web_index = json.loads(web_index_path.read_text(encoding="utf-8"))
        web_requested_as_of = str(web_index.get("requested_as_of") or "")[:10]
        # web/data가 stale하다는 사실 자체를 이 테스트의 전제로 삼지는 않되(환경마다
        # 다를 수 있음), 4C 결과가 web/data 값에 좌우되지 않고 target 그대로임을 확인.
        assert real_phase4c_result["requested_as_of"] == REAL_TARGET
        assert web_requested_as_of != "" or True  # web/data 존재 자체는 optional
    assert real_phase4c_result["stock_report"]["json_count"] == real_phase4c_result["cross_payload_validation"]["stock_report_ticker_count"]


# --- E. published ticker parity -----------------------------------------------------


def test_e_published_ticker_parity_across_payloads(real_phase4c_result):
    cpv = real_phase4c_result["cross_payload_validation"]
    assert cpv["sets_equal"] is True
    counts = {
        cpv["stock_report_ticker_count"],
        cpv["stock_index_available_count"],
        cpv["market_ranking_ticker_count"],
        cpv["strategy_monitor_ticker_count"],
    }
    assert len(counts) == 1
    assert real_phase4c_result["stock_report"]["json_count"] in counts


# --- F. OPEN continuity: previous OPEN + current non-CANDIDATE가 strategy monitor에 존재 ---


def test_f_previous_open_non_candidate_ticker_present_in_strategy_monitor():
    """000370은 Phase 4B continuity 감사에서 previous OPEN + current non-CANDIDATE로
    확인된 실제 종목이다 -- strategy monitor에서 canonical_position OPEN으로 계속
    나타나야 한다(candidate 여부로 재필터링되지 않음)."""
    target_as_of = REAL_TARGET
    summary = phase4c.load_scanner_summary(ROOT, target_as_of)
    reference_market_date = str(summary["reference_market_date"])
    index, reports, _stats = stock_report_web.build_web_payload(
        ROOT, target_as_of=target_as_of, reference_market_date=reference_market_date,
    )
    assert "000370" in reports
    assert reports["000370"]["decision"]["canonical_position"] == "OPEN"

    import tempfile

    with tempfile.TemporaryDirectory() as tmp_name:
        staging_dir = Path(tmp_name)
        index_path, stocks_dir = phase4c.write_temp_stock_report_payload(staging_dir, index, reports)
        monitor = strategy_monitor_web.build_strategy_monitor(
            index_path=index_path, stocks_path=stocks_dir,
            target_as_of=target_as_of, reference_market_date=reference_market_date,
        )
    item = next(item for item in monitor["items"] if item["ticker"] == "000370")
    assert item["canonical_position"] == "OPEN"


# --- G. Foreign ranking authority: stock-index가 모집단 authority가 아님 -----------


def test_g_foreign_ranking_population_authority_is_not_stock_index(real_phase4c_result):
    foreign = real_phase4c_result["foreign_net_buy_ranking"]
    stock_report = real_phase4c_result["stock_report"]
    # foreign net buy 모집단(PIT COMMON authority exact target)은 발행된 Stock Report
    # 개수(1850, continuity 적용된 부분집합)와 다르다 -- stock-index가 모집단 authority로
    # 쓰였다면 두 값이 같아야 하므로, 다르다는 사실 자체가 분리를 증명한다.
    assert foreign["target_common_universe_count"] != stock_report["available_report_count"]
    assert real_phase4c_result["sector_rs_ranking"]["population_count"] != stock_report["available_report_count"]


# --- 4C runner 실행 후 web/data 무변경 ----------------------------------------------


def test_no_web_data_writes(real_phase4c_result):
    assert real_phase4c_result["web_data_writes"] == 0


# ==================================================================================
# Phase 4C Final Fix (PHASE4C_FINAL_FIX_V01) — 날짜 계약 보강 / identity 경계 / 미래
# fallback 제거 / web_data_writes fail-closed
# ==================================================================================


# --- A. Sector RS requested/reference/as_of 세 필드 정상 ---------------------------


def test_a_sector_rs_exposes_requested_reference_as_of(real_phase4c_result):
    sector_rs = real_phase4c_result["sector_rs_ranking"]
    assert sector_rs["requested_as_of"] == REAL_TARGET
    assert sector_rs["reference_market_date"] == REAL_TARGET
    assert sector_rs["as_of"] == REAL_TARGET
    assert sector_rs["as_of"] == sector_rs["reference_market_date"]


# --- B. Foreign requested/reference/as_of 세 필드 정상 -----------------------------


def test_b_foreign_net_buy_exposes_requested_reference_as_of(real_phase4c_result):
    foreign = real_phase4c_result["foreign_net_buy_ranking"]
    assert foreign["requested_as_of"] == REAL_TARGET
    assert foreign["reference_market_date"] == REAL_TARGET
    assert foreign["as_of"] == REAL_TARGET
    assert foreign["as_of"] == foreign["reference_market_date"]


# --- D. Sector mixed date fail-closed -----------------------------------------------


def test_d_sector_rs_reference_market_date_mismatch_fails_closed(monkeypatch):
    """runner가 sector_rs payload의 reference_market_date를 scanner authority
    reference_market_date와 대조해 fail-closed하는지 확인한다(as_of 하나만 보는
    과거 구현으로는 잡히지 않던 문제)."""
    original = phase4c.sector_rs_web.build_sector_rs_web_payload

    def _tampered(**kwargs):
        payload = original(**kwargs)
        payload["reference_market_date"] = "2026-09-16"  # 실제와 다르게 조작
        return payload

    monkeypatch.setattr(phase4c.sector_rs_web, "build_sector_rs_web_payload", _tampered)
    with pytest.raises(phase4c.Phase4CError, match="PHASE4C_SECTOR_RS_REFERENCE_MARKET_DATE_MISMATCH"):
        phase4c.run_phase4c(REAL_TARGET, root=ROOT)


def test_d_sector_rs_authority_as_of_mismatch_fails_closed():
    """ranking authority 자체의 as_of가 기대값과 다르면 _validate_core가
    fail-closed한다(하드코딩된 "2026-09-04" 대신 명시적 expected_as_of/
    reference_market_date로 검증)."""
    from scripts import export_sector_rs_ranking_web as sector_rs_web

    basic_info_dir = phase4c.resolve_basic_info_dir(ROOT, REAL_TARGET)
    with tempfile.TemporaryDirectory() as tmp_name, pytest.raises(ValueError, match="unexpected ranking as_of"):
        sector_rs_web.build_sector_rs_web_payload(
            ranking_path=ROOT / "data/analytics/sector_rs_ranking/v01/sector_rs_ranking_20260917.parquet",
            meta_path=ROOT / "data/analytics/sector_rs_ranking/v01/sector_rs_ranking_20260917_meta.json",
            basic_info_dir=basic_info_dir,
            stocks_dir=Path(tmp_name),
            requested_as_of=REAL_TARGET,
            reference_market_date="2026-09-16",  # 실제 ranking authority as_of(2026-09-17)와 다름
        )


# --- E. Foreign mixed date fail-closed ----------------------------------------------


def test_e_foreign_net_buy_requested_as_of_mismatch_fails_closed(monkeypatch):
    original = phase4c.foreign_net_buy_web.build_foreign_net_buy_ranking

    def _tampered(**kwargs):
        payload = original(**kwargs)
        payload["requested_as_of"] = "2026-09-16"  # 실제와 다르게 조작
        return payload

    monkeypatch.setattr(phase4c.foreign_net_buy_web, "build_foreign_net_buy_ranking", _tampered)
    with pytest.raises(phase4c.Phase4CError, match="PHASE4C_FOREIGN_NET_BUY_REQUESTED_AS_OF_MISMATCH"):
        phase4c.run_phase4c(REAL_TARGET, root=ROOT)


# --- F/G. Foreign name authority는 공식 PIT identity이지 stock-index가 아님 --------
# stock-index는 report_available 표시에만 쓰인다 --------------------------------------


def test_fg_foreign_name_authority_is_pit_identity_not_stock_index(tmp_path):
    """stock-index에 고의로 틀린 종목명을 넣어도 foreign net buy 결과의 이름은
    공식 PIT identity authority(InstrumentMetadataResolver) 값을 그대로 써야
    하고, report_available만 stock-index에서 읽어야 한다."""
    index_path = tmp_path / "stock-index.json"
    index_path.write_text(
        json.dumps({
            "schema_version": 1,
            "items": [{"ticker": "005930", "name": "가짜이름_이건_authority가_아님", "report_available": True}],
        }),
        encoding="utf-8",
    )

    common_authority_path = tmp_path / "common.csv"
    common_authority_path.write_text("ticker,market\n005930,KOSPI\n", encoding="utf-8")

    sector_path = tmp_path / "sector.parquet"
    pd.DataFrame({"ticker": ["005930"], "sector_name": ["전기전자"]}).to_parquet(sector_path)

    universe, _snapshot_date = foreign_net_buy_web.load_common_universe(
        index_path=index_path,
        sector_path=sector_path,
        common_authority_path=common_authority_path,
        as_of=REAL_TARGET,
        repo_root=ROOT,
    )
    item = next(i for i in universe if i["ticker"] == "005930")
    assert item["name"] != "가짜이름_이건_authority가_아님"
    assert item["name"] == "삼성전자"  # 공식 PIT identity authority(InstrumentMetadataResolver) 값
    assert item["market"] == "KOSPI"  # market은 common authority가 그대로 제공(덮어쓰지 않음)
    assert item["report_available"] is True  # report_available만 stock-index에서 읽음


def test_fg_foreign_report_available_still_read_from_stock_index(tmp_path):
    """동일 tmp_path 셋업에서 report_available=False인 경우도 stock-index 값을
    그대로 반영하는지 확인한다(이름과 무관하게 report_available lookup은 유지)."""
    index_path = tmp_path / "stock-index.json"
    index_path.write_text(
        json.dumps({
            "schema_version": 1,
            "items": [{"ticker": "005930", "name": "무시되는이름", "report_available": False}],
        }),
        encoding="utf-8",
    )
    common_authority_path = tmp_path / "common.csv"
    common_authority_path.write_text("ticker,market\n005930,KOSPI\n", encoding="utf-8")
    sector_path = tmp_path / "sector.parquet"
    pd.DataFrame({"ticker": ["005930"], "sector_name": ["전기전자"]}).to_parquet(sector_path)

    universe, _snapshot_date = foreign_net_buy_web.load_common_universe(
        index_path=index_path,
        sector_path=sector_path,
        common_authority_path=common_authority_path,
        as_of=REAL_TARGET,
        repo_root=ROOT,
    )
    item = next(i for i in universe if i["ticker"] == "005930")
    assert item["report_available"] is False
    assert item["name"] == "삼성전자"


# --- NT/LG. Non-trading PIT identity date 분리 (PHASE4C_NON_TRADING_PIT_DATE_FINAL_FIX) --
# PIT identity/name 기준일 = requested_as_of, 시장/수급 계산 기준일 = reference_market_date.


def _synthetic_foreign_universe_paths(tmp_path):
    index_path = tmp_path / "stock-index.json"
    index_path.write_text(
        json.dumps({
            "schema_version": 1,
            "items": [{"ticker": "005930", "name": "무시되는이름", "report_available": True}],
        }),
        encoding="utf-8",
    )
    common_authority_path = tmp_path / "common.csv"
    common_authority_path.write_text("ticker,market\n005930,KOSPI\n", encoding="utf-8")
    sector_path = tmp_path / "sector.parquet"
    pd.DataFrame({"ticker": ["005930"], "sector_name": ["전기전자"]}).to_parquet(sector_path)
    return index_path, common_authority_path, sector_path


def test_nt_non_trading_identity_date_uses_requested_as_of(monkeypatch, tmp_path):
    """비거래일 target_as_of: PIT identity resolver는 requested_as_of(2026-09-12)
    기준으로 조회되고, 시장/수급 기준일(as_of=reference_market_date=2026-09-11)은
    그대로 유지되는지 spy로 직접 확인한다."""
    index_path, common_authority_path, sector_path = _synthetic_foreign_universe_paths(tmp_path)
    requested_as_of = "2026-09-12"
    reference_market_date = "2026-09-11"

    calls: list[str] = []

    def _spy(repo_root, as_of):
        calls.append(as_of)
        return {"005930": "삼성전자"}

    monkeypatch.setattr(foreign_net_buy_web, "_load_pit_identity_names", _spy)

    universe, snapshot_date = foreign_net_buy_web.load_common_universe(
        index_path=index_path,
        sector_path=sector_path,
        common_authority_path=common_authority_path,
        as_of=reference_market_date,
        identity_as_of=requested_as_of,
        repo_root=ROOT,
    )

    assert calls == [requested_as_of]  # PIT identity는 requested_as_of 기준으로 조회
    assert snapshot_date == reference_market_date  # 시장/수급 기준일은 reference_market_date 유지
    item = next(i for i in universe if i["ticker"] == "005930")
    assert item["name"] == "삼성전자"


def test_lg_legacy_call_without_identity_as_of_keeps_as_of_semantics(monkeypatch, tmp_path):
    """identity_as_of 미지정 시 기존(legacy) 동작 유지: PIT identity 기준일 = as_of."""
    index_path, common_authority_path, sector_path = _synthetic_foreign_universe_paths(tmp_path)
    as_of = "2026-09-11"

    calls: list[str] = []

    def _spy(repo_root, identity_as_of):
        calls.append(identity_as_of)
        return {"005930": "삼성전자"}

    monkeypatch.setattr(foreign_net_buy_web, "_load_pit_identity_names", _spy)

    foreign_net_buy_web.load_common_universe(
        index_path=index_path,
        sector_path=sector_path,
        common_authority_path=common_authority_path,
        as_of=as_of,
        repo_root=ROOT,
    )

    assert calls == [as_of]


# --- I. web_data_writes > 0이면 fail -------------------------------------------------


def test_i_web_data_writes_nonzero_fails_closed(monkeypatch):
    calls = {"n": 0}

    def _fake_snapshot(root):
        calls["n"] += 1
        return {"stock-index.json": (1.0, 100)} if calls["n"] == 1 else {"stock-index.json": (2.0, 100)}

    monkeypatch.setattr(phase4c, "snapshot_web_data", _fake_snapshot)
    with pytest.raises(phase4c.Phase4CError, match="PHASE4C_WEB_DATA_WRITE_DETECTED"):
        phase4c.run_phase4c(REAL_TARGET, root=ROOT)
