#!/usr/bin/env python3
"""Build a transparent partial report after the fail-closed P1 replay stopped."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pandas as pd

OUT = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[5]
RUNNER = OUT / "run_5window_simple_backtest.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("five_window_partial_metrics", RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("RUNNER_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    runner = load_runner()
    preflight = json.loads((OUT / "preflight.json").read_text(encoding="utf-8"))
    failure = json.loads((OUT / "failure.json").read_text(encoding="utf-8"))

    sources = [
        ("P1", "CONTROL", runner.CONTROL_ID, OUT / "p1_control_trades.csv", "COMPLETE_CONTROL_ONLY"),
        ("P3-2", "CONTROL", runner.CONTROL_ID, runner.CONTROL_DIR / "control_strategy_trades.csv", "REUSED_VALIDATED_SAVED_RESULT"),
        ("P3-2", "MA60", runner.MA60_ID, runner.MA60_DIR / "ma60_strategy_trades.csv", "REUSED_VALIDATED_SAVED_RESULT"),
        ("P3-2", "ALIGNMENT", runner.ALIGNMENT_ID, runner.ALIGNMENT_DIR / "alignment_strategy_trades.csv", "REUSED_VALIDATED_SAVED_RESULT"),
    ]
    metric_rows = []
    for window, strategy, strategy_id, path, result_status in sources:
        frame = pd.read_csv(path, dtype={"ticker": str, "pair_id": str})
        costed = runner.add_costed_returns(frame)
        row = runner.metric_summary(costed, window, strategy, strategy_id)
        row["result_status"] = result_status
        row["source_file"] = str(path.relative_to(ROOT))
        row["mdd_pct"] = None
        row["mdd_status"] = "NOT_AVAILABLE_IN_EXISTING_SIMPLE_TRADE_LEVEL_REPLAY"
        metric_rows.append(row)

    metrics = pd.DataFrame(metric_rows)
    metrics.to_csv(OUT / "metrics_by_window_partial.csv", index=False, encoding="utf-8")

    threshold_columns = [
        "window_id", "strategy", "result_status", "trade_count",
        "terminal_ge_20_count", "terminal_ge_20_rate_pct",
        "terminal_ge_50_count", "terminal_ge_50_rate_pct",
        "terminal_ge_100_count", "terminal_ge_100_rate_pct",
        "terminal_le_neg_10_count", "terminal_le_neg_10_rate_pct",
        "terminal_le_neg_15_count", "terminal_le_neg_15_rate_pct",
        "terminal_le_neg_20_count", "terminal_le_neg_20_rate_pct",
        "terminal_le_neg_30_count", "terminal_le_neg_30_rate_pct",
        "loss_guard_exit_count", "loss_guard_rate_pct",
    ]
    metrics[threshold_columns].to_csv(OUT / "threshold_summary_partial.csv", index=False, encoding="utf-8")

    p3 = metrics.loc[metrics["window_id"].eq("P3-2")].set_index("strategy")
    deltas = []
    for candidate in ("MA60", "ALIGNMENT"):
        deltas.append({
            "window_id": "P3-2",
            "candidate": candidate,
            "result_status": "REUSED_VALIDATED_SAVED_RESULT",
            "trade_count_delta": int(p3.loc[candidate, "trade_count"] - p3.loc["CONTROL", "trade_count"]),
            "average_terminal_delta_pp": float(p3.loc[candidate, "average_terminal_return_pct"] - p3.loc["CONTROL", "average_terminal_return_pct"]),
            "median_terminal_delta_pp": float(p3.loc[candidate, "median_terminal_return_pct"] - p3.loc["CONTROL", "median_terminal_return_pct"]),
            "realized_win_rate_delta_pp": float(p3.loc[candidate, "realized_win_rate_pct"] - p3.loc["CONTROL", "realized_win_rate_pct"]),
            "loss_guard_rate_delta_pp": float(p3.loc[candidate, "loss_guard_rate_pct"] - p3.loc["CONTROL", "loss_guard_rate_pct"]),
            "mdd_comparison": "NOT_AVAILABLE",
        })
    pd.DataFrame(deltas).to_csv(OUT / "p3_2_partial_candidate_deltas.csv", index=False, encoding="utf-8")

    execution_rows = [
        {"window_id": "P1", "strategy": "CONTROL", "status": "COMPLETE_CONTROL_ONLY", "worker_count": 10, "ticker_count": 2539, "trade_rows": 826, "worker_errors": 0, "notes": "standalone completed ledger; not a three-way comparison"},
        {"window_id": "P1", "strategy": "MA60", "status": "FAILED_CHECK_REQUIRED", "worker_count": 10, "ticker_count": 2539, "trade_rows": None, "worker_errors": 1, "notes": "614 successful-worker trade rows observed before fail-closed validation; not a complete ledger or metric"},
        {"window_id": "P1", "strategy": "ALIGNMENT", "status": "NOT_STARTED_AFTER_MA60_FAILURE", "worker_count": 10, "ticker_count": 0, "trade_rows": None, "worker_errors": None, "notes": "runner stopped at MA60 stage"},
        {"window_id": "P2-1", "strategy": "ALL", "status": "NOT_STARTED", "worker_count": 10, "ticker_count": 0, "trade_rows": None, "worker_errors": None, "notes": "runner stopped during P1"},
        {"window_id": "P2-2", "strategy": "ALL", "status": "NOT_STARTED", "worker_count": 10, "ticker_count": 0, "trade_rows": None, "worker_errors": None, "notes": "runner stopped during P1"},
        {"window_id": "P3-1", "strategy": "ALL", "status": "NOT_STARTED", "worker_count": 10, "ticker_count": 0, "trade_rows": None, "worker_errors": None, "notes": "runner stopped during P1"},
        {"window_id": "P3-2", "strategy": "CONTROL/MA60/ALIGNMENT", "status": "REUSED_VALIDATED_SAVED_RESULT", "worker_count": 10, "ticker_count": 2539, "trade_rows": "405/337/179", "worker_errors": 0, "notes": "saved ledgers reused after exact provenance and strategy checks"},
    ]
    execution = pd.DataFrame(execution_rows)
    execution.to_csv(OUT / "window_execution_status.csv", index=False, encoding="utf-8")

    audit_inputs = [
        OUT / "run_5window_simple_backtest.py",
        runner.MA60_DIR / "run_monthly_ma_entry_filter_backtest.py",
        runner.CONTROL_DIR / "control_strategy_trades.csv",
        runner.MA60_DIR / "ma60_strategy_trades.csv",
        runner.ALIGNMENT_DIR / "alignment_strategy_trades.csv",
        OUT / "p1_control_trades.csv",
        OUT / "p1_control_pit_mcap_audit.csv",
        OUT / "identity_authority_audit.csv",
        OUT / "failure.json",
    ]
    file_hashes = {str(path.relative_to(ROOT)): sha256(path) for path in audit_inputs if Path(path).is_file()}
    provenance = {
        "work_id": runner.WORK_ID,
        "status": "CHECK_REQUIRED",
        "final_token": runner.CHECK_TOKEN,
        "start_head": preflight.get("start_head"),
        "start_origin_main": preflight.get("start_origin_main"),
        "frozen_pit_sha256": preflight.get("frozen_pit_sha256"),
        "frozen_calendar_sha256": preflight.get("frozen_calendar_sha256"),
        "survivor_identity_count": preflight.get("survivor_identity_count"),
        "worker_count": 10,
        "cost_contract": preflight.get("cost_contract"),
        "mdd_contract": preflight.get("mdd_contract"),
        "network_calls": preflight.get("network_calls"),
        "p3_saved_results_reused": preflight.get("p3_saved_results_reused"),
        "p3_trade_artifacts_match_head": preflight.get("p3_trade_artifacts_match_head"),
        "post_p3_change_scope": preflight.get("post_p3_change_scope"),
        "failure": failure,
        "file_sha256": file_hashes,
    }
    (OUT / "partial_provenance.json").write_text(json.dumps(provenance, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")

    p1_control = metrics.loc[(metrics["window_id"].eq("P1")) & metrics["strategy"].eq("CONTROL")].iloc[0]
    report = f"""# FAST_CORE_V2_MA60_VS_BULLISH_ALIGNMENT_5WINDOW_SIMPLE_BACKTEST_V01\n\n**상태: CHECK_REQUIRED**\n\n## 결과 범위\n\n5개 기간의 3전략 비교는 완결되지 않았어. P3-2는 exact-match가 확인된 저장 결과를 재사용했고, P1 CONTROL은 2,539개 종목 처리를 완료했어. P1 MA60은 2,539개 순회를 마쳤지만 worker 오류 1건 때문에 fail-closed 검증에서 중단됐어. 그 결과 P1 MA60 완전 원장/지표, P1 ALIGNMENT, P2-1, P2-2, P3-1 결과는 없어.\n\n실패 세부 기록은 `failure.json`에 보존했어. 자동 재실행은 하지 않았어.\n\n## 완료된 단독/재사용 결과\n\nP1 CONTROL은 단독 산출물이므로 후보와 비교하지 않아.\n\n| 기간/전략 | 거래 수 | 실현 | cutoff 미종료 | 순 terminal 평균 | 순 terminal 중앙값 | 실현 승률 | Loss Guard 비율 | MDD |\n|---|---:|---:|---:|---:|---:|---:|---:|---|\n| P1 CONTROL | {int(p1_control['trade_count'])} | {int(p1_control['realized_count'])} | {int(p1_control['open_at_cutoff_count'])} | {p1_control['average_terminal_return_pct']:.2f}% | {p1_control['median_terminal_return_pct']:.2f}% | {p1_control['realized_win_rate_pct']:.2f}% | {p1_control['loss_guard_rate_pct']:.2f}% | 산출 불가 |\n| P3-2 CONTROL | {int(p3.loc['CONTROL', 'trade_count'])} | {int(p3.loc['CONTROL', 'realized_count'])} | {int(p3.loc['CONTROL', 'open_at_cutoff_count'])} | {p3.loc['CONTROL', 'average_terminal_return_pct']:.2f}% | {p3.loc['CONTROL', 'median_terminal_return_pct']:.2f}% | {p3.loc['CONTROL', 'realized_win_rate_pct']:.2f}% | {p3.loc['CONTROL', 'loss_guard_rate_pct']:.2f}% | 산출 불가 |\n| P3-2 MA60 | {int(p3.loc['MA60', 'trade_count'])} | {int(p3.loc['MA60', 'realized_count'])} | {int(p3.loc['MA60', 'open_at_cutoff_count'])} | {p3.loc['MA60', 'average_terminal_return_pct']:.2f}% | {p3.loc['MA60', 'median_terminal_return_pct']:.2f}% | {p3.loc['MA60', 'realized_win_rate_pct']:.2f}% | {p3.loc['MA60', 'loss_guard_rate_pct']:.2f}% | 산출 불가 |\n| P3-2 ALIGNMENT | {int(p3.loc['ALIGNMENT', 'trade_count'])} | {int(p3.loc['ALIGNMENT', 'realized_count'])} | {int(p3.loc['ALIGNMENT', 'open_at_cutoff_count'])} | {p3.loc['ALIGNMENT', 'average_terminal_return_pct']:.2f}% | {p3.loc['ALIGNMENT', 'median_terminal_return_pct']:.2f}% | {p3.loc['ALIGNMENT', 'realized_win_rate_pct']:.2f}% | {p3.loc['ALIGNMENT', 'loss_guard_rate_pct']:.2f}% | 산출 불가 |\n\nP3-2 단일 기간에서 MA60은 CONTROL 대비 terminal 평균 {p3.loc['MA60', 'average_terminal_return_pct'] - p3.loc['CONTROL', 'average_terminal_return_pct']:+.2f}%p, ALIGNMENT은 {p3.loc['ALIGNMENT', 'average_terminal_return_pct'] - p3.loc['CONTROL', 'average_terminal_return_pct']:+.2f}%p야. 이 관찰만으로 여러 기간의 반복성을 판단하거나 전략 채택 결정을 내릴 수 없어.\n\n## 중단 원인\n\nP1 MA60 재생에서 `005300` / `KR7005300009` / KOSPI 종목의 적격 NEG40 날짜 **2017-11-02**에 Pattern A stage가 `UNAVAILABLE`이어서 공통 V2 엔진이 예외를 발생시켰어. 해당 예외를 무시하거나 대체 stage를 넣으면 기존 exit lifecycle이 달라지므로 원래 fail-closed 동작을 유지했어. 오류가 난 worker의 거래 결과는 완전한 MA60 원장에 포함할 수 없어.\n\n- P1 CONTROL: worker 10, 2,539/2,539, 거래 826건, MCAP 감사 19,770건, worker 오류 0건\n- P1 MA60: worker 10, 2,539/2,539 순회, 성공 worker의 진행 출력상 614 trade rows, worker 오류 1건. **614는 완전 원장/성과 수치가 아니야.**\n- P1 ALIGNMENT, P2-1, P2-2, P3-1: 실행하지 않음\n- P3-2: 저장된 CONTROL 405건 / MA60 337건 / ALIGNMENT 179건을 재사용\n\n## 계약과 한계\n\n매수/매도 수수료는 각각 0.015%, 매수/매도 슬리피지는 각각 0.1%를 적용했고 거래세는 반영하지 않았어. portfolio/현금 제약은 적용하지 않았어. 기존 simple trade-level 산출물에는 공통 equity series가 없어 MDD는 `NOT_AVAILABLE_IN_EXISTING_SIMPLE_TRADE_LEVEL_REPLAY`로 남겼어.\n\n전략 채택이나 버전 승격 판단은 내리지 않았어. 상세 partial 지표는 `metrics_by_window_partial.csv`, threshold 집계는 `threshold_summary_partial.csv`, 실행 상태와 출처 해시는 각각 `window_execution_status.csv`, `partial_provenance.json`에 있어.\n\n## 최종 결과 토큰\n\n`{runner.CHECK_TOKEN}`\n"""
    (OUT / "report.md").write_text(report, encoding="utf-8")

    summary = {
        "work_id": runner.WORK_ID,
        "status": "CHECK_REQUIRED",
        "final_token": runner.CHECK_TOKEN,
        "five_window_comparison_complete": False,
        "completed_standalone_results": ["P1 CONTROL"],
        "reused_complete_windows": ["P3-2"],
        "failed_stage": failure.get("stage"),
        "failure": failure,
        "not_started": ["P1 ALIGNMENT", "P2-1 CONTROL/MA60/ALIGNMENT", "P2-2 CONTROL/MA60/ALIGNMENT", "P3-1 CONTROL/MA60/ALIGNMENT"],
        "metrics_rows": metric_rows,
        "mdd_status": "NOT_AVAILABLE_IN_EXISTING_SIMPLE_TRADE_LEVEL_REPLAY",
        "strategy_adoption_decision": "NOT_MADE",
        "worker_count": 10,
        "network_calls": preflight.get("network_calls"),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")

    files = sorted(path.name for path in OUT.iterdir() if path.is_file() and path.name != "run_manifest.json")
    manifest = {"status": "CHECK_REQUIRED", "final_token": runner.CHECK_TOKEN, "worker_count": 10, "automatic_retry": False, "files": files}
    (OUT / "run_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": summary["status"], "metrics_rows": len(metric_rows), "files": files}, ensure_ascii=False))


if __name__ == "__main__":
    main()
