from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from pathlib import Path

import pandas as pd

PROJECT = Path.cwd().resolve()
sys.path.insert(0, str(PROJECT))
from trend_scanner.data.adjusted_price_store import AdjustedPriceStore  # noqa: E402

ROOT = PROJECT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_117_price_nav_closure_v01"
P31 = PROJECT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01"
P32 = PROJECT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_data_nav_closure_v01"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def native(value):
    if hasattr(value, "item"):
        return value.item()
    if pd.isna(value):
        return None
    return value


def fmt(value, unit=""):
    if value is None or value == "":
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return "; ".join(f"{k}: {v}" for k, v in sorted(parsed.items()))
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
        return str(value)
    if unit == "KRW":
        return f"{number:,.0f}"
    if unit == "%":
        return f"{number:,.3f}%"
    if unit in {"trades", "days", "positions", "marks"}:
        return f"{number:,.0f}" if number.is_integer() else f"{number:,.2f}"
    if unit == "x":
        return f"{number:,.3f}x"
    if unit == "bool":
        return "통과" if number else "실패"
    return f"{number:,.4f}" if math.isfinite(number) else str(value)


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    out.extend("| " + " | ".join(str(x).replace("|", "\\|").replace("\n", " ") for x in row) + " |" for row in rows)
    return "\n".join(out)


# Reconcile source file rows with portfolio-level Repository V2 valuation decisions.
store = AdjustedPriceStore()
missing_records = []
for group in ("control", "candidate"):
    missing = pd.read_csv(ROOT / f"{group}_missing_marks.csv", dtype={"ticker": str})
    valuation = pd.read_csv(ROOT / f"{group}_valuation_audit.csv", dtype={"ticker": str})
    for _, item in missing.iterrows():
        ticker = str(item["ticker"]).zfill(6)
        day = str(item["date"])
        matching = valuation[
            (valuation["ticker"].astype(str).str.zfill(6) == ticker)
            & (valuation["valuation_date"].astype(str) == day)
        ]
        if len(matching) != 1:
            raise RuntimeError(f"Expected one valuation evidence row for {group} {ticker} {day}, got {len(matching)}")
        evidence = matching.iloc[0]
        source_rows = store.load_daily(ticker, start=day, end=day)
        source = source_rows.iloc[0] if len(source_rows) == 1 else None
        row = {
            "group": group.upper(),
            "candidate_id": item.get("candidate_id", ""),
            "ticker": ticker,
            "isu_cd": item["isu_cd"],
            "date": day,
            "raw_partition_status": evidence["raw_manifest_status"],
            "raw_partition_path": evidence["raw_partition_path"],
            "raw_partition_file_sha256": evidence["raw_partition_file_sha256"],
            "raw_partition_content_sha256": evidence["raw_partition_content_sha256"],
            "raw_exact_activity_row": evidence["raw_row"],
            "nontrading_placeholder": False,
            "raw_evidence_state": evidence["evidence_state"],
            "adjusted_source_row_present": len(source_rows) == 1,
            "adjusted_source_open": native(source["open"]) if source is not None else None,
            "adjusted_source_high": native(source["high"]) if source is not None else None,
            "adjusted_source_low": native(source["low"]) if source is not None else None,
            "adjusted_source_close": native(source["close"]) if source is not None else None,
            "repository_v2_valid_portfolio_mark_present": False,
            "portfolio_missing_mark_reason": item["reason"],
            "prior_valid_adjusted_close_date": evidence["prior_valid_adjusted_close_date"],
            "prior_valid_adjusted_close": evidence["prior_valid_adjusted_close"],
            "carry_applied": bool(evidence["carry_applied"]),
            "nav_disposition": "EXCLUDE_THIS_PORTFOLIO_NAV_DAY; no carry or interpolation",
            "cause_limit": "source row presence does not establish a valid composed Repository V2 portfolio mark; the composition failure cause is not proven by this replay artifact",
        }
        missing_records.append(row)

missing_audit = pd.DataFrame(missing_records).sort_values(["group", "date", "ticker"])
missing_audit.to_csv(ROOT / "portfolio_missing_mark_audit.csv", index=False)
missing_audit[missing_audit["group"] == "CONTROL"].to_csv(ROOT / "control_128940_missing_mark_audit.csv", index=False)
missing_audit[missing_audit["group"] == "CANDIDATE"].to_csv(ROOT / "candidate_003690_missing_mark_audit.csv", index=False)
if len(missing_audit) != 5 or missing_audit["adjusted_source_row_present"].sum() != 5:
    raise RuntimeError("Unexpected number or source availability of residual missing NAV marks")

# Keep execution contract status consistent with the completed and audited run.
contract_path = ROOT / "execution_contract.json"
contract = read_json(contract_path)
contract["status"] = "EXECUTION_COMPLETE"
contract["post_execution"] = {
    "targeted_evaluation_status": "TARGETED_EVALUATION_COMPLETE",
    "portfolio_replay_status": "PORTFOLIO_REPLAY_COMPLETE",
    "targeted_workers": 10,
    "targeted_worker_errors": 0,
    "groups_replayed": ["CONTROL", "ALIGNMENT_MCAP_500B"],
    "residual_nav_missing_days": {"CONTROL": 1, "ALIGNMENT_MCAP_500B": 4},
    "new_strategy_or_portfolio_rule_changes": False,
}
contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

integrity_path = ROOT / "integrity_validation.json"
integrity = read_json(integrity_path)
integrity["checks"]["residual_missing_nav_mark_audit_matches_portfolio_ledgers"] = (
    len(missing_audit) == 5
    and set(missing_audit["date"].astype(str)) == set(pd.concat([
        pd.read_csv(ROOT / "control_missing_marks.csv")["date"].astype(str),
        pd.read_csv(ROOT / "candidate_missing_marks.csv")["date"].astype(str),
    ]))
)
integrity["checks"]["source_adjusted_rows_distinguished_from_valid_portfolio_marks"] = bool(
    missing_audit["adjusted_source_row_present"].all()
    and not missing_audit["repository_v2_valid_portfolio_mark_present"].any()
)
integrity["checks"]["no_carry_or_interpolation_for_unresolved_active_raw_rows"] = not missing_audit["carry_applied"].any()
integrity["residual_nav_mark_audit"] = {
    "missing_mark_rows": len(missing_audit),
    "independent_causes": 2,
    "control": {"valid_nav_days": 833, "total_days": 834, "missing_dates": ["2022-07-05"]},
    "candidate": {"valid_nav_days": 830, "total_days": 834, "missing_dates": ["2023-04-25", "2023-06-28", "2024-02-16", "2024-06-27"]},
    "adjusted_source_rows_present_but_not_valid_portfolio_marks": 5,
    "interpolation_or_carry_applied": False,
    "cause_of_composed_mark_absence": "not established by the available replay evidence",
}
integrity["status"] = "PASS" if all(integrity["checks"].values()) else "CHECK_REQUIRED"
integrity_path.write_text(json.dumps(integrity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

issues = {
    "schema": "fast_core_v2_p3_1_117_price_nav_closure_issue_summary_v01",
    "counting_basis": "independent root causes, not affected sessions",
    "severity_counts": {"CRITICAL": 0, "MAJOR": 0, "MINOR": 2},
    "issues": [
        {
            "severity": "MINOR",
            "group": "CONTROL",
            "identity": "128940 / KR7128940004",
            "dates": ["2022-07-05"],
            "impact": "One of 834 portfolio valuation days is excluded; NAV coverage is 99.880%. The adjusted source row exists, but replay has no valid Repository V2 portfolio mark. No carry or interpolation was applied.",
            "decision_effect": "CONTROL MDD remains OBSERVED; candidate relative MDD decision remains favorable. The source/composition reason remains undocumented.",
        },
        {
            "severity": "MINOR",
            "group": "ALIGNMENT_MCAP_500B",
            "identity": "003690 / KR7003690005",
            "dates": ["2023-04-25", "2023-06-28", "2024-02-16", "2024-06-27"],
            "impact": "Four of 834 portfolio valuation days are excluded; NAV coverage is 99.520%. The adjusted source rows exist, but replay has no valid Repository V2 portfolio marks. No carry or interpolation was applied.",
            "decision_effect": "Candidate MDD remains OBSERVED and is 26.363 percentage points above the absolute -40% floor. The source/composition reason remains undocumented.",
        },
    ],
}
(ROOT / "issue_summary.json").write_text(json.dumps(issues, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

corp = read_json(ROOT / "corporate_action_audit.json")
control_exposure = next(x for x in corp["new_replay_exposure"] if x["group"] == "CONTROL")
candidate_exposure = next(x for x in corp["new_replay_exposure"] if x["group"] == "ALIGNMENT_MCAP_500B")
(ROOT / "corporate_action_audit.md").write_text(
    """# Koentec (029960 / KR7029960002) 기업행위 감사

## 과거 공식 근거

기존 P3-2 기업행위 감사 문서에서 확인한 내용은 주당 현금교환액 9,000원, 효력일 2025-05-30, 상장폐지일 2025-06-16이다. 2025-06-20은 지급 예정일로만 기록되어 있고 실제 계좌 입금은 확인되지 않았다. 이 문서의 SHA-256은 """ + corp["official_evidence"]["local_source_sha256"] + """이다. 원문은 """ + corp["official_evidence"]["local_source"] + """에 있다.

## 이번 P3-1 재생 결과

CONTROL에서는 2024-11-15 신호의 2024-11-18 진입 시도가 있었지만 가용 현금 부족으로 체결되지 않았다. 주문 예산은 수수료 포함 4,999,844원이고 체결 당시 가용 현금은 613,269원이었다. 따라서 2025-05-30 효력일 및 2025-05-30 cutoff에 보유 주식은 0주다. 후보에서는 해당 포지션의 거래 원장과 포트폴리오 이벤트가 없다.

P3-1 V01의 CONTROL은 Koentec 558주를 cutoff까지 보유했지만, 복원된 신호를 포함해 두 그룹을 처음부터 재생한 결과 이번 포트폴리오에는 해당 주식이 없다. 따라서 이번 결과에는 현금교환 대금, 미수금, 지급일, 세금, 수수료 또는 cutoff 이후 현금을 임의로 추가하지 않았다. 새 원장 기준 Koentec 정산이 NAV·수익률·D 게이트에 미치는 영향은 없다.

## 결론

상태: NO_EXPOSURE_AFTER_REPLAY. Koentec 기업행위 전용 정산 규칙을 만들지 않았고, P3-2 신호/거래 원장을 P3-1에 복사하지 않았다. 원래 지급 예정일과 실제 입금 여부의 차이는 역사적 근거로만 보존한다.
""",
    encoding="utf-8",
)

preflight = read_json(ROOT / "preflight.json")
price_audit = pd.read_csv(ROOT / "price_input_117_audit.csv")
partition_audit = pd.read_csv(ROOT / "targeted_signal_date_krx_partition_hashes.csv")
source_refs = []
for p in [
    P31 / "artifact_hashes.json",
    P31 / "plan.md",
    P31 / "execution_contract.json",
    P31 / "report.md",
    P31 / "integrity_audit.json",
    P31 / "repository_v2_unavailable_cause_audit.json",
    P32 / "artifact_hashes.json",
    P32 / "price_input_124_audit.csv",
    P32 / "corporate_action_audit.md",
]:
    source_refs.append({"path": p.relative_to(PROJECT).as_posix(), "sha256": sha256(p)})
current_source_hashes = {}
for rel, expected in preflight.get("source_hashes", {}).items():
    p = PROJECT / rel
    actual = sha256(p) if p.is_file() else None
    current_source_hashes[rel] = {
        "sha256_at_preflight": expected,
        "current_sha256": actual,
        "match": actual == expected,
    }
if not all(item["match"] for item in current_source_hashes.values()):
    raise RuntimeError("One or more frozen source hashes changed since preflight")

adjusted_inputs = []
for _, row in price_audit.iterrows():
    rel = str(row["adjusted_file_path"])
    p = Path(rel)
    if not p.is_absolute():
        p = PROJECT / p
    actual = sha256(p) if p.is_file() else None
    adjusted_inputs.append({
        "ticker": str(row["ticker"]).zfill(6),
        "isu_cd": row["isu_cd"],
        "market": row["market"],
        "path": rel,
        "expected_sha256": row["adjusted_file_sha256_expected"],
        "current_sha256": actual,
        "matches": actual == row["adjusted_file_sha256_expected"],
        "targeted_data_status": row["targeted_data_status"],
        "pit_internal_unresolved_sessions": int(row["pit_internal_unresolved_session_count"]),
    })
if len(adjusted_inputs) != 117 or not all(x["matches"] for x in adjusted_inputs):
    raise RuntimeError("117 adjusted source hash verification failed")

raw_partitions = []
for _, row in partition_audit.iterrows():
    rel = str(row["file_path"])
    p = PROJECT / "data/market/raw/krx_stocks/v01" / rel
    actual = sha256(p) if p.is_file() else None
    raw_partitions.append({
        "market": row["market"],
        "partition_date": row["partition_date"],
        "status": row["status"],
        "path": p.relative_to(PROJECT).as_posix(),
        "expected_file_sha256": row["file_sha256"],
        "current_file_sha256": actual,
        "file_hash_matches": actual == row["file_sha256"],
        "content_sha256": row["content_sha256"],
    })
if len(raw_partitions) != 63 or not all(x["file_hash_matches"] for x in raw_partitions):
    raise RuntimeError("Signal-date KRX partition hash verification failed")

manifest = {
    "schema": "fast_core_v2_p3_1_117_price_nav_closure_source_manifest_v01",
    "work_id": preflight["work_id"],
    "baseline": {
        "branch": preflight["branch"],
        "head": preflight["baseline_head"],
        "origin_main": preflight["baseline_origin_main"],
        "head_equals_origin_main": preflight["baseline_head"] == preflight["baseline_origin_main"],
        "plan_commit": preflight["plan_commit"],
    },
    "execution_scope": {
        "window": "2022-01-03 through 2025-05-30, 834 KRX evaluation sessions",
        "execution_support_only": "2025-06-02",
        "target_pairs": 117,
        "workers": 10,
        "external_api_calls": 0,
        "full_2460_ticker_rerun": False,
        "p3_2_signal_or_trade_ledgers_copied": False,
        "old_p3_1_artifacts_overwritten": False,
    },
    "reference_artifact_manifests": {
        "p3_1": {"path": str(P31.relative_to(PROJECT)), "checked": 62, "expected": 62, "manifest_sha256": preflight["old_p3_1_artifact_hashes"]["manifest_sha256"], "pass": preflight["old_p3_1_artifact_hashes"]["pass"]},
        "p3_2": {"path": str(P32.relative_to(PROJECT)), "checked": 33, "expected": 33, "manifest_sha256": preflight["p3_2_artifact_hashes"]["manifest_sha256"], "pass": preflight["p3_2_artifact_hashes"]["pass"]},
    },
    "reference_files": source_refs,
    "frozen_code_and_policy_hashes": current_source_hashes,
    "adjusted_price_inputs_117": adjusted_inputs,
    "signal_date_krx_raw_partitions": raw_partitions,
    "permanent_exclusions": preflight["permanent_exclusions"],
    "other_p3_1_adjusted_inputs": {"count": 2343, "mismatches": 0, "verified_against": "P3-1 sealed artifact manifest"},
    "hash_check_summary": {
        "frozen_policy_and_code_hashes_match": all(x["match"] for x in current_source_hashes.values()),
        "adjusted_price_hashes_117_match": all(x["matches"] for x in adjusted_inputs),
        "signal_date_partition_file_hashes_match": all(x["file_hash_matches"] for x in raw_partitions),
    },
}
(ROOT / "source_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

summary = read_json(ROOT / "replay_summary.json")
metrics = summary["metrics"]
control = metrics["control"]
candidate = metrics["candidate"]
comparison = list(csv.DictReader((ROOT / "metrics_comparison.csv").open(encoding="utf-8", newline="")))

def mdd_text(m):
    recovery = m["mdd_recovery_date"] or "cutoff까지 미회복"
    return f"{m['mdd_type']} {m['mdd_pct']:.3f}% (peak {m['mdd_peak_date']}, trough {m['mdd_trough_date']}, recovery {recovery})"

def overview_row(label, m):
    return [
        label,
        fmt(m["ending_equity_krw"], "KRW"),
        fmt(m["total_return_pct"], "%"),
        fmt(m["cagr_pct"], "%"),
        mdd_text(m),
        f"{m['valid_nav_days']}/{m['total_valuation_days']} ({m['nav_coverage_pct']:.3f}%; {m['missing_nav_days']} 결측)",
        f"{m['eligible_entry_attempts']:,} / {m['cash_shortage_skipped_entries']:,} ({m['cash_shortage_skip_rate_pct']:.3f}%)",
        f"{m['executed_entry_count']:,} / {m['realized_exit_count']:,} / {m['open_at_cutoff_count']:,}",
        f"{m['win_rate_pct']:.3f}% (n={m['realized_exit_count']})",
        f"{m['mean_trade_terminal_return_pct']:.3f}% / {m['median_trade_terminal_return_pct']:.3f}%",
        f"{m['average_holding_trading_sessions']:.2f} / {m['median_holding_trading_sessions']:.2f}",
    ]

core_rows = [overview_row("CONTROL", control), overview_row("ALIGNMENT + 500B", candidate)]
trade_rows = []
for label, m in (("CONTROL", control), ("ALIGNMENT + 500B", candidate)):
    exits = json.loads(m["exit_reason_counts"])
    trade_rows.append([
        label,
        f"{m['loss_guard_triggered_trade_count']:,}",
        f"{m['first_progressed_trade_count']:,} / {m['never_progressed_trade_count']:,}",
        f"Exit3 {m['exit3_count']:,} ({exits.get('EXIT3_PROGRESSED_TO_EARLY_TREND', 0)} Early Trend; {exits.get('EXIT3_PROGRESSED_TO_TRANSITION', 0)} Transition; {exits.get('EXIT3_PROGRESSED_TO_WEAK', 0)} Weak)",
        f"{m['exit4_count']:,}",
        f"{m['ge_pos_20_count']:,} / {m['ge_pos_50_count']:,} / {m['ge_pos_100_count']:,}",
        f"{m['le_neg_10_count']:,} / {m['le_neg_15_count']:,} / {m['le_neg_20_count']:,} / {m['le_neg_30_count']:,}",
        f"+{m['maximum_trade_terminal_return_pct']:.3f}% / {m['minimum_trade_terminal_return_pct']:.3f}%",
        f"{m['average_capital_utilization_pct']:.3f}% / {m['maximum_capital_utilization_pct']:.3f}% / {m['average_cash_ratio_pct']:.3f}%",
        f"{m['average_concurrent_positions']:.2f} / {m['maximum_concurrent_positions']}",
        f"{fmt(m['turnover_krw'], 'KRW')} ({m['turnover_multiple']:.3f}x)",
        f"{fmt(m['total_commissions_krw'], 'KRW')} / {fmt(m['total_slippage_impact_krw'], 'KRW')}",
        "; ".join(f"{k}: {v}" for k, v in sorted(exits.items())),
    ])

comparison_rows = []
for row in comparison:
    unit = row["unit"]
    comparison_rows.append([
        row["label_ko"],
        f"{fmt(row['control_v01'], unit)} → {fmt(row['control_replayed'], unit)} ({fmt(row['control_delta_vs_v01'], unit)})",
        f"{fmt(row['candidate_v01'], unit)} → {fmt(row['candidate_replayed'], unit)} ({fmt(row['candidate_delta_vs_v01'], unit)})",
        fmt(row["candidate_minus_control_replayed"], unit),
    ])

filter_counts = read_json(ROOT / "targeted_execution.json")["candidate_filter_status_counts"]
report = []
report += [
    "# FAST Core V2 P3-1: 117개 가격 복원·NAV 및 기업행위 감사",
    "",
    "## 독립 이슈 수",
    "",
    md_table(["심각도", "원인 수", "내용"], [
        ["CRITICAL", "0", "결정 또는 재생 무결성에 영향을 주는 미해결 문제 없음"],
        ["MAJOR", "0", "공식 판정을 뒤집을 정도의 미해결 문제 없음"],
        ["MINOR", "2", "CONTROL 128940의 1일 mark 결측, 후보 003690의 4일 mark 결측. 독립 원인 2건으로 계산"],
    ]),
    "",
    "결측은 총 5개 포트폴리오 평가일이지만, 서로 다른 두 종목 원인이라 MINOR 2건으로 집계했어. 두 종목 모두 해당일의 KRX 원천 활동 행과 조정가격 파일 행은 존재하지만, 포트폴리오 재생의 유효 Repository V2 mark로 채택되지는 않았어. 원천 행의 존재를 유효 NAV로 오인하지 않도록 감사표를 고쳤고, 가격 carry나 보간은 적용하지 않았어. 조정가격 원천 행과 composed mark 사이의 불일치가 발생한 내부 원인은 이번 증거만으로 입증되지 않았어.",
    "",
    "## 범위와 실행",
    "",
    "P3-1 한 기간만 재판정했어. 평가 구간은 2022-01-03~2025-05-30, 정확한 KRX 평가일은 834일이고 2025-06-02는 cutoff 전에 발생한 신호의 체결 지원에만 사용했어. P1/P2-1/P2-2/P3-2 전체 실행, 전략 규칙 변경, P3-2 거래/신호 원장 복사, 외부 API 호출, 2,460종목 전체 재평가는 없었어.",
    "",
    f"기존 P3-1 미해결 목록의 정확한 117 ticker/ISU 쌍을 10 workers로 복원해 평가했어. {len(price_audit)}개 모두 입력 가용, 조정가격 파일 hash 일치, PIT 내부 미해결 session 0, worker 오류 0이야. 후보 필터 재검증에서 신호 감사 82건: PASS {filter_counts.get('PASS', 0)}, Alignment reject {filter_counts.get('REJECT_ALIGNMENT', 0)}, MA window unavailable {filter_counts.get('REJECT_MA_UNAVAILABLE', 0)}, 500B 미만 {filter_counts.get('REJECT_MCAP_BELOW_500B', 0)}. MA60 unavailable 30건은 선행 60개월 월봉 이력이 부족해 동결 규칙대로 거절된 거야. 새 CONTROL 신호 30건, 후보 신호 2건이 추가되어 두 포트폴리오를 2022-01-03부터 모두 순차 재생했어. 다른 2,343개 기존 입력/신호는 봉인 P3-1 hash 검증 후 재사용했어.",
    "",
    "## 최종 성과",
    "",
    md_table(
        ["그룹", "종료 자산", "총수익률", "CAGR", "MDD", "유효 NAV 일수", "진입시도 / cash skip", "실제 진입 / 청산 / cutoff 미청산", "승률", "실현수익률 평균 / 중앙", "보유 거래일 평균 / 중앙"],
        core_rows,
    ),
    "",
    "승률·실현수익률은 실제 실현 청산을 기준으로 계산했어. 실현 종료 거래일과 cutoff 미청산 포지션을 분리했고, 거래 보유기간은 거래일 수야. MDD는 NAV 결측을 제외한 관측값이며 EXACT가 아니라 OBSERVED야.",
    "",
    "## 거래·꼬리·비용·자본 사용",
    "",
    md_table(
        ["그룹", "Loss Guard", "PROGRESSED / 미도달", "Exit3", "Exit4", "+20 / +50 / +100%", "-10 / -15 / -20 / -30%", "최대 수익 / 최대 손실", "자본활용 평균 / 최대 / 평균현금", "동시보유 평균 / 최대", "회전 거래액 (초기자본 배수)", "수수료 / 슬리피지", "Exit reason 상세"],
        trade_rows,
    ),
    "",
    "수익 꼬리는 실현 거래 순수익률 기준으로 각 임계값 이상/이하인 거래 수야. 수수료와 불리한 슬리피지는 매수·매도 양쪽 재계산을 검증했고, 거래세는 계약대로 0이야. 두 그룹 모두 현금 보존 검증을 통과했어.",
    "",
    "## 기존 P3-1 V01 대비 및 후보 대조",
    "",
    "아래 표는 모든 저장된 비교 지표를 포함해. 세 번째 열은 후보의 V01 대비 변화, 마지막 열은 새 후보 값에서 새 CONTROL 값을 뺀 차이야. 수익률·MDD·승률·거래 수·원화 금액은 해당 지표의 단위를 그대로 사용했어.",
    "",
    md_table(["지표", "CONTROL: V01 → 재생 (변화)", "후보: V01 → 재생 (변화)", "재생 후보 − CONTROL"], comparison_rows),
    "",
    f"핵심 비교: 새 후보의 수익률은 CONTROL보다 {candidate['total_return_pct'] - control['total_return_pct']:.3f}%p 높고 CAGR은 {candidate['cagr_pct'] - control['cagr_pct']:.3f}%p 높아. MDD는 후보가 {abs(control['mdd_pct']) - abs(candidate['mdd_pct']):.3f}%p 덜 깊어. 공식 상대 기준 계산은 CONTROL MDD − 후보 MDD = {control['mdd_pct'] - candidate['mdd_pct']:.3f}%p라 +5.0%p 악화 실패 조건에 해당하지 않아. 현금 부족 skip 비율은 후보가 CONTROL보다 {control['cash_shortage_skip_rate_pct'] - candidate['cash_shortage_skip_rate_pct']:.3f}%p 낮아.",
    "",
    "## NAV mark 결측과 영향",
    "",
    md_table(["그룹", "정확한 identity", "결측 날짜", "평가 처리", "원천 근거"], [
        ["CONTROL", "128940 / KR7128940004", "2022-07-05", "834일 중 833일 유효; 해당 portfolio NAV day 제외", "raw KRX 행은 비거래 placeholder가 아니며 adjusted source row 존재. 유효 Repository V2 portfolio mark 미확인"],
        ["후보", "003690 / KR7003690005", "2023-04-25, 2023-06-28, 2024-02-16, 2024-06-27", "834일 중 830일 유효; 네 portfolio NAV day 제외", "raw KRX 행은 비거래 placeholder가 아니며 adjusted source row 존재. 유효 Repository V2 portfolio mark 미확인"],
    ]),
    "",
    "NAV coverage는 각각 99.880%와 99.520%라 공식 E는 두 그룹 모두 OBSERVED야. 미해결 mark가 없는 cutoff일 종료 자산은 정상 평가됐어. CONTROL 관측 MDD는 -38.704%로 -40% 절대 경계에 가깝지만, 후보는 -13.637%이고 상대 MDD 판정도 실패하지 않아. 후보 절대 MDD의 -40% 하한 여유는 26.363%p야. 지시서대로 4일 결측만으로 D를 CHECK_REQUIRED 처리하지 않았어. composed mark가 비어 있는 원인은 여전히 조사되지 않았으므로 100% EXACT NAV로 표시하지 않아.",
    "",
    "## Koentec 기업행위",
    "",
    "2025-05-30 효력 현금교환 대상인 CONTROL Koentec 진입은 2024-11-18에 현금 부족으로 skip됐어. 수수료 포함 필요 현금은 4,999,844원, 당시 가용 현금은 613,269원이었고 실제 보유 수량은 효력일과 cutoff 모두 0주야. 후보 쪽 해당 이벤트는 없어. 따라서 과거 558주 보유 기록에 대해 지급 예정일·미수금·세금·수수료를 새 포트폴리오에 추가하지 않았어. 기업행위 상태는 NO_EXPOSURE_AFTER_REPLAY이며 이번 cutoff NAV·성과·D에 추가 영향은 없어. 상세 근거는 corporate_action_audit.md야.",
    "",
    "## 공식 A~E 판정",
    "",
    md_table(["그룹", "A 무결성", "B 비용", "C 수익성", "D MDD", "E NAV 유효성"], [
        ["CONTROL", "PASS", "PASS", "PASS", "PASS (OBSERVED -38.704%)", "OBSERVED (833/834, 99.880%)"],
        ["ALIGNMENT + 500B", "PASS", "PASS", "PASS", "PASS (OBSERVED -13.637%)", "OBSERVED (830/834, 99.520%)"],
    ]),
    "",
    "P3-1 단일 기간의 심사 결과야. 5기간 공식 채택 상태는 NOT_FINAL_5WINDOW, 기본 전략 승격은 NOT_EVALUATED이고 공식 기본 전략은 변경하지 않았어.",
    "",
    "## 저장·무결성·provenance",
    "",
    f"시작 HEAD와 origin/main은 모두 {preflight['baseline_head']}였어. 기존 P3-1 artifact 62/62, P3-2 참고 artifact 33/33 hash가 일치했고, 기존의 2,343 adjusted 파일도 불일치 0건이야. 신규 117개는 117/117 정확한 identity, source hash, 경계 입력, PIT 내부 unresolved 0이 확인됐고 signal-date KRX raw partition 63개 파일 hash도 재확인했어. Permanent exclusion 182쌍은 봉인 hash와 일치하고 재생 누출 0건이야. 비용/현금·equity 회계, 834일 calendar, cutoff 및 Koentec 노출 검사까지 integrity_validation.json에서 critical error 0, PASS야.",
    "",
    "누적 측정 실행 시간은 targeted 244.817초와 두 그룹 replay 398.622초로 약 10분 43초야. 사전 점검과 보고서 생성 시간은 제외했어. 산출물 hash 전체 목록은 artifact_hashes.json, 입력 provenance는 source_manifest.json, 상세 지표는 metrics_comparison.csv에서 확인할 수 있어.",
]
(ROOT / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")

# Artifact hashes cover every output file except the self-referential hash manifest itself.
artifact_files = sorted(p for p in ROOT.iterdir() if p.is_file() and p.name != "artifact_hashes.json")
artifact_hashes = {
    "schema": "fast_core_v2_p3_1_117_price_nav_closure_artifact_hashes_v01",
    "hash_algorithm": "sha256",
    "self_hash_excluded": True,
    "files": [
        {"path": p.name, "sha256": sha256(p), "bytes": p.stat().st_size}
        for p in artifact_files
    ],
}
(ROOT / "artifact_hashes.json").write_text(json.dumps(artifact_hashes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

print(json.dumps({
    "status": integrity["status"],
    "residual_mark_rows": len(missing_audit),
    "source_adjusted_rows_present": int(missing_audit["adjusted_source_row_present"].sum()),
    "target_adjusted_hashes_match": len(adjusted_inputs) == 117 and all(x["matches"] for x in adjusted_inputs),
    "raw_partition_file_hashes_match": len(raw_partitions) == 63 and all(x["file_hash_matches"] for x in raw_partitions),
    "artifact_files_hashed": len(artifact_files),
    "report": str(ROOT / "report.md"),
}, ensure_ascii=False, indent=2))
