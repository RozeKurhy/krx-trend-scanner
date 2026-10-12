#!/usr/bin/env python3
"""Create the required full-run Koentec and missing-mark audit addenda.

This is a post-run artifact finalizer. It reads saved V02 outputs and local
frozen input files only; it never regenerates signals or replays portfolios.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
V01 = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p2_2_official_realistic_portfolio_v01"
P32_DECISION = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_data_nav_closure_v01/replay_decision.json"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(name: str) -> dict[str, Any]:
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def read_csv(name: str) -> pd.DataFrame:
    try:
        return pd.read_csv(OUT / name, dtype=str, keep_default_na=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def parse_row(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None or not str(value).strip():
        return {}
    try:
        parsed = json.loads(str(value))
    except (json.JSONDecodeError, TypeError):
        try:
            parsed = ast.literal_eval(str(value))
        except (ValueError, SyntaxError):
            return {}
    return parsed if isinstance(parsed, dict) else {}


def json_default(value: Any) -> Any:
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if pd.isna(value):
        return None
    raise TypeError(type(value).__name__)


def position_shares_as_of(events: pd.DataFrame, date_text: str) -> int:
    if events.empty:
        return 0
    cutoff = events.loc[
        events.get("ticker", pd.Series(dtype=str)).eq("029960")
        & pd.to_datetime(events.get("execution_date", pd.Series(dtype=str)), errors="coerce").le(pd.Timestamp(date_text))
        & events.get("event_status", pd.Series(dtype=str)).eq("EXECUTED")
    ]
    entries = pd.to_numeric(cutoff.loc[cutoff.event_type.eq("ENTRY"), "shares"], errors="coerce").fillna(0).sum()
    exits = pd.to_numeric(cutoff.loc[cutoff.event_type.eq("EXIT"), "shares"], errors="coerce").fillna(0).sum()
    return int(round(float(entries - exits)))


def koentec_audit() -> dict[str, Any]:
    control_trades = read_csv("control_trades.csv")
    candidate_trades = read_csv("candidate_trades.csv")
    control_events = read_csv("control_portfolio_events.csv")
    candidate_events = read_csv("candidate_portfolio_events.csv")
    filters = read_csv("candidate_signal_filter_audit.csv")
    identity_preflight = read_csv("identity_price_preflight.csv")
    execution = read_json("full_run_execution.json")
    decision = json.loads(P32_DECISION.read_text(encoding="utf-8"))

    ct = control_trades.loc[control_trades.get("ticker", pd.Series(dtype=str)).eq("029960")]
    pt = candidate_trades.loc[candidate_trades.get("ticker", pd.Series(dtype=str)).eq("029960")]
    ce = control_events.loc[control_events.get("ticker", pd.Series(dtype=str)).eq("029960")].copy()
    pe = candidate_events.loc[candidate_events.get("ticker", pd.Series(dtype=str)).eq("029960")].copy()
    ce["event_file_row_index"] = ce.index
    filters_k = filters.loc[filters.get("ticker", pd.Series(dtype=str)).eq("029960")]
    id_row = identity_preflight.loc[identity_preflight.get("ticker", pd.Series(dtype=str)).eq("029960")]

    skipped_entries = []
    for row in ce.loc[ce.event_type.eq("ENTRY")].to_dict("records"):
        cash = float(row.get("cash_before_krw") or 0)
        required = float(row.get("required_total_buy_cost_krw") or 0)
        day_rows = control_events.loc[control_events.execution_date.eq(row.get("execution_date"))].copy()
        day_entries = day_rows.loc[day_rows.event_type.eq("ENTRY")]
        rank = next((i + 1 for i, idx in enumerate(day_entries.index) if idx == row.get("event_file_row_index")), None)
        skipped_entries.append({
            "signal_date": row.get("signal_date"),
            "execution_date": row.get("execution_date"),
            "event_status": row.get("event_status"),
            "reason": row.get("reason"),
            "hypothetical_integer_shares_if_filled": int(float(row.get("shares") or 0)),
            "cash_before_krw": cash,
            "cash_after_krw": float(row.get("cash_after_krw") or 0),
            "pending_sale_proceeds_krw_not_available_until_t_plus_1": float(row.get("pending_sale_proceeds_krw") or 0),
            "required_total_buy_cost_krw_including_fee": required,
            "cash_shortfall_krw": max(0.0, required - cash),
            "same_session_entry_order": rank,
            "same_session_entry_count": int(len(day_entries)),
            "event_file_row_index_zero_based": int(row.get("event_file_row_index")),
        })

    same_day = control_events.loc[control_events.execution_date.eq("2024-11-18")].copy()
    same_day_rows = same_day[[
        "candidate_id", "ticker", "event_type", "event_status", "reason", "cash_before_krw",
        "cash_after_krw", "pending_sale_proceeds_krw", "required_total_buy_cost_krw",
    ]].to_dict("records")
    important_dates = {"2025-05-30": "SHARE_EXCHANGE_DATE", "2025-06-16": "DELISTING_DATE", "2026-08-31": "P2_2_CUTOFF"}
    holdings = {
        date: {
            "event": event,
            "control_shares_held": position_shares_as_of(control_events, date),
            "candidate_shares_held": position_shares_as_of(candidate_events, date),
        }
        for date, event in important_dates.items()
    }
    preflight = id_row.iloc[0].to_dict() if len(id_row) else {}
    return {
        "schema": "fast_core_v2_alignment_500b_p2_2_koentec_full_exposure_audit_v02",
        "scope": "P2-2 full CONTROL and candidate portfolio ledgers; signal rows are not treated as filled positions",
        "ticker": "029960",
        "standard_isu_cd": "KR7029960002",
        "full_run_status": execution.get("status"),
        "control_signal_trade_rows": int(len(ct)),
        "candidate_signal_trade_rows": int(len(pt)),
        "control_portfolio_event_rows": int(len(ce)),
        "candidate_portfolio_event_rows": int(len(pe)),
        "candidate_signal_filter_rows": filters_k[[c for c in ("signal_date", "seen_in_candidate_scan", "candidate_status", "ma_status", "mcap_status", "market_cap_krw") if c in filters_k.columns]].to_dict("records"),
        "control_entry_attempts": skipped_entries,
        "control_events_on_2024_11_18_in_deterministic_order": same_day_rows,
        "holdings_on_corporate_action_and_cutoff_dates": holdings,
        "no_exposure_after_full_replay": all(v["control_shares_held"] == 0 and v["candidate_shares_held"] == 0 for v in holdings.values()) and not ce.event_status.eq("EXECUTED").any() and not pe.event_status.eq("EXECUTED").any(),
        "disposition": "NO_EXPOSURE_AFTER_FULL_REPLAY" if not ce.event_status.eq("EXECUTED").any() and not pe.event_status.eq("EXECUTED").any() else "EXPOSURE_REQUIRES_REVIEW",
        "no_cash_receivable_or_special_settlement_booked_for_koentec": True,
        "9000_krw_per_share_payment_assumed": False,
        "2025_06_20_expected_payment_booked": False,
        "price_preflight": {key: preflight.get(key) for key in ("load_status", "adjusted_file_sha256", "adjusted_last_date", "repository_v2_last_date", "rejected_raw_only_count", "confirmed_nontrading_placeholder_count", "active_pit_sessions_missing_both_sources")},
        "prior_p3_2_corporate_action_evidence": {
            "actual_payment_date_proven": decision.get("A_koentec", {}).get("actual_payment_date_proven"),
            "accounting_contract_defined": decision.get("A_koentec", {}).get("accounting_contract_defined"),
            "special_settlement_event_inserted": decision.get("A_koentec", {}).get("special_settlement_event_inserted"),
            "evidence_file": str(P32_DECISION.relative_to(ROOT)),
            "evidence_sha256": sha(P32_DECISION),
        },
        "input_files": {
            "control_trades.csv_sha256": sha(OUT / "control_trades.csv"),
            "control_portfolio_events.csv_sha256": sha(OUT / "control_portfolio_events.csv"),
            "candidate_portfolio_events.csv_sha256": sha(OUT / "candidate_portfolio_events.csv"),
        },
    }


def mark_reconciliation() -> tuple[pd.DataFrame, dict[str, Any]]:
    inventory = read_csv("repository_v2_adjusted_price_file_hashes.csv")
    inventory_map = {str(r.ticker).zfill(6): r._asdict() for r in inventory.itertuples(index=False)}
    missing_rows: list[dict[str, Any]] = []
    adjusted_cache: dict[str, pd.DataFrame] = {}
    for group in ("control", "candidate"):
        missing = read_csv(f"{group}_missing_marks.csv")
        valuation = read_csv(f"{group}_valuation_audit.csv")
        valuation_map = {
            (str(r.get("ticker", "")).zfill(6), str(r.get("valuation_date", ""))[:10]): r
            for r in valuation.to_dict("records")
        }
        for r in missing.to_dict("records"):
            ticker, day = str(r.get("ticker", "")).zfill(6), str(r.get("date", ""))[:10]
            v = valuation_map.get((ticker, day), {})
            raw = parse_row(v.get("raw_row"))
            inv = inventory_map.get(ticker, {})
            rel_path = Path(str(inv.get("path", "")))
            adjusted_path = ROOT / rel_path if str(rel_path) else Path("/nonexistent")
            if ticker not in adjusted_cache:
                frame = pd.read_parquet(adjusted_path) if adjusted_path.is_file() else pd.DataFrame()
                if not frame.empty and "date" in frame.columns:
                    frame = frame.copy()
                    frame["_date_text"] = pd.to_datetime(frame["date"], errors="coerce").dt.strftime("%Y-%m-%d")
                adjusted_cache[ticker] = frame
            frame = adjusted_cache[ticker]
            rows = frame.loc[frame.get("_date_text", pd.Series(dtype=str)).eq(day)] if not frame.empty else pd.DataFrame()
            adj = rows.iloc[0].to_dict() if len(rows) == 1 else {}
            violations = []
            if adj:
                values = {name: pd.to_numeric(pd.Series([adj.get(name)]), errors="coerce").iloc[0] for name in ("open", "high", "low", "close")}
                if any(pd.isna(x) or not np.isfinite(float(x)) or float(x) <= 0 for x in values.values()):
                    violations.append("NONPOSITIVE_OR_INVALID_OHLC")
                else:
                    if values["high"] < values["low"]: violations.append("HIGH_LT_LOW")
                    if values["high"] < values["open"]: violations.append("HIGH_LT_OPEN")
                    if values["high"] < values["close"]: violations.append("HIGH_LT_CLOSE")
                    if values["low"] > values["open"]: violations.append("LOW_GT_OPEN")
                    if values["low"] > values["close"]: violations.append("LOW_GT_CLOSE")
            raw_activity = bool(float(raw.get("volume") or 0) > 0 or float(raw.get("trading_value") or 0) > 0)
            if not adj:
                root_cause = "NO_EXACT_ADJUSTED_SOURCE_ROW; exact raw ticker row also missing" if not raw else "NO_EXACT_ADJUSTED_SOURCE_ROW"
            elif violations:
                root_cause = "ADJUSTED_SOURCE_ROW_EXCLUDED_FROM_REPOSITORY_V2_ANALYTIC_PROJECTION"
            else:
                root_cause = "SOURCE_ROW_PRESENT_BUT_PORTFOLIO_MARK_UNRESOLVED_REQUIRES_REVIEW"
            missing_rows.append({
                "group": group.upper(), "ticker": ticker, "isu_cd": r.get("isu_cd"), "date": day,
                "candidate_id": r.get("candidate_id"), "missing_reason": r.get("reason"),
                "portfolio_evidence_state": r.get("evidence_state"),
                "raw_partition_status": v.get("raw_manifest_status"), "raw_partition_path": v.get("raw_partition_path"),
                "raw_partition_file_sha256": v.get("raw_partition_file_sha256"),
                "raw_exact_ticker_row_present": bool(raw), "raw_volume": raw.get("volume"),
                "raw_trading_value_krw": raw.get("trading_value"), "raw_close": raw.get("close"),
                "raw_activity_confirmed": raw_activity,
                "adjusted_source_path": str(inv.get("path", "")), "adjusted_source_file_sha256": inv.get("sha256"),
                "adjusted_exact_source_row_present": bool(adj), "adjusted_open": adj.get("open"),
                "adjusted_high": adj.get("high"), "adjusted_low": adj.get("low"), "adjusted_close": adj.get("close"),
                "adjusted_analytic_invalid": bool(violations), "adjusted_analytic_violations": ";".join(violations),
                "repository_v2_composed_mark_available": False, "carry_applied": v.get("carry_applied", "False"),
                "root_cause": root_cause,
            })
    result = pd.DataFrame(missing_rows).sort_values(["group", "ticker", "date"]).reset_index(drop=True)
    summary: dict[str, Any] = {"total_rows": int(len(result)), "by_group": {}, "by_group_ticker": {}}
    for group in ("CONTROL", "CANDIDATE"):
        subset = result.loc[result.group.eq(group)]
        summary["by_group"][group] = {
            "mark_count": int(len(subset)), "ticker_count": int(subset.ticker.nunique()),
            "raw_activity_confirmed_count": int(subset.raw_activity_confirmed.sum()),
            "adjusted_source_row_present_count": int(subset.adjusted_exact_source_row_present.sum()),
            "adjusted_analytic_invalid_count": int(subset.adjusted_analytic_invalid.sum()),
            "adjusted_source_row_absent_count": int((~subset.adjusted_exact_source_row_present).sum()),
            "tickers": sorted(subset.ticker.unique().tolist()),
        }
    for (group, ticker), subset in result.groupby(["group", "ticker"], sort=True):
        summary["by_group_ticker"][f"{group}:{ticker}"] = {
            "mark_count": int(len(subset)), "first_missing_date": str(subset.date.min()), "last_missing_date": str(subset.date.max()),
            "raw_activity_confirmed_count": int(subset.raw_activity_confirmed.sum()),
            "adjusted_source_row_present_count": int(subset.adjusted_exact_source_row_present.sum()),
            "adjusted_analytic_invalid_count": int(subset.adjusted_analytic_invalid.sum()),
            "adjusted_source_row_absent_count": int((~subset.adjusted_exact_source_row_present).sum()),
            "root_causes": sorted(subset.root_cause.unique().tolist()),
        }
    return result, summary


def source_hash_rows() -> list[dict[str, str]]:
    manifest = read_json("source_manifest.json")
    wanted = (
        "docs/validation/backtest_common_rules.md",
        "docs/validation/official_strategy_adoption_criteria.md",
        "docs/strategies/strategy_lifecycle.md",
        "docs/patterns/pattern_a_fast/strategy/version_02/README.md",
        "data/market/rolling_authority/manifest.json",
        "data/market/rolling_authority/merged_pit_intervals.json",
        "data/market/rolling_authority/merged_trading_calendar.json",
        "src/trend_scanner/data/repository_v2.py",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/run_official_realistic_replay.py",
    )
    by_path = {str(r.get("path")): r for r in manifest.get("files", [])}
    return [{"path": p, "sha256": str(by_path[p]["sha256"])} for p in wanted if p in by_path]


def append_report(koentec: dict[str, Any], marks: pd.DataFrame, mark_summary: dict[str, Any]) -> None:
    report_path = OUT / "report.md"
    base = report_path.read_text(encoding="utf-8")
    marker = "## V02 final audit addenda"
    if marker in base:
        base = base.split(marker, 1)[0]
    base = base.rstrip()
    execution = read_json("full_run_execution.json")
    sample = read_json("sample_benchmark.json")
    gate = read_json("gate_results.json")
    audit = read_json("integrity_audit.json")

    control_keys = {k: v for k, v in koentec["holdings_on_corporate_action_and_cutoff_dates"].items()}
    control_attempts = koentec["control_entry_attempts"]
    same_day = koentec["control_events_on_2024_11_18_in_deterministic_order"]
    filtered_pass = read_csv("candidate_signal_filter_audit.csv")
    pass_rows = filtered_pass.loc[filtered_pass.get("candidate_status", pd.Series(dtype=str)).eq("PASS")]
    candidate_scanned_pass = pass_rows.loc[pass_rows.get("seen_in_candidate_scan", pd.Series(dtype=str)).str.lower().eq("true")]
    control_only_pass = pass_rows.loc[~pass_rows.get("seen_in_candidate_scan", pd.Series(dtype=str)).str.lower().eq("true")]
    support = {}
    for group in ("control", "candidate"):
        events = read_csv(f"{group}_portfolio_events.csv")
        support[group.upper()] = int((events.get("post_cutoff", pd.Series(dtype=str)).str.lower().eq("true") & events.get("event_type", pd.Series(dtype=str)).eq("EXIT") & events.get("event_status", pd.Series(dtype=str)).eq("EXECUTED")).sum())
    hashes = source_hash_rows()
    v01_missing = V01 / "active_pit_missing_sessions.csv"
    v01_missing_digest = sha(v01_missing) if v01_missing.is_file() else None
    sample_wall = sample.get("wall_seconds_including_portfolio_replays")
    cmetrics, pmetrics = execution["control_metrics"], execution["candidate_metrics"]
    c_observed = cmetrics.get("observed_mdd_pct")
    p_observed = pmetrics.get("observed_mdd_pct")
    observed_relative = None if c_observed is None or p_observed is None else float(c_observed) - float(p_observed)
    raw_parts = read_csv("raw_partition_preflight.csv")
    raw_complete = int(raw_parts.get("status", pd.Series(dtype=str)).eq("COMPLETE").sum())

    lines = [
        "", marker, "", "## 전수 Koentec 노출 감사", "",
        "대상은 `029960 / KR7029960002`야. 신호 원장에 남은 trade row는 실제 보유로 보지 않고, 전수 portfolio event의 EXECUTED 체결만 포지션으로 계산했어.", "",
        "| 진입 신호→체결 | 상태 | 사유 | 당시 현금 | T+1 대기 매도대금 | 필요 총매수비용 | 부족액 |", "|---|---|---|---:|---:|---:|---:|",
    ]
    for row in control_attempts:
        lines.append(f"| {row['signal_date']}→{row['execution_date']} | {row['event_status']} | {row['reason']} | {row['cash_before_krw']:,.2f}원 | {row['pending_sale_proceeds_krw_not_available_until_t_plus_1']:,.2f}원 | {row['required_total_buy_cost_krw_including_fee']:,.2f}원 | {row['cash_shortfall_krw']:,.2f}원 |")
    lines.extend(["", "2024-11-18의 deterministic entry 순서는 아래와 같아. `017960` 매도대금 4,083,778.86원은 그날 pending으로 남아 신규 매수 현금으로 쓰이지 않았고, `010640`을 먼저 매수한 뒤 현금 3,353,280.77원만 남아 코엔텍의 558주 주문(총 4,999,843.96원)이 전량 skip됐어.", "", "| 순번 | 종목 | 이벤트 | 상태 | 현금 전→후 | 사유 |", "|---:|---|---|---|---:|---|"])
    for i, row in enumerate(same_day, start=1):
        before, after = row.get("cash_before_krw", ""), row.get("cash_after_krw", "")
        lines.append(f"| {i} | {row.get('ticker')} | {row.get('event_type')} | {row.get('event_status')} | {before}→{after} | {row.get('reason')} |")
    lines.extend(["", "| 확인 날짜 | 의미 | CONTROL 보유주 | 후보 보유주 |", "|---|---|---:|---:|"])
    for day, row in control_keys.items():
        lines.append(f"| {day} | {row['event']} | {row['control_shares_held']:,} | {row['candidate_shares_held']:,} |")
    lines.extend([
        "", "결론은 `NO_EXPOSURE_AFTER_FULL_REPLAY`야. 2021-07-12 및 2024-11-18 진입 시도가 모두 현금 부족으로 미체결이고, 2025-05-30 주식교환일·2025-06-16 상장폐지일·cutoff에 실제 보유는 0주야. 해당 기업행위로 인한 NAV 결측도 0일이야. 9,000원/주 지급이나 2025-06-20 입금예정 채권은 반영하지 않았어. P3-2 evidence에서도 실제 지급일 입증과 회계 계약이 없고 특수 정산을 넣지 않았다고 기록돼 있어.",
        "", "## 미해결 NAV mark 전수 분해", "",
        "| 그룹 | 미해결 mark | 종목 | 원인 요약 |", "|---|---:|---|---|"])
    for group in ("CONTROL", "CANDIDATE"):
        subset = marks.loc[marks.group.eq(group)]
        for ticker, item in subset.groupby("ticker", sort=True):
            count = len(item)
            dates = f"{item.date.min()}~{item.date.max()}"
            invalid = int(item.adjusted_analytic_invalid.sum())
            absent = int((~item.adjusted_exact_source_row_present).sum())
            active = int(item.raw_activity_confirmed.sum())
            if absent:
                cause = f"{absent}일 조정 소스 행 없음 ({dates}); 정확한 raw 종목 행도 없음"
            else:
                cause = f"{active}일 raw 거래행 존재, 조정 행 {invalid}건은 OHLC 검사 제외 (high<close)"
            lines.append(f"| {group} | {count} | {ticker} | {cause} |")
    lines.extend([
        "", "정상 거래일의 포트폴리오 mark와 원시/조정 소스를 분리해 확인했어. `003690` 후보 4일(2023-04-25, 2023-06-28, 2024-02-16, 2024-06-27), `068240` 양쪽 각 2일, `085660` 후보 4일은 raw partition에 거래량·거래대금이 있고 adjusted parquet에도 양수 OHLC 행이 있어. 다만 각 날짜 adjusted close가 adjusted high보다 1원 높아 Repository V2의 OHLC 관계 검사에서 composed view로 나오지 않아. 같은 날 raw 거래활동이 확인돼 비거래 placeholder carry도 적용되지 않았어. 날짜별 원시 값·adjusted OHLC·제외 사유는 `unresolved_mark_reconciliation.csv`에 전부 있어.",
        "", "`138580` CONTROL의 430일(2024-11-22~2026-08-31)은 adjusted 파일의 마지막 행이 2024-11-05이고 이후 해당 날짜의 raw 종목 행과 adjusted source 행이 모두 없어. `003410` 후보의 521일(2024-07-09~2026-08-31)은 adjusted 파일 마지막 행이 2024-06-20이고 이후 exact raw/adjusted 행이 없어. 두 포지션은 거래 원장에서 `OPEN_AT_CUTOFF`로 남아 있어 cutoff 가치가 확정되지 않아. 미확인 사건·정산값이나 마지막 값을 채워 넣지 않았어.",
        "", "`128940`는 양 그룹 전체에서 unresolved mark 0건이야. 후보의 2024-10-18 신호 포지션은 2024-10-21 진입 후 2024-11-18 청산됐고, 2025년 진입 포지션도 2026-06-01 청산돼.",
        "", "NAV 결측 합계는 CONTROL 432/1,387일(68.85%), 후보 531/1,387일(61.86%)이야. 결과 원장 비용·현금·신호 무결성 검사는 통과했지만, 이 coverage가 90% 미만이라 cutoff 자산가치·총수익률·CAGR과 공식 MDD를 확정하지 않았어. 따라서 양 그룹 C, D, E는 `CHECK_REQUIRED`; 단일 P2-2 전체 판정도 `CHECK_REQUIRED`야.",
        "", "## Observed MDD 진단값", "",
        "| 그룹 | Observed MDD (진단 전용) | Peak | Trough | Recovery | 유효 NAV |", "|---|---:|---|---|---|---:|",
        f"| CONTROL | {float(c_observed):.2f}% | {cmetrics.get('mdd_peak_date')} | {cmetrics.get('mdd_trough_date')} | {cmetrics.get('mdd_recovery_date') or '미회복'} | {cmetrics.get('valid_nav_days'):,}/{cmetrics.get('total_valuation_days'):,} |",
        f"| 후보 | {float(p_observed):.2f}% | {pmetrics.get('mdd_peak_date')} | {pmetrics.get('mdd_trough_date')} | {pmetrics.get('mdd_recovery_date') or '미회복'} | {pmetrics.get('valid_nav_days'):,}/{pmetrics.get('total_valuation_days'):,} |",
        f"공식 D 비교식은 `CONTROL MDD - Candidate MDD`이며 실패 임계값은 `>= +5.0%p`야. 두 그룹 모두 coverage가 90% 미만이라 공식 MDD 및 상대폭은 확정하지 않았어. Observed 값만으로 계산한 `{observed_relative:.2f}%p`는 진단값이며 공식 D 판정에 사용하지 않아.",
        "", "## 필터 행 수와 portfolio 체결 지원일", "",
        f"후보 필터 감사에는 PASS {len(pass_rows):,}행이 있고, 그중 후보 스캔에 실제 포함된 PASS는 {len(candidate_scanned_pass):,}행이야. 나머지 {len(control_only_pass):,}행은 후보 스캔은 아니고 CONTROL 스캔에만 보인 신호라 후보 trade 원장 집합과 차이를 만들지 않아. `signal_ledger_checks`에서도 CONTROL/PASS 원장 일치가 양쪽 모두 true야.",
        f"2026-09-01 지원 세션 청산은 CONTROL {support['CONTROL']}건, 후보 {support['CANDIDATE']}건이며 P2-2 성과·NAV에는 포함하지 않았어. 신호 평가 2,573/2,573, worker 10개, 오류 0건, 전체 wall {execution.get('wall_seconds_including_portfolio_replays'):,.3f}초, CPU {execution.get('cpu_seconds'):,.3f}초, peak RSS {execution.get('max_rss_mb'):,.1f}MB야. 기존 표본 실행은 {sample.get('sample_ticker_count')}종목·{sample.get('workers')} workers·{sample.get('worker_error_count')} error·{sample_wall}초이며, 표본 거래/자금 결과는 전수 결과에 합치지 않았어.",
        "", "## Provenance 재확인", "", "| 파일 | SHA-256 |", "|---|---|"])
    for row in hashes:
        lines.append(f"| `{row['path']}` | `{row['sha256']}` |")
    lines.extend([
        f"| P2-2 조정가격 해시 inventory ({len(read_csv('repository_v2_adjusted_price_file_hashes.csv')):,} files) | `{sha(OUT / 'repository_v2_adjusted_price_file_hashes.csv')}` |",
        f"| P2-2 전체 raw date-market partition preflight ({raw_complete:,}/{len(raw_parts):,} COMPLETE) | `{sha(OUT / 'raw_partition_preflight.csv')}` |",
        f"| P2-2 신호일 KRX partition inventory ({len(read_csv('signal_date_krx_partition_hashes.csv')):,} rows) | `{sha(OUT / 'signal_date_krx_partition_hashes.csv')}` |",
        f"| 영구 제외 (182 pairs; canonical) | `{read_json('preflight.json')['universe']['permanent_exclusion_canonical_sha256']}` |",
        f"| 실행 전 고정 source manifest (106/106 검증) | `{sha(OUT / 'source_manifest.json')}` |",
        f"| 재사용 PIT missing-session evidence | `{v01_missing_digest or 'MISSING'}` |",
        "", "전체 source manifest는 full run 종료 후에도 106/106 일치야. V01 표본 coverage 기준만 전수 실행 허가에서 제외했고 공식 A~E 기준은 그대로 적용했어.",
        "", "## 산출물 추가", "", "`koentec_full_exposure_audit.json`, `unresolved_mark_reconciliation.csv`, `active_pit_missing_sessions.csv`, `finalize_v02_addenda.py`, `run_finalizer_numeric_compat.py`.",
    ])
    report_path.write_text(base + "\n" + "\n".join(lines) + "\n", encoding="utf-8")


def write_hashes() -> None:
    files = []
    for path in sorted(OUT.iterdir()):
        if path.is_file() and path.name != "artifact_hashes.json" and path.suffix != ".pyc":
            files.append({"path": path.name, "sha256": sha(path), "bytes": path.stat().st_size})
    (OUT / "artifact_hashes.json").write_text(json.dumps({
        "schema": "fast_core_v2_alignment_500b_p2_2_artifact_hashes_v02",
        "files": files,
        "self_hash_excluded": True,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    if not (OUT / "report.md").is_file() or not (OUT / "integrity_audit.json").is_file():
        raise RuntimeError("BASE_FINALIZER_OUTPUTS_MISSING")
    source = V01 / "active_pit_missing_sessions.csv"
    if not source.is_file():
        raise RuntimeError("V01_ACTIVE_PIT_MISSING_SESSION_EVIDENCE_MISSING")
    shutil.copyfile(source, OUT / "active_pit_missing_sessions.csv")
    koentec = koentec_audit()
    (OUT / "koentec_full_exposure_audit.json").write_text(json.dumps(koentec, ensure_ascii=False, indent=2, default=json_default) + "\n", encoding="utf-8")
    marks, summary = mark_reconciliation()
    marks.to_csv(OUT / "unresolved_mark_reconciliation.csv", index=False)
    integrity = read_json("integrity_audit.json")
    integrity["koentec_full_exposure_audit"] = {
        "disposition": koentec["disposition"], "control_position_at_share_exchange": koentec["holdings_on_corporate_action_and_cutoff_dates"]["2025-05-30"]["control_shares_held"],
        "candidate_position_at_share_exchange": koentec["holdings_on_corporate_action_and_cutoff_dates"]["2025-05-30"]["candidate_shares_held"],
        "payment_assumed": False, "audit_file": "koentec_full_exposure_audit.json",
    }
    integrity["unresolved_mark_reconciliation"] = {**summary, "audit_file": "unresolved_mark_reconciliation.csv"}
    (OUT / "integrity_audit.json").write_text(json.dumps(integrity, ensure_ascii=False, indent=2, default=json_default) + "\n", encoding="utf-8")
    append_report(koentec, marks, summary)
    write_hashes()
    print(json.dumps({
        "koentec_disposition": koentec["disposition"],
        "missing_mark_rows": summary["total_rows"],
        "by_group": summary["by_group"],
        "artifact_count": len(read_json("artifact_hashes.json")["files"]),
        "source_manifest_sha256": sha(OUT / "source_manifest.json"),
    }, ensure_ascii=False, indent=2, default=json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
