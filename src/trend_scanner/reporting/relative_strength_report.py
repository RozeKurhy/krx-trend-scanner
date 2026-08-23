"""Local exact-date consumer for the Phase 12 Market RS authority snapshot."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pandas as pd

from trend_scanner.reporting.models import RelativeStrengthSection


PHASE12_CLOSURE_SHA = "5fdf97793c1fd7683c33d5fe77ff4da97fc75a19"
RS_ARTIFACT_TEMPLATE = (
    "artifacts/patterns/pattern_a/validation/relative_strength/"
    "market_completion_v01/market_rs_universe_{date}.csv"
)
COMMON_MARKETS = {"KOSPI", "KOSDAQ"}
RS_FIELDS = (
    "market_rs_3m",
    "market_rs_6m",
    "market_rs_12m",
    "market_rs_delta_3m_vs_6m",
    "market_rs_delta_6m_vs_12m",
    "market_rs_acceleration_3_6_12m",
    "all_market_rs_rank_3m",
    "all_market_rs_rank_6m",
    "all_market_rs_rank_12m",
    "all_market_rs_percentile_3m",
    "all_market_rs_percentile_6m",
    "all_market_rs_percentile_12m",
)


def _clean_as_of(value: str) -> str:
    clean = str(value).strip()[:10].replace("/", "-")
    timestamp = pd.Timestamp(clean)
    return timestamp.strftime("%Y-%m-%d")


def _source_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _none_if_missing(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    return value


def _as_float(value: Any) -> float | None:
    value = _none_if_missing(value)
    if value is None:
        return None
    return float(value)


def _as_str(value: Any) -> str | None:
    value = _none_if_missing(value)
    return None if value is None else str(value)


def _narrative(row: dict[str, Any]) -> str:
    rs_3m = _as_float(row.get("market_rs_3m"))
    rs_6m = _as_float(row.get("market_rs_6m"))
    rs_12m = _as_float(row.get("market_rs_12m"))

    if rs_3m is None or rs_6m is None or rs_12m is None:
        return "일부 기간의 시장 상대강도 데이터가 없어 전체 기간 흐름은 제한적으로 해석됩니다."
    if rs_12m < 0 and rs_6m > rs_12m and rs_3m > rs_6m:
        return (
            "12개월 기준으로는 시장 대비 약세였으나 6개월, 3개월로 갈수록 "
            "상대강도가 연속 개선되며 최근 시장 대비 강도가 뚜렷하게 회복되고 있습니다."
        )
    if rs_3m > rs_6m > rs_12m:
        return "최근으로 갈수록 시장 대비 상대강도가 개선되는 흐름입니다."
    if rs_3m < rs_6m < rs_12m:
        return "장기 대비 최근 시장 상대강도가 낮아지며 상대적인 주가 강도가 약화되는 흐름입니다."
    return "기간별 시장 상대강도가 엇갈리는 혼조 흐름입니다."


def _empty_section(
    applicability: str,
    data_status: str,
    explanation: str,
    source_as_of: str | None = None,
    source_artifact: str | None = None,
    source_sha256: str | None = None,
) -> RelativeStrengthSection:
    values = {field: None for field in RS_FIELDS}
    return RelativeStrengthSection(
        applicability=applicability,
        data_status=data_status,
        benchmark_name=None,
        benchmark_code=None,
        benchmark_last_observation_date=None,
        **values,
        market_anchor_date_3m=None,
        market_anchor_date_6m=None,
        market_anchor_date_12m=None,
        explanation=explanation,
        source_as_of=source_as_of,
        source_artifact=source_artifact,
        source_sha256=source_sha256,
        phase12_closure_sha=PHASE12_CLOSURE_SHA,
    )


def load_relative_strength_section(
    ticker: str,
    requested_as_of: str,
    asset_type: str,
    market: str,
    repo_root: Path,
) -> RelativeStrengthSection:
    """Load one ticker from the exact requested-date Phase 12 CSV only.

    This function intentionally does not import or execute the Full Universe
    Scanner and never falls back to another snapshot date.
    """

    clean_as_of = _clean_as_of(requested_as_of)
    relative_artifact = RS_ARTIFACT_TEMPLATE.format(date=clean_as_of.replace("-", ""))
    artifact_path = repo_root / relative_artifact
    if str(asset_type).upper() != "COMMON" or str(market).upper() not in COMMON_MARKETS:
        return _empty_section(
            applicability="NOT_APPLICABLE",
            data_status="NOT_EVALUATED",
            explanation=(
                "Phase12 Market RS는 KOSPI/KOSDAQ 보통주(COMMON)를 대상으로 정의되어 "
                "이 종목에는 적용되지 않습니다."
            ),
        )

    if not artifact_path.exists():
        return _empty_section(
            applicability="DATA_UNAVAILABLE",
            data_status="DATA_UNAVAILABLE",
            explanation=(
                "해당 기준일의 전체 시장 RS 기준 snapshot이 없어 "
                "시장 상대강도 백분위 분석을 제공할 수 없습니다."
            ),
        )

    source_sha = _source_sha256(artifact_path)
    try:
        # round_trip preserves the decimal representation emitted by the
        # Phase 12 CSV instead of pandas' default float shortening.
        frame = pd.read_csv(artifact_path, dtype={"ticker": str}, float_precision="round_trip")
        frame["ticker"] = frame["ticker"].astype(str).str.strip().str.zfill(6)
    except Exception:
        return _empty_section(
            applicability="DATA_UNAVAILABLE",
            data_status="DATA_UNAVAILABLE",
            explanation=(
                "해당 기준일의 전체 시장 RS 기준 snapshot을 읽을 수 없어 "
                "시장 상대강도 분석을 제공할 수 없습니다."
            ),
            source_as_of=clean_as_of,
            source_artifact=relative_artifact,
            source_sha256=source_sha,
        )

    matches = frame[frame["ticker"] == str(ticker).strip().zfill(6)]
    if matches.empty:
        return _empty_section(
            applicability="DATA_UNAVAILABLE",
            data_status="DATA_UNAVAILABLE",
            explanation=(
                "해당 기준일의 전체 시장 RS snapshot에 종목 row가 없어 "
                "시장 상대강도 분석을 제공할 수 없습니다."
            ),
            source_as_of=clean_as_of,
            source_artifact=relative_artifact,
            source_sha256=source_sha,
        )

    row = matches.iloc[0].to_dict()
    status = _as_str(row.get("market_rs_data_status")) or "DATA_UNAVAILABLE"
    values = {field: _as_float(row.get(field)) for field in RS_FIELDS}
    return RelativeStrengthSection(
        applicability="APPLICABLE",
        data_status=status,
        benchmark_name=_as_str(row.get("market_benchmark_name")),
        benchmark_code=(str(int(float(row["market_benchmark_code"]))) if _none_if_missing(row.get("market_benchmark_code")) is not None else None),
        benchmark_last_observation_date=_as_str(row.get("market_benchmark_last_observation_date")),
        **values,
        market_anchor_date_3m=_as_str(row.get("market_anchor_date_3m")),
        market_anchor_date_6m=_as_str(row.get("market_anchor_date_6m")),
        market_anchor_date_12m=_as_str(row.get("market_anchor_date_12m")),
        explanation=_narrative(row),
        source_as_of=clean_as_of,
        source_artifact=relative_artifact,
        source_sha256=source_sha,
        phase12_closure_sha=PHASE12_CLOSURE_SHA,
    )
