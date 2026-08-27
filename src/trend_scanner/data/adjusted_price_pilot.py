"""Adjusted Price Store Bounded Live Pilot (ADJUSTED_PRICE_STORE_BOUNDED_LIVE_PILOT_V01).

Validates PyKRX adjusted=True behavior against risk-stratified sample groups
derived from the frozen Historical Common Population Universe (3,162 identities).

Evaluates source capabilities without mutating or altering the frozen universe.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any, Mapping, Sequence

import pandas as pd

from trend_scanner.data.adjusted_price_provider import (
    ADJUSTED_OHLC_COLUMNS,
    _FORBIDDEN_OUTPUT_COLUMNS,
    _PYKRX_COLUMNS,
    _correct_minor_rounding_violations,
    _empty_adjusted_frame,
    _normalise_index,
    validate_adjusted_ohlc,
)
from trend_scanner.data.errors import MarketDataError
from trend_scanner.universe.survivorship_safe_denominator_freeze import (
    DEFAULT_POPULATION_ARTIFACT_PATH,
    EXPECTED_HISTORICAL_END,
    EXPECTED_HISTORICAL_START,
    load_historical_common_population,
    population_manifest_sha256,
)

EXPECTED_POPULATION_SHA256 = "f14c3d46e5305571b311c4d120d9a2f1eba1644e7f059cde4e59eabab42d1aff"
EXPECTED_POPULATION_COUNT = 3162


class PilotSampleGroup(str, Enum):
    GROUP_A_NUMERIC = "GROUP_A_NUMERIC"
    GROUP_B_HISTORICAL_DELISTED = "GROUP_B_HISTORICAL_DELISTED"
    GROUP_C_CORPORATE_ACTION = "GROUP_C_CORPORATE_ACTION"
    GROUP_D_ALPHA = "GROUP_D_ALPHA"
    GROUP_E_MARKET_TRANSFER = "GROUP_E_MARKET_TRANSFER"


class SourceEligibilityStatus(str, Enum):
    ELIGIBLE_FULL = "ELIGIBLE_FULL"
    ELIGIBLE_PARTIAL = "ELIGIBLE_PARTIAL"
    INELIGIBLE_UNSUPPORTED_IDENTIFIER = "INELIGIBLE_UNSUPPORTED_IDENTIFIER"
    INELIGIBLE_SOURCE_EMPTY = "INELIGIBLE_SOURCE_EMPTY"
    SOURCE_TRANSIENT_ERROR = "SOURCE_TRANSIENT_ERROR"


@dataclass(frozen=True)
class PilotSample:
    ticker: str
    isu_cd: list[str]
    market: list[str]
    sample_group: PilotSampleGroup
    numeric_or_alpha: str
    first_common_date: str
    last_common_date: str
    query_start: str
    query_end: str
    sample_reason: str
    currently_common: bool
    historical_only: bool


@dataclass
class PilotResult:
    ticker: str
    isu_cd: str
    market: str
    sample_group: str
    numeric_or_alpha: str
    source: str
    adjusted: bool
    request_start: str
    request_end: str
    attempt_count: int
    source_status: str
    eligibility_status: str
    row_count: int
    first_date: str | None
    last_date: str | None
    duplicate_count: int
    invalid_ohlc_count: int
    future_row_count: int
    error_type: str | None
    error_message_sanitized: str | None
    evidence_summary: str


class PilotLiveAdjustedPriceProvider:
    """Pilot-specific PyKRX adjusted=True query provider supporting both numeric and alphanumeric tickers."""

    def __init__(self) -> None:
        self._call_count = 0

    @property
    def call_count(self) -> int:
        return self._call_count

    def load_daily(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        clean_ticker = str(ticker).strip()
        if not clean_ticker or len(clean_ticker) > 6:
            raise MarketDataError(f"유효하지 않은 종목코드입니다: {ticker!r}")
        clean_ticker = clean_ticker.zfill(6)

        self._call_count += 1
        try:
            from pykrx import stock

            raw = stock.get_market_ohlcv_by_date(
                start,
                end,
                clean_ticker,
                adjusted=True,
            )
        except Exception as exc:
            raise MarketDataError(
                f"PyKRX adjusted=True 조회 실패 (ticker={clean_ticker}, start={start}, end={end}): {exc}"
            ) from exc

        return self._normalise_response(raw)

    def _normalise_response(self, raw: pd.DataFrame) -> pd.DataFrame:
        if raw is None or raw.empty:
            return _empty_adjusted_frame()
        missing = [column for column in _PYKRX_COLUMNS if column not in raw.columns]
        if missing:
            raise MarketDataError(f"PyKRX adjusted=True 응답 schema 오류: missing={missing}")

        index = _normalise_index(raw.index)
        frame = pd.DataFrame(index=index)
        try:
            for korean, standard in _PYKRX_COLUMNS.items():
                numeric = pd.to_numeric(raw[korean], errors="coerce")
                if numeric.isna().any():
                    raise MarketDataError(f"PyKRX adjusted=True {korean} 컬럼에 NaN이 있습니다.")
                frame[standard] = numeric.astype("float64").to_numpy()
        except (TypeError, ValueError) as exc:
            raise MarketDataError(f"PyKRX adjusted=True 응답 정규화 실패: {exc}") from exc

        # Filter phantom rows where open, high, and low are all zero (regardless of volume)
        phantom = (
            (frame["open"] == 0)
            & (frame["high"] == 0)
            & (frame["low"] == 0)
            & (frame["close"] > 0)
        )
        frame = frame.loc[~phantom].sort_index()
        frame = _correct_minor_rounding_violations(frame)
        output = frame[list(ADJUSTED_OHLC_COLUMNS)]
        if _FORBIDDEN_OUTPUT_COLUMNS.intersection(output.columns):
            raise MarketDataError("PilotLiveAdjustedPriceProvider가 ancillary column을 반환했습니다.")
        validate_adjusted_ohlc(output)
        return output.astype("float64")


def build_pilot_sample_manifest(
    population_path: Path = Path(DEFAULT_POPULATION_ARTIFACT_PATH),
) -> list[PilotSample]:
    """Derive risk-stratified bounded pilot samples from the frozen population."""
    records = load_historical_common_population(population_path)
    calc_sha = population_manifest_sha256(records)
    if calc_sha != EXPECTED_POPULATION_SHA256:
        raise RuntimeError(
            f"Population manifest SHA mismatch: got {calc_sha}, expected {EXPECTED_POPULATION_SHA256}"
        )

    records_by_ticker = {r["ticker"]: r for r in records}
    samples: list[PilotSample] = []

    # Helper to build PilotSample from population record
    def _make_sample(
        ticker: str,
        group: PilotSampleGroup,
        query_start: str,
        query_end: str,
        reason: str,
    ) -> PilotSample:
        rec = records_by_ticker.get(ticker)
        if rec is None:
            raise KeyError(f"Ticker {ticker} not found in frozen population!")
        return PilotSample(
            ticker=ticker,
            isu_cd=rec["isu_cd"],
            market=rec["market"],
            sample_group=group,
            numeric_or_alpha=rec["numeric_or_alpha"],
            first_common_date=rec["first_common_date"],
            last_common_date=rec["last_common_date"],
            query_start=query_start,
            query_end=query_end,
            sample_reason=reason,
            currently_common=rec["currently_common"],
            historical_only=rec["historical_only"],
        )

    # Group A: Normal Numeric Common (8 tickers: 4 KOSPI, 4 KOSDAQ)
    group_a_tickers = [
        ("005930", "2024-01-02", "2024-06-28", "Major KOSPI large-cap reference (Samsung Electronics)"),
        ("000660", "2024-01-02", "2024-06-28", "Major KOSPI semi large-cap reference (SK Hynix)"),
        ("035420", "2024-01-02", "2024-06-28", "Major KOSPI platform mid/large reference (NAVER)"),
        ("005380", "2024-01-02", "2024-06-28", "Major KOSPI auto large-cap reference (Hyundai Motor)"),
        ("247540", "2024-01-02", "2024-06-28", "Major KOSDAQ battery large-cap reference (Ecopro BM)"),
        ("086520", "2024-01-02", "2024-06-28", "Major KOSDAQ material reference (Ecopro)"),
        ("035900", "2024-01-02", "2024-06-28", "Major KOSDAQ entertainment reference (JYP Ent.)"),
        ("058470", "2024-01-02", "2024-06-28", "Major KOSDAQ semi equip reference (Leeno Industrial)"),
    ]
    for t, qs, qe, r in group_a_tickers:
        samples.append(_make_sample(t, PilotSampleGroup.GROUP_A_NUMERIC, qs, qe, r))

    # Group B: Historical-Only Delisted Common (5 tickers)
    group_b_tickers = [
        ("000030", "2014-11-19", "2019-02-12", "Historical delisted common (Woori Pharmaceutical / Samhwa)"),
        ("000060", "2010-12-20", "2023-02-20", "Historical delisted common (Meritz Fire & Marine)"),
        ("000360", "2010-01-04", "2015-04-14", "Historical delisted common (Samick Musical Instruments / LMS)"),
        ("000470", "2010-01-04", "2012-07-13", "Historical delisted common (Samick LMS / Hankook Paper)"),
        ("001040", "2010-01-04", "2018-03-23", "Historical delisted common (CJ Corp predecessor / delisted)"),
    ]
    for t, qs, qe, r in group_b_tickers:
        samples.append(_make_sample(t, PilotSampleGroup.GROUP_B_HISTORICAL_DELISTED, qs, qe, r))

    # Group C: Corporate-Action / Adjustment-Sensitive (4 tickers)
    group_c_tickers = [
        ("005930", "2018-04-20", "2018-05-15", "Samsung Electronics 50:1 stock split boundary (2018-05-04)"),
        ("035720", "2021-04-05", "2021-04-25", "Kakao 5:1 stock split boundary (2021-04-15)"),
        ("003670", "2019-05-15", "2019-06-15", "POSCO Future M corporate action and capital expansion window"),
        ("022100", "2023-12-15", "2024-01-15", "POSCO DX corporate action and market transition boundary"),
    ]
    for t, qs, qe, r in group_c_tickers:
        samples.append(_make_sample(t, PilotSampleGroup.GROUP_C_CORPORATE_ACTION, qs, qe, r))

    # Group D: Alpha Common (All 23 tickers in Population)
    alpha_records = [r for r in records if r.get("numeric_or_alpha") == "alphanumeric"]
    for rec in sorted(alpha_records, key=lambda x: x["ticker"]):
        t = rec["ticker"]
        qs = rec["first_common_date"]
        qe = rec["last_common_date"]
        r = f"Alpha-shaped legitimate COMMON stock full census ({t})"
        samples.append(_make_sample(t, PilotSampleGroup.GROUP_D_ALPHA, qs, qe, r))

    # Group E: Market-Transfer / Lifecycle (3 tickers)
    group_e_tickers = [
        ("035720", "2017-07-03", "2017-07-14", "Kakao market migration boundary (KOSDAQ -> KOSPI on 2017-07-10)"),
        ("068270", "2018-02-01", "2018-02-20", "Celltrion market migration boundary (KOSDAQ -> KOSPI on 2018-02-09)"),
        ("022100", "2023-12-20", "2024-01-10", "POSCO DX market migration boundary (KOSDAQ -> KOSPI on 2024-01-02)"),
    ]
    for t, qs, qe, r in group_e_tickers:
        samples.append(_make_sample(t, PilotSampleGroup.GROUP_E_MARKET_TRANSFER, qs, qe, r))

    return samples


def execute_single_pilot_query(
    sample: PilotSample,
    provider: PilotLiveAdjustedPriceProvider | None = None,
    max_retries: int = 2,
    retry_delay_seconds: float = 0.5,
) -> PilotResult:
    """Execute live PyKRX adjusted=True query for a single pilot sample and validate result."""
    if provider is None:
        provider = PilotLiveAdjustedPriceProvider()

    clean_start = sample.query_start.replace("-", "")
    clean_end = sample.query_end.replace("-", "")

    attempt_count = 0
    last_error: Exception | None = None
    frame: pd.DataFrame = pd.DataFrame()

    for attempt in range(1, max_retries + 2):
        attempt_count = attempt
        try:
            # Use provider load_daily
            frame = provider.load_daily(sample.ticker, sample.query_start, sample.query_end)
            last_error = None
            break
        except Exception as exc:
            last_error = exc
            if attempt <= max_retries:
                time.sleep(retry_delay_seconds * attempt)

    # Analyze result
    error_type = type(last_error).__name__ if last_error else None
    error_msg = str(last_error) if last_error else None

    # Sanitize credential/sensitive tokens if any in error
    if error_msg:
        error_msg = re.sub(r"(token|auth|pw|password|key)=\S+", r"\1=***", error_msg, flags=re.IGNORECASE)

    row_count = len(frame)
    duplicate_count = 0
    invalid_ohlc_count = 0
    future_row_count = 0
    first_date = None
    last_date = None

    if row_count > 0:
        first_date = frame.index[0].strftime("%Y-%m-%d")
        last_date = frame.index[-1].strftime("%Y-%m-%d")
        duplicate_count = int(frame.index.duplicated().sum())

        # Check future rows
        req_end_ts = pd.Timestamp(sample.query_end)
        future_mask = frame.index > req_end_ts
        future_row_count = int(future_mask.sum())

        # Validate OHLC relations
        relation_violations = (
            (frame["high"] < frame["low"])
            | (frame["high"] < frame["open"])
            | (frame["high"] < frame["close"])
            | (frame["low"] > frame["open"])
            | (frame["low"] > frame["close"])
            | (frame["open"] <= 0)
            | (frame["high"] <= 0)
            | (frame["low"] <= 0)
            | (frame["close"] <= 0)
            | frame[list(ADJUSTED_OHLC_COLUMNS)].isna().any(axis=1)
        )
        invalid_ohlc_count = int(relation_violations.sum())

    # Determine status
    if last_error is not None:
        source_status = "ERROR"
        eligibility_status = SourceEligibilityStatus.SOURCE_TRANSIENT_ERROR.value
        evidence = f"Query failed after {attempt_count} attempts: {error_type}: {error_msg}"
    elif row_count == 0:
        source_status = "EMPTY"
        eligibility_status = SourceEligibilityStatus.INELIGIBLE_SOURCE_EMPTY.value
        evidence = f"Query returned empty DataFrame across requested window {sample.query_start} ~ {sample.query_end}"
    elif invalid_ohlc_count > 0 or duplicate_count > 0 or future_row_count > 0:
        source_status = "SCHEMA_ANOMALY"
        eligibility_status = SourceEligibilityStatus.ELIGIBLE_PARTIAL.value
        evidence = (
            f"Returned {row_count} rows but contains data quality violations: "
            f"invalid_ohlc={invalid_ohlc_count}, duplicates={duplicate_count}, future_rows={future_row_count}"
        )
    else:
        source_status = "SUCCESS"
        eligibility_status = SourceEligibilityStatus.ELIGIBLE_FULL.value
        evidence = (
            f"Successfully returned {row_count} valid adjusted OHLC rows spanning {first_date} ~ {last_date} "
            f"(requested {sample.query_start} ~ {sample.query_end}, 0 anomalies)"
        )

    return PilotResult(
        ticker=sample.ticker,
        isu_cd=",".join(sample.isu_cd),
        market=",".join(sample.market),
        sample_group=sample.sample_group.value,
        numeric_or_alpha=sample.numeric_or_alpha,
        source="PyKRX (get_market_ohlcv_by_date)",
        adjusted=True,
        request_start=sample.query_start,
        request_end=sample.query_end,
        attempt_count=attempt_count,
        source_status=source_status,
        eligibility_status=eligibility_status,
        row_count=row_count,
        first_date=first_date,
        last_date=last_date,
        duplicate_count=duplicate_count,
        invalid_ohlc_count=invalid_ohlc_count,
        future_row_count=future_row_count,
        error_type=error_type,
        error_message_sanitized=error_msg,
        evidence_summary=evidence,
    )


def run_bounded_live_pilot(
    samples: Sequence[PilotSample] | None = None,
    population_path: Path = Path(DEFAULT_POPULATION_ARTIFACT_PATH),
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Run full bounded live pilot across sample groups and record artifacts."""
    if samples is None:
        samples = build_pilot_sample_manifest(population_path)

    provider = PilotLiveAdjustedPriceProvider()
    results: list[PilotResult] = []

    total_requests = 0
    total_retries = 0

    for idx, sample in enumerate(samples, 1):
        res = execute_single_pilot_query(sample, provider=provider)
        total_requests += res.attempt_count
        if res.attempt_count > 1:
            total_retries += (res.attempt_count - 1)
        results.append(res)

    # Compute group statistics
    group_counts: dict[str, int] = {}
    group_outcomes: dict[str, dict[str, int]] = {}

    for res in results:
        g = res.sample_group
        group_counts[g] = group_counts.get(g, 0) + 1
        if g not in group_outcomes:
            group_outcomes[g] = {"SUCCESS": 0, "EMPTY": 0, "ERROR": 0, "SCHEMA_ANOMALY": 0}
        group_outcomes[g][res.source_status] = group_outcomes[g].get(res.source_status, 0) + 1

    alpha_results = [r for r in results if r.sample_group == PilotSampleGroup.GROUP_D_ALPHA.value]
    alpha_summary = {
        "total": len(alpha_results),
        "supported": sum(1 for r in alpha_results if r.source_status == "SUCCESS"),
        "empty": sum(1 for r in alpha_results if r.source_status == "EMPTY"),
        "error": sum(1 for r in alpha_results if r.source_status == "ERROR"),
        "anomaly": sum(1 for r in alpha_results if r.source_status == "SCHEMA_ANOMALY"),
    }

    historical_delisted_results = [r for r in results if r.sample_group == PilotSampleGroup.GROUP_B_HISTORICAL_DELISTED.value]
    historical_delisted_summary = {
        "total": len(historical_delisted_results),
        "supported": sum(1 for r in historical_delisted_results if r.source_status == "SUCCESS"),
        "empty": sum(1 for r in historical_delisted_results if r.source_status == "EMPTY"),
        "error": sum(1 for r in historical_delisted_results if r.source_status == "ERROR"),
    }

    numeric_results = [r for r in results if r.sample_group == PilotSampleGroup.GROUP_A_NUMERIC.value]
    numeric_summary = {
        "total": len(numeric_results),
        "supported": sum(1 for r in numeric_results if r.source_status == "SUCCESS"),
        "empty": sum(1 for r in numeric_results if r.source_status == "EMPTY"),
        "error": sum(1 for r in numeric_results if r.source_status == "ERROR"),
    }

    corporate_action_results = [r for r in results if r.sample_group == PilotSampleGroup.GROUP_C_CORPORATE_ACTION.value]
    corporate_action_summary = {
        "total": len(corporate_action_results),
        "supported": sum(1 for r in corporate_action_results if r.source_status == "SUCCESS"),
        "empty": sum(1 for r in corporate_action_results if r.source_status == "EMPTY"),
        "error": sum(1 for r in corporate_action_results if r.source_status == "ERROR"),
    }

    market_transfer_results = [r for r in results if r.sample_group == PilotSampleGroup.GROUP_E_MARKET_TRANSFER.value]
    market_transfer_summary = {
        "total": len(market_transfer_results),
        "supported": sum(1 for r in market_transfer_results if r.source_status == "SUCCESS"),
        "empty": sum(1 for r in market_transfer_results if r.source_status == "EMPTY"),
        "error": sum(1 for r in market_transfer_results if r.source_status == "ERROR"),
    }

    total_success = sum(1 for r in results if r.source_status == "SUCCESS")
    total_empty = sum(1 for r in results if r.source_status == "EMPTY")
    total_error = sum(1 for r in results if r.source_status == "ERROR")
    total_anomaly = sum(1 for r in results if r.source_status == "SCHEMA_ANOMALY")

    verdict = (
        "ACCEPT"
        if total_error == 0 and total_anomaly == 0 and alpha_summary["supported"] == 23 and historical_delisted_summary["supported"] == len(historical_delisted_results)
        else "CONDITIONAL"
    )

    next_state = (
        "READY_FOR_ADJUSTED_PRICE_STORE_FULL_POPULATION"
        if verdict == "ACCEPT"
        else "NEEDS_ADJUSTED_PRICE_ALPHA_SOURCE_POLICY"
    )

    summary_payload: dict[str, Any] = {
        "schema": "adjusted_price_store_bounded_live_pilot_v01",
        "status": "PILOT_COMPLETED",
        "final_verdict": verdict,
        "next_state": next_state,
        "frozen_authority": {
            "population_count": EXPECTED_POPULATION_COUNT,
            "population_manifest_sha256": EXPECTED_POPULATION_SHA256,
            "population_mutated": False,
        },
        "sample_counts": {
            "total_samples": len(samples),
            "unique_tickers": len({s.ticker for s in samples}),
            "group_a_numeric": group_counts.get(PilotSampleGroup.GROUP_A_NUMERIC.value, 0),
            "group_b_historical_delisted": group_counts.get(PilotSampleGroup.GROUP_B_HISTORICAL_DELISTED.value, 0),
            "group_c_corporate_action": group_counts.get(PilotSampleGroup.GROUP_C_CORPORATE_ACTION.value, 0),
            "group_d_alpha": group_counts.get(PilotSampleGroup.GROUP_D_ALPHA.value, 0),
            "group_e_market_transfer": group_counts.get(PilotSampleGroup.GROUP_E_MARKET_TRANSFER.value, 0),
        },
        "outcome_counts": {
            "success": total_success,
            "empty": total_empty,
            "error": total_error,
            "schema_anomaly": total_anomaly,
        },
        "group_summaries": {
            "numeric_normal": numeric_summary,
            "historical_delisted": historical_delisted_summary,
            "corporate_action": corporate_action_summary,
            "alpha_23_census": alpha_summary,
            "market_transfer": market_transfer_summary,
        },
        "request_accounting": {
            "pykrx_requests": total_requests,
            "pykrx_retries": total_retries,
            "krx_open_api_requests": 0,
            "opendart_requests": 0,
            "krx_mdc_requests": 0,
        },
        "data_quality": {
            "total_duplicate_rows": sum(r.duplicate_count for r in results),
            "total_invalid_ohlc_rows": sum(r.invalid_ohlc_count for r in results),
            "total_future_rows": sum(r.future_row_count for r in results),
        },
    }

    # Save artifacts if output_dir is provided
    if output_dir is not None:
        out_p = Path(output_dir)
        out_p.mkdir(parents=True, exist_ok=True)

        manifest_payload = [
            {
                "ticker": s.ticker,
                "isu_cd": s.isu_cd,
                "market": s.market,
                "sample_group": s.sample_group.value,
                "numeric_or_alpha": s.numeric_or_alpha,
                "first_common_date": s.first_common_date,
                "last_common_date": s.last_common_date,
                "query_start": s.query_start,
                "query_end": s.query_end,
                "sample_reason": s.sample_reason,
            }
            for s in samples
        ]
        (out_p / "pilot_sample_manifest.json").write_text(
            json.dumps(manifest_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

        results_df = pd.DataFrame([asdict(r) for r in results])
        results_df.to_csv(out_p / "pilot_results.csv", index=False, encoding="utf-8")

        (out_p / "pilot_summary.json").write_text(
            json.dumps(summary_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    return {
        "summary": summary_payload,
        "results": results,
        "samples": samples,
    }
