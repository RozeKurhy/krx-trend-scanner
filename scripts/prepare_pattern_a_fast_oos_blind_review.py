#!/usr/bin/env python
"""Phase 13I-1 reserved OOS blind-review package generator.

This script deliberately performs no model scoring, staging, candidate selection,
or evaluation.  It only freezes the pre-reserved unlabeled population, creates
human-facing blank review material, and renders raw-OHLCV charts from the local
Parquet cache.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

plt.rcParams["font.family"] = ["AppleGothic", "NanumGothic", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

from trend_scanner.data.cache import ParquetCache  # noqa: E402
from trend_scanner.data.resampler import to_monthly, to_weekly  # noqa: E402

BASE_SHA = "ddc7480bb24119ca3e8caca6d7b7f451f8eb097a"
FAST_CONTRACT_SHA = "2da3fc36744b27ec13edae3f690df72c796906e5"
PATTERN_A_FROZEN_SHA = "05d03e16501adbca889488294aaaaa0bd84005de"
ORDER_SEED = "PATTERN_A_FAST_13I_OOS_A_V01"
OOS_SET = "RESERVED_OOS_A"
SAMPLE_SOURCE = "RESERVED_13C_UNLABELED_HOLDOUT"

SOURCE_CSV = Path("artifacts/pattern_a_fast/ground_truth/pattern_a_fast_ground_truth_source_v01.csv")
CALIBRATION_CSV = Path("artifacts/pattern_a_fast/ground_truth/pattern_a_fast_human_review_v01.csv")
OOS_DIR = Path("artifacts/pattern_a_fast/oos")
MANIFEST_CSV = OOS_DIR / "pattern_a_fast_oos_sample_manifest_v01.csv"
REVIEW_CSV = OOS_DIR / "pattern_a_fast_oos_human_review_v01.csv"
ASSET_MANIFEST_CSV = OOS_DIR / "pattern_a_fast_oos_blind_asset_manifest_v01.csv"
PROTOCOL_JSON = OOS_DIR / "pattern_a_fast_oos_evaluation_protocol_v01.json"
AUDIT_JSON = OOS_DIR / "pattern_a_fast_oos_blindness_audit_v01.json"
STAGE_DIR = OOS_DIR / "charts/stage_blind"
OUTCOME_DIR = OOS_DIR / "charts/outcome_blind"
VALIDATION_DIR = Path("docs/validation")

MANIFEST_COLUMNS = [
    "oos_sample_id", "source_sample_id", "ticker", "name", "reference_date",
    "outcome_review_end", "market", "original_sampling_cohort", "oos_set",
    "review_order", "sample_source", "human_stage_status", "human_outcome_status",
    "template_sha256",
]
REVIEW_COLUMNS = [
    "review_order", "oos_sample_id", "source_sample_id", "ticker", "name",
    "reference_date", "outcome_review_end", "weekly_stage_at_reference",
    "weekly_stage_confidence", "human_trigger_event_observed",
    "human_trigger_event_date", "human_label", "human_outcome_confidence",
    "review_note", "stage_review_status", "outcome_review_status",
]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def stable_order_key(source_sample_id: str) -> tuple[str, str]:
    """Return the immutable seeded ordering key for a source sample."""
    return (_sha256_bytes(f"{ORDER_SEED}:{source_sample_id}".encode()), source_sample_id)


def load_reserved_oos_population() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Select exactly the frozen dual-unlabeled holdout; do not substitute rows."""
    source = pd.read_csv(SOURCE_CSV, dtype={"ticker": str}, keep_default_na=False)
    review = pd.read_csv(CALIBRATION_CSV, dtype={"ticker": str}, keep_default_na=False)
    review_status = review[["sample_id", "weekly_stage_at_reference", "human_label"]]
    merged = source.merge(review_status, on="sample_id", how="left", validate="one_to_one")
    oos = merged.loc[
        (merged["weekly_stage_at_reference_y"] == "UNLABELED")
        & (merged["human_label_y"] == "UNLABELED")
    ].copy()
    calibration = merged.loc[
        (merged["weekly_stage_at_reference_y"] != "UNLABELED")
        & (merged["human_label_y"] != "UNLABELED")
    ].copy()
    if len(oos) != 20 or len(calibration) != 40 or len(source) != 60:
        raise ValueError(
            f"Frozen population mismatch: source={len(source)}, calibration={len(calibration)}, oos={len(oos)}"
        )
    if set(oos.sample_id) & set(calibration.sample_id):
        raise ValueError("Calibration and reserved OOS sample IDs overlap.")
    if set(zip(oos.ticker, oos.reference_date)) & set(zip(calibration.ticker, calibration.reference_date)):
        raise ValueError("Calibration and reserved OOS ticker/reference pairs overlap.")
    return oos, calibration


def build_review_tables(oos: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    ordered = oos.assign(_order_key=oos.sample_id.map(stable_order_key)).sort_values("_order_key").reset_index(drop=True)
    rows = []
    for index, (_, row) in enumerate(ordered.iterrows()):
        order = index + 1
        rows.append(
            {
                "oos_sample_id": f"OOS_A_{order:03d}",
                "source_sample_id": row["sample_id"],
                "ticker": row["ticker"],
                "name": row["name"],
                "reference_date": row["reference_date"],
                "outcome_review_end": row["outcome_review_end"],
                "market": row["market"],
                "original_sampling_cohort": row["source_cohort"],
                "oos_set": OOS_SET,
                "review_order": order,
                "sample_source": SAMPLE_SOURCE,
                "human_stage_status": "UNLABELED",
                "human_outcome_status": "UNLABELED",
            }
        )
    manifest = pd.DataFrame(rows)
    review = manifest[["review_order", "oos_sample_id", "source_sample_id", "ticker", "name", "reference_date", "outcome_review_end"]].copy()
    review["weekly_stage_at_reference"] = "UNLABELED"
    review["weekly_stage_confidence"] = "UNLABELED"
    review["human_trigger_event_observed"] = "UNLABELED"
    review["human_trigger_event_date"] = ""
    review["human_label"] = "UNLABELED"
    review["human_outcome_confidence"] = "UNLABELED"
    review["review_note"] = ""
    review["stage_review_status"] = "PENDING"
    review["outcome_review_status"] = "PENDING"
    return manifest, review[REVIEW_COLUMNS]


def _plot_raw_ohlcv(df: pd.DataFrame, title: str, reference_date: pd.Timestamp | None, path: Path) -> None:
    fig, (ax_price, ax_volume) = plt.subplots(
        2, 1, figsize=(8, 5), sharex=True, gridspec_kw={"height_ratios": [3, 1]}
    )
    ax_price.plot(df.index, df["close"], color="#2c6fbb", linewidth=1.2)
    ax_volume.bar(df.index, df["volume"], color="#8a8a8a", width=3.5)
    if reference_date is not None:
        for axis in (ax_price, ax_volume):
            axis.axvline(reference_date, color="#c0392b", linestyle="--", linewidth=1.0)
    ax_price.set_title(title, fontsize=10)
    ax_price.set_ylabel("close")
    ax_volume.set_ylabel("volume")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def _stage_slices(daily: pd.DataFrame, reference_date: pd.Timestamp) -> dict[str, pd.DataFrame]:
    pit_daily = daily.loc[daily.index <= reference_date].copy()
    if pit_daily.empty:
        raise ValueError(f"No cached data at or before {reference_date.date()}.")
    # Resample labels can lie beyond a partial calendar period, so filter them again.
    return {
        "monthly": to_monthly(pit_daily).loc[lambda frame: frame.index <= reference_date],
        "weekly": to_weekly(pit_daily).loc[lambda frame: frame.index <= reference_date],
        "daily": pit_daily,
    }


def _outcome_slice(daily: pd.DataFrame, outcome_end: pd.Timestamp) -> pd.DataFrame:
    outcome_daily = daily.loc[daily.index <= outcome_end].copy()
    if outcome_daily.empty:
        raise ValueError(f"No cached data at or before {outcome_end.date()}.")
    return to_weekly(outcome_daily).loc[lambda frame: frame.index <= outcome_end]


def generate_charts(manifest: pd.DataFrame) -> pd.DataFrame:
    STAGE_DIR.mkdir(parents=True, exist_ok=True)
    OUTCOME_DIR.mkdir(parents=True, exist_ok=True)
    cache = ParquetCache()
    assets: list[dict[str, object]] = []
    expected_stage: set[Path] = set()
    expected_outcome: set[Path] = set()

    for row in manifest.to_dict(orient="records"):
        daily = cache.load(row["ticker"])
        if daily is None:
            raise FileNotFoundError(f"CACHE_MISSING: {row['ticker']}; reserved OOS rows may not be substituted.")
        daily = daily.sort_index()
        reference_date = pd.Timestamp(row["reference_date"])
        outcome_end = pd.Timestamp(row["outcome_review_end"])
        if daily.index.max() < outcome_end:
            raise ValueError(f"CACHE_INCOMPLETE: {row['ticker']} ends {daily.index.max().date()}, needs {outcome_end.date()}.")

        stage = _stage_slices(daily, reference_date)
        for granularity, frame in stage.items():
            filename = f"{row['review_order']:03d}_{row['oos_sample_id']}_{granularity}.png"
            path = STAGE_DIR / filename
            expected_stage.add(path)
            _plot_raw_ohlcv(
                frame,
                f"OOS-A Review {row['review_order']:03d} | {row['ticker']} {row['name']} | as of {row['reference_date']}",
                reference_date if granularity == "daily" else None,
                path,
            )
            assets.append(
                {
                    "review_order": row["review_order"],
                    "oos_sample_id": row["oos_sample_id"],
                    "asset_type": f"STAGE_{granularity.upper()}",
                    "file_path": path.as_posix(),
                    "sha256": _sha256_bytes(path.read_bytes()),
                    "reference_date": row["reference_date"],
                    "max_visible_date": frame.index.max().date().isoformat(),
                    "blindness_status": "PASS",
                }
            )

        outcome = _outcome_slice(daily, outcome_end)
        outcome_path = OUTCOME_DIR / f"{row['review_order']:03d}_{row['oos_sample_id']}_outcome.png"
        expected_outcome.add(outcome_path)
        _plot_raw_ohlcv(
            outcome,
            f"OOS-A Review {row['review_order']:03d} | {row['ticker']} {row['name']} | outcome through {row['outcome_review_end']}",
            reference_date,
            outcome_path,
        )
        assets.append(
            {
                "review_order": row["review_order"],
                "oos_sample_id": row["oos_sample_id"],
                "asset_type": "OUTCOME_WEEKLY",
                "file_path": outcome_path.as_posix(),
                "sha256": _sha256_bytes(outcome_path.read_bytes()),
                "reference_date": row["reference_date"],
                "max_visible_date": outcome.index.max().date().isoformat(),
                "blindness_status": "PASS",
            }
        )

    actual_stage = set(STAGE_DIR.glob("*.png"))
    actual_outcome = set(OUTCOME_DIR.glob("*.png"))
    if actual_stage != expected_stage or actual_outcome != expected_outcome:
        raise ValueError("OOS chart directories contain unexpected or missing assets; do not silently delete files.")
    return pd.DataFrame(assets)


def build_protocol() -> dict[str, object]:
    return {
        "version": "pattern_a_fast_oos_evaluation_protocol_v01",
        "base_sha": BASE_SHA,
        "oos_set": OOS_SET,
        "oos_sample_count": 20,
        "calibration_excluded_count": 40,
        "fast_contract": "HIERARCHICAL_V01",
        "fast_contract_sha": FAST_CONTRACT_SHA,
        "pattern_a_frozen_sha": PATTERN_A_FROZEN_SHA,
        "human_label_taxonomy": ["GOOD_TRIGGER", "BORDERLINE_TRIGGER", "TOO_EARLY", "TOO_LATE", "TOO_EXTENDED", "FALSE_TRIGGER", "NO_SETUP"],
        "human_stage_taxonomy": ["WATCH", "SETUP", "TRIGGER", "TREND", "EXTENDED"],
        "evaluation_metrics": {
            "score": ["median", "iqr", "label_group_median_difference", "cliffs_delta"],
            "stage": ["confusion_matrix", "stage_distribution", "exact_match_descriptive"],
            "event": ["clean_primary_lead_weeks_median", "clean_primary_lead_weeks_iqr"],
        },
        "pairing_semantics": [
            "DATA_UNAVAILABLE", "PATTERN_A_ALREADY_ACTIVE", "PATTERN_A_PRIOR_ACTIVITY_BEFORE_FAST_EVENT",
            "SAME_WEEK", "FAST_EARLIER_PATTERN_A_LATER", "FAST_EVENT_NO_PATTERN_A_CATCHUP",
        ],
        "availability_semantics": {
            "pattern_a_checked_first": True,
            "fast_stage_ready_coverage_below": 0.8,
            "fast_stage_ready_failure": "OOS_DATA_COVERAGE_FAIL",
            "fast_score_unavailable_above": 0.2,
            "fast_score_failure": "OOS_DATA_COVERAGE_FAIL",
            "partial_availability_reported_separately": True,
        },
        "decision_rules": {
            "score_direction": "When both groups have n >= 3, positive-label median must exceed TOO_EARLY median; otherwise OOS_SCORE_DIRECTION_FAIL.",
            "score_effect": "No hard Cliff's delta threshold is preregistered.",
            "lead_direction": "When clean primary n >= 3, median lead weeks must be > 0; otherwise OOS_LEAD_DIRECTION_FAIL.",
            "no_retuning_after_labels": True,
        },
        "inconclusive_rules": {"clean_primary_lead_n_below": 3, "status": "OOS_LEAD_INCONCLUSIVE"},
        "production_frozen": False,
        "evaluation_executed_in_13i_1": False,
    }


def write_human_guides(manifest: pd.DataFrame) -> None:
    stage_rows = "\n".join(
        f"| {r['review_order']:03d} | {r['oos_sample_id']} | {r['ticker']} | {r['name']} | {r['reference_date']} | "
        f"`artifacts/pattern_a_fast/oos/charts/stage_blind/{r['review_order']:03d}_{r['oos_sample_id']}_monthly.png` / weekly / daily |"
        for r in manifest.to_dict(orient="records")
    )
    outcome_rows = "\n".join(
        f"| {r['review_order']:03d} | {r['oos_sample_id']} | {r['ticker']} | {r['name']} | {r['reference_date']} | {r['outcome_review_end']} | "
        f"`artifacts/pattern_a_fast/oos/charts/outcome_blind/{r['review_order']:03d}_{r['oos_sample_id']}_outcome.png` |"
        for r in manifest.to_dict(orient="records")
    )
    (VALIDATION_DIR / "pattern_a_fast_oos_stage_blind_review_v01.md").write_text(
        """pattern_a_fast_oos_stage_blind_review_v01.md
==================================================
Phase 13I-1 Reserved OOS Stage Blind Review Guide
==================================================

PASS A에서는 reference_date 이후 chart를 열지 않는다. 먼저 weekly_stage_at_reference, weekly_stage_confidence, human_trigger_event_observed, human_trigger_event_date를 작성하고 저장. 그 뒤 PASS B.

작성 대상: artifacts/pattern_a_fast/oos/pattern_a_fast_oos_human_review_v01.csv
허용 단계: WATCH, SETUP, TRIGGER, TREND, EXTENDED
신뢰도: HIGH, MEDIUM, LOW. trigger_event_observed는 YES, NO, UNLABELED 중 하나로 기록한다.
이 문서와 차트에는 자동 판단, 점수, 후보 여부 또는 다른 모델 산출물을 표시하지 않는다.

| 순서 | OOS ID | 티커 | 종목명 | 기준일 | Stage chart |
|---:|---|---|---|---|---|
""" + stage_rows + "\n",
        encoding="utf-8",
    )
    (VALIDATION_DIR / "pattern_a_fast_oos_outcome_blind_review_v01.md").write_text(
        """pattern_a_fast_oos_outcome_blind_review_v01.md
====================================================
Phase 13I-1 Reserved OOS Outcome Blind Review Guide
====================================================

Outcome guide only then; write human_label, human_outcome_confidence, review_note. Do not modify stage after outcome.

허용 human_label: GOOD_TRIGGER, BORDERLINE_TRIGGER, TOO_EARLY, TOO_LATE, TOO_EXTENDED, FALSE_TRIGGER, NO_SETUP
신뢰도: HIGH, MEDIUM, LOW. outcome chart는 동결된 outcome_review_end까지만 보여 주며, 기준일 표시선 이후 구간은 결과 검토에만 사용한다.

| 순서 | OOS ID | 티커 | 종목명 | 기준일 | 결과 검토 종료일 | Outcome chart |
|---:|---|---|---|---|---|---|
""" + outcome_rows + "\n",
        encoding="utf-8",
    )
    (VALIDATION_DIR / "pattern_a_fast_oos_preregistration_v01.md").write_text(
        f"""pattern_a_fast_oos_preregistration_v01.md
=================================================
Phase 13I-1 Reserved OOS Evaluation Preregistration
=================================================

상태: READY_FOR_BLIND_HUMAN_OOS_LABELING
Base SHA: {BASE_SHA}
OOS set: {OOS_SET}, 20건. 기존 사람이 주봉 단계와 결과 라벨을 모두 작성한 40건은 calibration으로 제외했다.

1. 모집단 동결
원본 60건 중 기존 review에서 weekly_stage_at_reference와 human_label이 모두 UNLABELED인 20건만 전량 사용한다. 선택, 제외, 대체는 허용하지 않는다. ticker+reference_date 기준으로 calibration과 겹치지 않으며, 같은 ticker의 다른 시점은 허용한다. reference_date와 outcome_review_end는 Phase 13C 원본 값 그대로이며 현재 데이터로 연장하지 않는다.

2. 블라인드 절차
PASS A에서 월/주/일 차트를 reference_date까지만 열어 단계·신뢰도·trigger 관찰값을 기록하고 저장한다. PASS B에서만 frozen outcome_review_end까지의 결과 차트를 열어 결과 라벨·신뢰도·메모를 기록한다. PASS B 이후 PASS A 기록을 수정하지 않는다. 사람용 자료에는 모델 점수·단계·후보·pairing·표본 분류를 노출하지 않는다.

3. 13I-2 사전등록 평가
Fast contract는 HIERARCHICAL_V01 ({FAST_CONTRACT_SHA}), Pattern A production closure는 {PATTERN_A_FROZEN_SHA}로 고정한다. 결과 라벨별 점수 median/IQR, positive-vs-TOO_EARLY median 차이와 Cliff's delta, 단계 confusion matrix·분포·정확 일치(기술통계), clean primary pairing의 lead weeks median/IQR를 계산한다. pairing precedence는 DATA_UNAVAILABLE → PATTERN_A_ALREADY_ACTIVE → PATTERN_A_PRIOR_ACTIVITY_BEFORE_FAST_EVENT → SAME_WEEK → FAST_EARLIER_PATTERN_A_LATER → FAST_EVENT_NO_PATTERN_A_CATCHUP 순서다.

가용성은 Pattern A를 먼저 확인한다. Fast stage-ready coverage < 0.80 또는 Fast score unavailable > 0.20이면 OOS_DATA_COVERAGE_FAIL이며 부분 가용성은 별도 보고한다. 두 비교군 모두 n >= 3일 때 positive median이 TOO_EARLY median 이하이면 OOS_SCORE_DIRECTION_FAIL이다. clean primary n >= 3이면 median lead weeks는 0보다 커야 하며 아니면 OOS_LEAD_DIRECTION_FAIL이다. clean primary n < 3이면 OOS_LEAD_INCONCLUSIVE이다. 라벨 동결 후 재튜닝·임계값 변경·샘플 교체는 금지한다.

4. 경계
13I-1에서는 OOS에 대한 Fast 또는 Pattern A 실행, 점수/단계/후보 산출, 비교 평가를 하지 않았다. production_frozen은 false이며 다음 단계는 사람 라벨 동결 뒤의 13I-2 평가다.
""",
        encoding="utf-8",
    )


def main() -> None:
    oos, calibration = load_reserved_oos_population()
    manifest, review = build_review_tables(oos)
    OOS_DIR.mkdir(parents=True, exist_ok=True)
    review.to_csv(REVIEW_CSV, index=False)
    template_sha = _sha256_bytes(REVIEW_CSV.read_bytes())
    manifest["template_sha256"] = template_sha
    manifest = manifest[MANIFEST_COLUMNS]
    manifest.to_csv(MANIFEST_CSV, index=False)
    assets = generate_charts(manifest)
    assets.to_csv(ASSET_MANIFEST_CSV, index=False)
    protocol = build_protocol()
    PROTOCOL_JSON.write_text(json.dumps(protocol, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    audit = {
        "oos_rows": 20,
        "calibration_rows": len(calibration),
        "calibration_overlap": 0,
        "fast_output_columns_in_review_sheet": [],
        "pattern_a_output_columns_in_review_sheet": [],
        "model_annotations_in_stage_charts": 0,
        "model_annotations_in_outcome_charts": 0,
        "stage_chart_future_leak_count": 0,
        "unlabeled_stage_count": 20,
        "unlabeled_outcome_count": 20,
        "evaluation_run_on_oos": False,
        "human_review_template_sha256": template_sha,
        "stage_chart_count": 60,
        "outcome_chart_count": 20,
        "status": "PASS",
    }
    AUDIT_JSON.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_human_guides(manifest)
    print(f"Reserved OOS blind package ready: {len(manifest)} rows, {len(assets)} assets")


if __name__ == "__main__":
    main()
