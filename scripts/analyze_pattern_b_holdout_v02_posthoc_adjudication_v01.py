#!/usr/bin/env python3
"""Pattern B Holdout V02 post-hoc adjudication V01 (diagnosis only).

Record: docs/patterns/pattern_b/validation/holdout_v02_posthoc_adjudication_v01.md

The official Holdout V02 evaluation stays as sealed. This script overlays the
user's post-hoc labels for the 7 official errors of size >= 2 and computes
counterfactual diagnostics. It never rewrites official files, never runs the
state rule, and its numbers are not an independent validation.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V = ROOT / "docs/patterns/pattern_b/validation"
OFFICIAL_PREDICTIONS = V / "state_rule_v01_holdout_v02_predictions.csv"
OFFICIAL_EVALUATION_SEAL = V / "state_rule_v01_holdout_v02_evaluation_seal.json"
OFFICIAL_HGT = V / "human_ground_truth_labels_v02.csv"
FEATURES = V / "feature_raw_values_v02.csv"
POSTHOC_CSV = V / "holdout_v02_posthoc_adjudication_v01.csv"
POSTHOC_RECORD = V / "holdout_v02_posthoc_adjudication_v01.md"
POSTHOC_SEAL = V / "holdout_v02_posthoc_adjudication_v01_seal.json"

ORDINAL = {"DEEP_DEPRESSED": -2, "DEPRESSED": -1, "NORMAL": 0, "OVERHEATED": 1, "EXTREME_OVERHEATED": 2}
# User's last explicit post-hoc judgments (authoritative); AI opinions are not used.
POSTHOC_LABELS: dict[str, tuple[str, str]] = {
    "PBHOLD_012": ("NORMAL", "MEDIUM"),
    "PBHOLD_017": ("DEEP_DEPRESSED", "HIGH"),
    "PBHOLD_018": ("DEEP_DEPRESSED", "HIGH"),
    "PBHOLD_019": ("DEPRESSED", "HIGH"),
    "PBHOLD_024": ("DEPRESSED", "HIGH"),
    "PBHOLD_026": ("NORMAL", "MEDIUM"),
    "PBHOLD_028": ("OVERHEATED", "MEDIUM"),
}
FIELDS = (
    "sample_id", "official_hgt_label", "official_confidence", "automatic_label", "official_absolute_error",
    "posthoc_label", "posthoc_confidence", "posthoc_ordinal_error", "posthoc_absolute_error",
)
KEEP = ("36M_RANGE_POSITION", "MONTHLY_MA24_DISTANCE", "52W_RANGE_POSITION")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def verify_official() -> dict:
    seal = json.loads(OFFICIAL_EVALUATION_SEAL.read_text(encoding="utf-8"))
    if seal["predictions_file_sha256"] != sha256(OFFICIAL_PREDICTIONS) or \
            seal["hgt_v02_labels_sha256"] != sha256(OFFICIAL_HGT):
        raise SystemExit("CHECK_REQUIRED: official Holdout V02 files differ from the evaluation seal")
    return seal


def build_rows(predictions: list[dict], hgt: list[dict]) -> list[dict]:
    pred = {r["sample_id"]: r for r in predictions}
    human = {r["sample_id"]: r for r in hgt}
    big = sorted(s for s, r in pred.items() if int(r["absolute_error"]) >= 2)
    if big != sorted(POSTHOC_LABELS):
        raise SystemExit(f"CHECK_REQUIRED: official >=2 errors {big} differ from the adjudicated set")
    rows = []
    for sid in sorted(POSTHOC_LABELS):
        label, confidence = POSTHOC_LABELS[sid]
        if pred[sid]["human_label"] != human[sid]["label"]:
            raise SystemExit(f"CHECK_REQUIRED: {sid} official HGT mismatch")
        error = ORDINAL[pred[sid]["automatic_label"]] - ORDINAL[label]
        rows.append({
            "sample_id": sid,
            "official_hgt_label": human[sid]["label"],
            "official_confidence": human[sid]["confidence"],
            "automatic_label": pred[sid]["automatic_label"],
            "official_absolute_error": int(pred[sid]["absolute_error"]),
            "posthoc_label": label,
            "posthoc_confidence": confidence,
            "posthoc_ordinal_error": error,
            "posthoc_absolute_error": abs(error),
        })
    return rows


def _counts(errors: list[int]) -> dict:
    n = len(errors)
    return {
        "sample_count": n,
        "exact_match_count": sum(e == 0 for e in errors),
        "within_1_count": sum(e <= 1 for e in errors),
        "absolute_error_sum": sum(errors),
        "ordinal_mae": round(sum(errors) / n, 4),
        "error_ge_2_count": sum(e >= 2 for e in errors),
        "error_ge_3_count": sum(e >= 3 for e in errors),
    }


def diagnostics(rows: list[dict], predictions: list[dict]) -> dict:
    overlay = {r["sample_id"]: r["posthoc_label"] for r in rows}
    full = [abs(ORDINAL[p["automatic_label"]] - ORDINAL[overlay.get(p["sample_id"], p["human_label"])])
            for p in predictions]
    remaining = [r["sample_id"] for r in rows if r["posthoc_absolute_error"] >= 2]
    return {"subset": _counts([r["posthoc_absolute_error"] for r in rows]), "full": _counts(full),
            "remaining_ge_2": remaining}


def render_record(rows: list[dict], d: dict, official: dict, features: dict) -> str:
    s, f = d["subset"], d["full"]
    f028 = features["PBHOLD_028"]
    L: list[str] = []
    add = L.append
    add("# Pattern B 별도 검증 표본 V02 사후진단 V01\n")
    add("> 상태: 사후진단(post-hoc adjudication) 기록. 공식 평가를 바꾸거나 다시 평가한 것이 아니다.")
    add("> 이 수치로 상태 판정 규칙 V01의 독립 검증 결과를 주장할 수 없다.\n")
    add("이 문서는 `scripts/analyze_pattern_b_holdout_v02_posthoc_adjudication_v01.py`가 생성한다.\n")
    add("## 1. 목적과 범위\n")
    add("[공식 평가](state_rule_v01_holdout_v02_evaluation.md)에서 순서 오차가 2단계 이상이었던 7개 "
        "표본을, 사용자가 명확해진 \"현재 상태\" 판정 기준으로 다시 본 결과를 기록한다. 공식 사람 판정 "
        "V02, 공식 자동 판정, 공식 평가와 그 봉인은 바꾸지 않았다.\n")
    add("## 2. 해석 제한\n")
    add("- 별도 검증 표본 V02의 공식 평가는 그대로 유효하며, 소진된 상태다.")
    add("- 이번 7개 재판정은 공식 평가 결과를 본 뒤에 했다.")
    add("- 사용자는 대형 오류 표본 번호와 기존 자동 판정 결과를 알고 있었다. 따라서 사후 판정은 "
        "자동 판정에 대해 가려진 판정이 아니다.")
    add("- 이 결과는 오류 원인 진단과 다음 사람 판정 기준·규칙 버전 설계에만 쓴다.")
    add("- 사후 판정값은 사용자의 마지막 명시 판정이다. `PBHOLD_018`에서 AI가 낸 `DEPRESSED` / "
        "`MEDIUM` 의견은 채택되지 않았고, 사용자 판정 `DEEP_DEPRESSED` / `HIGH`를 썼다.\n")
    add("## 3. 사후 판정 기준\n")
    add("평가 시점의 오른쪽 마지막 가격이 자기 장기 가격 사이클에서 현재 어느 위치에 있는지를 먼저 "
        "본다. 과거 급등·폭락, 차트 왼쪽 시작 가격 대비 배수, 과거 최고점은 현재 위치를 이해하는 보조 "
        "맥락으로만 쓴다. 과거에 극단 과열이었다는 사실만으로 그 상태를 현재까지 유지하지 않고, 고점 "
        "대비 하락 폭이 크다는 이유만으로 극단 침체로 보지 않는다. 월봉이 핵심이고 주봉은 현재 "
        "극단성을 보조로 확인한다.\n")
    add("## 4. 사후 재판정 7개\n")
    add("| sample_id | 공식 사람 판정 | 공식 자동 판정 | 공식 오차 | 사후 판정 | 사후 신뢰도 | 사후 순서 오차 |")
    add("|---|---|---|---|---|---|---|")
    for r in rows:
        add(f"| `{r['sample_id']}` | `{r['official_hgt_label']}` | `{r['automatic_label']}` | "
            f"{r['official_absolute_error']} | `{r['posthoc_label']}` | `{r['posthoc_confidence']}` | "
            f"{r['posthoc_ordinal_error']:+d} |")
    add("\n순서 값은 공식 평가와 같다(`DEEP_DEPRESSED`=−2 ~ `EXTREME_OVERHEATED`=+2, 오차 = 자동 − 사후).\n")
    add("## 5. 진단 지표\n")
    add("### 7개 표본\n")
    add(f"- 정확 일치 {s['exact_match_count']}/7, 1단계 이내 {s['within_1_count']}/7, "
        f"2단계 이상 {s['error_ge_2_count']}/7, 3단계 이상 {s['error_ge_3_count']}/7\n")
    add("### 전체 36개 반사실 진단 (공식 수치 아님)\n")
    add("공식 사람 판정 중 위 7개만 사후 판정으로 바꿔 계산한 진단용 수치다.\n")
    add("| 지표 | 진단값 | 공식 평가 |")
    add("|---|---|---|")
    add(f"| 정확 일치 | {f['exact_match_count']}/36 ({f['exact_match_count'] / 36:.4f}) | "
        f"{official['exact_match_count']}/36 |")
    add(f"| 1단계 이내 | {f['within_1_count']}/36 ({f['within_1_count'] / 36:.4f}) | "
        f"{official['within_1_count']}/36 |")
    add(f"| 순서 평균절대오차 | {f['ordinal_mae']:.4f} | {official['ordinal_mae']:.4f} |")
    add(f"| 2단계 이상 오류 | {f['error_ge_2_count']} | {official['error_ge_2_count']} |")
    add(f"| 3단계 이상 오류 | {f['error_ge_3_count']} | {official['error_ge_3_count']} |")
    add("")
    add("## 6. 진단 결론 (사실)\n")
    exact = sum(r["posthoc_absolute_error"] == 0 for r in rows)
    one = [r["sample_id"] for r in rows if r["posthoc_absolute_error"] == 1]
    add(f"공식 대형 오류 7개 중 사후 판정이 자동 판정과 정확히 같은 표본은 {exact}개, 1단계 차이로 "
        f"줄어든 표본은 {len(one)}개({', '.join(f'`{x}`' for x in one)}), 2단계 오류가 남은 표본은 "
        f"{len(d['remaining_ge_2'])}개({', '.join(f'`{x}`' for x in d['remaining_ge_2'])}), 3단계 "
        f"오류가 남은 표본은 {s['error_ge_3_count']}개다.\n")
    add("이는 공식 사람 판정 V02의 일부 대형 오류에 \"현재 상태\"와 \"과거 급등·폭락 경로\"를 섞은 "
        "판정 기준의 흔들림이 포함됐을 **가능성**을 보여 주는 사후진단 근거다. 확정된 사실은 아니다.\n")
    add("## 7. 남는 핵심 오류 후보: `PBHOLD_028`\n")
    add("| 항목 | 값 |")
    add("|---|---|")
    for k in KEEP:
        add(f"| `{k}` | {float(f028[k]):+.3f} |")
    add("| 사후 판정 | `OVERHEATED` / `MEDIUM` |")
    add("| 자동 판정 | `DEPRESSED` |")
    add("")
    add("해석 후보: 급격한 초고점 이후 범위 위치 지표는 낮아졌지만 현재 가격은 장기 정상 가격대와 "
        "24개월 이동평균보다 여전히 높은 경우, 규칙안 C가 36개월 범위 위치를 과도하게 우선할 수 있다. "
        "이번 작업에서는 규칙을 바꾸지 않았고, 이 표본을 위한 예외 규칙도 만들지 않는다.\n")
    add("## 8. 다음 사람 판정 기준 후보\n")
    add("다음 버전에서 검토할 원칙 후보다. 기존 [사람 판정 기준 V01](human_ground_truth_v01.md)은 바꾸지 "
        "않았다.\n")
    add("1. 오른쪽 마지막 가격의 현재 장기 위치를 우선한다.")
    add("2. 왼쪽 첫 가격 대비 상승 배수를 상태 판정 기준으로 쓰지 않는다.")
    add("3. 과거 최고점은 현재 상태를 유지시키는 근거가 아니다.")
    add("4. 고점 대비 큰 하락만으로 `DEEP_DEPRESSED`를 주지 않는다.")
    add("5. 현재 가격이 장기 범위의 어디에 있는지 월봉 중심으로 본다.")
    add("6. 주봉은 현재 극단성의 보조 확인이다.")
    add("7. 과거 경로·사이클 이력이 필요하면 현재 상태와 별도 축으로 연구한다.\n")
    add("## 9. 산출물\n")
    add("- 표본별 결과: [holdout_v02_posthoc_adjudication_v01.csv](holdout_v02_posthoc_adjudication_v01.csv)")
    add("- 봉인: [holdout_v02_posthoc_adjudication_v01_seal.json](holdout_v02_posthoc_adjudication_v01_seal.json)")
    add("- 별도 검증 표본 V02는 이후 규칙 검증에 다시 쓰지 않는다.")
    return "\n".join(L) + "\n"


def main() -> None:
    official = verify_official()
    predictions = _read(OFFICIAL_PREDICTIONS)
    rows = build_rows(predictions, _read(OFFICIAL_HGT))
    d = diagnostics(rows, predictions)
    features = {r["sample_id"]: r for r in _read(FEATURES)}
    with POSTHOC_CSV.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    POSTHOC_RECORD.write_text(render_record(rows, d, official, features), encoding="utf-8")
    seal = {
        "version": "PATTERN_B_HOLDOUT_V02_POSTHOC_ADJUDICATION_V01",
        "official_holdout_unchanged": True,
        "posthoc_only": True,
        "automatic_prediction_blind": False,
        "judge": "user",
        "sample_count": len(rows),
        "sample_ids": [r["sample_id"] for r in rows],
        "subset_diagnostic": d["subset"],
        "full_counterfactual_diagnostic": d["full"],
        "remaining_error_ge_2": d["remaining_ge_2"],
        "official_evaluation_seal_sha256": sha256(OFFICIAL_EVALUATION_SEAL),
        "official_predictions_sha256": sha256(OFFICIAL_PREDICTIONS),
        "official_hgt_labels_sha256": sha256(OFFICIAL_HGT),
        "posthoc_csv_sha256": sha256(POSTHOC_CSV),
        "posthoc_record_sha256": sha256(POSTHOC_RECORD),
    }
    POSTHOC_SEAL.write_text(json.dumps(seal, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(d, indent=2))


if __name__ == "__main__":
    main()
