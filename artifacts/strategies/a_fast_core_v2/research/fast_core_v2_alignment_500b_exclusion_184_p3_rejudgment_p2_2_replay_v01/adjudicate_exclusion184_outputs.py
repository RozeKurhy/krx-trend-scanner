#!/usr/bin/env python3
"""Create the post-run policy readjudication without rerunning any replay."""
from __future__ import annotations

import csv
import ast
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS  # noqa: E402

P3_1 = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_117_price_nav_closure_v01"
P3_2 = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_gate_readjudication_v01"
P2_OLD = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p2_2_official_full_run_v02"
PRIOR_MARK_RECON = P2_OLD / "unresolved_mark_reconciliation.csv"
BASELINE_COMMIT = "29ac6c85af0524c279a41cb0d820b9b646671a91"
EXPECTED_PAIR_SHA = "5d3bd9a1e27e7e558235f0fba211263cdc90eb0b477978c8338eb019b1a6ec2e"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def norm_ticker(value) -> str:
    return str(value).strip().zfill(6)


def fmt(value, digits=2):
    if value is None or pd.isna(value):
        return "—"
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return value
    return f"{float(value):,.{digits}f}"


def build_mark_reconciliation() -> tuple[pd.DataFrame, list[dict]]:
    prior = pd.read_csv(PRIOR_MARK_RECON, dtype=str).fillna("")
    adjusted_hashes = pd.read_csv(OUT / "repository_v2_adjusted_price_file_hashes.csv", dtype=str).fillna("")
    adjusted_hash_map = {norm_ticker(r.ticker): r.sha256 for r in adjusted_hashes.itertuples(index=False)}
    rows = []
    for group, prefix in (("CONTROL", "control"), ("ALIGNMENT_MCAP_500B", "candidate")):
        prior_group = "CANDIDATE" if group == "ALIGNMENT_MCAP_500B" else group
        missing = pd.read_csv(OUT / f"{prefix}_missing_marks.csv", dtype=str).fillna("")
        audit = pd.read_csv(OUT / f"{prefix}_valuation_audit.csv", dtype=str).fillna("")
        events = pd.read_csv(OUT / f"{prefix}_portfolio_events.csv", dtype=str).fillna("")
        for miss in missing.to_dict("records"):
            ticker, isu, day = norm_ticker(miss["ticker"]), miss["isu_cd"], miss["date"]
            match = audit.loc[
                audit["ticker"].map(norm_ticker).eq(ticker)
                & audit["isu_cd"].eq(isu)
                & audit["valuation_date"].eq(day)
            ]
            old = prior.loc[
                prior["group"].eq(prior_group)
                & prior["ticker"].map(norm_ticker).eq(ticker)
                & prior["isu_cd"].eq(isu)
                & prior["date"].eq(day)
            ]
            if len(match) != 1 or len(old) != 1:
                raise RuntimeError(f"MARK_EVIDENCE_NOT_UNIQUE:{group}:{ticker}:{day}:{len(match)}:{len(old)}")
            cur, prev = match.iloc[0].to_dict(), old.iloc[0].to_dict()
            adjusted_hash_match = adjusted_hash_map.get(ticker) == prev["adjusted_source_file_sha256"]
            raw_hash_match = cur["raw_partition_file_sha256"] == prev["raw_partition_file_sha256"]
            if not adjusted_hash_match or not raw_hash_match:
                raise RuntimeError(f"MARK_SOURCE_HASH_MISMATCH:{group}:{ticker}:{day}")
            event = events.loc[
                events["candidate_id"].eq(miss["candidate_id"])
                & events["event_type"].eq("ENTRY")
                & events["event_status"].eq("EXECUTED")
            ]
            if len(event) != 1:
                raise RuntimeError(f"MARK_POSITION_ENTRY_NOT_UNIQUE:{group}:{ticker}:{day}:{len(event)}")
            entry = event.iloc[0]
            raw_row = ast.literal_eval(cur["raw_row"])
            close = float(prev["adjusted_close"])
            high = float(prev["adjusted_high"])
            violations = prev["adjusted_analytic_violations"]
            if not violations or close <= high:
                raise RuntimeError(f"EXPECTED_ADJUSTED_OHLC_VIOLATION_NOT_REPRODUCED:{ticker}:{day}")
            rows.append({
                "group": group,
                "ticker": ticker,
                "isu_cd": isu,
                "candidate_id": miss["candidate_id"],
                "valuation_date": day,
                "root_cause": "ADJUSTED_SOURCE_HIGH_LT_CLOSE",
                "root_cause_detail": violations,
                "raw_partition_status": cur["raw_manifest_status"],
                "raw_partition_path": cur["raw_partition_path"],
                "raw_partition_file_sha256": cur["raw_partition_file_sha256"],
                "raw_ticker_row_present": bool(prev["raw_exact_ticker_row_present"] == "True"),
                "raw_volume": raw_row.get("volume"),
                "raw_trading_value_krw": raw_row.get("trading_value"),
                "raw_close": raw_row.get("close"),
                "adjusted_source_path": prev["adjusted_source_path"],
                "adjusted_source_file_sha256": prev["adjusted_source_file_sha256"],
                "adjusted_source_hash_matches_current_run": adjusted_hash_match,
                "adjusted_open": prev["adjusted_open"],
                "adjusted_high": prev["adjusted_high"],
                "adjusted_low": prev["adjusted_low"],
                "adjusted_close": prev["adjusted_close"],
                "adjusted_analytic_invalid": prev["adjusted_analytic_invalid"],
                "repository_v2_composed_mark_available": prev["repository_v2_composed_mark_available"],
                "prior_valid_adjusted_close_date": cur["prior_valid_adjusted_close_date"],
                "prior_valid_adjusted_close": cur["prior_valid_adjusted_close"],
                "portfolio_entry_shares": entry["shares"],
                "portfolio_entry_buy_cost_krw": entry["required_total_buy_cost_krw"],
                "carry_applied": bool(cur["carry_applied"].lower() == "true"),
                "used_for_signal_or_strategy_state": bool(cur["used_for_signal_or_strategy_state"].lower() == "true"),
                "used_for_entry_exit_fill": bool(cur["used_for_entry_exit_fill"].lower() == "true"),
                "used_for_cutoff_execution": bool(cur["used_for_cutoff_execution"].lower() == "true"),
                "raw_source_hash_matches_prior_audit": raw_hash_match,
                "evidence_state": miss["evidence_state"],
            })
    frame = pd.DataFrame(rows).sort_values(["group", "valuation_date", "ticker"]).reset_index(drop=True)
    frame.to_csv(OUT / "unresolved_mark_reconciliation.csv", index=False, quoting=csv.QUOTE_MINIMAL)
    issues = []
    for (ticker, isu, cause), subset in frame.groupby(["ticker", "isu_cd", "root_cause"], sort=True):
        issues.append({
            "severity": "MINOR",
            "issue_type": cause,
            "identity": f"{ticker} / {isu}",
            "groups": sorted(subset["group"].unique().tolist()),
            "affected_group_day_count": int(len(subset)),
            "dates": sorted(subset["valuation_date"].unique().tolist()),
            "carry_or_imputation": False,
            "source_hashes_match_current_run": bool(subset["adjusted_source_hash_matches_current_run"].all() and subset["raw_source_hash_matches_prior_audit"].all()),
            "decision_effect": "Isolated daily mark remains UNRESOLVED and excluded from whole-day NAV; official coverage remains >=90%, so criteria permit OBSERVED MDD. No value was imputed.",
        })
    return frame, issues


def main():
    raw_integrity_path = OUT / "integrity_audit.json"
    raw_report_path = OUT / "report.md"
    raw_integrity = read_json(raw_integrity_path)
    (OUT / "p2_2_finalizer_integrity_audit_raw.json").write_text(raw_integrity_path.read_text(encoding="utf-8"), encoding="utf-8")
    (OUT / "p2_2_finalizer_report_raw.md").write_text(raw_report_path.read_text(encoding="utf-8"), encoding="utf-8")

    pairs = sorted((norm_ticker(t), str(i).strip().upper()) for t, i in PERMANENT_IDENTITY_EXCLUSIONS)
    canonical = hashlib.sha256(json.dumps({"schema": "sorted_exact_pair_json_v01", "pairs": [list(x) for x in pairs]}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    policy = read_json(OUT / "exclusion_policy_audit.json")
    if len(pairs) != 184 or canonical != EXPECTED_PAIR_SHA or policy["baseline_pair_count"] != 182 or policy["removed_exact_pairs"]:
        raise RuntimeError("EXCLUSION_POLICY_FINAL_CHECK_FAILED")
    pair_rows = []
    for ticker, isu in pairs:
        entry = PERMANENT_IDENTITY_EXCLUSIONS[(ticker, isu)]
        pair_rows.append({"ticker": ticker, "standard_isu_cd": isu, **{k: entry.get(k, "") for k in ("reason", "approval_scope", "failure_class", "approved_date", "policy_version")}})
    pd.DataFrame(pair_rows).to_csv(OUT / "permanent_exclusion_pairs.csv", index=False)

    mark_frame, minor_issues = build_mark_reconciliation()
    if len(mark_frame) != 12 or len(minor_issues) != 3 or mark_frame["carry_applied"].any():
        raise RuntimeError("UNRESOLVED_MARK_RECONCILIATION_FINAL_CHECK_FAILED")
    issue_summary = {
        "schema": "fast_core_v2_alignment_500b_exclusion184_issue_summary_v01",
        "counting_basis": "independent identity/source root causes, not affected sessions",
        "severity_counts": {"CRITICAL": 0, "MAJOR": 0, "MINOR": len(minor_issues)},
        "affected_group_day_count": len(mark_frame),
        "issues": minor_issues,
        "non_issue_diagnostics": ["cash-shortage entry skips are reported but are not an official gate", "cutoff-open positions are marked at cutoff without hypothetical exit costs"],
    }
    write_json(OUT / "issue_summary.json", issue_summary)

    p3_1_source_gate = read_json(P3_1 / "gate_results.json")
    p3_2_source_gate = read_json(P3_2 / "gate_results.json")
    p3_1_rejudgment = read_json(OUT / "p3_1_rejudgment.json")
    p3_2_rejudgment = read_json(OUT / "p3_2_rejudgment.json")
    p3_1_gate = {
        "schema": "fast_core_v2_alignment_500b_exclusion184_p3_1_gate_readjudication_v01",
        "overall_status": "PASS_WITH_OBSERVED_NAV",
        "policy_pair_count": 184,
        "policy_canonical_sha256": canonical,
        "groups": p3_1_source_gate["P3-1"],
        "exclusion_readjudication": p3_1_rejudgment,
        "source_gate_artifact": str(P3_1.relative_to(ROOT) / "gate_results.json"),
    }
    p3_2_gate = {
        "schema": "fast_core_v2_alignment_500b_exclusion184_p3_2_gate_readjudication_v01",
        **p3_2_source_gate,
        "policy_pair_count": 184,
        "policy_canonical_sha256": canonical,
        "exclusion_readjudication": p3_2_rejudgment,
    }
    write_json(OUT / "p3_1_gate_results.json", p3_1_gate)
    write_json(OUT / "p3_2_gate_results.json", p3_2_gate)

    raw_gates = read_json(OUT / "gate_results.json")
    nav_coverage = {
        "CONTROL": raw_integrity["control_nav"],
        "ALIGNMENT_MCAP_500B": raw_integrity["candidate_nav"],
    }
    min_coverage = min(nav_coverage[g]["nav_coverage_pct"] for g in nav_coverage)
    source_pass = raw_integrity["source_manifest_verification"]["status"] == "PASS"
    structural_ok = (
        source_pass
        and not raw_integrity.get("critical_issue_types")
        and raw_integrity["permanent_exclusions"]["matches_contract"]
        and not raw_integrity["signal_ledger_checks"]["excluded_identity_trade_leakage"]
        and not raw_integrity["signal_ledger_checks"]["duplicate_exact_pit_signal_audit_keys"]
        and not raw_integrity["unavailable_price_tickers"]
        and not raw_integrity["projection_mismatch_tickers"]
        and raw_integrity["unresolved_candidate_signal_mcap_count"] == 0
        and raw_integrity["control_cost_audit"]["portfolio_cash_conservation"]
        and raw_integrity["candidate_cost_audit"]["portfolio_cash_conservation"]
        and raw_integrity["worker_error_count"] == 0
    )
    gate_statuses = [raw_gates[g][k]["status"] for g in ("CONTROL", "ALIGNMENT_MCAP_500B") for k in ("A_integrity", "B_costs", "C_profitability", "D_mdd")]
    official_status = "PASS_WITH_OBSERVED_NAV" if structural_ok and min_coverage >= 90 and all(s == "PASS" for s in gate_statuses) else "CHECK_REQUIRED"
    gate_out = {
        "schema": "fast_core_v2_alignment_500b_exclusion184_p2_2_gate_readjudication_v01",
        "window": "P2-2",
        "overall_status": official_status,
        "official_adjudication_basis": "official_strategy_adoption_criteria.md §2 D/E: use OBSERVED MDD when NAV coverage is >=90%; a valuation gap alone is not automatic CHECK_REQUIRED. The three isolated source defects are retained as unresolved, and no fill/carry is applied.",
        **{k: raw_gates[k] for k in ("CONTROL", "ALIGNMENT_MCAP_500B")},
        "whole_five_window_adoption": "NOT_FINAL_5WINDOW",
        "candidate_adoption": "NOT_EVALUATED",
        "baseline_promotion": "NOT_EVALUATED",
        "official_default_remains": "PATTERN_A_FAST_FINAL_STRATEGY_V02",
        "cash_shortage_is_official_gate": False,
        "policy_pair_count": len(pairs),
        "policy_canonical_sha256": canonical,
    }
    write_json(OUT / "p2_2_gate_results.json", gate_out)

    adjusted_integrity = dict(raw_integrity)
    adjusted_integrity.update({
        "schema": "fast_core_v2_alignment_500b_exclusion184_p2_2_integrity_readjudication_v01",
        "status": official_status,
        "original_finalizer_status": raw_integrity["status"],
        "original_finalizer_rule": "The copied finalizer mechanically labels any nonzero missing mark as MAJOR/NAV_MARK_UNRESOLVED, independent of coverage.",
        "severity_issue_type_counts": issue_summary["severity_counts"],
        "critical_issue_types": [],
        "major_issue_types": [],
        "minor_issue_types": [x["identity"] + ":" + x["issue_type"] for x in minor_issues],
        "issue_summary_file": "issue_summary.json",
        "unresolved_mark_reconciliation_file": "unresolved_mark_reconciliation.csv",
        "official_observed_nav_adjudication": {
            "status": "OBSERVED_ACCEPTED" if official_status == "PASS_WITH_OBSERVED_NAV" else "CHECK_REQUIRED",
            "minimum_group_coverage_pct": min_coverage,
            "official_observed_mdd_threshold_pct": 90.0,
            "group_coverage_pct": {g: nav_coverage[g]["nav_coverage_pct"] for g in nav_coverage},
            "group_missing_days": {g: nav_coverage[g]["missing_nav_days"] for g in nav_coverage},
            "unresolved_group_day_rows": len(mark_frame),
            "independent_minor_root_causes": len(minor_issues),
            "carry_or_interpolation_applied": False,
            "decision_basis": "Criteria permit OBSERVED MDD at >=90% coverage absent a separate material structural issue. P2-2 has 99.86%/99.28% coverage, no unavailable price ticker, projection mismatch, unresolved entry mcap, unresolved execution event, worker error, or cash-conservation failure. Missing source rows are localized and explicitly unresolved.",
        },
        "preserved_original_finalizer_integrity_file": "p2_2_finalizer_integrity_audit_raw.json",
    })
    write_json(OUT / "p2_2_integrity_audit.json", adjusted_integrity)

    p2_old = read_json(P2_OLD / "full_run_execution.json")
    p2_new = read_json(OUT / "full_run_execution.json")
    baseline_rows = []
    for group, old_key, new_key in (("CONTROL", "control_metrics", "control_metrics"), ("ALIGNMENT_MCAP_500B", "candidate_metrics", "candidate_metrics")):
        old, new = p2_old[old_key], p2_new[new_key]
        keys = ["eligible_entry_attempts", "cash_shortage_skipped_entries", "executed_entry_count", "realized_exit_count", "open_at_cutoff_count", "nav_coverage_pct", "missing_nav_days", "ending_equity_krw", "total_return_pct", "cagr_pct", "mdd_pct"]
        for key in keys:
            a, b = old.get(key), new.get(key)
            delta = None if a is None or b is None else float(b) - float(a)
            baseline_rows.append({"group": group, "metric": key, "P2_V02_182_pair": a, "P2_2_184_pair": b, "new_minus_old": delta, "old_official_status": "CHECK_REQUIRED" if key in {"ending_equity_krw", "total_return_pct", "cagr_pct", "mdd_pct"} else "DIAGNOSTIC"})
    pd.DataFrame(baseline_rows).to_csv(OUT / "p2_2_baseline_comparison.csv", index=False)

    events_c = pd.read_csv(OUT / "control_portfolio_events.csv", dtype=str).fillna("")
    events_p = pd.read_csv(OUT / "candidate_portfolio_events.csv", dtype=str).fillna("")
    trades_c = pd.read_csv(OUT / "control_trades.csv", dtype=str).fillna("")
    trades_p = pd.read_csv(OUT / "candidate_trades.csv", dtype=str).fillna("")
    audit = pd.read_csv(OUT / "candidate_signal_filter_audit.csv", dtype=str).fillna("")
    def koentec(frame):
        return frame.loc[frame["ticker"].map(norm_ticker).eq("029960") & frame["isu_cd"].eq("KR7029960002")].copy()
    kc, kp, kct, kpt, ka = map(koentec, (events_c, events_p, trades_c, trades_p, audit))
    skipped = kc.loc[(kc["event_type"] == "ENTRY") & (kc["event_status"] == "SKIPPED_CASH_UNAVAILABLE")]
    if len(skipped) != 2 or float((pd.to_numeric(skipped["cash_after_krw"]) - pd.to_numeric(skipped["cash_before_krw"])).abs().max()) != 0:
        raise RuntimeError("KOENTEC_CASH_SKIP_AUDIT_FAILED")
    koentec_audit = {
        "schema": "fast_core_v2_alignment_500b_exclusion184_koentec_audit_v01",
        "identity": {"ticker": "029960", "isu_cd": "KR7029960002"},
        "replay_scope": "P2-2 full chronological replay under changed cash path; no cash-skip ledger reuse as evidence of position status",
        "control": {"trade_rows": len(kct), "entry_events": len(kc), "executed_entries": int(((kc["event_type"] == "ENTRY") & (kc["event_status"] == "EXECUTED")).sum()), "executed_exits": int(((kc["event_type"] == "EXIT") & (kc["event_status"] == "EXECUTED")).sum()), "cash_skipped_entries": len(skipped), "cash_delta_on_skips_krw": [float(pd.to_numeric(r.cash_after_krw) - pd.to_numeric(r.cash_before_krw)) for r in skipped.itertuples()], "missing_marks": int(pd.read_csv(OUT / "control_missing_marks.csv", dtype=str).assign(ticker=lambda d: d.ticker.map(norm_ticker)).query("ticker == '029960' and isu_cd == 'KR7029960002'").shape[0])},
        "candidate": {"trade_rows": len(kpt), "portfolio_event_rows": len(kp), "executed_entries": int(((kp["event_type"] == "ENTRY") & (kp["event_status"] == "EXECUTED")).sum()), "executed_exits": int(((kp["event_type"] == "EXIT") & (kp["event_status"] == "EXECUTED")).sum()), "filter_audit_rows": len(ka), "filter_status_counts": ka["candidate_status"].value_counts().sort_index().to_dict(), "missing_marks": int(pd.read_csv(OUT / "candidate_missing_marks.csv", dtype=str).assign(ticker=lambda d: d.ticker.map(norm_ticker)).query("ticker == '029960' and isu_cd == 'KR7029960002'").shape[0])},
        "portfolio_effect": {"executed_share_exposure_any_group": False, "cutoff_open_position_any_group": False, "cash_proceeds_or_fees_from_position": False, "target_identity_trade_or_mark_leakage": False},
        "final_status": "NO_EXECUTED_KOENTEC_EXPOSURE_IN_EITHER_GROUP",
    }
    write_json(OUT / "koentec_exclusion184_audit.json", koentec_audit)

    authority_paths = [
        "docs/validation/backtest_common_rules.md",
        "docs/validation/official_strategy_adoption_criteria.md",
        "docs/strategies/strategy_lifecycle.md",
        "docs/patterns/pattern_a_fast/strategy/version_02/README.md",
        "src/trend_scanner/universe/permanent_identity_exclusions.py",
    ]
    authority = {p: {"sha256": sha(ROOT / p), "git_blob": None} for p in authority_paths}
    write_json(OUT / "authority_hashes.json", {"baseline_git_sha": BASELINE_COMMIT, "files": authority, "execution_code_and_inputs": {"source_manifest": "source_manifest.json", "verified": raw_integrity["source_manifest_verification"]}})

    comparison = pd.read_csv(OUT / "metrics_comparison.csv", dtype=str).fillna("")
    def metric(key, group):
        x = comparison.loc[comparison["metric"].eq(key), group]
        return x.iloc[0] if len(x) else ""
    cfull, pfull = p2_new["control_metrics"], p2_new["candidate_metrics"]
    cgate, pgate = gate_out["CONTROL"], gate_out["ALIGNMENT_MCAP_500B"]
    delta = float(cfull["mdd_pct"]) - float(pfull["mdd_pct"])
    report = [
        "# FAST Core V2 Alignment + 500B — 영구 제외 184쌍 반영, P3 재판정 및 P2-2 재생 V01",
        "",
        "| 심각도 | 독립 원인 수 | 사유 |", "|---|---:|---|",
        "| CRITICAL | 0 | 없음 |",
        "| MAJOR | 0 | 공식 게이트를 막는 별도 구조 오류 없음 |",
        f"| MINOR | {len(minor_issues)} | 종목별 adjusted OHLC 행의 `HIGH_LT_CLOSE`; 미해결 mark는 UNRESOLVED로 유지하고 carry/보간하지 않음 |",
        "",
        f"**P2-2 단일 기간 공식 판정: {official_status}.** A~D는 양 그룹 PASS, E는 관측 NAV로 OBSERVED야. 이 결과는 5기간 종합 채택이나 후보 승격을 뜻하지 않아.",
        "",
        "## 정책 변경과 출처",
        "",
        f"- 실행 기준 Git: `{BASELINE_COMMIT}`; 실행 직전 HEAD와 origin/main이 일치했어. 기존 registry 182 exact pairs는 유지했고 신규는 2쌍만 추가했어 (`+2 / -0`, 다른 pair 변경 0).",
        f"- 신규 exact pair canonical hash (`sorted_exact_pair_json_v01`): `{canonical}`. Registry source SHA-256: `{policy['current_source_sha256']}`. 기준선 182-pair hash: `{policy['baseline_canonical_sha256']}`.",
        "- 승인 사유는 두 exact identity의 미해결 주식교환·현금대가 정산/가치평가와 범용 처리 구현의 비경제성이야. 과거 손익·승률을 이유로 삼지 않았고, 다른 ticker/ISU는 추가 제외하지 않았어.",
        f"- `source_manifest.json`은 입력·코드·계약 {raw_integrity['source_manifest_verification']['checked']}/{raw_integrity['source_manifest_verification']['expected']}개 hash 일치. 과거 P2 source 106/106 및 P3 sealed artifacts 194/194 검증 결과도 `exclusion_policy_audit.json`과 `source_artifact_hash_evidence.csv`에 보존했어.",
        "- authority 문서와 수정된 registry의 SHA-256은 `authority_hashes.json`에 있어. 전략 evaluator/체결/비용/웹/운영 코드는 수정하지 않았어.",
        "",
        "## P3-1 / P3-2 영향 감사와 A~E 재판정",
        "",
        "두 기간은 저장된 공식 거래·현금·NAV 원장만 읽었고 전수 신호 재계산이나 portfolio replay는 하지 않았어. 제거된 target 거래행은 CONTROL 3건씩이고 모두 `SKIPPED_CASH_UNAVAILABLE`; cash_before와 cash_after가 같아. 후보 target trade/fill은 0건이고 관련 후보 filter audit 행은 각 20건이 거절 상태였어. 비제외 event/cash rows, NAV 및 성과는 exact 동일해.",
        "",
        "| 기간 | 그룹 | 거래일 | 총수익률 | CAGR | Observed MDD | NAV coverage | NAV 누락 | 공식 A~E |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for period, rows in (("P3-1", p3_1_gate["groups"]), ("P3-2", p3_2_gate["groups"])):
        for group, g in rows.items():
            if period == "P3-1":
                c = g["C_profitability"]; d = g["D_mdd"]; e = g["E_validity"]
                total, cagr, mdd, coverage, missing, sessions = c["total_return_pct"], c["cagr_pct"], d["mdd_pct"], e["nav_coverage_pct"], e["missing_nav_days"], e["total_valuation_days"]
                statuses = "/".join(g[k]["status"] for k in ("A_integrity", "B_costs", "C_profitability", "D_mdd", "E_validity"))
            else:
                total, cagr, mdd, coverage, missing, sessions = g["C_total_return_pct"], g["C_cagr_pct"], g["D_mdd_pct"], g["E_coverage_pct"], g["E_missing_marks"], g["E_total_days"]
                combined = p3_2_source_gate["combined"]
                statuses = "/".join((g["A_integrity"], g["B_costs"], g["C_profitability"], combined["D_mdd"], g["E_validity"]))
            report.append(f"| {period} | {group} | {sessions} | {fmt(total)}% | {fmt(cagr)}% | {fmt(mdd)}% | {fmt(coverage)}% | {missing} | {statuses} |")
    report += [
        "",
        "- P3-1/P3-2 양쪽 모두 `PASS_WITH_OBSERVED_NAV` 유지. 기존 A~E 수치와 비제외 cash/event/NAV 흐름이 그대로인 근거는 `p3_1_rejudgment.json`, `p3_2_rejudgment.json`, `p3_1_gate_results.json`, `p3_2_gate_results.json`이야.",
        "",
        "## P2-2 동결 신호 재사용과 전체 포트폴리오 재생",
        "",
        "- P2 V02의 동결 signal/filter ledger를 hash·PIT·identity·전략 버전 기준으로 확인하고 정확한 신규 pair 행만 제거했어. CONTROL trade 4행, 후보 trade 1행, 후보 filter audit 21행을 제외한 뒤 재생했어. 잔여 ledger는 CONTROL 2,283행, 후보 282행, 후보 filter audit 9,062행이야.",
        "- 평가 구간 2021-01-04~2026-08-31의 정확한 KRX 1,387 sessions를 새 cash path로 chronological replay했어. 2026-09-01은 exit 지원만 했고 NAV/성과에 포함하지 않았어. 신호 평가 0회; CONTROL/후보 portfolio replay 각각 1회; worker 오류 0; retry 0; replay journal 완료.",
        "",
        "| A~E | CONTROL | ALIGNMENT_MCAP_500B |",
        "|---|---|---|",
    ]
    for key, label in (("A_integrity", "A 무결성"), ("B_costs", "B 비용"), ("C_profitability", "C 수익성"), ("D_mdd", "D MDD"), ("E_validity", "E NAV 유효성")):
        report.append(f"| {label} | {cgate[key]['status']} | {pgate[key]['status']} |")
    report += [
        "",
        "| 지표 | CONTROL | 후보 | 후보−CONTROL |",
        "|---|---:|---:|---:|",
    ]
    display_rows = [
        ("종료 자산(원)", "ending_equity_krw"), ("총수익률(%)", "total_return_pct"), ("CAGR(%)", "cagr_pct"), ("Observed MDD(%)", "mdd_pct"),
        ("NAV coverage(%)", "nav_coverage_pct"), ("NAV 결측일", "missing_nav_days"), ("진입 시도", "eligible_entry_attempts"), ("현금 부족 skip", "cash_shortage_skipped_entries"),
        ("현금 부족률(%)", "cash_shortage_skip_rate_pct"), ("실제 매수", "executed_entry_count"), ("실현 청산", "realized_exit_count"), ("cutoff 미청산", "open_at_cutoff_count"),
        ("실현 거래", "realized_trade_count"), ("승률(%)", "realized_win_rate_pct"), ("평균 순수익률(%)", "realized_mean_net_return_pct"), ("중앙 순수익률(%)", "realized_median_net_return_pct"),
        ("평균 보유 거래일", "realized_mean_holding_trading_sessions"), ("중앙 보유 거래일", "realized_median_holding_trading_sessions"), ("최대 수익률(%)", "realized_max_net_return_pct"), ("최대 손실률(%)", "realized_min_net_return_pct"),
        ("+20% 이상", "realized_ge_20_pct_count"), ("+50% 이상", "realized_ge_50_pct_count"), ("+100% 이상", "realized_ge_100_pct_count"),
        ("-10% 이하", "realized_le_minus_10_pct_count"), ("-15% 이하", "realized_le_minus_15_pct_count"), ("-20% 이하", "realized_le_minus_20_pct_count"), ("-30% 이하", "realized_le_minus_30_pct_count"),
        ("Loss Guard 진입", "loss_guard_triggered_executed_entry_count"), ("PROGRESSED 진입", "progressed_executed_entry_count"), ("평균 자본 활용률(%)", "average_capital_utilization_pct"),
        ("최대 동시 보유", "maximum_concurrent_positions"), ("회전율 배수", "turnover_multiple"), ("수수료(원)", "total_commissions_krw"), ("슬리피지 영향(원)", "total_slippage_impact_krw"),
    ]
    for label, key in display_rows:
        c, p = cfull.get(key), pfull.get(key)
        if key in set(comparison["metric"]):
            c, p = metric(key, "CONTROL"), metric(key, "ALIGNMENT_MCAP_500B")
        d = None if c in (None, "") or p in (None, "") else float(p) - float(c)
        report.append(f"| {label} | {fmt(c)} | {fmt(p)} | {fmt(d)} |")
    report += [
        "",
        f"- MDD: CONTROL {fmt(cfull['mdd_pct'])}% (peak {cfull['mdd_peak_date']}, trough {cfull['mdd_trough_date']}, recovery {cfull['mdd_recovery_date']}); 후보 {fmt(pfull['mdd_pct'])}% (peak {pfull['mdd_peak_date']}, trough {pfull['mdd_trough_date']}, recovery {pfull['mdd_recovery_date']}). `CONTROL MDD - 후보 MDD = {fmt(delta)}%p`; 공식 실패 기준 +5.0%p에 미달해 후보 상대 MDD는 통과야.",
        f"- 청산 사유: CONTROL `{metric('exit_reason_counts', 'CONTROL')}`; 후보 `{metric('exit_reason_counts', 'ALIGNMENT_MCAP_500B')}`.",
        f"- 비용: CONTROL 수수료 {fmt(cfull['total_commissions_krw'])}원·슬리피지 {fmt(cfull['total_slippage_impact_krw'])}원; 후보 수수료 {fmt(pfull['total_commissions_krw'])}원·슬리피지 {fmt(pfull['total_slippage_impact_krw'])}원. 양쪽에서 수수료와 슬리피지 재계산, 정수주, 500만원 포함예산, T+1 매도자금, 현금 보존 검사가 PASS야.",
        f"- cutoff 미청산 {cfull['open_at_cutoff_count']}/{pfull['open_at_cutoff_count']}건은 실현 청산과 분리했고 유효 cutoff mark로만 평가했어. 허구 매도·가상 비용은 넣지 않았어.",
        "",
        "### NAV 결측과 최종 integrity readjudication",
        "",
        "관측 NAV coverage는 CONTROL 99.86%(1,385/1,387), 후보 99.28%(1,377/1,387)야. 양쪽 최장 연속 결측은 1일이고 전체 NAV 결측은 CONTROL 2일, 후보 10일이야. 세 identity의 adjusted 원천 행은 `HIGH_LT_CLOSE`라 Repository V2 analytic projection이 거부했어. 같은 날 raw 거래행은 있지만 adjusted close를 유효 mark라고 임의 승인할 수 없어서 모든 mark를 UNRESOLVED로 두고 날짜 전체를 NAV/MDD에서 제외했어. 날짜·raw/adjusted hash·OHLC·shares/진입원가 증거는 `unresolved_mark_reconciliation.csv`에 있어.",
        "- 원본 finalizer의 `integrity_audit.json`은 결측 mark가 1건이라도 있으면 MAJOR/CHECK_REQUIRED로 분류했어. 공식 채택 기준 §2 D/E는 coverage ≥90%이면 관측 MDD를 허용하고 valuation gap 자체로 자동 CHECK_REQUIRED하지 않는다고 명시해. P3-1/P3-2 선행 공식 재판정도 같은 유형의 isolated invalid adjusted row를 MINOR로 취급했어.",
        "- 이번 원인은 3 identity·12 group-day에 국한돼 있고 coverage 하락은 90% 기준과 멀어. 별도 구조 오류(신호/PIT, 가격파일 미가용, projection mismatch, 시총, 현금/비용/정산, worker, cutoff entry)는 없어. 이 근거로 raw finalizer 기록은 보존하고 `p2_2_integrity_audit.json`에서 공식 기준에 따라 `PASS_WITH_OBSERVED_NAV`로 재판정했어. 원자료 결측 자체는 지우거나 수치 보정하지 않았어.",
        "",
        "### 코엔텍(`029960 / KR7029960002`) 현금 경로와 보유 감사",
        "",
        "새 현금 경로로 다시 확인했어. CONTROL에는 signal trade 2건이 있었지만 둘 다 `SKIPPED_CASH_UNAVAILABLE`; 현금 변화는 각각 0원이야. 실제 매수·매도 0건, cutoff 보유 0주, NAV mark 0건이야. 후보는 trade/event 0건이며 3개 필터 감사행은 2건 alignment 거절, 1건 시총 거절이야. 따라서 재생 후 어느 그룹에도 Koentec 보유·정산 노출이 없어. 상세 행은 `koentec_exclusion184_audit.json`과 그룹 원장에 남겼어.",
        "",
        "### 182쌍 P2 V02와의 변화",
        "",
        "기존 V02는 182쌍 기준이었고 CONTROL coverage 68.85%, 후보 61.86%여서 총수익·CAGR·MDD는 공식 산출 불가였어. 184쌍 재생에서는 CONTROL 99.86%, 후보 99.28%야. CONTROL attempts 2,287→2,283, cash skip 1,829→1,821, 실매수 458→462, 실현 청산 410→414. 후보 attempts 283→282, cash skip 33→29, 실매수 250→253, 실현 청산 228→233, cutoff 미청산 22→20. old outputs로 새 cash path를 추정하지 않고 전체 portfolio를 각각 1회 재생했어. 항목별 차이는 `p2_2_baseline_comparison.csv`에 있어.",
        "",
        "## 판정 범위 및 산출물",
        "",
        "- P2-2만 재판정했어. `NOT_FINAL_5WINDOW`, 후보 공식 채택 `NOT_EVALUATED`, 기본 전략 승격 `NOT_EVALUATED`; 기본 전략 `PATTERN_A_FAST_FINAL_STRATEGY_V02` 유지.",
        "- 필수 evidence: `exclusion_policy_audit.json`, `p3_1_rejudgment.json`, `p3_2_rejudgment.json`, `p3_1_gate_results.json`, `p3_2_gate_results.json`, `p2_2_gate_results.json`, `p2_2_integrity_audit.json`, `permanent_exclusion_pairs.csv`, 양 그룹 trades/events/cash/NAV/missing marks, `source_manifest.json`, `artifact_hashes.json`, replay/finalizer/adjudication scripts.",
        "- 추가 provenance: raw conservative finalizer outputs `p2_2_finalizer_integrity_audit_raw.json` / `p2_2_finalizer_report_raw.md`; original sealed source snapshots and hash evidence remain in place. `artifact_hashes.json` lists the current research directory files; its own hash is excluded.",
    ]
    raw_report_path.write_text("\n".join(report) + "\n", encoding="utf-8")

    # The exact full-run source manifest is input provenance; it is not rewritten.
    current_hash = {e["path"]: e["sha256"] for e in read_json(OUT / "source_manifest.json")["files"]}
    if current_hash.get("artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_exclusion_184_p3_rejudgment_p2_2_replay_v01/finalize_p2_2_exclusion184.py") != sha(OUT / "finalize_p2_2_exclusion184.py"):
        raise RuntimeError("FROZEN_FINALIZER_SOURCE_HASH_CHANGED")
    hashes = []
    for path in sorted(OUT.iterdir()):
        if path.is_file() and path.name != "artifact_hashes.json" and path.suffix != ".pyc":
            hashes.append({"path": path.name, "sha256": sha(path), "bytes": path.stat().st_size})
    write_json(OUT / "artifact_hashes.json", {"schema": "fast_core_v2_alignment_500b_exclusion184_artifact_hashes_v01", "files": hashes, "self_hash_excluded": True})
    print(json.dumps({"status": official_status, "pair_count": len(pairs), "pair_hash": canonical, "mark_rows": len(mark_frame), "minor_roots": len(minor_issues), "raw_integrity_status": raw_integrity["status"], "source_hash_check": "PASS", "replays_started": 0, "report": str(OUT / "report.md")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
