#!/usr/bin/env python3
"""Read-only, targeted diagnosis for the 12 P1 unavailable-stage failures."""

from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts import run_fastcore_neg40_weak_protect_p2_1 as runner  # noqa: E402
from trend_scanner.patterns.pattern_a_stage import (  # noqa: E402
    _REQUIRED_FIELDS,
    classify_pattern_a_stage,
)
from trend_scanner.validation.historical_snapshot import (  # noqa: E402
    build_historical_snapshot,
)
from trend_scanner.validation import pattern_a_fast_core_v02_reentry as v2  # noqa: E402


FAILURES = (
    ("001140", "2023-05-31", "001140|KR7001140003|KOSPI|2010-01-04|2026-01-26|001140_01"),
    ("009730", "2017-12-21", "009730|KR7009730003|KOSDAQ|2010-01-04|2026-09-01|009730_04"),
    ("031980", "2020-03-13", "031980|KR7031980006|KOSDAQ|2010-01-04|2026-09-01|031980_01"),
    ("035290", "2022-04-29", "035290|KR7035290006|KOSDAQ|2010-01-04|2026-09-01|035290_05"),
    ("036260", "2016-10-04", "036260|KR7036260008|KOSDAQ|2010-01-04|2021-02-10|036260_01"),
    ("036620", "2017-10-31", "036620|KR7036620003|KOSDAQ|2010-01-04|2026-09-01|036620_02"),
    ("043710", "2017-01-18", "043710|KR7043710003|KOSDAQ|2010-01-04|2026-09-01|043710_01"),
    ("044060", "2025-08-20", "044060|KR7044060002|KOSDAQ|2010-01-04|2025-08-20|044060_03"),
    ("052300", "2017-12-20", "052300|KR7052300001|KOSDAQ|2010-01-04|2026-09-01|052300_02"),
    ("052400", "2022-06-13", "052400|KR7052400009|KOSDAQ|2010-01-04|2026-09-01|052400_02"),
    ("068150", "2017-02-23", "068150|KR7068150002|KOSDAQ|2010-01-04|2017-03-06|068150_01"),
    ("130660", "2020-02-21", "130660|KR7130660004|KOSPI|2010-12-16|2026-09-01|130660_01"),
)

MINIMUM_ROWS = {
    "ma24_slope": ("monthly", 27),
    "weekly_ma12_slope": ("weekly", 17),
    "ma24_slope_acceleration": ("monthly", 31),
    "avg_price_change_12m": ("monthly", 24),
    "ma_spread": ("monthly", 24),
    "range_position": ("monthly", 36),
    "distance_to_resistance": ("monthly", 36),
}


def _missing_fields(features: Any) -> list[str]:
    return [name for name in _REQUIRED_FIELDS if pd.isna(getattr(features, name))]


def _same_value(left: Any, right: Any) -> bool:
    left_missing = bool(pd.isna(left))
    right_missing = bool(pd.isna(right))
    if left_missing or right_missing:
        return left_missing and right_missing
    try:
        return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-12)
    except (TypeError, ValueError):
        return left == right


def _source_reason(feature: str, snapshot: Any) -> tuple[str, bool, bool]:
    """Return immediate formula/input reason, source-gap flag, degenerate flag."""
    features = snapshot.features
    frame = snapshot.monthly if feature != "weekly_ma12_slope" else snapshot.weekly
    frequency, needed = MINIMUM_ROWS[feature]
    actual = features.monthly_rows if frequency == "monthly" else features.weekly_rows
    if actual < needed:
        return (
            f"{frequency} bars {actual}개로 계산 최소치 {needed}개 미달",
            False,
            False,
        )

    source_columns = ("close",) if feature in {
        "ma24_slope", "ma24_slope_acceleration", "avg_price_change_12m", "ma_spread", "weekly_ma12_slope"
    } else ("high", "low", "close")
    tail_size = needed
    bad = []
    for column in source_columns:
        if column not in frame.columns:
            bad.append(f"{column}:column_absent")
        else:
            count = int(frame[column].tail(tail_size).isna().sum())
            if count:
                bad.append(f"{column}:NaN_{count}")
    if bad:
        return f"필요 구간 원천 OHLC 입력 결손({';'.join(bad)})", True, False

    monthly = snapshot.monthly
    if feature in {"range_position", "distance_to_resistance"}:
        high = features.high_36m
        low = features.low_36m
        if feature == "range_position" and high == low:
            return f"36개월 고가와 저가가 같음(high_36m=low_36m={high})", False, True
        if feature == "distance_to_resistance" and high == 0:
            return "36개월 고가(저항 분모)가 0", False, True
        return "필수 입력 수는 충족하나 산출 결과가 결측; formula parity 재검토 필요", False, False
    if feature == "avg_price_change_12m":
        prior_mean = float(monthly["close"].iloc[-24:-12].mean())
        if prior_mean == 0:
            return "직전 12개월 평균 종가가 0(변화율 분모 퇴화)", False, True
    if feature == "ma_spread" and features.close == 0:
        return "월봉 종가가 0(MA spread 정규화 분모 퇴화)", False, True
    if feature in {"ma24_slope", "ma24_slope_acceleration"}:
        if float(monthly["close"].iloc[-4]) == 0:
            return "24개월 MA 기울기의 기준 종가가 0", False, True
    if feature == "weekly_ma12_slope" and float(snapshot.weekly["close"].iloc[-5]) == 0:
        return "12주 MA 기울기의 기준 주봉 종가가 0", False, True
    return "필수 행 수와 원천 입력은 충족; direct-vs-optimized 산식 parity 확인 필요", False, False


def _stage_for_month(context: Any, month_end: pd.Timestamp, calendar: Any) -> tuple[Any, list[str]]:
    snapshot = v2.build_historical_snapshot_from_context(
        context,
        month_end,
        include_incomplete_periods=False,
        market_calendar=calendar,
    )
    return snapshot, _missing_fields(snapshot.features)


def _missing_bucket_evidence(
    feature: str,
    snapshot: Any,
    daily: pd.DataFrame,
    market_dates: pd.DatetimeIndex,
) -> list[dict[str, Any]]:
    """Map NaN rolling-window bars back to raw Repository V2 dates/sessions."""
    frequency, needed = MINIMUM_ROWS[feature]
    frame = snapshot.weekly if frequency == "weekly" else snapshot.monthly
    bad_labels = frame.tail(needed).index[frame.tail(needed)["close"].isna()]
    evidence = []
    for raw_label in bad_labels:
        label = pd.Timestamp(raw_label).normalize()
        if frequency == "weekly":
            start = label - pd.Timedelta(6, unit="D")  # W-FRI bucket: Saturday through Friday
        else:
            start = label.replace(day=1)
        expected_sessions = int(((market_dates >= start) & (market_dates <= label)).sum())
        daily_rows = int(((daily.index >= start) & (daily.index <= label)).sum())
        if expected_sessions == 0 and daily_rows == 0:
            kind = "EMPTY_CALENDAR_BUCKET_RESAMPLER_ARTIFACT"
        elif expected_sessions > 0 and daily_rows == 0:
            kind = "EXPECTED_SESSION_SOURCE_OR_AUTHORITY_GAP"
        else:
            kind = "OHLC_CLOSE_MISSING_WITHIN_SOURCE_BUCKET"
        evidence.append({
            "frequency": frequency,
            "bucket_label": label.strftime("%Y-%m-%d"),
            "bucket_start": start.strftime("%Y-%m-%d"),
            "expected_krx_sessions": expected_sessions,
            "repository_v2_daily_rows": daily_rows,
            "kind": kind,
        })
    return evidence


def _bucket_summary(items: list[dict[str, Any]]) -> str:
    if not items:
        return ""
    labels = [item["bucket_label"] for item in items]
    kinds = {item["kind"] for item in items}
    if kinds == {"EMPTY_CALENDAR_BUCKET_RESAMPLER_ARTIFACT"}:
        return (
            f"{','.join(labels)} empty {items[0]['frequency']} bin: 0 KRX sessions and 0 Repository V2 rows; "
            "resampler's volume sum leaves an all-price-NaN/volume-0 bucket in the rolling window"
        )
    missing_sessions = sum(
        item["expected_krx_sessions"] for item in items
        if item["kind"] == "EXPECTED_SESSION_SOURCE_OR_AUTHORITY_GAP"
    )
    gap_items = [item for item in items if item["kind"] == "EXPECTED_SESSION_SOURCE_OR_AUTHORITY_GAP"]
    if gap_items:
        return (
            f"{len(gap_items)} empty {items[0]['frequency']} bucket(s) ({gap_items[0]['bucket_label']}"
            f"..{gap_items[-1]['bucket_label']}): {missing_sessions} KRX trading sessions expected, "
            "but 0 Repository V2 daily rows; rolling OHLC close becomes NaN"
        )
    return "; ".join(
        f"{item['bucket_label']} {item['kind']} (sessions={item['expected_krx_sessions']}, rows={item['repository_v2_daily_rows']})"
        for item in items
    )


def diagnose() -> dict[str, Any]:
    run = runner._load_context("P1")
    output_root = ROOT / "artifacts/backtests/p1_neg40_weak_protect_v01/diagnostics/unavailable_stage_12_v01"
    output_root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    market_dates = pd.DatetimeIndex(pd.to_datetime(run.calendar.trading_dates)).normalize()

    for ticker, failure_text, pair_id in FAILURES:
        failure_date = pd.Timestamp(failure_text).normalize()
        segment_key = pair_id.rsplit("|", 1)[0]
        segment = next(item for item in run.segments_by_ticker[ticker] if item.key == segment_key)
        loader = runner.RepositoryV2DailyLoader(
            run.loader.repository,
            start=segment.effective_from,
            end=run.window.execution_support,
        )
        loaded = loader.load(ticker)
        if loaded is None or loaded.empty:
            raise RuntimeError(f"Repository V2 history unavailable for targeted case {ticker}")
        daily = loaded.sort_index()

        strategy_cutoff = run.window.effective_end
        strategy_daily = daily
        lifecycle_event = runner._confirmed_lifecycle_event_for_segment(
            segment,
            tuple(run.lifecycle_settlements),
            run.window.effective_end,
            run.segments_by_ticker,
        )
        if lifecycle_event is not None:
            event_date = runner._event_effective_date(lifecycle_event)
            trading_dates = pd.DatetimeIndex(pd.to_datetime(run.calendar.trading_dates)).normalize()
            prior_sessions = trading_dates[trading_dates < event_date]
            if len(prior_sessions):
                strategy_cutoff = min(strategy_cutoff, pd.Timestamp(prior_sessions[-1]).normalize())
                strategy_daily = daily[daily.index < event_date]

        context = v2.build_precomputed_ticker_context(ticker, ticker, strategy_daily)
        monthly = context.monthly_up_to(strategy_cutoff)
        timeline_entries: dict[pd.Timestamp, pd.Timestamp] = {}
        for raw_month_end in monthly.index:
            month_end = pd.Timestamp(raw_month_end).normalize()
            if month_end < run.window.effective_start:
                continue
            effective_dates = strategy_daily.index[
                (strategy_daily.index <= month_end) & (strategy_daily.index <= strategy_cutoff)
            ]
            if effective_dates.empty:
                continue
            effective_date = pd.Timestamp(effective_dates[-1]).normalize()
            if run.window.effective_start <= effective_date <= strategy_cutoff:
                # Mirrors _stage_timeline's dict overwrite when sparse monthly labels
                # resolve to the same last observed trading date.
                timeline_entries[effective_date] = month_end

        timeline_dates = sorted(timeline_entries)
        eligible = [value for value in timeline_dates if value <= failure_date]
        if not eligible:
            raise RuntimeError(f"no P1 stage-timeline snapshot at/before failure for {ticker}")
        failed_asof = eligible[-1]
        failed_month_end = timeline_entries[failed_asof]
        failed_snapshot, _ = _stage_for_month(context, failed_month_end, run.calendar)
        stage_result = classify_pattern_a_stage(failed_snapshot)
        missing = _missing_fields(failed_snapshot.features)

        legacy_snapshot = build_historical_snapshot(
            ticker,
            ticker,
            strategy_daily,
            failed_month_end,
            include_incomplete_periods=False,
            market_calendar=run.calendar,
        )
        parity_mismatches = [
            name
            for name in _REQUIRED_FIELDS
            if not _same_value(getattr(failed_snapshot.features, name), getattr(legacy_snapshot.features, name))
        ]

        previous_usable = None
        for effective_date in reversed([value for value in timeline_dates if value < failed_asof]):
            month_end = timeline_entries[effective_date]
            candidate, candidate_missing = _stage_for_month(context, month_end, run.calendar)
            if not candidate_missing:
                candidate_stage = classify_pattern_a_stage(candidate)
                previous_usable = {
                    "effective_date": effective_date.strftime("%Y-%m-%d"),
                    "snapshot_month_end": month_end.strftime("%Y-%m-%d"),
                    "snapshot_effective_as_of": candidate.features.as_of.strftime("%Y-%m-%d") if candidate.features.as_of is not None else None,
                    "stage": candidate_stage.stage.value.upper() if candidate_stage.stage else None,
                }
                break

        next_usable = None
        for effective_date in [value for value in timeline_dates if value > failed_asof]:
            month_end = timeline_entries[effective_date]
            candidate, candidate_missing = _stage_for_month(context, month_end, run.calendar)
            if not candidate_missing:
                candidate_stage = classify_pattern_a_stage(candidate)
                next_usable = {
                    "effective_date": effective_date.strftime("%Y-%m-%d"),
                    "snapshot_month_end": month_end.strftime("%Y-%m-%d"),
                    "snapshot_effective_as_of": candidate.features.as_of.strftime("%Y-%m-%d") if candidate.features.as_of is not None else None,
                    "stage": candidate_stage.stage.value.upper() if candidate_stage.stage else None,
                }
                break

        upstream = {}
        bucket_evidence = {}
        source_gap = False
        resampler_artifact = False
        degenerate = False
        insufficient_history = False
        for name in missing:
            reason, has_gap, is_degenerate = _source_reason(name, failed_snapshot)
            buckets = _missing_bucket_evidence(name, failed_snapshot, strategy_daily, market_dates)
            bucket_evidence[name] = buckets
            empty_bins = [item for item in buckets if item["kind"] == "EMPTY_CALENDAR_BUCKET_RESAMPLER_ARTIFACT"]
            session_gaps = [item for item in buckets if item["kind"] == "EXPECTED_SESSION_SOURCE_OR_AUTHORITY_GAP"]
            if empty_bins:
                resampler_artifact = True
                upstream[name] = _bucket_summary(empty_bins)
            elif session_gaps:
                source_gap = True
                upstream[name] = _bucket_summary(session_gaps)
            else:
                upstream[name] = reason
                source_gap = source_gap or has_gap
            degenerate = degenerate or is_degenerate
            frequency, needed = MINIMUM_ROWS[name]
            actual = (
                failed_snapshot.features.monthly_rows
                if frequency == "monthly"
                else failed_snapshot.features.weekly_rows
            )
            insufficient_history = insufficient_history or actual < needed

        if parity_mismatches or resampler_artifact:
            cause_class = "A_PIPELINE_BUG"
            upstream_cause = "최적화 snapshot과 legacy 직접 snapshot의 required feature 값 불일치"
            if resampler_artifact and not parity_mismatches:
                upstream_cause = "; ".join(
                    f"{name}: {upstream[name]}"
                    for name in missing
                    if any(item["kind"] == "EMPTY_CALENDAR_BUCKET_RESAMPLER_ARTIFACT" for item in bucket_evidence[name])
                )
        elif insufficient_history:
            cause_class = "B_LEGITIMATE_INSUFFICIENT_HISTORY"
            upstream_cause = "; ".join(f"{name}: {upstream[name]}" for name in missing)
        elif source_gap:
            cause_class = "C_SOURCE_OR_AUTHORITY_GAP"
            upstream_cause = "; ".join(f"{name}: {upstream[name]}" for name in missing)
        elif degenerate:
            cause_class = "D_TICKER_SPECIFIC_EXCEPTION"
            upstream_cause = "; ".join(f"{name}: {upstream[name]}" for name in missing)
        else:
            cause_class = "E_OTHER"
            upstream_cause = "; ".join(f"{name}: {upstream[name]}" for name in missing)

        f = failed_snapshot.features
        session_audit = strategy_daily.attrs.get("session_projection_summary", {})
        rows.append({
            "ticker": ticker,
            "isu": segment.stable_security_id,
            "isu_cd": segment.stable_security_id,
            "identity_key": segment.key,
            "pair_id": pair_id,
            "error_eod": failure_text,
            "failure_eod": failure_text,
            "stage_timeline_effective_date": failed_asof.strftime("%Y-%m-%d"),
            "snapshot_requested_month_end": failed_month_end.strftime("%Y-%m-%d"),
            "snapshot_effective_as_of": f.as_of.strftime("%Y-%m-%d") if f.as_of is not None else None,
            "snapshot_monthly_as_of": failed_snapshot.monthly_as_of.strftime("%Y-%m-%d") if failed_snapshot.monthly_as_of is not None else None,
            "daily_rows": int(f.daily_rows),
            "weekly_rows": int(f.weekly_rows),
            "monthly_rows": int(f.monthly_rows),
            "repository_v2_first_daily_date": strategy_daily.index.min().strftime("%Y-%m-%d"),
            "repository_v2_last_daily_date": strategy_daily.index.max().strftime("%Y-%m-%d"),
            "missing_features": missing,
            "feature_values": {name: getattr(f, name) for name in _REQUIRED_FIELDS},
            "classifier_stage": stage_result.stage.value.upper() if stage_result.stage else None,
            "classifier_reason": ",".join(stage_result.reason_codes),
            "classifier_reason_codes": list(stage_result.reason_codes),
            "classifier_insufficient_data": stage_result.evidence.insufficient_data,
            "upstream_cause_by_feature": upstream,
            "missing_bucket_evidence_by_feature": bucket_evidence,
            "legacy_snapshot_required_feature_mismatches": parity_mismatches,
            "previous_usable_snapshot": previous_usable,
            "next_usable_snapshot": next_usable,
            "previous_stage": previous_usable["stage"] if previous_usable else None,
            "previous_stage_date": previous_usable["snapshot_effective_as_of"] if previous_usable else None,
            "next_stage": next_usable["stage"] if next_usable else None,
            "next_stage_date": next_usable["snapshot_effective_as_of"] if next_usable else None,
            "cause_class": cause_class,
            "upstream_cause": upstream_cause,
            "notes": (
                f"snapshot={failed_snapshot.requested_snapshot_date:%Y-%m-%d}/"
                f"effective={f.as_of:%Y-%m-%d}; legacy_required_feature_mismatches={parity_mismatches}"
            ),
            "session_projection_summary": session_audit,
            "lifecycle_event_applied": lifecycle_event.get("evidence_id") if lifecycle_event else None,
        })
        print(f"DIAG_DONE {ticker} {failure_text}", flush=True)

    class_names = (
        "A_PIPELINE_BUG",
        "B_LEGITIMATE_INSUFFICIENT_HISTORY",
        "C_SOURCE_OR_AUTHORITY_GAP",
        "D_TICKER_SPECIFIC_EXCEPTION",
        "E_OTHER",
    )
    counts = Counter(row["cause_class"] for row in rows)
    cause_distribution = {name: counts.get(name, 0) for name in class_names}
    summary = {
        "status": "P1_UNAVAILABLE_12_DIAGNOSTIC_COMPLETE",
        "window": "P1",
        "scope": "12 logged failing ticker/pair_id/EOD cases only",
        "failure_count": len(rows),
        "cause_class_distribution": cause_distribution,
        "repeated_cause_counts": {
            "same_cause_class": dict(sorted(counts.items())),
            "same_pipeline_artifact": sum(row["cause_class"] == "A_PIPELINE_BUG" for row in rows),
            "source_or_authority_gap_cases": sum(row["cause_class"] == "C_SOURCE_OR_AUTHORITY_GAP" for row in rows),
        },
        "repeated_cause_details": {
            "A_PIPELINE_BUG": "009730/036620/052300 all include the 2017-10-06 W-FRI bucket with 0 KRX sessions, 0 V2 rows, NaN OHLC, and volume=0.",
            "C_SOURCE_OR_AUTHORITY_GAP": "9 cases have one or more KRX trading sessions in rolling-window buckets but 0 Repository V2 daily rows.",
            "pipeline_code_path": "src/trend_scanner/data/resampler.py::_resample: OHLCV resample volume sum yields 0 for empty bins; dropna(how='all') retains the bin.",
        },
        "classifier_reason_distribution": dict(sorted(Counter(
            code for row in rows for code in row["classifier_reason_codes"]
        ).items())),
        "replay_performed": False,
        "production_code_modified": False,
        "diagnostic_helper_added": True,
        "strategy_or_threshold_modified": False,
        "partial_raw_files_modified": False,
        "canonical_files_modified": False,
        "recommendation": "B. UNAVAILABLE semantics 설계 필요",
        "rows": rows,
    }

    csv_rows = []
    for row in rows:
        csv_rows.append({
            key: json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else value
            for key, value in row.items()
        })
    pd.DataFrame(csv_rows).to_csv(output_root / "p1_unavailable_stage_12_v01.csv", index=False)
    (output_root / "p1_unavailable_stage_12_v01.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    lines = [
        summary["status"],
        "",
        "# P1 unavailable-stage 12-case diagnostic",
        "",
        f"- 대상: {len(rows)}개 실패 로그의 ticker/pair_id/EOD만",
        f"- 원인 분포: {json.dumps(summary['cause_class_distribution'], ensure_ascii=False, sort_keys=True)}",
        f"- classifier reason: {json.dumps(summary['classifier_reason_distribution'], ensure_ascii=False, sort_keys=True)}",
        "- production code 변경: 없음 (diagnostic-only helper 추가)",
        "- replay / 전략 변경 / 부분 raw 수정 / canonical 교체: 모두 없음",
        f"- 다음 권고: {summary['recommendation']}",
        "",
        "| Ticker | ISU | 실패 EOD | Classifier reason | Missing features | Upstream cause | Cause class | 이전 usable stage/date | 다음 usable stage/date |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        prior = row["previous_usable_snapshot"]
        later = row["next_usable_snapshot"]
        lines.append(
            "| {ticker} | {isu} | {failure_eod} | {reason} | {missing} | {cause} | {klass} | {prior} | {later} |".format(
                ticker=row["ticker"],
                isu=row["isu"],
                failure_eod=row["failure_eod"],
                reason=row["classifier_reason"],
                snapshot_effective_as_of=row["snapshot_effective_as_of"],
                missing=", ".join(row["missing_features"]) or "없음",
                cause=row["upstream_cause"].replace("|", "\\|"),
                klass=row["cause_class"],
                prior=(f"{prior['stage']} @ {prior['snapshot_effective_as_of']}" if prior else "없음"),
                later=(f"{later['stage']} @ {later['snapshot_effective_as_of']}" if later else "없음"),
            )
        )
    lines.extend([
        "",
        "## 분류 기준",
        "",
        "- A_PIPELINE_BUG: 거래 세션이 0개인 달력 주가 volume=0/close=NaN 빈 resample bucket으로 rolling 계산에 포함됨",
        "- B_LEGITIMATE_INSUFFICIENT_HISTORY: feature 산식의 최소 완료 monthly/weekly bar 수 미달",
        "- C_SOURCE_OR_AUTHORITY_GAP: KRX 거래 세션은 있었지만 해당 구간 Repository V2 일봉이 0개",
        "- D_TICKER_SPECIFIC_EXCEPTION: 충분한 입력에서 0 분모/평탄 범위 등 종목별 가격 예외",
        "- E_OTHER: 위 기준으로 단정 불가한 기타 계산 이상",
        "",
        "반복 원인: 달력상 거래 0일인 주의 빈 resample bucket이 3건에서 반복되고, 거래 세션 대비 Repository V2 가격행 공백이 9건에서 관찰됐다.",
        "A 증거 코드 경로: `src/trend_scanner/data/resampler.py::_resample`의 volume `sum` 결과 0이 `dropna(how='all')` 이후에도 빈 OHLC bucket을 유지한다.",
        "세부 수치, feature별 upstream 이유, 원인 bucket별 거래일/일봉 수, pair_id, session audit은 동반 CSV/JSON에 기록했다.",
    ])
    (output_root / "p1_unavailable_stage_12_v01.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({key: summary[key] for key in (
        "status", "failure_count", "cause_class_distribution", "classifier_reason_distribution", "recommendation"
    )}, ensure_ascii=False, indent=2))
    for row in rows:
        print("\t".join((
            row["ticker"], row["failure_eod"], row["snapshot_effective_as_of"] or "",
            ",".join(row["missing_features"]), row["cause_class"], row["upstream_cause"],
            json.dumps(row["previous_usable_snapshot"], ensure_ascii=False),
            json.dumps(row["next_usable_snapshot"], ensure_ascii=False),
        )))
    return summary


if __name__ == "__main__":
    diagnose()
