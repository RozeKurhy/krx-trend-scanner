#!/usr/bin/env python3
"""Pattern B HGT V01 x raw Feature V01 fitness diagnostics (diagnosis only).

Report: docs/patterns/pattern_b/validation/feature_fitness_v01.md

Inputs are the two sealed public files joined on sample_id; no private manifest,
ticker, as_of, or future return is read. The HGT ordinal (0~4) is an internal
ordering for rank diagnostics only, not a score or state rule. Nothing here
decides KEEP/MODIFY/DROP, thresholds, weights, or states.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
VALIDATION_DIR = ROOT / "docs/patterns/pattern_b/validation"
DEFAULT_HGT = VALIDATION_DIR / "human_ground_truth_labels_v01.csv"
DEFAULT_RAW = VALIDATION_DIR / "feature_raw_values_v01.csv"
DEFAULT_REPORT = VALIDATION_DIR / "feature_fitness_v01.md"

SAMPLE_IDS = tuple(f"PBHGT_{i:03d}" for i in range(1, 37))
LABEL_ORDER = ("DEEP_DEPRESSED", "DEPRESSED", "NORMAL", "OVERHEATED", "EXTREME_OVERHEATED")
ORDINAL = {label: i for i, label in enumerate(LABEL_ORDER)}
EXPECTED_LABEL_COUNTS = {
    "DEEP_DEPRESSED": 2, "DEPRESSED": 4, "NORMAL": 12, "OVERHEATED": 8, "EXTREME_OVERHEATED": 10,
}
EXPECTED_CONFIDENCE_COUNTS = {"HIGH": 22, "MEDIUM": 14, "LOW": 0}
HGT_COLUMNS = ("sample_id", "label", "confidence", "note")
FEATURES = (
    "36M_RANGE_POSITION",
    "MONTHLY_MA24_DISTANCE",
    "12M_RETURN_HISTORICAL_PERCENTILE",
    "36M_HIGH_DRAWDOWN",
    "52W_RANGE_POSITION",
    "WEEKLY_MA40_DISTANCE",
    "26W_RETURN_HISTORICAL_PERCENTILE",
)
RAW_COLUMNS = ("sample_id",) + tuple(c for f in FEATURES for c in (f, f"{f}_status"))
ADJACENT_PAIRS = tuple(zip(LABEL_ORDER[:-1], LABEL_ORDER[1:]))


class InputContractError(ValueError):
    """A sealed input does not match its contract; analysis must not run (CHECK_REQUIRED)."""


def _check_ids(ids: pd.Series, name: str) -> None:
    if ids.duplicated().any() or sorted(ids) != list(SAMPLE_IDS):
        raise InputContractError(f"{name}: sample_id set is not PBHGT_001~036 exactly once")


def validate_hgt(hgt: pd.DataFrame) -> None:
    if tuple(hgt.columns) != HGT_COLUMNS:
        raise InputContractError(f"HGT columns {list(hgt.columns)} != {list(HGT_COLUMNS)}")
    _check_ids(hgt["sample_id"], "HGT")
    labels = hgt["label"].value_counts().to_dict()
    if labels != EXPECTED_LABEL_COUNTS:
        raise InputContractError(f"HGT label counts {labels} != {EXPECTED_LABEL_COUNTS}")
    confidence = {k: int((hgt["confidence"] == k).sum()) for k in EXPECTED_CONFIDENCE_COUNTS}
    if confidence != EXPECTED_CONFIDENCE_COUNTS or not hgt["confidence"].isin(EXPECTED_CONFIDENCE_COUNTS).all():
        raise InputContractError(f"HGT confidence counts {confidence} != {EXPECTED_CONFIDENCE_COUNTS}")


def validate_raw(raw: pd.DataFrame) -> None:
    if tuple(raw.columns) != RAW_COLUMNS:
        raise InputContractError(f"raw feature columns != the 15-column public contract")
    _check_ids(raw["sample_id"], "raw features")
    for feature in FEATURES:
        if not (raw[f"{feature}_status"] == "OK").all():
            raise InputContractError(f"{feature}: status other than OK")
        if raw[feature].isna().any():
            raise InputContractError(f"{feature}: missing value")


def load_joined(hgt: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
    validate_hgt(hgt)
    validate_raw(raw)
    if set(hgt["sample_id"]) != set(raw["sample_id"]):
        raise InputContractError("HGT and raw feature sample_id sets differ")
    joined = hgt[["sample_id", "label", "confidence"]].merge(
        raw[["sample_id", *FEATURES]], on="sample_id", how="inner", validate="one_to_one"
    )
    if len(joined) != len(SAMPLE_IDS):
        raise InputContractError(f"join produced {len(joined)} rows")
    joined["ordinal"] = joined["label"].map(ORDINAL)
    return joined.sort_values("sample_id").reset_index(drop=True)


def spearman(x, y) -> float:
    """Spearman rho: Pearson correlation of average ranks (ties share the mean rank)."""
    rx = pd.Series(np.asarray(x, dtype=float)).rank(method="average").to_numpy()
    ry = pd.Series(np.asarray(y, dtype=float)).rank(method="average").to_numpy()
    return float(np.corrcoef(rx, ry)[0, 1])


def label_summary(df: pd.DataFrame, feature: str) -> pd.DataFrame:
    """n, median, Q1, Q3, min, max per label (pandas linear-interpolation quantiles)."""
    rows = []
    for label in LABEL_ORDER:
        values = df.loc[df["label"] == label, feature]
        rows.append({
            "label": label,
            "n": int(len(values)),
            "median": values.median() if len(values) else np.nan,
            "q1": values.quantile(0.25) if len(values) else np.nan,
            "q3": values.quantile(0.75) if len(values) else np.nan,
            "min": values.min() if len(values) else np.nan,
            "max": values.max() if len(values) else np.nan,
        })
    return pd.DataFrame(rows).set_index("label")


def median_ordering(summary: pd.DataFrame) -> list[dict]:
    out = []
    for left, right in ADJACENT_PAIRS:
        diff = summary.at[right, "median"] - summary.at[left, "median"]
        out.append({"pair": (left, right), "diff": diff, "expected": bool(diff > 0) if pd.notna(diff) else None})
    return out


def iqr_overlap(summary: pd.DataFrame) -> list[dict]:
    out = []
    for left, right in ADJACENT_PAIRS:
        lq = (summary.at[left, "q1"], summary.at[left, "q3"])
        rq = (summary.at[right, "q1"], summary.at[right, "q3"])
        valid = all(pd.notna(v) for v in lq + rq)
        overlap = bool(max(lq[0], rq[0]) <= min(lq[1], rq[1])) if valid else None
        out.append({"pair": (left, right), "left": lq, "right": rq, "overlap": overlap})
    return out


def feature_correlation(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        [[spearman(df[a], df[b]) for b in FEATURES] for a in FEATURES], index=FEATURES, columns=FEATURES
    )


def top_pairs(corr: pd.DataFrame, k: int = 5) -> list[tuple[str, str, float]]:
    pairs = [(a, b, corr.at[a, b]) for i, a in enumerate(FEATURES) for b in FEATURES[i + 1:]]
    return sorted(pairs, key=lambda p: abs(p[2]), reverse=True)[:k]


def diagnose(df: pd.DataFrame) -> dict:
    high = df[df["confidence"] == "HIGH"]
    per_feature = {}
    for feature in FEATURES:
        summary_all = label_summary(df, feature)
        summary_high = label_summary(high, feature)
        per_feature[feature] = {
            "summary": summary_all,
            "ordering": median_ordering(summary_all),
            "ordering_high": median_ordering(summary_high),
            "overlap": iqr_overlap(summary_all),
            "spearman_all": spearman(df[feature], df["ordinal"]),
            "spearman_high": spearman(high[feature], high["ordinal"]),
        }
    corr = feature_correlation(df)
    return {
        "per_feature": per_feature,
        "corr": corr,
        "top_pairs": top_pairs(corr),
        "high_label_counts": {l: int((high["label"] == l).sum()) for l in LABEL_ORDER},
        "medium": df[df["confidence"] == "MEDIUM"][["sample_id", "label", *FEATURES]],
    }


# --- report ------------------------------------------------------------------

SHORT = {
    "DEEP_DEPRESSED": "DEEP", "DEPRESSED": "DEP", "NORMAL": "NORM",
    "OVERHEATED": "OVH", "EXTREME_OVERHEATED": "EXT",
}
FEATURE_SHORT = {
    "36M_RANGE_POSITION": "M36_RP", "MONTHLY_MA24_DISTANCE": "M_MA24",
    "12M_RETURN_HISTORICAL_PERCENTILE": "M_R12P", "36M_HIGH_DRAWDOWN": "M36_DD",
    "52W_RANGE_POSITION": "W52_RP", "WEEKLY_MA40_DISTANCE": "W_MA40",
    "26W_RETURN_HISTORICAL_PERCENTILE": "W_R26P",
}


def _f(v, digits: int = 3) -> str:
    return "—" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.{digits}f}"


def _pair(p) -> str:
    return f"{SHORT[p[0]]}→{SHORT[p[1]]}"


def _yn(v) -> str:
    return "—" if v is None else ("예" if v else "아니오")


def _observations(feature: str, r: dict, high_counts: dict) -> list[str]:
    ordered = [o for o in r["ordering"] if o["expected"]]
    reversed_ = [_pair(o["pair"]) for o in r["ordering"] if o["expected"] is False]
    overlaps = [_pair(o["pair"]) for o in r["overlap"] if o["overlap"]]
    lines = [f"인접 4구간 중 {len(ordered)}구간에서 median이 기대 방향으로 증가했다"
             + (f" (역전·동률: {', '.join(reversed_)})." if reversed_ else ".")]
    lines.append("인접 IQR이 겹치는 구간: " + (", ".join(overlaps) if overlaps else "없음") + ".")
    diff = r["spearman_high"] - r["spearman_all"]
    direction = "높다" if diff > 0 else "낮다" if diff < 0 else "같다"
    lines.append(f"Spearman은 전체 {_f(r['spearman_all'])}, HIGH-only {_f(r['spearman_high'])}로 "
                 f"HIGH-only가 {abs(diff):.3f} {direction}.")
    rev_high = [_pair(o["pair"]) for o in r["ordering_high"] if o["expected"] is False]
    if rev_high:
        thin = [p for p in r["ordering_high"] if _thin(p, high_counts)]
        note = " (HIGH에서 표본 1개 이하인 label이 걸린 구간 포함)" if thin else ""
        lines.append(f"HIGH-only median 역전·동률 구간: {', '.join(rev_high)}{note}.")
    return lines


def _thin(o: dict, high_counts: dict) -> bool:
    return o["expected"] is False and min(high_counts[o["pair"][0]], high_counts[o["pair"][1]]) <= 1


def render_report(df: pd.DataFrame, result: dict) -> str:
    L: list[str] = []
    add = L.append
    counts = df["label"].value_counts()
    add("# Pattern B Feature 적합성 진단 V01\n")
    add("> 상태: 진단 완료. 봉인된 사람 판정 V01과 raw Feature V01의 관계를 진단만 했다.")
    add("> Feature 유지·수정·제외 여부, 임계값, 가중치, 점수, 자동 상태 판정은 정하지 않았다.\n")
    add("이 문서는 `scripts/analyze_pattern_b_feature_fitness_v01.py`가 생성한다.\n")

    add("## 1. 목적과 입력\n")
    add("[사람 판정 V01](human_ground_truth_labels_v01.csv)과 "
        "[raw Feature V01](feature_raw_values_v01.csv)을 `sample_id`로 처음 결합해, "
        "[Feature 계약 V01](../spec/feature_contract_v01.md)의 7개 Feature가 사람의 장기 가격 "
        "사이클 판정과 어떤 관계를 보이는지 진단한다.\n")
    add("- 두 입력은 각각 봉인된 공개 파일이며 이번 진단에서 수정하지 않았다.")
    add("- 비공개 대응표, ticker, 기준일, 미래 수익률은 사용하지 않았다.")
    add("- 판정 순서 값(`DEEP_DEPRESSED`=0 ~ `EXTREME_OVERHEATED`=4)은 순위 진단용 내부 표현이며 "
        "점수나 상태 규칙이 아니다. 7개 Feature 모두 값이 클수록 과열 방향을 기대한다.\n")

    add("## 2. 결합 검증\n")
    add(f"- 결합: {len(df)}/36, `PBHGT_001`~`PBHGT_036` 각 1회")
    add("- label: " + ", ".join(f"`{l}` {int(counts.get(l, 0))}" for l in LABEL_ORDER))
    add("- confidence: " + ", ".join(
        f"`{c}` {int((df['confidence'] == c).sum())}" for c in EXPECTED_CONFIDENCE_COUNTS))
    add(f"- raw Feature: 7개 × 36 = {7 * len(df)}개 값 모두 `OK`")
    add("- HIGH-only label 수: " + ", ".join(
        f"`{l}` {result['high_label_counts'][l]}" for l in LABEL_ORDER) + "\n")

    add("## 3. Feature별 label 분포\n")
    add("분위수는 선형 보간이다. `DEEP_DEPRESSED`는 n=2라 Q1·Q3가 두 값 사이의 보간값이다.\n")
    for feature in FEATURES:
        s = result["per_feature"][feature]["summary"]
        add(f"### `{feature}`\n")
        add("| label | n | median | Q1 | Q3 | min | max |")
        add("|---|---|---|---|---|---|---|")
        for label in LABEL_ORDER:
            row = s.loc[label]
            add(f"| `{label}` | {int(row['n'])} | {_f(row['median'])} | {_f(row['q1'])} | "
                f"{_f(row['q3'])} | {_f(row['min'])} | {_f(row['max'])} |")
        add("")

    add("## 4. median 순서\n")
    add("인접 label의 median 차이(오른쪽 − 왼쪽)다. 양수면 기대 방향이다. "
        "약어: DEEP=`DEEP_DEPRESSED`, DEP=`DEPRESSED`, NORM=`NORMAL`, OVH=`OVERHEATED`, "
        "EXT=`EXTREME_OVERHEATED`.\n")
    add("| Feature | " + " | ".join(_pair(p) for p in ADJACENT_PAIRS) + " |")
    add("|---|" + "---|" * len(ADJACENT_PAIRS))
    for feature in FEATURES:
        cells = [f"{_f(o['diff'])} {'✓' if o['expected'] else '✗'}"
                 for o in result["per_feature"][feature]["ordering"]]
        add(f"| `{feature}` | " + " | ".join(cells) + " |")
    add("")

    add("## 5. Spearman 순위 상관 (전체 / HIGH-only)\n")
    add("고정 연구 표본이므로 유의성 판단 없이 진단 지표로만 본다. "
        "HIGH-only의 median 순서는 표본이 적은 label이 있어 참고용이다.\n")
    add("| Feature | 전체 (n=36) | HIGH-only (n=22) | 차이 | HIGH-only median 역전·동률 |")
    add("|---|---|---|---|---|")
    for feature in FEATURES:
        r = result["per_feature"][feature]
        rev = [_pair(o["pair"]) for o in r["ordering_high"] if o["expected"] is False]
        add(f"| `{feature}` | {_f(r['spearman_all'])} | {_f(r['spearman_high'])} | "
            f"{_f(r['spearman_high'] - r['spearman_all'])} | {', '.join(rev) if rev else '없음'} |")
    add("")

    add("## 6. 인접 label IQR 겹침\n")
    add("`DEEP_DEPRESSED`(n=2)와 `DEPRESSED`(n=4)가 걸린 구간은 표본이 적어 과도하게 해석하지 않는다.\n")
    add("| Feature | 구간 | 왼쪽 IQR | 오른쪽 IQR | 겹침 |")
    add("|---|---|---|---|---|")
    for feature in FEATURES:
        for o in result["per_feature"][feature]["overlap"]:
            add(f"| `{feature}` | {_pair(o['pair'])} | {_f(o['left'][0])} ~ {_f(o['left'][1])} | "
                f"{_f(o['right'][0])} ~ {_f(o['right'][1])} | {_yn(o['overlap'])} |")
    add("")

    add("## 7. Feature 간 상관\n")
    add("36개 전체의 Spearman 상관이다. 약어: " + ", ".join(
        f"{v}=`{k}`" for k, v in FEATURE_SHORT.items()) + ".\n")
    add("| | " + " | ".join(FEATURE_SHORT[f] for f in FEATURES) + " |")
    add("|---|" + "---|" * len(FEATURES))
    for a in FEATURES:
        add(f"| {FEATURE_SHORT[a]} | " + " | ".join(_f(result["corr"].at[a, b], 2) for b in FEATURES) + " |")
    add("\n절대 상관이 큰 순서 상위 5쌍:\n")
    for i, (a, b, v) in enumerate(result["top_pairs"], start=1):
        add(f"{i}. `{a}` – `{b}`: {_f(v)}")
    add("")

    add("## 8. MEDIUM confidence 표본 14개\n")
    add("다음 단계에서 경계 사례를 사람이 직접 검토하기 위한 표다. 자동 분류는 붙이지 않았다.\n")
    add("| sample_id | label | " + " | ".join(FEATURE_SHORT[f] for f in FEATURES) + " |")
    add("|---|---|" + "---|" * len(FEATURES))
    for _, row in result["medium"].iterrows():
        add(f"| `{row['sample_id']}` | `{row['label']}` | "
            + " | ".join(_f(row[f]) for f in FEATURES) + " |")
    add("")

    add("## 9. 관찰 사항\n")
    add("표의 수치를 옮긴 사실만 적는다.\n")
    for feature in FEATURES:
        add(f"**`{feature}`**\n")
        for line in _observations(feature, result["per_feature"][feature], result["high_label_counts"]):
            add(f"- {line}")
        add("")
    add("**Feature 간 상관**\n")
    for a, b, v in result["top_pairs"]:
        add(f"- `{a}`와 `{b}`의 Spearman 상관은 {_f(v)}다.")
    add("")
    add("**한계**\n")
    add("- 36개는 12종목 × 기준일 3개라 같은 종목의 표본끼리 독립이 아니다. 상관은 독립 "
        "표본 36개보다 과장될 수 있다.")
    add("- `DEEP_DEPRESSED`는 2개, `DEPRESSED`는 4개(HIGH-only 1개)라 하단 구간의 순서·겹침은 "
        "불안정하다.\n")

    add("## 10. 다음 단계\n")
    add("이 진단을 근거로 Feature별 검토를 거쳐 유지·수정·제외 여부를 정한다. 그 전에는 "
        "임계값, 가중치, 상태 규칙을 만들지 않는다.")
    return "\n".join(L) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hgt", type=Path, default=DEFAULT_HGT)
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    hgt = pd.read_csv(args.hgt, dtype=str, keep_default_na=False)
    raw = pd.read_csv(args.raw, dtype={"sample_id": str})
    df = load_joined(hgt, raw)
    result = diagnose(df)
    args.report.write_text(render_report(df, result), encoding="utf-8")
    for feature in FEATURES:
        r = result["per_feature"][feature]
        print(f"{feature}: spearman all={r['spearman_all']:.3f} high={r['spearman_high']:.3f} "
              f"ordering={[o['expected'] for o in r['ordering']]} overlap={[o['overlap'] for o in r['overlap']]}")
    for a, b, v in result["top_pairs"]:
        print(f"corr {a} ~ {b}: {v:.3f}")


if __name__ == "__main__":
    main()
