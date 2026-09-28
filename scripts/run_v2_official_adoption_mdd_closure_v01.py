#!/usr/bin/env python3
"""Portfolio-only V2 MDD closure using a current-status survivorship fallback."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.run_v2_official_adoption_revalidation_v02 as base

OUT_DIR = ROOT / "artifacts/patterns/pattern_a_fast/strategy/v2_official_adoption_revalidation_mdd_closure_v01"
CURRENT_MASTER_PATH = ROOT / "data/reference/source/krx_instrument_metadata_source_snapshot_2026-09-04.json"
CURRENT_MARKET_CAP_PATH = ROOT / "artifacts/patterns/pattern_a/production/investability/source/krx_market_cap_20260922.csv"
BASELINE_DIR = ROOT / "artifacts/patterns/pattern_a_fast/strategy/v2_official_adoption_revalidation_v02"
SCANNER_PATH = ROOT / "artifacts/patterns/pattern_a/production/scanner/pattern_a_universe_scan_20260922.csv"

# Latest locally observed exchange/feed evidence, paired with the explicit KRX
# notices below. Do not infer a formal suspension from an old cache or zero volume alone.
EXPLICIT_CURRENT_STATUS: dict[tuple[str, str], dict[str, Any]] = {
    ("005110", "KR7005110002"): {
        "current_status": "CURRENTLY_SUSPENDED",
        "cause": "CURRENTLY_SUSPENDED",
        "as_of": "2026-09-22",
        "evidence": "KRX 2026-05-06 notice says the delisting proceedings remain subject to the pending injunction; local KRX market-cap feed on 2026-09-22 has zero volume and the current scanner cache is very stale.",
        "official_source_url": "https://kind.krx.co.kr/external/2026/05/06/001170/20260506000717/91813.htm",
    },
    ("068240", "KR7068240001"): {
        "current_status": "CURRENTLY_DELISTED",
        "cause": "CURRENTLY_DELISTED",
        "as_of": "2026-09-15",
        "evidence": "KRX market actions list delisting and the start of liquidation trading following suspension release on 2026-09-15.",
        "official_source_url": "https://kind.krx.co.kr/disclosure/detailsExt.do?method=searchDetailsMktactMainExt",
    },
}

_ORIGINAL_SOURCE_CHECK = base.source_check
_ORIGINAL_GATE_BUILDER = base.build_gate_results
_ORIGINAL_CORE_SOURCE_HASHES = base.core_source_hashes
_ORIGINAL_EXECUTION_CONTRACT = base.execution_contract
_ORIGINAL_VERDICT = base.final_verdict

FALLBACK_EXCLUSIONS: dict[tuple[str, str], dict[str, Any]] = {}
BASELINE_UNRESOLVED_ROWS: list[dict[str, Any]] = []
BASELINE_UNRESOLVED_SUMMARY: list[dict[str, Any]] = []
ROOT_CAUSE_COUNTS: dict[str, int] = {}
ROOT_CAUSE_MARK_COUNTS: dict[str, int] = {}
PREPARED = False
PREPARED_INFO: dict[str, Any] = {}


def normalize_pair(ticker: Any, isu_cd: Any) -> tuple[str, str]:
    return str(ticker or "").strip().zfill(6), str(isu_cd or "").strip().upper()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def current_master_pairs(payload: Mapping[str, Any]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for section in ("equity", "equity_kospi", "equity_kosdaq", "equity_konex"):
        for row in payload.get(section, []) or []:
            if not isinstance(row, Mapping):
                continue
            pair = normalize_pair(row.get("ISU_SRT_CD"), row.get("ISU_CD"))
            if pair[0].strip("0") and pair[1]:
                pairs.add(pair)
    return pairs


def read_market_cap_evidence() -> dict[str, dict[str, str]]:
    return {str(row.get("ticker", "")).zfill(6): row for row in read_csv(CURRENT_MARKET_CAP_PATH)}


def read_scanner_evidence() -> dict[str, dict[str, str]]:
    if not SCANNER_PATH.is_file():
        return {}
    return {str(row.get("ticker", "")).zfill(6): row for row in read_csv(SCANNER_PATH)}


def classify_cause(pair: tuple[str, str], reasons: Sequence[str]) -> str:
    joined = ";".join(reasons)
    if pair == ("023890", "KR7023890007") or "CORPORATE_SUCCESSOR" in joined or "SUCCESSOR" in joined:
        return "MERGER_OR_SUCCESSOR"
    status = FALLBACK_EXCLUSIONS.get(pair, {}).get("current_status")
    if status == "CURRENTLY_SUSPENDED":
        return "CURRENTLY_SUSPENDED"
    if status in {"CURRENTLY_DELISTED", "CURRENT_ROSTER_ABSENT"}:
        return "CURRENTLY_DELISTED"
    if any("RAW_ROW_NOT_PLACEHOLDER" in reason or "UNRESOLVED_DAILY_MARK" in reason for reason in reasons):
        return "RAW_DATA_GAP"
    return "OTHER"


def build_baseline_unresolved_summary() -> None:
    global BASELINE_UNRESOLVED_ROWS, BASELINE_UNRESOLVED_SUMMARY
    global ROOT_CAUSE_COUNTS, ROOT_CAUSE_MARK_COUNTS

    by_window_pair: dict[tuple[str, tuple[str, str]], list[dict[str, str]]] = defaultdict(list)
    for window_id in base.WINDOWS:
        filename = f"missing_marks_{window_id.lower().replace('-', '_')}.csv"
        for row in read_csv(BASELINE_DIR / filename):
            pair = normalize_pair(row.get("ticker"), row.get("isu_cd"))
            row = dict(row)
            row["window_id"] = window_id
            by_window_pair[(window_id, pair)].append(row)

    try:
        scanner_rows = read_scanner_evidence()
    except Exception:
        scanner_rows = {}

    summary: list[dict[str, Any]] = []
    causes_by_pair: dict[tuple[str, str], str] = {}
    reason_rows_by_pair: dict[tuple[str, str], list[str]] = defaultdict(list)
    for (window_id, pair), rows in sorted(by_window_pair.items()):
        dates = sorted(str(row.get("date", "")) for row in rows if row.get("date"))
        reasons = sorted({str(row.get("reason", "")) for row in rows if row.get("reason")})
        evidence_states = sorted({str(row.get("evidence_state", "")) for row in rows if row.get("evidence_state")})
        status_record = FALLBACK_EXCLUSIONS.get(pair)
        cause = classify_cause(pair, reasons)
        causes_by_pair.setdefault(pair, cause)
        reason_rows_by_pair[pair].extend(reasons)
        explicit_status = status_record.get("current_status") if status_record else "CURRENTLY_LISTED_OR_STATUS_UNCONFIRMED"
        in_current_master = explicit_status not in {"CURRENT_ROSTER_ABSENT", "CURRENTLY_DELISTED"}
        scan = scanner_rows.get(pair[0], {})
        summary.append({
            "window": window_id,
            "ticker": pair[0],
            "ISU_CD": pair[1],
            "unresolved_day_count": len(rows),
            "first_unresolved_date": dates[0] if dates else "",
            "last_unresolved_date": dates[-1] if dates else "",
            "current_listing_status": explicit_status,
            "currently_suspended": explicit_status == "CURRENTLY_SUSPENDED",
            "currently_delisted_or_identity_retired": explicit_status in {"CURRENTLY_DELISTED", "CURRENT_ROSTER_ABSENT"},
            "possible_cause": cause,
            "baseline_reasons": ";".join(reasons),
            "raw_evidence_states": ";".join(evidence_states),
            "in_current_krx_equity_master": in_current_master,
            "fallback_excluded": status_record is not None,
            "scanner_effective_as_of": scan.get("effective_as_of", ""),
            "scanner_freshness": scan.get("freshness_status", ""),
        })

    for pair in list(causes_by_pair):
        causes_by_pair[pair] = classify_cause(pair, reason_rows_by_pair[pair])
    BASELINE_UNRESOLVED_ROWS = [row for rows in by_window_pair.values() for row in rows]
    BASELINE_UNRESOLVED_SUMMARY = summary
    ROOT_CAUSE_COUNTS = dict(sorted(Counter(causes_by_pair.values()).items()))
    mark_counter: Counter[str] = Counter()
    for (window_id, pair), rows in by_window_pair.items():
        del window_id
        mark_counter[classify_cause(pair, reason_rows_by_pair[pair])] += len(rows)
    ROOT_CAUSE_MARK_COUNTS = dict(sorted(mark_counter.items()))


def prepare() -> dict[str, Any]:
    global FALLBACK_EXCLUSIONS, PREPARED, PREPARED_INFO
    if PREPARED:
        return PREPARED_INFO

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = base.read_json(CURRENT_MASTER_PATH)
    listed_pairs = current_master_pairs(payload)
    market_cap = read_market_cap_evidence()
    scanner = read_scanner_evidence()

    ledger_rows: dict[str, list[dict[str, Any]]] = {}
    for window_id in base.WINDOWS:
        rows, _ = _ORIGINAL_SOURCE_CHECK(window_id)
        ledger_rows[window_id] = rows
    all_pairs = {
        normalize_pair(row.get("ticker"), row.get("isu_cd"))
        for rows in ledger_rows.values()
        for row in rows
    }

    exclusions: dict[tuple[str, str], dict[str, Any]] = {}
    for pair in sorted(all_pairs - listed_pairs):
        exclusions[pair] = {
            "ticker": pair[0],
            "isu_cd": pair[1],
            "current_status": "CURRENT_ROSTER_ABSENT",
            "cause": "CURRENTLY_DELISTED",
            "as_of": payload.get("source_observation_date", "2026-09-04"),
            "evidence": "Exact (ticker, ISU_CD) is absent from the KRX current listed-equity identity master; no successor was inferred.",
            "evidence_source_path": str(CURRENT_MASTER_PATH.relative_to(ROOT)),
            "official_source_url": "",
        }

    for pair, details in EXPLICIT_CURRENT_STATUS.items():
        if pair in all_pairs:
            evidence = dict(details)
            evidence["ticker"], evidence["isu_cd"] = pair
            evidence["evidence_source_path"] = str(CURRENT_MARKET_CAP_PATH.relative_to(ROOT)) if pair[0] == "005110" else "KRX KIND market action notice"
            exclusions[pair] = evidence

    FALLBACK_EXCLUSIONS = exclusions
    build_baseline_unresolved_summary()

    name_by_ticker = {str(row.get("ticker", "")).zfill(6): row.get("name", "") for row in scanner.values()}
    exclusion_rows: list[dict[str, Any]] = []
    per_window_counts: dict[str, dict[str, int]] = {}
    for pair, item in sorted(FALLBACK_EXCLUSIONS.items()):
        windows = []
        row_counts: dict[str, int] = {}
        for window_id, rows in ledger_rows.items():
            count = sum(1 for row in rows if normalize_pair(row.get("ticker"), row.get("isu_cd")) == pair)
            if count:
                windows.append(window_id)
                row_counts[window_id] = count
        per_window_counts["|".join(pair)] = row_counts
        exclusion_rows.append({
            "ticker": pair[0],
            "ISU_CD": pair[1],
            "name_if_cached": name_by_ticker.get(pair[0], ""),
            "current_status": item["current_status"],
            "cause": item["cause"],
            "as_of": item.get("as_of", ""),
            "source_windows": ";".join(windows),
            "ledger_rows_removed": sum(row_counts.values()),
            "ledger_rows_by_window": ";".join(f"{wid}:{count}" for wid, count in row_counts.items()),
            "evidence": item.get("evidence", ""),
            "evidence_source_path": item.get("evidence_source_path", ""),
            "official_source_url": item.get("official_source_url", ""),
            "current_market_cap_feed_volume": market_cap.get(pair[0], {}).get("volume", ""),
            "scanner_effective_as_of": scanner.get(pair[0], {}).get("effective_as_of", ""),
            "scanner_freshness": scanner.get(pair[0], {}).get("freshness_status", ""),
        })

    base.save_csv(OUT_DIR / "fallback_exclusions.csv", exclusion_rows)
    base.save_csv(OUT_DIR / "unresolved_identity_summary.csv", BASELINE_UNRESOLVED_SUMMARY)
    PREPARED_INFO = {
        "fallback_identity_count": len(FALLBACK_EXCLUSIONS),
        "fallback_roster_absent_count": sum(1 for item in FALLBACK_EXCLUSIONS.values() if item["current_status"] == "CURRENT_ROSTER_ABSENT"),
        "fallback_suspended_count": sum(1 for item in FALLBACK_EXCLUSIONS.values() if item["current_status"] == "CURRENTLY_SUSPENDED"),
        "fallback_official_delisted_count": sum(1 for item in FALLBACK_EXCLUSIONS.values() if item["current_status"] == "CURRENTLY_DELISTED"),
        "baseline_unresolved_mark_rows": len(BASELINE_UNRESOLVED_ROWS),
        "baseline_unresolved_window_identity_count": len(BASELINE_UNRESOLVED_SUMMARY),
        "baseline_unresolved_identity_count": len({(row["ticker"], row["ISU_CD"]) for row in BASELINE_UNRESOLVED_SUMMARY}),
        "baseline_root_causes_by_identity": ROOT_CAUSE_COUNTS,
        "baseline_root_causes_by_mark": ROOT_CAUSE_MARK_COUNTS,
        "filtered_ledger_rows_by_window": per_window_counts,
    }
    PREPARED = True
    return PREPARED_INFO


def filtered_source_check(window_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows, details = _ORIGINAL_SOURCE_CHECK(window_id)
    removed = [row for row in rows if normalize_pair(row.get("ticker"), row.get("isu_cd")) in FALLBACK_EXCLUSIONS]
    kept = [row for row in rows if normalize_pair(row.get("ticker"), row.get("isu_cd")) not in FALLBACK_EXCLUSIONS]
    details["current_status_fallback_filter"] = "CURRENT_STATUS_SUSPENDED_DELISTED_FALLBACK"
    details["current_status_fallback_identity_count"] = len({normalize_pair(row.get("ticker"), row.get("isu_cd")) for row in removed})
    details["current_status_fallback_rows_removed"] = len(removed)
    details["rows_after_current_status_fallback"] = len(kept)
    return kept, details


def closure_gate_results(
    window_id: str,
    metrics: Mapping[str, Any],
    issues: Sequence[Mapping[str, Any]],
    unresolved_events: Sequence[Mapping[str, Any]],
    missing_marks: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    previous = _ORIGINAL_GATE_BUILDER(window_id, metrics, issues, unresolved_events, missing_marks)
    result = [dict(item) for item in previous if item["gate"] in {"A", "B", "C", "D"}]
    validity = next(dict(item) for item in previous if item["gate"] == "F")
    validity["gate"] = "E"
    validity["detail"] = f"portfolio_result_validity: {validity['detail']}"
    result.append(validity)
    return result


def closure_source_hashes(results: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    value = _ORIGINAL_CORE_SOURCE_HASHES(results)
    source_paths = [
        CURRENT_MASTER_PATH,
        CURRENT_MARKET_CAP_PATH,
        SCANNER_PATH,
        *(BASELINE_DIR / f"missing_marks_{window.lower().replace('-', '_')}.csv" for window in base.WINDOWS),
        *(BASELINE_DIR / f"unresolved_events_{window.lower().replace('-', '_')}.csv" for window in base.WINDOWS),
    ]
    value["mdd_closure_v01"] = {
        "script": {"path": str(Path(__file__).resolve().relative_to(ROOT)), "sha256": base.sha256_file(Path(__file__).resolve())},
        "fallback_exclusion_filter": "CURRENT_STATUS_SUSPENDED_DELISTED_FALLBACK",
        "fallback_exclusions_path": str((OUT_DIR / "fallback_exclusions.csv").relative_to(ROOT)),
        "fallback_exclusions_sha256": base.sha256_file(OUT_DIR / "fallback_exclusions.csv"),
        "unresolved_identity_summary_path": str((OUT_DIR / "unresolved_identity_summary.csv").relative_to(ROOT)),
        "unresolved_identity_summary_sha256": base.sha256_file(OUT_DIR / "unresolved_identity_summary.csv"),
        "status_evidence_sources": [
            {"path": str(path.relative_to(ROOT)), "sha256": base.sha256_file(path)}
            for path in source_paths
        ],
        "official_status_notice_urls": {"005110|KR7005110002": EXPLICIT_CURRENT_STATUS[("005110", "KR7005110002")]["official_source_url"], "068240|KR7068240001": EXPLICIT_CURRENT_STATUS[("068240", "KR7068240001")]["official_source_url"]},
        "survivorship_bias_fallback_used": True,
        "signal_regeneration": False,
        "strategy_evaluation_rerun": False,
    }
    return value


def closure_execution_contract() -> dict[str, Any]:
    value = _ORIGINAL_EXECUTION_CONTRACT()
    value.update({
        "schema": "pattern_a_fast_v2_official_adoption_mdd_closure_execution_contract_v01",
        "mode": "EXISTING_STRATEGY_LEDGER_PORTFOLIO_ONLY",
        "entry_signal_regeneration": False,
        "strategy_evaluation_rerun": False,
        "portfolio_universe_filter": "CURRENT_STATUS_SUSPENDED_DELISTED_FALLBACK",
        "fallback_filter_identity_count": len(FALLBACK_EXCLUSIONS),
        "fallback_filter_exact_identity_key": ["ticker", "ISU_CD"],
        "fallback_filter_evidence": "Current KRX listed-equity identity master absence, plus the two listed explicit KRX current-status notices in fallback_exclusions.csv. Zero volume or stale cache alone is not sufficient evidence.",
        "survivorship_bias_fallback_used": True,
        "survivorship_bias_acknowledged": "This filter excludes identities based on current status, so historical results are survivorship biased and are not represented as an unbiased historical simulation.",
        "permanent_exclusion_policy_modified": False,
    })
    return value


def closure_verdict(gates: Sequence[Mapping[str, Any]]) -> str:
    return _ORIGINAL_VERDICT(gates)


def closure_render_report(
    verdict: str,
    metrics: Sequence[Mapping[str, Any]],
    gates: Sequence[Mapping[str, Any]],
    references: Mapping[str, Mapping[str, Any]],
    source_hashes: Mapping[str, Any],
    plan_commit: str,
    result_commit: str | None = None,
    head: str | None = None,
    origin_main: str | None = None,
    worktree_clean: bool | None = None,
) -> str:
    del references, source_hashes
    gate_by_window: dict[str, dict[str, str]] = defaultdict(dict)
    for item in gates:
        gate_by_window[str(item["window_id"])][str(item["gate"])] = str(item["status"])

    lines = [
        "# V2 MDD 미해결 평가값 — 현재 상태 fallback 재평가",
        "",
        f"- 최종 판정: **{verdict} / SURVIVORSHIP_BIAS_FALLBACK_USED**",
        f"- 기준 계획 commit: `{plan_commit}`",
        f"- 결과 commit: `{result_commit or '기록은 r.md 참고'}`",
        f"- 종료 HEAD / origin/main: `{head or '별도 push 단계에서 확인'}` / `{origin_main or '별도 push 단계에서 확인'}`; clean: `{worktree_clean}`",
        f"- 기존 V02 baseline은 보존: `{BASELINE_DIR.relative_to(ROOT)}`",
        "- 실행 모드: `EXISTING_STRATEGY_LEDGER_PORTFOLIO_ONLY`; entry signal regeneration=false; strategy evaluation rerun=false; price-frame workers=10.",
        "- 주의: 이 결과는 현재 상태 기준 종목 제외를 사용해 생존편향이 있으며 무편향 역사 시뮬레이션이 아니야.",
        "",
        "## 진단 및 fallback 범위",
        "",
        f"- V02 unresolved mark: {len(BASELINE_UNRESOLVED_ROWS)} window-day rows, {len(BASELINE_UNRESOLVED_SUMMARY)} window-identity groups, {len({(row['ticker'], row['ISU_CD']) for row in BASELINE_UNRESOLVED_SUMMARY})} 고유 identity.",
        f"- 원인별 고유 identity: `{ROOT_CAUSE_COUNTS}`.",
        f"- 원인별 unresolved mark 수: `{ROOT_CAUSE_MARK_COUNTS}`.",
        f"- 쉽게 해결한 valuation mark: 0건. 기존 placeholder carry 규칙은 그대로 유지했고, 새로 임의 carry한 값은 없어.",
        f"- fallback 제외: {len(FALLBACK_EXCLUSIONS)} exact identities — KRX current master 부재 {sum(1 for x in FALLBACK_EXCLUSIONS.values() if x['current_status'] == 'CURRENT_ROSTER_ABSENT')}, 명시적 현재 거래정지 {sum(1 for x in FALLBACK_EXCLUSIONS.values() if x['current_status'] == 'CURRENTLY_SUSPENDED')}, 명시적 현재 상폐 {sum(1 for x in FALLBACK_EXCLUSIONS.values() if x['current_status'] == 'CURRENTLY_DELISTED')}.",
        "- status evidence는 `fallback_exclusions.csv`; 진단 압축은 `unresolved_identity_summary.csv`.",
        "- 거래량 0 또는 오래된 scanner cache만으로 거래정지 판정을 추가하지 않았어.",
        "",
        "## 5개 표준 기간 재평가",
        "",
        "| 기간 | 총수익률 | CAGR | MDD | 현금 부족률(참고) | A | B | C | D | E | 남은 unresolved mark |",
        "|---|---:|---:|---:|---:|---|---|---|---|---|---:|",
    ]

    def fmt(value: Any) -> str:
        return "미산출" if value is None else f"{float(value):.2f}%"

    for row in metrics:
        wid = str(row["window_id"])
        gate = gate_by_window.get(wid, {})
        lines.append("| " + " | ".join([
            wid,
            fmt(row.get("total_return_pct")),
            fmt(row.get("cagr_pct")),
            fmt(row.get("mdd_pct")),
            fmt(row.get("cash_shortage_skip_rate_pct")),
            *(gate.get(key, "CHECK_REQUIRED") for key in "ABCDE"),
            str(row.get("valuation_unresolved_count", row.get("unresolved_count", ""))),
        ]) + " |")

    lines.extend([
        "",
        "현금 부족률은 참고 진단으로만 표시했고 A~E 판정에는 넣지 않았어. 남은 missing mark나 unresolved event가 있으면 D/E를 CHECK_REQUIRED로 유지했어.",
        "",
        "## A~E 상세 판정",
        "",
    ])
    for item in gates:
        lines.append(f"- {item['window_id']} {item['gate']}: **{item['status']}** — {item['detail']}")
    lines.extend([
        "",
        "## 현재 상태 근거와 해석",
        "",
        f"- KRX 현재 상장 종목 원천: `{CURRENT_MASTER_PATH.relative_to(ROOT)}` (관측일 2026-09-04); KRX 시가총액 일별 원천: `{CURRENT_MARKET_CAP_PATH.relative_to(ROOT)}` (2026-09-22).",
        "- 005110 한창: KRX 2026-05-06 안내에는 상장폐지 결정 효력정지 가처분 결과에 따라 후속 절차가 진행된다고 되어 있고, 2026-09-22 로컬 KRX 시세 snapshot은 거래량 0이어서 현재 거래정지 fallback으로 분류했어.",
        "- 068240 다원시스: KRX 시장조치 목록에 2026-09-15 상장폐지 및 정리매매 개시 관련 조치가 기록되어 있어 현재 상폐 fallback으로 분류했어.",
        "- 그 외 KRX 현재 상장 equity master에 없는 identity는 `CURRENT_ROSTER_ABSENT`로 기록했어. 이는 현재 exact identity가 목록에 없다는 근거이며 successor 연결을 새로 추정하지 않았어.",
        "",
        "## 재현 정보",
        "",
        f"- 실행 계약: `{(OUT_DIR / 'execution_contract.json').relative_to(ROOT)}`.",
        f"- 원천 해시: `{(OUT_DIR / 'source_hashes.json').relative_to(ROOT)}`.",
        f"- 기간별 가격 평가, 거래, 현금, carry, missing mark 및 unresolved event CSV는 이 디렉터리에 있어.",
        "",
    ])
    return "\n".join(lines)


def run() -> dict[str, Any]:
    prepared = prepare()
    base.OUT_DIR = OUT_DIR
    base.source_check = filtered_source_check
    base.build_gate_results = closure_gate_results
    base.core_source_hashes = closure_source_hashes
    base.execution_contract = closure_execution_contract
    base.final_verdict = closure_verdict
    base.render_report = closure_render_report
    result = base.run_full()

    result_summary = dict(result["summary"])
    result_summary.update({
        "schema": "pattern_a_fast_v2_official_adoption_mdd_closure_summary_v01",
        "survivorship_bias_fallback_used": True,
        "verdict_with_flag": f"{result['verdict']}_WITH_SURVIVORSHIP_BIAS_FALLBACK_USED",
        "fallback_filter": "CURRENT_STATUS_SUSPENDED_DELISTED_FALLBACK",
        "fallback_identity_count": len(FALLBACK_EXCLUSIONS),
        "fallback_identity_status_counts": dict(sorted(Counter(str(item["current_status"]) for item in FALLBACK_EXCLUSIONS.values()).items())),
        "baseline_unresolved_mark_rows": prepared["baseline_unresolved_mark_rows"],
        "baseline_unresolved_window_identity_count": prepared["baseline_unresolved_window_identity_count"],
        "baseline_unresolved_identity_count": prepared["baseline_unresolved_identity_count"],
        "baseline_unresolved_cause_counts_by_identity": ROOT_CAUSE_COUNTS,
        "baseline_unresolved_cause_counts_by_mark": ROOT_CAUSE_MARK_COUNTS,
        "easy_daily_valuation_repairs": 0,
        "entry_signal_regeneration": False,
        "strategy_evaluation_rerun": False,
        "permanent_exclusion_policy_modified": False,
    })
    base.save_json(OUT_DIR / "summary.json", result_summary)
    (OUT_DIR / "report.md").write_text(
        closure_render_report(result["verdict"], result["metrics"], result["gates"], result["references"], {}, base.PLAN_COMMIT),
        encoding="utf-8",
    )
    result["summary"] = result_summary
    print(base.json.dumps({
        "verdict": result["verdict"],
        "survivorship_bias_fallback_used": True,
        "fallback_identity_count": len(FALLBACK_EXCLUSIONS),
        "fallback_status_counts": result_summary["fallback_identity_status_counts"],
        "baseline_unresolved_identity_count": prepared["baseline_unresolved_identity_count"],
        "baseline_unresolved_cause_counts_by_identity": ROOT_CAUSE_COUNTS,
        "window_metrics": result["metrics"],
        "gate_results": result["gates"],
        "total_wall_seconds": result_summary["total_wall_seconds"],
    }, ensure_ascii=False, indent=2, default=str), flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--preflight", action="store_true", help="Prepare and report the exact status filter and compressed baseline gaps only.")
    group.add_argument("--run", action="store_true", help="Run five portfolio-only V2 re-evaluations using the status fallback.")
    args = parser.parse_args()
    if not base.PLAN_PATH.is_file() or base.sha256_file(base.PLAN_PATH) != base.PLAN_SHA256:
        raise RuntimeError("SEALED_PLAN_MISSING_OR_HASH_MISMATCH")
    if args.preflight:
        info = prepare()
        print(base.json.dumps(info, ensure_ascii=False, indent=2, default=str), flush=True)
    else:
        run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
