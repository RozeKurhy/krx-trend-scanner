#!/usr/bin/env python3
"""Official one-time evaluation of sealed State Rule V01 on sealed Holdout V02.

Record: docs/patterns/pattern_b/validation/state_rule_v01_holdout_v02_evaluation.md

Order: verify the three seals -> apply the sealed rule function to all 36 feature
rows -> join the sealed HGT V02 labels -> compute metrics once -> write the
predictions, the record, and the seal. The rule logic and thresholds are never
copied here; ``classify_pattern_b_state_v01`` is called as sealed.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from trend_scanner.patterns.pattern_b_state_v01 import STATES, classify_pattern_b_state_v01

ROOT = Path(__file__).resolve().parents[1]
V = ROOT / "docs/patterns/pattern_b/validation"
RULE_PATH = ROOT / "src/trend_scanner/patterns/pattern_b_state_v01.py"
RULE_SEAL = V / "state_rule_v01_seal.json"
FEATURES = V / "feature_raw_values_v02.csv"
FEATURE_SEAL = V / "feature_raw_values_v02_seal.json"
LABELS = V / "human_ground_truth_labels_v02.csv"
LABEL_SEAL = V / "human_ground_truth_v02_seal.json"
PREDICTIONS = V / "state_rule_v01_holdout_v02_predictions.csv"
RECORD = V / "state_rule_v01_holdout_v02_evaluation.md"
SEAL = V / "state_rule_v01_holdout_v02_evaluation_seal.json"

SAMPLE_IDS = [f"PBHOLD_{i:03d}" for i in range(1, 37)]
KEEP = ("36M_RANGE_POSITION", "MONTHLY_MA24_DISTANCE", "52W_RANGE_POSITION")
ORDINAL = {"DEEP_DEPRESSED": -2, "DEPRESSED": -1, "NORMAL": 0, "OVERHEATED": 1, "EXTREME_OVERHEATED": 2}
PREDICTION_FIELDS = ("sample_id", "human_label", "confidence", "automatic_label", "ordinal_error", "absolute_error")
SHORT = {"DEEP_DEPRESSED": "DEEP", "DEPRESSED": "DEP", "NORMAL": "NORM",
         "OVERHEATED": "OVH", "EXTREME_OVERHEATED": "EXT"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def verify_seals() -> None:
    rule = json.loads(RULE_SEAL.read_text(encoding="utf-8"))
    feat = json.loads(FEATURE_SEAL.read_text(encoding="utf-8"))
    hgt = json.loads(LABEL_SEAL.read_text(encoding="utf-8"))
    checks = {
        "state rule file": rule["rule_file_sha256"] == sha256(RULE_PATH),
        "feature raw values": feat["raw_values_file_sha256"] == sha256(FEATURES),
        "HGT V02 labels": hgt["labels_file_sha256"] == sha256(LABELS),
    }
    failed = [k for k, ok in checks.items() if not ok]
    if failed:
        raise SystemExit(f"CHECK_REQUIRED: seal mismatch: {failed}")


def predict(features: list[dict], labels: list[dict]) -> list[dict]:
    """Apply the sealed rule to all rows first, then join the human labels."""
    for name, rows in (("features", features), ("labels", labels)):
        ids = [r["sample_id"] for r in rows]
        if sorted(ids) != SAMPLE_IDS or len(set(ids)) != 36:
            raise SystemExit(f"CHECK_REQUIRED: {name} sample set is not PBHOLD_001~036")
    automatic = {
        r["sample_id"]: classify_pattern_b_state_v01(*(float(r[k]) for k in KEEP)) for r in features
    }
    human = {r["sample_id"]: r for r in labels}
    out = []
    for sid in SAMPLE_IDS:
        error = ORDINAL[automatic[sid]] - ORDINAL[human[sid]["label"]]
        out.append({
            "sample_id": sid, "human_label": human[sid]["label"], "confidence": human[sid]["confidence"],
            "automatic_label": automatic[sid], "ordinal_error": error, "absolute_error": abs(error),
        })
    return out


def metrics(rows: list[dict]) -> dict:
    n = len(rows)
    abs_err = [r["absolute_error"] for r in rows]
    signed = [r["ordinal_error"] for r in rows]
    high = [r for r in rows if r["confidence"] == "HIGH"]
    high_abs = [r["absolute_error"] for r in high]
    extremes = {}
    for label in ("DEEP_DEPRESSED", "EXTREME_OVERHEATED"):
        sub = [r for r in rows if r["human_label"] == label]
        extremes[label] = {
            "sample_count": len(sub),
            "exact_match_count": sum(r["absolute_error"] == 0 for r in sub),
            "within_1_count": sum(r["absolute_error"] <= 1 for r in sub),
            "error_ge_2_count": sum(r["absolute_error"] >= 2 for r in sub),
        }
    extremes["combined"] = {k: sum(extremes[l][k] for l in ("DEEP_DEPRESSED", "EXTREME_OVERHEATED"))
                            for k in extremes["DEEP_DEPRESSED"]}
    confusion = {h: {a: sum(r["human_label"] == h and r["automatic_label"] == a for r in rows) for a in STATES}
                 for h in STATES}
    return {
        "sample_count": n,
        "exact_match_count": sum(e == 0 for e in abs_err),
        "exact_match_rate": round(sum(e == 0 for e in abs_err) / n, 4),
        "within_1_count": sum(e <= 1 for e in abs_err),
        "within_1_rate": round(sum(e <= 1 for e in abs_err) / n, 4),
        "ordinal_mae": round(sum(abs_err) / n, 4),
        "error_ge_2_count": sum(e >= 2 for e in abs_err),
        "error_ge_3_count": sum(e >= 3 for e in abs_err),
        "high_count": len(high),
        "high_exact_match_count": sum(e == 0 for e in high_abs),
        "high_exact_match_rate": round(sum(e == 0 for e in high_abs) / len(high), 4),
        "high_ordinal_mae": round(sum(high_abs) / len(high), 4),
        "high_error_ge_2_count": sum(e >= 2 for e in high_abs),
        "negative_error_count": sum(e < 0 for e in signed),
        "zero_error_count": sum(e == 0 for e in signed),
        "positive_error_count": sum(e > 0 for e in signed),
        "mean_signed_error": round(sum(signed) / n, 4),
        "extremes": extremes,
        "confusion": confusion,
    }


def _errors_table(rows: list[dict], minimum: int) -> list[str]:
    big = [r for r in rows if r["absolute_error"] >= minimum]
    if not big:
        return ["0건", ""]
    lines = ["| sample_id | 사람 판정 | 자동 판정 | 신뢰도 | 순서 오차 |", "|---|---|---|---|---|"]
    lines += [f"| `{r['sample_id']}` | `{r['human_label']}` | `{r['automatic_label']}` | "
              f"`{r['confidence']}` | {r['ordinal_error']:+d} |" for r in big]
    return lines + [""]


def render_record(m: dict, rows: list[dict]) -> str:
    L: list[str] = []
    add = L.append
    add("# Pattern B 상태 판정 규칙 V01 — 별도 검증 표본 V02 공식 평가\n")
    add("> 상태: 공식 1회 평가 완료. 별도 검증 표본 V02는 상태 판정 규칙 V01의 독립 검증에")
    add("> 사용되어 소진됐다. 이 결과를 보고 규칙을 고치면, 고친 규칙의 독립 검증에는 새")
    add("> 별도 검증 표본(V03)이 필요하다.\n")
    add("이 문서는 `scripts/evaluate_pattern_b_state_rule_v01_holdout_v02.py`가 계산과 함께 생성한다.\n")
    add("## 1. 목적과 입력\n")
    add("봉인된 [상태 판정 규칙 V01](state_rule_v01.md)(규칙안 C)을 봉인된 "
        "[별도 검증 표본 V02 원시 지표값](feature_raw_values_v02.md)에 그대로 적용하고, 봉인된 "
        "[사람 판정 V02](human_ground_truth_v02.md)와 한 번 비교한다.\n")
    add("- 세 봉인(규칙 코드, 원시 지표값, 사람 판정)의 SHA-256을 평가 전에 확인했다.")
    add("- 36개 자동 판정을 모두 만든 뒤에 사람 판정과 결합했다.")
    add("- 규칙, 임계값, 사람 판정, 지표값은 바꾸지 않았다.")
    add("- 순서 값: `DEEP_DEPRESSED`=−2, `DEPRESSED`=−1, `NORMAL`=0, `OVERHEATED`=+1, "
        "`EXTREME_OVERHEATED`=+2. 순서 오차 = 자동 − 사람.\n")
    add("## 2. 전체 36개\n")
    add("| 지표 | 값 |")
    add("|---|---|")
    add(f"| 정확 일치 | {m['exact_match_count']}/36 ({m['exact_match_rate']:.4f}) |")
    add(f"| 1단계 이내 일치 | {m['within_1_count']}/36 ({m['within_1_rate']:.4f}) |")
    add(f"| 순서 평균절대오차 | {m['ordinal_mae']:.4f} |")
    add(f"| 2단계 이상 오류 | {m['error_ge_2_count']} |")
    add(f"| 3단계 이상 오류 | {m['error_ge_3_count']} |")
    add("")
    add("## 3. 높은 신뢰도(`HIGH`)만\n")
    add("| 지표 | 값 |")
    add("|---|---|")
    add(f"| 표본 수 | {m['high_count']} |")
    add(f"| 정확 일치 | {m['high_exact_match_count']}/{m['high_count']} ({m['high_exact_match_rate']:.4f}) |")
    add(f"| 순서 평균절대오차 | {m['high_ordinal_mae']:.4f} |")
    add(f"| 2단계 이상 오류 | {m['high_error_ge_2_count']} |")
    add("")
    add("## 4. 혼동 행렬\n")
    add("행은 사람 판정, 열은 자동 판정이다.\n")
    add("| 사람 \\ 자동 | " + " | ".join(SHORT[s] for s in STATES) + " |")
    add("|---|" + "---|" * len(STATES))
    for h in STATES:
        add(f"| `{h}` | " + " | ".join(str(m["confusion"][h][a]) for a in STATES) + " |")
    add("")
    add("## 5. 방향 편향\n")
    add("| 구분 | 표본 수 |")
    add("|---|---|")
    add(f"| 자동 판정이 더 침체 쪽 (오차 < 0) | {m['negative_error_count']} |")
    add(f"| 일치 (오차 = 0) | {m['zero_error_count']} |")
    add(f"| 자동 판정이 더 과열 쪽 (오차 > 0) | {m['positive_error_count']} |")
    add(f"| 평균 부호 오차 | {m['mean_signed_error']:+.4f} |")
    add("")
    add("## 6. 극단 상태 (사람 판정 기준)\n")
    add("| 사람 판정 | 표본 수 | 정확 일치 | 1단계 이내 | 2단계 이상 오류 |")
    add("|---|---|---|---|---|")
    for key, name in (("DEEP_DEPRESSED", "`DEEP_DEPRESSED`"), ("EXTREME_OVERHEATED", "`EXTREME_OVERHEATED`"),
                      ("combined", "두 극단 합계")):
        e = m["extremes"][key]
        add(f"| {name} | {e['sample_count']} | {e['exact_match_count']} | {e['within_1_count']} | "
            f"{e['error_ge_2_count']} |")
    add("")
    add("## 7. 2단계 이상 오류 표본\n")
    L.extend(_errors_table(rows, 2))
    add("## 8. 3단계 이상 오류 표본\n")
    L.extend(_errors_table(rows, 3))
    add("## 9. 산출물과 이후 절차\n")
    add("- 표본별 결과: [state_rule_v01_holdout_v02_predictions.csv](state_rule_v01_holdout_v02_predictions.csv)")
    add("- 봉인: [state_rule_v01_holdout_v02_evaluation_seal.json](state_rule_v01_holdout_v02_evaluation_seal.json)")
    add("- 이 평가는 한 번만 수행했다. 채택 여부와 이후 연구 방향은 이 문서의 범위가 아니다.")
    return "\n".join(L) + "\n"


def main() -> None:
    verify_seals()
    rows = predict(_read(FEATURES), _read(LABELS))
    m = metrics(rows)
    with PREDICTIONS.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=PREDICTION_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    RECORD.write_text(render_record(m, rows), encoding="utf-8")
    rule_seal = json.loads(RULE_SEAL.read_text(encoding="utf-8"))
    seal = {
        "version": "PATTERN_B_STATE_RULE_V01_HOLDOUT_V02_EVALUATION",
        "official_holdout_evaluation": True,
        "holdout_consumed": True,
        "sample_count": 36,
        "state_rule_version": rule_seal["version"],
        "state_rule_family": rule_seal["rule_family"],
        "state_rule_sha256": sha256(RULE_PATH),
        "state_rule_seal_sha256": sha256(RULE_SEAL),
        "feature_raw_values_sha256": sha256(FEATURES),
        "hgt_v02_labels_sha256": sha256(LABELS),
        "ordinal_mapping": ORDINAL,
        **{k: v for k, v in m.items() if k not in ("extremes", "confusion")},
        "predictions_file_sha256": sha256(PREDICTIONS),
        "evaluation_record_sha256": sha256(RECORD),
    }
    SEAL.write_text(json.dumps(seal, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in m.items() if k != "confusion"}, indent=2))


if __name__ == "__main__":
    main()
