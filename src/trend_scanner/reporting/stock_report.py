"""Stock Report Generator Engine (Contract v0.1).

로컬 Parquet 일봉 캐시와 정본 아티팩트만을 활용하여 단일 종목의 종합 분석 리포트를 생성하고
JSON 및 GitHub Flavored Markdown 형식으로 출력한다.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.filters.investability import evaluate_investability
from trend_scanner.flow.foreign_flow import (
    FlowDataStatus,
    ForeignFlowFeatureResult,
    compute_foreign_flow_features,
)
from trend_scanner.patterns.pattern_a_evaluator import (
    PatternACandidateState,
    evaluate_pattern_a,
)
from trend_scanner.patterns.pattern_a_feature_set import PatternAStage
from trend_scanner.reporting.models import (
    CurrentSnapshot,
    DataQualitySection,
    FlowState,
    ForeignFlowSection,
    MonthlyHistorySection,
    MonthlyObservation,
    ProvenanceSection,
    ReportHeader,
    ReportStatus,
    ReportSummary,
    ScoreTrend,
    StageTransition,
    StockReport,
    TradingValueFlowSection,
    TradingValueState,
)
from trend_scanner.validation.historical_snapshot import build_historical_snapshot

logger = logging.getLogger(__name__)


def _format_ticker(ticker: str) -> str:
    return str(ticker).strip().zfill(6)


def _resolve_latest_local_as_of(repo_root: Path) -> str:
    """로컬 데이터 및 아티팩트에서 최신 GLOBAL reference market date를 결정한다."""
    # 1. Primary Authority: Market reference stock 005930 cache
    cache = ParquetCache(base_dir=repo_root / "data/raw/stocks")
    daily_ref = cache.load("005930")
    if daily_ref is not None and not daily_ref.empty:
        return daily_ref.index.max().strftime("%Y-%m-%d")

    # 2. Secondary: Investability universe canonical files
    inv_dir = repo_root / "artifacts/investability"
    if inv_dir.exists():
        univ_files = sorted(inv_dir.glob("pattern_a_investability_universe_*.csv"))
        if univ_files:
            latest_file = univ_files[-1]
            date_part = latest_file.stem.split("_")[-1]
            if len(date_part) == 8 and date_part.isdigit():
                return f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:]}"

    # 3. Secondary: Scanner canonical files
    scanner_dir = repo_root / "artifacts/scanner"
    if scanner_dir.exists():
        scan_files = sorted(scanner_dir.glob("pattern_a_universe_scan_*.csv"))
        if scan_files:
            latest_file = scan_files[-1]
            date_part = latest_file.stem.split("_")[-1]
            if len(date_part) == 8 and date_part.isdigit():
                return f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:]}"

    raise RuntimeError("Unable to resolve latest local reference market date: no local market reference data found.")


def _get_reference_market_month_ends(cache: ParquetCache, requested_as_of: pd.Timestamp) -> list[pd.Timestamp]:
    """Reference market stock (005930) 캐시로부터 표준 시장 월말 거래일 목록을 추출한다."""
    ref_daily = cache.load("005930")
    if ref_daily is not None and not ref_daily.empty:
        sliced = ref_daily.loc[ref_daily.index <= requested_as_of]
        if not sliced.empty:
            monthly_groups = sliced.groupby([sliced.index.year, sliced.index.month])
            return [group.index.max() for _, group in monthly_groups]
    return []


def _determine_flow_state_and_explanation(
    data_status: str,
    nb_1d: float | None,
    nb_5d: float | None,
    nb_20d: float | None,
    nb_60d: float | None,
    int_5d: float | None,
) -> tuple[FlowState, str]:
    if data_status == "DATA_UNAVAILABLE" or nb_5d is None or nb_20d is None or nb_60d is None:
        return (
            FlowState.FLOW_UNAVAILABLE,
            "외국인 수급 데이터가 준비되지 않아 수급 분석을 제공할 수 없습니다.",
        )

    int_str = f" (5일 순매수 강도: {int_5d * 100:+.2f}%)" if int_5d is not None else ""

    if nb_5d > 0 and nb_20d > 0 and nb_60d > 0:
        state = FlowState.FLOW_ACCUMULATION
        desc = (
            "최근 5일, 20일, 60일 모두 외국인 누적 순매수가 플러스를 유지하며 "
            f"중단기 전 구간에서 순매수 우위(매집) 기조입니다{int_str}."
        )
    elif nb_5d > 0 and nb_20d > 0 and nb_60d <= 0:
        state = FlowState.FLOW_RECENT_RECOVERY
        desc = (
            "최근 5일과 20일 외국인 수급은 순매수로 개선되었으나 60일 누적으로는 아직 순매도 상태로, "
            f"단기 수급 반등 및 회복 국면입니다{int_str}."
        )
    elif nb_5d < 0 and nb_20d > 0 and nb_60d > 0:
        state = FlowState.FLOW_RECENT_WEAKENING
        desc = (
            "20일 및 60일 누적 기준 외국인 순매수 기조는 유지되고 있으나, "
            f"최근 5일은 순매도로 전환되어 단기 수급이 다소 둔화된 상태입니다{int_str}."
        )
    elif nb_5d < 0 and nb_20d < 0 and nb_60d < 0:
        state = FlowState.FLOW_DISTRIBUTION
        desc = (
            "5일, 20일, 60일 모두 외국인 누적 순매도 상태로, "
            f"중단기 외국인 수급은 전반적인 매도 우위(이탈) 흐름입니다{int_str}."
        )
    else:
        state = FlowState.FLOW_MIXED
        desc = f"외국인 수급이 기간별로 엇갈리는 혼조세 흐름입니다{int_str}."

    return state, desc


def _determine_trading_value_state_and_explanation(
    tv_5d: float | None,
    tv_20d: float | None,
    tv_60d: float | None,
    r_5_20: float | None,
    r_20_60: float | None,
) -> tuple[TradingValueState, str]:
    if tv_5d is None or tv_20d is None or tv_60d is None or r_5_20 is None or r_20_60 is None:
        return (
            TradingValueState.TRADING_VALUE_UNAVAILABLE,
            "거래대금 시계열 데이터가 부족하여 분석을 제공할 수 없습니다 (5D/20D/60D 윈도우 필요).",
        )

    if tv_5d > tv_20d and tv_20d > tv_60d:
        state = TradingValueState.TRADING_VALUE_EXPANDING
        desc = (
            f"최근 거래대금이 지속 확대되는 흐름입니다. "
            f"5일 평균 거래대금({tv_5d:.2f}억원)은 20일 평균의 약 {r_5_20:.2f}배이며 60일 평균({tv_60d:.2f}억원)을 상회하고 있습니다."
        )
    elif tv_5d < tv_20d and tv_20d < tv_60d:
        state = TradingValueState.TRADING_VALUE_WEAKENING
        desc = (
            f"최근 거래대금이 지속 감소(둔화)하는 흐름입니다. "
            f"5일 평균 거래대금({tv_5d:.2f}억원)이 20일 평균({tv_20d:.2f}억원) 및 60일 평균({tv_60d:.2f}억원)을 밑돌고 있습니다."
        )
    elif abs(r_5_20 - 1.0) <= 0.1 and abs(r_20_60 - 1.0) <= 0.1:
        state = TradingValueState.TRADING_VALUE_STABLE
        desc = f"최근 거래대금이 급격한 변동 없이 일정 범위({tv_20d:.2f}억원 수준)를 안정적으로 유지하고 있습니다."
    else:
        state = TradingValueState.TRADING_VALUE_MIXED
        desc = (
            f"최근 거래대금이 특정 방향성 없이 기간별로 혼조세를 나타내고 있습니다. "
            f"(5일: {tv_5d:.2f}억원, 20일: {tv_20d:.2f}억원, 60일: {tv_60d:.2f}억원)"
        )

    return state, desc


def _generate_deterministic_narrative(
    ticker: str,
    name: str,
    current_snapshot: CurrentSnapshot,
    recent_12m: list[MonthlyObservation],
    flow_section: ForeignFlowSection,
    tv_section: TradingValueFlowSection,
) -> tuple[str, list[str], str]:
    if current_snapshot.investability_status == "INVESTABLE":
        headline = (
            f"{name}({ticker})는 현재 Pattern A {current_snapshot.official_stage} 단계이며 "
            f"투자 적격 상태는 INVESTABLE입니다."
        )
        inv_bullet = (
            f"시가총액 {current_snapshot.market_cap_eok:.1f}억원, 20일 평균 거래대금 {current_snapshot.avg_trading_value_20d_eok:.2f}억원으로 "
            f"Phase 10 Investability 기준을 충족합니다."
        )
        inv_clause = "Phase 10 Investability 조건(시총 1,000억 이상 및 20일 거래대금 3억 이상)을 충족(INVESTABLE)했습니다."
    elif current_snapshot.investability_status == "FILTERED_MARKET_CAP":
        mcap_str = f"{current_snapshot.market_cap_eok:.1f}억원" if current_snapshot.market_cap_eok is not None else "N/A"
        headline = (
            f"{name}({ticker})는 현재 Pattern A {current_snapshot.official_stage} 단계이나, "
            f"시가총액 기준 미달(FILTERED_MARKET_CAP)로 투자 대상에서 제외되었습니다."
        )
        inv_bullet = (
            f"시가총액 {mcap_str}(기준 1,000억원 미달)으로 "
            f"Phase 10 Investability 시가총액 요건을 충족하지 못했습니다."
        )
        inv_clause = f"시가총액 기준 미달(FILTERED_MARKET_CAP, {mcap_str} < 1,000억원)로 투자 대상에서 제외되었습니다."
    elif current_snapshot.investability_status == "FILTERED_LIQUIDITY":
        tv_str = f"{current_snapshot.avg_trading_value_20d_eok:.2f}억원" if current_snapshot.avg_trading_value_20d_eok is not None else "N/A"
        headline = (
            f"{name}({ticker})는 현재 Pattern A {current_snapshot.official_stage} 단계이나, "
            f"20일 평균 거래대금 기준 미달(FILTERED_LIQUIDITY)로 투자 대상에서 제외되었습니다."
        )
        inv_bullet = (
            f"20일 평균 거래대금 {tv_str}(기준 3.0억원 미달)으로 "
            f"Phase 10 Investability 유동성 요건을 충족하지 못했습니다."
        )
        inv_clause = f"20일 평균 거래대금 기준 미달(FILTERED_LIQUIDITY, {tv_str} < 3.0억원)로 투자 대상에서 제외되었습니다."
    else:  # DATA_UNAVAILABLE
        headline = (
            f"{name}({ticker})는 현재 Pattern A {current_snapshot.official_stage} 단계이며, "
            f"필수 데이터 부족(DATA_UNAVAILABLE)으로 투자 적격성을 판정할 수 없습니다."
        )
        inv_bullet = f"필수 데이터 부족({current_snapshot.investability_reason})으로 Phase 10 Investability 판정이 불가능합니다."
        inv_clause = f"필수 데이터 부족({current_snapshot.investability_reason})으로 투자 적격성 판정이 보류되었습니다."

    score_bullet = (
        f"현재 Pattern A Score는 {current_snapshot.pattern_a_score:.2f}점(Stage: {current_snapshot.official_stage}, Candidate: {'YES' if current_snapshot.is_candidate else 'NO'})입니다."
        if current_snapshot.pattern_a_score is not None
        else f"현재 Pattern A Score는 산출 불가(Stage: {current_snapshot.official_stage}) 상태입니다."
    )

    bullet_points = [
        score_bullet,
        inv_bullet,
        f"외국인 수급: {flow_section.explanation}",
        f"거래대금 추세: {tv_section.explanation}",
    ]

    valid_recent = [obs for obs in recent_12m if obs.data_available and obs.stage != "UNAVAILABLE"]
    if len(valid_recent) >= 2:
        first_stage = valid_recent[0].stage
        last_stage = valid_recent[-1].stage
        first_score = f"{valid_recent[0].score:.2f}" if valid_recent[0].score is not None else "N/A"
        last_score = f"{valid_recent[-1].score:.2f}" if valid_recent[-1].score is not None else "N/A"
        traj_sentence = (
            f"최근 12개월 동안 {first_stage}({first_score}점)에서 {last_stage}({last_score}점)로 국면 이동이 관찰되었습니다."
        )
    else:
        traj_sentence = "최근 12개월 이력 중 유효한 기술적 국면 관측치가 제한적입니다."

    if current_snapshot.pattern_a_score is not None:
        combined_narrative = (
            f"현재 {name}은(는) Pattern A Score {current_snapshot.pattern_a_score:.2f}점, {current_snapshot.official_stage} 단계이며 "
            f"{inv_clause} {traj_sentence} "
            f"외국인 수급은 {flow_section.flow_state.value} 상태로, {flow_section.explanation} "
            f"거래대금은 {tv_section.trading_value_state.value} 상태로, {tv_section.explanation}"
        )
    else:
        combined_narrative = f"{headline} {traj_sentence}"

    return headline, bullet_points, combined_narrative


def render_markdown_report(report: StockReport) -> str:
    """StockReport JSON 객체를 사람이 읽기 쉬운 GitHub Flavored Markdown 보고서로 렌더링한다."""
    cur = report.current_snapshot
    hist = report.monthly_history
    flow = report.foreign_flow
    tv = report.trading_value_flow
    dq = report.data_quality
    prov = report.provenance

    md = []
    md.append(f"# [{report.name} ({report.ticker})] 종목 리포트 v{report.report_version}")
    md.append("")
    md.append(f"- **시장 구분**: `{report.market}`")
    md.append(f"- **분석 기준일 (Requested As-Of)**: `{report.requested_as_of}`")
    md.append(f"- **신선도 기준일 (Reference Market Date)**: `{report.reference_market_date}`")
    md.append(f"- **리포트 상태**: `{report.header.report_status.value}`")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 0. 핵심 요약 (Executive Summary)")
    md.append(f"> **{report.summary.headline}**")
    md.append(">")
    for bp in report.summary.bullet_points:
        md.append(f"> - {bp}")
    md.append("")
    md.append(f"{report.summary.combined_narrative}")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 1. 현재 기술적 국면 & 투자 적격성 스냅샷 (Current Snapshot)")
    md.append(f"- **Pattern A Score**: `{cur.pattern_a_score:.2f}`" if cur.pattern_a_score is not None else "- **Pattern A Score**: `N/A`")
    md.append(f"- **공식 국면 (Official Stage)**: `{cur.official_stage}`")
    md.append(f"- **Candidate 판정**: `{'YES (CANDIDATE)' if cur.is_candidate else 'NO (' + cur.candidate_state + ')'}`")
    md.append(f"- **시가총액**: `{cur.market_cap_eok:.2f}억원`" if cur.market_cap_eok is not None else "- **시가총액**: `N/A`")
    md.append(f"- **20일 평균 거래대금**: `{cur.avg_trading_value_20d_eok:.2f}억원`" if cur.avg_trading_value_20d_eok is not None else "- **20일 평균 거래대금**: `N/A`")
    md.append(f"- **Investability 상태**: `{cur.investability_status}` (사유: `{cur.investability_reason}`)")
    md.append(f"- **최종 투자 가능 여부 (Is Investable)**: `{'YES' if cur.is_investable else 'NO'}`")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 2. 최근 12개월 월별 추이 (Recent 12M Trajectory)")
    md.append("")
    md.append("| 기준일 | 종가 | Pattern A Score | Stage | Candidate State | Data Available |")
    md.append("|---|---:|---:|---|---|---|")
    for obs in hist.recent_12m_history:
        cl_str = f"{int(round(obs.close)):,}" if obs.close is not None else "N/A"
        sc_str = f"{obs.score:.2f}" if obs.score is not None else "N/A"
        md.append(f"| {obs.as_of} | {cl_str} | {sc_str} | {obs.stage} | {obs.candidate_state} | {str(obs.data_available)} |")
    md.append("")
    if hist.score_trend.current_score is not None:
        st = hist.score_trend
        c1 = f"{st.change_1m:+.2f}" if st.change_1m is not None else "N/A"
        c3 = f"{st.change_3m:+.2f}" if st.change_3m is not None else "N/A"
        c6 = f"{st.change_6m:+.2f}" if st.change_6m is not None else "N/A"
        c12 = f"{st.change_12m:+.2f}" if st.change_12m is not None else "N/A"
        md.append(f"- **점수 변화 모멘텀**: 1M ({c1}), 3M ({c3}), 6M ({c6}), 12M ({c12})")
        md.append("")
    md.append("---")
    md.append("")
    md.append("## 3. 국면 전환 이력 (Stage Transition History)")
    if hist.stage_transitions:
        for tr in hist.stage_transitions:
            md.append(f"- **{tr.as_of}**: `{tr.from_stage}` -> `{tr.to_stage}`")
    else:
        md.append("- 기록된 국면 전환 이력이 없습니다 (동일 국면 유지).")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 4. 외국인 수급 확증 (Foreign Flow Analysis - Phase 11)")
    md.append(f"- **수급 데이터 상태**: `{flow.data_status}`")
    md.append(f"- **수급 국면 판정**: `{flow.flow_state.value}`")
    md.append(f"- **규칙 기반 해석**: {flow.explanation}")
    md.append("")
    if flow.foreign_net_buy_value_5d_krw is not None:
        nb1 = f"{flow.foreign_net_buy_value_1d_krw / 1e8:+.2f}억원" if flow.foreign_net_buy_value_1d_krw is not None else "N/A"
        nb5 = f"{flow.foreign_net_buy_value_5d_krw / 1e8:+.2f}억원"
        nb20 = f"{flow.foreign_net_buy_value_20d_krw / 1e8:+.2f}억원" if flow.foreign_net_buy_value_20d_krw is not None else "N/A"
        nb60 = f"{flow.foreign_net_buy_value_60d_krw / 1e8:+.2f}억원" if flow.foreign_net_buy_value_60d_krw is not None else "N/A"
        i5 = f"{flow.foreign_flow_intensity_5d * 100:+.2f}%" if flow.foreign_flow_intensity_5d is not None else "N/A"
        i20 = f"{flow.foreign_flow_intensity_20d * 100:+.2f}%" if flow.foreign_flow_intensity_20d is not None else "N/A"
        i60 = f"{flow.foreign_flow_intensity_60d * 100:+.2f}%" if flow.foreign_flow_intensity_60d is not None else "N/A"
        p5 = f"{flow.foreign_positive_days_5d} / 5" if flow.foreign_positive_days_5d is not None else "N/A"
        p20 = f"{flow.foreign_positive_days_20d} / 20" if flow.foreign_positive_days_20d is not None else "N/A"
        p60 = f"{flow.foreign_positive_days_60d} / 60" if flow.foreign_positive_days_60d is not None else "N/A"
        md.append("| 구간 | 순매수 금액 | 거래대금 대비 강도 | 양수 거래일 |")
        md.append("|---|---:|---:|---:|")
        md.append(f"| 1D | {nb1} | N/A | N/A |")
        md.append(f"| 5D | {nb5} | {i5} | {p5} |")
        md.append(f"| 20D | {nb20} | {i20} | {p20} |")
        md.append(f"| 60D | {nb60} | {i60} | {p60} |")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 5. 거래대금 추세 분석 (Trading Value Flow)")
    md.append(f"- **거래대금 상태**: `{tv.trading_value_state.value}`")
    md.append(f"- **규칙 기반 해석**: {tv.explanation}")
    if tv.avg_trading_value_5d_eok is not None:
        md.append(f"- **5일 평균 거래대금**: `{tv.avg_trading_value_5d_eok:.2f}억원`")
        md.append(f"- **20일 평균 거래대금**: `{tv.avg_trading_value_20d_eok:.2f}억원`" if tv.avg_trading_value_20d_eok is not None else "- **20일 평균 거래대금**: `N/A`")
        md.append(f"- **60일 평균 거래대금**: `{tv.avg_trading_value_60d_eok:.2f}억원`" if tv.avg_trading_value_60d_eok is not None else "- **60일 평균 거래대금**: `N/A`")
        r5_20 = f"{tv.ratio_5d_to_20d:.2f}배" if tv.ratio_5d_to_20d is not None else "N/A"
        r20_60 = f"{tv.ratio_20d_to_60d:.2f}배" if tv.ratio_20d_to_60d is not None else "N/A"
        md.append(f"- **단기 확장 비율 (5D / 20D)**: `{r5_20}`")
        md.append(f"- **중기 확장 비율 (20D / 60D)**: `{r20_60}`")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 6. 전체 월별 이력 (Full Monthly History)")
    md.append(f"- **전체 관측 시작월**: `{hist.history_start_as_of}`")
    md.append(f"- **전체 관측 종료월**: `{hist.history_end_as_of}`")
    md.append(f"- **최초 Pattern A 산출월**: `{hist.first_pattern_a_available_as_of}`")
    md.append(f"- **총 월별 관측 개수**: `{hist.observation_count}개월` (Pattern A 산출 가능: `{hist.pattern_a_available_observation_count}개월`)")
    md.append("")
    md.append("| 기준일 | 종가 | Pattern A Score | Stage | Candidate State | Data Available | Reason |")
    md.append("|---|---:|---:|---|---|---|---|")
    for obs in hist.full_monthly_history:
        cl_str = f"{int(round(obs.close)):,}" if obs.close is not None else "N/A"
        sc_str = f"{obs.score:.2f}" if obs.score is not None else "N/A"
        r_str = str(obs.reason) if obs.reason is not None else "-"
        md.append(f"| {obs.as_of} | {cl_str} | {sc_str} | {obs.stage} | {obs.candidate_state} | {str(obs.data_available)} | {r_str} |")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 7. 데이터 품질 및 신원 (Data Quality & Provenance)")
    md.append(f"- **로컬 일봉 캐시**: `{'정상 로드 (' + str(dq.daily_rows_count) + '행)' if dq.cache_present else '부재 (MISSING)'}`")
    md.append(f"- **데이터 기간**: `{dq.cache_first_date}` ~ `{dq.cache_last_date}`")
    md.append(f"- **완성 월봉 수**: `{dq.completed_month_count}개월`")
    md.append(f"- **데이터 품질 상태**: `{dq.quality_status}`")
    md.append(f"- **적용 계약**: Score(`{prov.score_contract}`), Stage(`{prov.stage_contract}`), Investability(`{prov.investability_contract}`), Flow(`{prov.foreign_flow_contract}`)")
    md.append(f"- **외부 네트워크 요청**: `{prov.network_requests}회` (Zero Network Request)")
    md.append("")
    md.append("---")
    md.append("")
    md.append("*주의 (Disclaimer): 본 리포트는 기술적 지표 및 과거 수급/유동성 통계에 기반한 설명 자료이며, 매수/매도 추천이나 목표가를 제시하지 않습니다.*")
    md.append("")

    return "\n".join(md)


def generate_stock_report(
    ticker: str,
    as_of: str | pd.Timestamp | None = None,
    repo_root: Path | str | None = None,
    save_artifacts: bool = True,
    output_dir: Path | str | None = None,
) -> tuple[StockReport, Path | None, Path | None]:
    """단일 종목의 Stock Report v0.1을 생성하고 선택적으로 JSON/MD 아티팩트를 저장한다."""
    root_path = Path(repo_root) if repo_root else Path(__file__).resolve().parent.parent.parent.parent
    clean_ticker = _format_ticker(ticker)

    # 1. As-Of 및 Reference Market Date 결정 (No hardcoded date fallback)
    if as_of is None:
        canonical_as_of = _resolve_latest_local_as_of(root_path)
    else:
        canonical_as_of = str(as_of).strip()[:10]

    req_as_of_ts = pd.Timestamp(canonical_as_of)
    ref_market_date = canonical_as_of

    # 2. 로컬 Universe 및 종목 메타데이터 로드
    cache = ParquetCache(base_dir=root_path / "data/raw/stocks")
    daily = cache.load(clean_ticker)
    has_cache = daily is not None and not daily.empty

    # Universe meta search
    name = clean_ticker
    market = "UNKNOWN"
    univ_csv = root_path / "artifacts/investability" / f"pattern_a_investability_universe_{canonical_as_of.replace('-', '')}.csv"
    if univ_csv.exists():
        try:
            df_univ = pd.read_csv(univ_csv)
            df_univ["ticker"] = df_univ["ticker"].astype(str).str.zfill(6)
            match = df_univ[df_univ["ticker"] == clean_ticker]
            if not match.empty:
                name = str(match["name"].iloc[0])
                market = str(match["market"].iloc[0]).upper()
        except Exception as exc:
            logger.warning("Failed loading universe csv %s: %s", univ_csv, exc)

    # 3. Daily Slice 생성 (Lookahead 방지)
    if has_cache and daily is not None:
        daily_slice = daily.loc[daily.index <= req_as_of_ts].copy()
        cache_first_str = daily.index.min().strftime("%Y-%m-%d") if not daily.empty else None
        cache_last_str = daily.index.max().strftime("%Y-%m-%d") if not daily.empty else None
        daily_rows_count = len(daily)
    else:
        daily_slice = pd.DataFrame()
        cache_first_str = None
        cache_last_str = None
        daily_rows_count = 0

    # 4. Investability & Market Cap Snapshot 로드
    mcap_val = None
    mcap_eff_date = None
    mcap_csv = root_path / "artifacts/investability/source" / f"krx_market_cap_{canonical_as_of.replace('-', '')}.csv"
    if mcap_csv.exists():
        try:
            df_mcap_snap = pd.read_csv(mcap_csv, dtype={"ticker": str})
            df_mcap_snap["ticker"] = df_mcap_snap["ticker"].astype(str).str.zfill(6)
            match_mcap = df_mcap_snap[df_mcap_snap["ticker"] == clean_ticker]
            if not match_mcap.empty:
                mcap_val = float(match_mcap["market_cap"].iloc[0])
                mcap_eff_date = str(match_mcap["effective_date"].iloc[0]) if "effective_date" in match_mcap.columns else canonical_as_of
        except Exception as exc:
            logger.warning("Failed reading local market cap file %s: %s", mcap_csv, exc)

    inv_eval = evaluate_investability(
        ticker=clean_ticker,
        as_of=req_as_of_ts,
        daily=daily_slice if not daily_slice.empty else None,
        market_cap=mcap_val,
        market_cap_effective_date=mcap_eff_date,
    )

    # 5. Current Pattern A Snapshot
    if not daily_slice.empty:
        try:
            cur_snap = build_historical_snapshot(
                ticker=clean_ticker,
                name=name,
                daily=daily_slice,
                snapshot_date=canonical_as_of,
                include_incomplete_periods=False,
            )
            cur_eval = evaluate_pattern_a(cur_snap)
            cur_score = round(cur_eval.score, 2) if cur_eval.score is not None else None
            cur_stage = cur_eval.lifecycle_stage.value.upper() if cur_eval.lifecycle_stage is not None else "UNAVAILABLE"
            cur_cand_state = cur_eval.candidate_state.value.lower() if cur_eval.candidate_state is not None else "insufficient_data"
            cur_is_candidate = cur_eval.candidate_state == PatternACandidateState.CANDIDATE
            completed_months = len(cur_snap.monthly) if cur_snap.monthly is not None else 0
            quality_status = "OK" if cur_score is not None else "INSUFFICIENT_LOOKBACK"
        except Exception as exc:
            logger.warning("Evaluation error for %s: %s", clean_ticker, exc)
            cur_score = None
            cur_stage = "UNAVAILABLE"
            cur_cand_state = "insufficient_data"
            cur_is_candidate = False
            completed_months = 0
            quality_status = "EVALUATION_ERROR"
    else:
        cur_score = None
        cur_stage = "UNAVAILABLE"
        cur_cand_state = "insufficient_data"
        cur_is_candidate = False
        completed_months = 0
        quality_status = "MISSING_CACHE"

    current_snapshot = CurrentSnapshot(
        pattern_a_score=cur_score,
        official_stage=cur_stage,
        candidate_state=cur_cand_state,
        is_candidate=cur_is_candidate,
        market_cap_eok=round(inv_eval.market_cap_eok, 2) if inv_eval.market_cap_eok is not None else None,
        avg_trading_value_20d_eok=round(inv_eval.avg_trading_value_20d_eok, 2) if inv_eval.avg_trading_value_20d_eok is not None else None,
        investability_status=inv_eval.status.value,
        investability_reason=inv_eval.reason,
        is_investable=inv_eval.status.value == "INVESTABLE",
    )

    # 6. Monthly Score & Stage History (Full & Recent 12M) using Common Market Reference Calendar & Exact Daily Check
    full_monthly_history: list[MonthlyObservation] = []
    if not daily_slice.empty:
        stock_first_date = daily_slice.index.min()
        market_month_ends = _get_reference_market_month_ends(cache, req_as_of_ts)

        if not market_month_ends:
            # Common market calendar unavailable -> Fail closed (No fallback to target stock's own calendar)
            quality_status = "MARKET_CALENDAR_UNAVAILABLE"
        else:
            first_month_start = pd.Timestamp(stock_first_date.year, stock_first_date.month, 1)
            stock_month_ends = [me for me in market_month_ends if me >= first_month_start]

            for me_date in stock_month_ends:
                me_str = me_date.strftime("%Y-%m-%d")

                # Exact daily observation check: stock MUST have traded on that exact market trading date
                if me_date not in daily_slice.index:
                    full_monthly_history.append(
                        MonthlyObservation(
                            as_of=me_str,
                            close=None,
                            score=None,
                            stage="UNAVAILABLE",
                            candidate_state="insufficient_data",
                            data_available=False,
                            reason="NO_EXACT_MARKET_MONTH_END_OBSERVATION",
                        )
                    )
                    continue

                exact_close = float(daily_slice.loc[me_date, "close"]) if "close" in daily_slice.columns and not pd.isna(daily_slice.loc[me_date, "close"]) else None

                d_sub = daily_slice.loc[daily_slice.index <= me_date]
                try:
                    sub_snap = build_historical_snapshot(
                        ticker=clean_ticker,
                        name=name,
                        daily=d_sub,
                        snapshot_date=me_str,
                        include_incomplete_periods=False,
                    )
                    sub_eval = evaluate_pattern_a(sub_snap)
                    s_val = round(sub_eval.score, 2) if sub_eval.score is not None else None
                    st_val = sub_eval.lifecycle_stage.value.upper() if sub_eval.lifecycle_stage is not None else "UNAVAILABLE"
                    c_val = sub_eval.candidate_state.value.lower() if sub_eval.candidate_state is not None else "insufficient_data"
                    d_avail = s_val is not None
                    r_val = None if d_avail else "INSUFFICIENT_LOOKBACK"
                except Exception as exc:
                    s_val = None
                    st_val = "UNAVAILABLE"
                    c_val = "insufficient_data"
                    d_avail = False
                    r_val = str(exc)

                full_monthly_history.append(
                    MonthlyObservation(
                        as_of=me_str,
                        close=exact_close,
                        score=s_val,
                        stage=st_val,
                        candidate_state=c_val,
                        data_available=d_avail,
                        reason=r_val,
                    )
                )

    # Sort strictly ascending
    full_monthly_history.sort(key=lambda x: x.as_of)
    recent_12m_history = full_monthly_history[-13:] if len(full_monthly_history) >= 13 else list(full_monthly_history)

    # Stage Transitions (Protected from interim UNAVAILABLE observation noise)
    stage_transitions: list[StageTransition] = []
    last_valid_stage: str | None = None
    for obs in full_monthly_history:
        st = obs.stage
        if st == "UNAVAILABLE":
            continue
        if last_valid_stage is None:
            stage_transitions.append(StageTransition(as_of=obs.as_of, from_stage="UNAVAILABLE", to_stage=st))
            last_valid_stage = st
        elif st != last_valid_stage:
            stage_transitions.append(StageTransition(as_of=obs.as_of, from_stage=last_valid_stage, to_stage=st))
            last_valid_stage = st

    # Score Trend Deltas (from recent observations)
    score_1m = None
    score_3m = None
    score_6m = None
    score_12m = None
    if len(full_monthly_history) >= 2:
        score_1m = full_monthly_history[-2].score
    if len(full_monthly_history) >= 4:
        score_3m = full_monthly_history[-4].score
    if len(full_monthly_history) >= 7:
        score_6m = full_monthly_history[-7].score
    if len(full_monthly_history) >= 13:
        score_12m = full_monthly_history[-13].score

    change_1m = round(cur_score - score_1m, 2) if (cur_score is not None and score_1m is not None) else None
    change_3m = round(cur_score - score_3m, 2) if (cur_score is not None and score_3m is not None) else None
    change_6m = round(cur_score - score_6m, 2) if (cur_score is not None and score_6m is not None) else None
    change_12m = round(cur_score - score_12m, 2) if (cur_score is not None and score_12m is not None) else None

    score_trend = ScoreTrend(
        current_score=cur_score,
        score_1m_ago=score_1m,
        score_3m_ago=score_3m,
        score_6m_ago=score_6m,
        score_12m_ago=score_12m,
        change_1m=change_1m,
        change_3m=change_3m,
        change_6m=change_6m,
        change_12m=change_12m,
    )

    pattern_a_available_obs = [obs for obs in full_monthly_history if obs.score is not None]
    first_pattern_a_avail_as_of = pattern_a_available_obs[0].as_of if pattern_a_available_obs else None
    pattern_a_available_count = len(pattern_a_available_obs)

    monthly_section = MonthlyHistorySection(
        history_start_as_of=full_monthly_history[0].as_of if full_monthly_history else None,
        history_end_as_of=full_monthly_history[-1].as_of if full_monthly_history else None,
        observation_count=len(full_monthly_history),
        recent_12m_observation_count=len(recent_12m_history),
        score_trend=score_trend,
        stage_transitions=stage_transitions,
        recent_12m_history=recent_12m_history,
        full_monthly_history=full_monthly_history,
        first_pattern_a_available_as_of=first_pattern_a_avail_as_of,
        pattern_a_available_observation_count=pattern_a_available_count,
    )

    # 7. Foreign Flow Section (Phase 11)
    flow_df_loaded = None
    flow_file = root_path / "artifacts/flow/source" / f"foreign_flow_daily_{canonical_as_of.replace('-', '')}.parquet"
    if not flow_file.exists():
        flow_file = root_path / "artifacts/flow/source" / f"foreign_flow_daily_{canonical_as_of.replace('-', '')}.csv"

    if flow_file.exists():
        try:
            flow_df_loaded = pd.read_parquet(flow_file) if str(flow_file).endswith(".parquet") else pd.read_csv(flow_file)
        except Exception as exc:
            logger.warning("Failed loading flow file: %s", exc)

    flow_feat: ForeignFlowFeatureResult = compute_foreign_flow_features(
        ticker=clean_ticker,
        as_of=canonical_as_of,
        flow_df=flow_df_loaded,
        price_df=daily_slice if not daily_slice.empty else None,
    )

    flow_state, flow_explanation = _determine_flow_state_and_explanation(
        data_status=flow_feat.data_status.value,
        nb_1d=flow_feat.foreign_net_buy_value_1d,
        nb_5d=flow_feat.foreign_net_buy_value_5d,
        nb_20d=flow_feat.foreign_net_buy_value_20d,
        nb_60d=flow_feat.foreign_net_buy_value_60d,
        int_5d=flow_feat.foreign_flow_intensity_5d,
    )

    foreign_flow_section = ForeignFlowSection(
        data_status=flow_feat.data_status.value,
        flow_state=flow_state,
        explanation=flow_explanation,
        foreign_net_buy_value_1d_krw=flow_feat.foreign_net_buy_value_1d,
        foreign_net_buy_value_5d_krw=flow_feat.foreign_net_buy_value_5d,
        foreign_net_buy_value_20d_krw=flow_feat.foreign_net_buy_value_20d,
        foreign_net_buy_value_60d_krw=flow_feat.foreign_net_buy_value_60d,
        foreign_flow_intensity_5d=round(flow_feat.foreign_flow_intensity_5d, 4) if flow_feat.foreign_flow_intensity_5d is not None else None,
        foreign_flow_intensity_20d=round(flow_feat.foreign_flow_intensity_20d, 4) if flow_feat.foreign_flow_intensity_20d is not None else None,
        foreign_flow_intensity_60d=round(flow_feat.foreign_flow_intensity_60d, 4) if flow_feat.foreign_flow_intensity_60d is not None else None,
        foreign_positive_days_5d=flow_feat.foreign_positive_days_5d,
        foreign_positive_days_20d=flow_feat.foreign_positive_days_20d,
        foreign_positive_days_60d=flow_feat.foreign_positive_days_60d,
    )

    # 8. Trading Value Flow Section (Strict Window Fail-Closed)
    tv_5d_val: float | None = None
    tv_20d_val: float | None = None
    tv_60d_val: float | None = None
    r_5_20: float | None = None
    r_20_60: float | None = None

    if not daily_slice.empty and "trading_value" in daily_slice.columns:
        valid_tv = daily_slice["trading_value"].dropna()
        n_obs = len(valid_tv)
        if n_obs >= 5:
            tv_5d_val = float(valid_tv.tail(5).mean() / 1e8)
        if n_obs >= 20:
            tv_20d_val = float(valid_tv.tail(20).mean() / 1e8)
        if n_obs >= 60:
            tv_60d_val = float(valid_tv.tail(60).mean() / 1e8)

        if tv_5d_val is not None and tv_20d_val is not None and tv_20d_val > 0:
            r_5_20 = round(tv_5d_val / tv_20d_val, 2)
        if tv_20d_val is not None and tv_60d_val is not None and tv_60d_val > 0:
            r_20_60 = round(tv_20d_val / tv_60d_val, 2)

    tv_state, tv_explanation = _determine_trading_value_state_and_explanation(
        tv_5d=tv_5d_val,
        tv_20d=tv_20d_val,
        tv_60d=tv_60d_val,
        r_5_20=r_5_20,
        r_20_60=r_20_60,
    )

    trading_value_section = TradingValueFlowSection(
        trading_value_state=tv_state,
        explanation=tv_explanation,
        avg_trading_value_5d_eok=round(tv_5d_val, 2) if tv_5d_val is not None else None,
        avg_trading_value_20d_eok=round(tv_20d_val, 2) if tv_20d_val is not None else None,
        avg_trading_value_60d_eok=round(tv_60d_val, 2) if tv_60d_val is not None else None,
        ratio_5d_to_20d=r_5_20,
        ratio_20d_to_60d=r_20_60,
    )

    # 9. Header & Summary (Consistent Exact Report Status Semantics)
    # READY:
    #   Pattern A core Score/Stage READY
    #   AND Market Calendar READY (quality_status != "MARKET_CALENDAR_UNAVAILABLE")
    #   AND Investability status != "DATA_UNAVAILABLE" (FILTERED is allowed)
    #   AND Foreign Flow status == READY
    #   AND Trading Value state != TRADING_VALUE_UNAVAILABLE
    # PARTIAL:
    #   Pattern A core is READY, but at least one of (Market Calendar unavailable, Investability DATA_UNAVAILABLE, Flow unavailable, TV unavailable)
    # DATA_UNAVAILABLE:
    #   Pattern A core is UNAVAILABLE
    if (
        cur_score is not None
        and quality_status != "MARKET_CALENDAR_UNAVAILABLE"
        and inv_eval.status.value != "DATA_UNAVAILABLE"
        and flow_feat.data_status == FlowDataStatus.READY
        and tv_state != TradingValueState.TRADING_VALUE_UNAVAILABLE
    ):
        rep_status = ReportStatus.READY
    elif cur_score is not None:
        rep_status = ReportStatus.PARTIAL
    else:
        rep_status = ReportStatus.DATA_UNAVAILABLE

    header = ReportHeader(
        ticker=clean_ticker,
        name=name,
        market=market,
        requested_as_of=canonical_as_of,
        reference_market_date=ref_market_date,
        effective_as_of=daily_slice.index.max().strftime("%Y-%m-%d") if not daily_slice.empty else None,
        cache_present=has_cache,
        cache_last_date=cache_last_str,
        report_status=rep_status,
    )

    headline, bullet_points, narrative = _generate_deterministic_narrative(
        ticker=clean_ticker,
        name=name,
        current_snapshot=current_snapshot,
        recent_12m=recent_12m_history,
        flow_section=foreign_flow_section,
        tv_section=trading_value_section,
    )

    summary = ReportSummary(
        headline=headline,
        bullet_points=bullet_points,
        combined_narrative=narrative,
    )

    data_quality = DataQualitySection(
        cache_present=has_cache,
        cache_first_date=cache_first_str,
        cache_last_date=cache_last_str,
        daily_rows_count=daily_rows_count,
        completed_month_count=completed_months,
        quality_status=quality_status,
        quality_flags=[],
    )

    provenance = ProvenanceSection(
        stock_price_source="local parquet cache",
        score_contract="pattern_a_score_v0.2",
        stage_contract="pattern_a_stage_v0.1",
        investability_contract="phase10",
        foreign_flow_contract="phase11",
        network_requests=0,
    )

    report = StockReport(
        report_version="0.1",
        ticker=clean_ticker,
        name=name,
        market=market,
        requested_as_of=canonical_as_of,
        reference_market_date=ref_market_date,
        header=header,
        summary=summary,
        current_snapshot=current_snapshot,
        monthly_history=monthly_section,
        foreign_flow=foreign_flow_section,
        trading_value_flow=trading_value_section,
        data_quality=data_quality,
        provenance=provenance,
    )

    # 10. Save Artifacts if requested
    json_path: Path | None = None
    md_path: Path | None = None
    if save_artifacts:
        date_dir_name = canonical_as_of.replace("-", "")
        base_out = Path(output_dir) if output_dir else root_path / "artifacts/stock_reports" / date_dir_name
        base_out.mkdir(parents=True, exist_ok=True)

        json_path = base_out / f"{clean_ticker}.json"
        md_path = base_out / f"{clean_ticker}.md"

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)

        md_content = render_markdown_report(report)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

    return report, json_path, md_path


def main() -> None:
    """CLI entrypoint for stock report generation."""
    parser = argparse.ArgumentParser(description="Generate Local Stock Report (Contract v0.1)")
    parser.add_argument("--ticker", required=True, help="6-digit stock ticker (e.g. 001540)")
    parser.add_argument("--as-of", default=None, help="As-Of date YYYY-MM-DD (defaults to latest local available date)")
    parser.add_argument("--output-dir", default=None, help="Custom output directory")
    args = parser.parse_args()

    report, j_path, m_path = generate_stock_report(
        ticker=args.ticker,
        as_of=args.as_of,
        output_dir=args.output_dir,
    )

    print(f"Successfully generated stock report for {report.name} ({report.ticker})!")
    print(f"JSON Report: {j_path}")
    print(f"Markdown Report: {m_path}")
    print("-" * 50)
    print(report.summary.combined_narrative)


if __name__ == "__main__":
    main()
