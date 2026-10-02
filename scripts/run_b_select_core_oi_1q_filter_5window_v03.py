#!/usr/bin/env python3
"""B Select Core V1 + latest 1Q operating-income entry filter: 5-window V03.

CONTROL is the official ``PATTERN_B_SELECT_CORE_V01`` rule.  TEST adds only the
V03 latest-quarter operating-income gate to the entry qualification, and both
scenarios are replayed independently from the raw Pattern B signals through
the same lifecycle engine, prices, exclusions and window contract.

Two stages run separately so the fundamentals rule is frozen and reviewed
before any return is computed:

* ``--stage evaluate`` writes the PIT operating-income evaluation of every
  CONTROL entry signal (cache-only; sockets are blocked).
* ``--stage backtest`` replays CONTROL and TEST for P1, P2-1, P2-2, P3-1, P3-2.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import socket
import subprocess
import sys
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT, ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from scripts import run_pattern_b_progressed_weak_exclusion_p1_simple_v01 as runner  # noqa: E402
from scripts import run_pattern_b_progressed_previous_stage_early_transition_only_5window_v01 as et5  # noqa: E402
from trend_scanner.backtest.b_select_core_oi_1q_v03 import (  # noqa: E402
    BASIS_OR_CURRENCY_MISMATCH,
    FAIL,
    OPERATING_INCOME_MIN_KRW,
    PASS,
    UNAVAILABLE,
    evaluate_signal,
)
from trend_scanner.data.rolling_market_data_refresh import _content_digest  # noqa: E402
from trend_scanner.fundamentals.corp_code_repository import CorpCodeRepository  # noqa: E402
from trend_scanner.fundamentals.filing_registry import FilingRegistry  # noqa: E402
from trend_scanner.fundamentals.opendart_contract import CompanyFamily, classify_company_family  # noqa: E402
from trend_scanner.fundamentals.periodization_provider import PeriodizationProvider  # noqa: E402
from trend_scanner.fundamentals.xbrl_repository import XbrlRepository  # noqa: E402
from trend_scanner.strategies.b_select_core_v1 import ALLOWED_PREVIOUS_STAGES, STRATEGY_ID  # noqa: E402
from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS  # noqa: E402

base = runner.base
entry_filter = runner.entry_filter

STUDY_ID = "B_SELECT_CORE_OI_1Q_FILTER_5WINDOW_V03"
OUTPUT_ROOT = Path("artifacts/strategies/b_select_core_v1/research/oi_1q_filter_5window_v03")
EVALUATION_FILE = "oi_entry_evaluations.csv"
WINDOW_IDS = ("P1", "P2-1", "P2-2", "P3-1", "P3-2")
FROZEN_5WINDOW = Path("artifacts/patterns/pattern_b/progressed_previous_stage_early_transition_only_5window_v01")
FROZEN_DIR = {window: FROZEN_5WINDOW / window.lower().replace("-", "_") for window in WINDOW_IDS}
BASELINE_EXCLUSION_COMMIT = "7d5fbcd83273f644eb48ae3f595aaf1f23f54091"
PREVIOUS_STAGE_CODE_COMMIT = "7b0b5821986b75e3c204874350bdbfd53b8ac882"
EXCLUSION_MODULE = Path("src/trend_scanner/universe/permanent_identity_exclusions.py")
CACHE = ROOT / "data/cache/opendart"
FUNDAMENTALS_BUILD_AS_OF = "2026-08-31"
XBRL_FIRST_YEAR = 2015
PRE_XBRL_SIGNAL_BEFORE = "2016-01-01"
EPS = 1e-9


# ---------------------------------------------------------------- utilities

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, stdout=subprocess.PIPE, text=True).stdout.strip()


def _git_bytes(revision: str, relative: Path) -> bytes:
    return subprocess.run(["git", "show", f"{revision}:{relative.as_posix()}"], cwd=ROOT, check=True,
                          stdout=subprocess.PIPE).stdout


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(runner._json_clean(payload), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8")


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return runner._key(row)


def _identity(row: Mapping[str, Any]) -> tuple[str, str]:
    return base.norm_ticker(row["ticker"]), base.norm_isu(row["isu_cd"])


class NetworkBlocked(RuntimeError):
    pass


@contextmanager
def network_guard() -> Iterator[None]:
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def blocked(self: socket.socket, address: Any) -> Any:  # noqa: ARG001
        raise NetworkBlocked(f"V03 cache-only guard blocked socket connect: {address!r}")

    socket.socket.connect = blocked  # type: ignore[method-assign]
    socket.socket.connect_ex = blocked  # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = original_connect_ex  # type: ignore[method-assign]


def _git_start(allowed_prefixes: tuple[str, ...]) -> dict[str, Any]:
    head = _git("rev-parse", "HEAD")
    origin = _git("rev-parse", "origin/main")
    branch = _git("branch", "--show-current")
    status = _git("status", "--porcelain").splitlines()
    unexpected = [line for line in status if not any(line[3:].startswith(prefix) for prefix in allowed_prefixes)]
    if branch != "main" or unexpected:
        raise RuntimeError(f"unexpected start state: branch={branch} head={head} origin={origin} changes={unexpected}")
    ahead = _git("rev-list", "--count", f"{origin}..{head}")
    return {"head": head, "origin_main": origin, "branch": branch, "commits_ahead_of_origin": int(ahead),
            "start_status": status}


# ------------------------------------------------- frozen authority projection

def _frozen_authority_provenance() -> dict[str, Any]:
    reference = None
    for window in WINDOW_IDS:
        provenance = _json(ROOT / FROZEN_DIR[window] / "summary.json")["source_provenance"]["market_authority"]
        if reference is None:
            reference = provenance
        elif provenance != reference:
            raise RuntimeError(f"frozen 5-window market authority differs between windows: {window}")
    assert reference is not None
    return reference


def make_projected_authority_loader() -> tuple[Any, dict[str, Any]]:
    """Project the current rolling authority onto the frozen 2026-09-21 frontier.

    The projection is accepted only if its interval and calendar payload digests
    equal the digests recorded by the frozen B Select Core 5-window run.
    """

    frozen = _frozen_authority_provenance()
    cutoff = base.CUTOFF
    pit = _json(ROOT / base.PIT_PATH)
    calendar = _json(ROOT / base.CALENDAR_PATH)
    projected = []
    clamped = 0
    dropped = 0
    for raw in pit["intervals"]:
        if str(raw["effective_from"])[:10] > cutoff:
            dropped += 1
            continue
        row = dict(raw)
        if str(row["effective_to"])[:10] > cutoff:
            row["effective_to"] = cutoff
            clamped += 1
        projected.append(row)
    dates = [str(day)[:10] for day in calendar["trading_dates"] if str(day)[:10] <= cutoff]
    pit_digest = _content_digest(projected)
    calendar_digest = _content_digest(dates)
    proof = {
        "projection_cutoff": cutoff,
        "current_pit_frontier": pit.get("pit_frontier"),
        "current_calendar_frontier": calendar.get("calendar_frontier"),
        "current_pit_file_sha256": _sha256(ROOT / base.PIT_PATH),
        "current_calendar_file_sha256": _sha256(ROOT / base.CALENDAR_PATH),
        "current_interval_count": len(pit["intervals"]),
        "projected_interval_count": len(projected),
        "open_intervals_clamped": clamped,
        "intervals_started_after_cutoff_dropped": dropped,
        "projected_pit_content_digest": pit_digest,
        "frozen_pit_content_digest": frozen["pit_content_digest"],
        "projected_calendar_content_digest": calendar_digest,
        "frozen_calendar_content_digest": frozen["calendar_content_digest"],
        "projected_first_trading_date": dates[0],
        "projected_last_trading_date": dates[-1],
        "frozen_first_trading_date": frozen["first_trading_date"],
        "frozen_last_trading_date": frozen["last_trading_date"],
        "frozen_interval_count": frozen["interval_count"],
    }
    proof["equivalent"] = bool(
        pit_digest == frozen["pit_content_digest"]
        and calendar_digest == frozen["calendar_content_digest"]
        and len(projected) == frozen["interval_count"]
        and dates[0] == frozen["first_trading_date"]
        and dates[-1] == frozen["last_trading_date"]
    )
    if not proof["equivalent"]:
        raise RuntimeError(f"projected authority is not content-identical to the frozen authority: {proof}")
    original = base._load_authorities

    def loader(data_root: Path) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
        intervals = []
        for raw in projected:
            row = dict(raw)
            row["ticker"] = base.norm_ticker(row["ticker"])
            row["isu_cd"] = base.norm_isu(row["isu_cd"])
            row["market"] = str(row["market"]).upper()
            row["effective_from"] = str(row["effective_from"])[:10]
            row["effective_to"] = str(row["effective_to"])[:10]
            intervals.append(row)
        provenance = {
            "pit_frontier": cutoff,
            "pit_content_digest": pit_digest,
            "calendar_frontier": cutoff,
            "calendar_content_digest": calendar_digest,
            "interval_count": len(intervals),
            "common_interval_count": sum(row.get("state") == "COMMON" for row in intervals),
            "first_trading_date": dates[0],
            "last_trading_date": dates[-1],
            "projection": "current rolling authority projected to the frozen frontier; digest-equivalent",
        }
        return intervals, list(dates), provenance

    loader.original = original  # type: ignore[attr-defined]
    return loader, proof


# ------------------------------------------------------- frozen input checks

def _baseline_exclusions() -> set[tuple[str, str]]:
    namespace: dict[str, Any] = {}
    exec(compile(_git_bytes(BASELINE_EXCLUSION_COMMIT, EXCLUSION_MODULE), "baseline_exclusions", "exec"), namespace)
    return {(base.norm_ticker(t), base.norm_isu(i)) for t, i in namespace["PERMANENT_IDENTITY_EXCLUSIONS"]}


def current_exclusions() -> set[tuple[str, str]]:
    return {(base.norm_ticker(t), base.norm_isu(i)) for t, i in PERMANENT_IDENTITY_EXCLUSIONS}


def _read_stage_linkage(all_keys: set[tuple[str, str, str]], newly_excluded: set[tuple[str, str]]) -> tuple[pd.DataFrame, dict[str, Any]]:
    linkage_path = ROOT / entry_filter.STAGE_LINKAGE
    metadata = _json(ROOT / entry_filter.STAGE_METADATA)
    if metadata.get("study_id") != "PATTERN_B_DEPRESSED_ENTRY_PATTERN_A_STATE_V01":
        raise RuntimeError("Pattern A linkage metadata is not the expected PIT diagnostic")
    if _sha256(linkage_path) != metadata["generated_files"]["signal_stage_path_trade_linkage.csv"]["sha256"]:
        raise RuntimeError("Pattern A linkage CSV differs from its committed metadata")
    if _git_bytes("HEAD", entry_filter.STAGE_LINKAGE) != linkage_path.read_bytes():
        raise RuntimeError("Pattern A linkage CSV differs from the committed HEAD blob")
    replaced = {"data/market/rolling_authority/merged_pit_intervals.json",
                "data/market/rolling_authority/merged_trading_calendar.json"}
    for relative, expected in metadata["input_sha256"].items():
        if relative in replaced:
            continue  # replaced by the digest-equivalence proof of the projected authority
        if _sha256(ROOT / relative) != expected:
            raise RuntimeError(f"Pattern A linkage input changed: {relative}")
    if metadata["pattern_a_authority"].get("classifier") != "trend_scanner.patterns.pattern_a_stage.classify_pattern_a_stage":
        raise RuntimeError("Pattern A linkage does not name the official classifier")
    frame = pd.read_csv(linkage_path, dtype={"ticker": "string", "isu_cd": "string"})
    frame["entry_signal_date"] = frame["entry_signal_date"].astype(str).str[:10]
    if frame.duplicated(list(runner.SIGNAL_KEY)).any():
        raise RuntimeError("Pattern A linkage contains duplicate signal keys")
    excluded_mask = frame.apply(lambda row: _identity(row) in newly_excluded, axis=1)
    removed = frame.loc[excluded_mask]
    kept = frame.loc[~excluded_mask].copy()
    kept_keys = set(kept[list(runner.SIGNAL_KEY)].astype(str).itertuples(index=False, name=None))
    if kept_keys != all_keys:
        raise RuntimeError(f"Pattern A linkage keys drift beyond the new exclusions: missing={len(all_keys - kept_keys)} extra={len(kept_keys - all_keys)}")
    if not set(kept["pattern_a_stage"].dropna().astype(str)).issubset(runner.STAGES):
        raise RuntimeError("Pattern A linkage contains an unknown stage")
    if not (kept["pattern_a_requested_asof"].astype(str).str[:10].eq(kept["entry_signal_date"]).all()
            and kept["pattern_a_lookahead_free"].map(entry_filter._bool).all()):
        raise RuntimeError("Pattern A stage is not exact signal-date PIT")
    for column in ("pattern_a_last_daily_date", "pattern_a_last_weekly_bar_date", "pattern_b_monthly_last_bar", "pattern_b_weekly_last_bar"):
        observed = kept[column].fillna("").astype(str).str[:10]
        if (observed.ne("") & observed.gt(kept["entry_signal_date"])).any():
            raise RuntimeError(f"future-dated PIT input in linkage column {column}")
    audit = {
        "linkage_rows": int(len(frame)),
        "linkage_rows_removed_by_new_exclusions": int(len(removed)),
        "linkage_identities_removed": int(removed[["ticker", "isu_cd"]].drop_duplicates().shape[0]),
        "linkage_rows_kept": int(len(kept)),
        "linkage_sha256": _sha256(linkage_path),
    }
    return kept, audit


def _read_previous_stage_history(newly_excluded: set[tuple[str, str]]) -> tuple[dict[tuple[str, str, str], dict[str, Any]], dict[str, Any]]:
    metadata = _json(ROOT / runner.PREVIOUS_STAGE_METADATA)
    summary = _json(ROOT / runner.PREVIOUS_STAGE_SUMMARY)
    if metadata.get("study_id") != "PATTERN_B_PROGRESSED_PREVIOUS_PATTERN_A_STAGE_V01":
        raise RuntimeError("previous-stage metadata is not the expected study")
    if summary.get("verdict") != "PATTERN_B_PROGRESSED_PREVIOUS_STAGE_PROMISING":
        raise RuntimeError("previous-stage verdict differs")
    history_path = ROOT / runner.PREVIOUS_STAGE_HISTORY
    if _sha256(history_path) != metadata["generated_files"]["candidate_signal_stage_history.csv"]["sha256"]:
        raise RuntimeError("previous-stage history differs from its committed metadata")
    for relative in (runner.PREVIOUS_STAGE_METADATA, runner.PREVIOUS_STAGE_SUMMARY, runner.PREVIOUS_STAGE_HISTORY):
        if _git_bytes("HEAD", relative) != (ROOT / relative).read_bytes():
            raise RuntimeError(f"previous-stage input differs from HEAD blob: {relative}")
    replaced = {"data/market/rolling_authority/merged_pit_intervals.json",
                "data/market/rolling_authority/merged_trading_calendar.json"}
    for relative, expected in metadata["source_sha256"].items():
        if relative in replaced:
            continue
        if _sha256(ROOT / relative) != expected:
            raise RuntimeError(f"previous-stage source changed: {relative}")
    code_notes = {}
    for relative, expected in metadata["code_sha256"].items():
        current = _sha256(ROOT / relative)
        if current == expected:
            code_notes[relative] = "UNCHANGED"
            continue
        generating = hashlib.sha256(_git_bytes(PREVIOUS_STAGE_CODE_COMMIT, Path(relative))).hexdigest()
        if generating != expected:
            raise RuntimeError(f"previous-stage generating code cannot be verified: {relative}")
        code_notes[relative] = f"REFACTORED_AFTER_GENERATION; generating blob at {PREVIOUS_STAGE_CODE_COMMIT[:9]} verified"
    history = pd.read_csv(history_path, dtype={"ticker": "string", "isu_cd": "string", "entry_signal_date": "string"})
    history["ticker"] = history["ticker"].map(base.norm_ticker)
    history["isu_cd"] = history["isu_cd"].map(base.norm_isu)
    history["entry_signal_date"] = history["entry_signal_date"].astype(str).str[:10]
    if history.duplicated(list(runner.SIGNAL_KEY)).any():
        raise RuntimeError("previous-stage history has duplicate keys")
    if not history["entry_pattern_a_stage_recomputed"].astype(str).eq("PROGRESSED").all():
        raise RuntimeError("previous-stage history contains a non-PROGRESSED entry")
    if not history["entry_pattern_a_lookahead_free"].map(entry_filter._bool).all():
        raise RuntimeError("previous-stage history failed its PIT lookahead check")
    excluded_mask = history.apply(lambda row: _identity(row) in newly_excluded, axis=1)
    kept = history.loc[~excluded_mask]
    records = {_key(row): row for row in kept.to_dict("records")}
    audit = {
        "history_rows": int(len(history)),
        "history_rows_removed_by_new_exclusions": int(excluded_mask.sum()),
        "history_sha256": _sha256(history_path),
        "code_verification": code_notes,
    }
    return records, audit


def prepare_inputs(resolved: Any) -> tuple[list[dict[str, Any]], pd.DataFrame, list[dict[str, Any]], dict[str, Any]]:
    """Same event construction as the frozen Select Core replay, under current exclusions."""

    intervals, trading_dates, authority_provenance = base._load_authorities(ROOT)
    interval_to_component, intervals_by_component = base._interval_components(intervals, trading_dates)
    samples, exclusion_count = base._read_monthly_samples(ROOT, intervals, interval_to_component)
    events_by_identity, blocked = base._make_entry_signals(samples)
    all_events = [event for group in events_by_identity.values() for event in group]
    all_keys = {_key(event) for event in all_events}
    if len(all_keys) != len(all_events):
        raise RuntimeError("duplicate raw Pattern B signal keys")
    excluded_now = current_exclusions()
    newly_excluded = excluded_now - _baseline_exclusions()
    linkage, linkage_audit = _read_stage_linkage(all_keys, newly_excluded)
    linked = {_key(row): row for row in linkage.to_dict("records")}
    previous_rows, history_audit = _read_previous_stage_history(newly_excluded)
    progressed_keys = {key for key, row in linked.items() if str(row.get("pattern_a_stage")) == "PROGRESSED"}
    if progressed_keys != set(previous_rows):
        raise RuntimeError(f"previous-stage keys do not cover PROGRESSED linkage exactly: "
                           f"missing={len(progressed_keys - set(previous_rows))} extra={len(set(previous_rows) - progressed_keys)}")
    start = resolved.effective_start.strftime("%Y-%m-%d")
    end = resolved.effective_end.strftime("%Y-%m-%d")
    window_events = []
    for event in all_events:
        if not start <= event["entry_signal_date"] <= end:
            continue
        row = copy.deepcopy(event)
        stage = linked[_key(row)]
        row["pattern_a_stage"] = str(stage["pattern_a_stage"])
        row["pattern_a_stage_reason"] = stage.get("pattern_a_stage_reason")
        row["pattern_a_requested_asof"] = str(stage["pattern_a_requested_asof"])[:10]
        row["pattern_a_lookahead_free"] = entry_filter._bool(stage["pattern_a_lookahead_free"])
        row["pattern_a_last_daily_date"] = stage.get("pattern_a_last_daily_date")
        row["pattern_a_last_monthly_bar_date"] = stage.get("pattern_a_last_monthly_bar_date")
        row["pattern_a_last_weekly_bar_date"] = stage.get("pattern_a_last_weekly_bar_date")
        if row["pattern_a_requested_asof"] != row["entry_signal_date"] or not row["pattern_a_lookahead_free"]:
            raise RuntimeError(f"Pattern A entry stage is not exact-date PIT for {_key(row)}")
        if row["pattern_a_stage"] == "PROGRESSED":
            previous = previous_rows[_key(row)]
            row["previous_pattern_a_stage"] = str(previous["previous_pattern_a_stage"])
            row["previous_pattern_a_stage_date"] = str(previous["previous_pattern_a_stage_date"])
            row["progressed_segment_start_date"] = str(previous["progressed_segment_start_date"])
            row["progressed_segment_krx_sessions"] = int(previous["progressed_segment_krx_sessions"])
        else:
            row["previous_pattern_a_stage"] = None
            row["previous_pattern_a_stage_date"] = None
            row["progressed_segment_start_date"] = None
            row["progressed_segment_krx_sessions"] = None
        window_events.append(row)
    leaked = [event for event in window_events if _identity(event) in excluded_now]
    if leaked:
        raise RuntimeError(f"permanent exclusion leak: {len(leaked)} events")
    provenance = {
        "pattern_b_authorized_event_count": len(all_events),
        "pattern_b_authority_discontinuity_count": len(blocked),
        "window_pattern_b_raw_event_count": len(window_events),
        "permanent_exclusion_identity_count": exclusion_count,
        "baseline_exclusion_identity_count": len(_baseline_exclusions()),
        "newly_excluded_identity_count": len(newly_excluded),
        "linkage_audit": linkage_audit,
        "previous_stage_audit": history_audit,
        "market_authority": authority_provenance,
        "intervals_by_component": intervals_by_component,
    }
    return window_events, samples, blocked, provenance


def select_core_candidates(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row for row in events
        if row["pattern_a_stage"] == "PROGRESSED" and row["previous_pattern_a_stage"] in ALLOWED_PREVIOUS_STAGES
    ]


# ------------------------------------------------------ fundamentals stage

def _company_payload(ticker: str) -> dict[str, Any] | None:
    path = CACHE / "company" / f"{ticker}.json"
    if not path.exists():
        return None
    payload = _json(path)
    return payload if str(payload.get("status") or "") == "000" else None


def _needed_years(dates: list[str]) -> list[int]:
    years: set[int] = set()
    for value in dates:
        year = int(value[:4])
        years.update(y for y in (year - 2, year - 1, year) if y >= XBRL_FIRST_YEAR)
    return sorted(years)


def evaluate_fundamentals(candidates: list[dict[str, Any]]) -> pd.DataFrame:
    corp = CorpCodeRepository.from_cache(CACHE / "corp_code_cache.json")
    registry = FilingRegistry(None, cache_dir=CACHE / "filings")
    provider = PeriodizationProvider(corp, registry, XbrlRepository(None, cache_dir=CACHE / "xbrl"))
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for row in candidates:
        by_ticker.setdefault(row["ticker"], []).append(row)
    rows: list[dict[str, Any]] = []
    for number, (ticker, group) in enumerate(sorted(by_ticker.items()), start=1):
        payload = _company_payload(ticker)
        family = (str(classify_company_family(payload, ()).get("company_family") or CompanyFamily.UNKNOWN.value)
                  if payload else CompanyFamily.UNKNOWN.value)
        try:
            corp_code = corp.get_record(ticker).corp_code
        except Exception:  # noqa: BLE001 - identity gap is reported per signal
            corp_code = None
        observations: list[Any] = []
        build_failed: dict[int, str] = {}
        dates = [row["entry_signal_date"] for row in group if row["entry_signal_date"] >= PRE_XBRL_SIGNAL_BEFORE]
        if payload is not None and corp_code and family == CompanyFamily.NON_FINANCIAL.value and dates:
            for year in _needed_years(dates):
                try:
                    build = provider.build(ticker, str(year), FUNDAMENTALS_BUILD_AS_OF, company_metadata=payload)
                    observations.extend(build.result.observations)
                except NetworkBlocked:
                    raise
                except Exception as exc:  # noqa: BLE001 - a bounded cache gap for this fiscal year
                    build_failed[year] = type(exc).__name__
        for row in group:
            as_of = row["entry_signal_date"]
            reason = None
            filings: list[dict[str, Any]] = []
            if as_of < PRE_XBRL_SIGNAL_BEFORE:
                reason = "PRE_XBRL_ERA"
            elif payload is None:
                reason = "COMPANY_METADATA_UNAVAILABLE"
            elif corp_code is None:
                reason = "CORP_CODE_UNAVAILABLE"
            elif family == CompanyFamily.NON_FINANCIAL.value:
                year = int(as_of[:4])
                for fiscal_year in (year - 1, year):
                    for code in ("11013", "11012", "11014", "11011"):
                        try:
                            listed = registry.list_regular_filings(
                                ticker=ticker, corp_code=corp_code, bsns_year=str(fiscal_year),
                                reprt_code=code, as_of=as_of,
                            )
                        except NetworkBlocked:
                            raise
                        except Exception as exc:  # noqa: BLE001
                            reason = f"REGISTRY_CACHE_UNAVAILABLE_{type(exc).__name__}"
                            break
                        filings.extend(item.to_dict() for item in listed)
                    if reason:
                        break
            evaluation = evaluate_signal(
                company_family=family, filings=filings, observations=observations, as_of=as_of,
                unavailable_reason=reason,
            )
            out = {
                "ticker": row["ticker"], "isu_cd": row["isu_cd"], "entry_signal_date": as_of,
                "market_at_signal": row.get("market_at_signal"), "corp_code": corp_code,
                **evaluation.to_row(),
            }
            latest = evaluation.latest_quarter
            if evaluation.status == UNAVAILABLE and latest and evaluation.reason.startswith(("CURRENT_", "PRIOR_")):
                current_year = int(latest[:4])
                failed_year = current_year if evaluation.reason.startswith("CURRENT_") else current_year - 1
                if failed_year < XBRL_FIRST_YEAR:
                    out["oi_reason"] = "PRE_XBRL_ERA"
                elif failed_year in build_failed:
                    out["oi_reason"] = f"FISCAL_YEAR_BUILD_FAILED_{build_failed[failed_year]}"
            rows.append(out)
        if number % 50 == 0:
            print(f"fundamentals {number}/{len(by_ticker)} tickers", flush=True)
    frame = pd.DataFrame(rows).sort_values(["entry_signal_date", "ticker", "isu_cd"]).reset_index(drop=True)
    return frame


def audit_evaluations(frame: pd.DataFrame) -> dict[str, Any]:
    """Independent re-check of PIT and rule arithmetic for every evaluation."""

    future = 0
    quarter_mismatch = 0
    rule_mismatch = 0
    yoy_contract = 0
    for row in frame.to_dict("records"):
        as_of = row["entry_signal_date"]
        for column in ("latest_quarter_first_rcept_dt", "current_source_rcept_dt", "prior_source_rcept_dt"):
            value = row.get(column)
            if isinstance(value, str) and value and value[:10] > as_of:
                future += 1
        latest, prior = row.get("latest_quarter"), row.get("prior_year_same_quarter")
        if isinstance(latest, str) and latest:
            if prior != f"{int(latest[:4]) - 1}{latest[4:]}":
                quarter_mismatch += 1
        if row["oi_status"] in {PASS, FAIL}:
            current = int(row["current_operating_income"])
            prior_value = int(row["prior_operating_income"])
            expected = current >= OPERATING_INCOME_MIN_KRW and (prior_value <= 0 or 100 * current >= 101 * prior_value)
            if expected != (row["oi_status"] == PASS):
                rule_mismatch += 1
            has_yoy = _num(row.get("yoy_pct")) is not None
            if has_yoy != (prior_value > 0):
                yoy_contract += 1
    return {
        "future_disclosure_reference_count": future,
        "non_same_quarter_yoy_count": quarter_mismatch,
        "rule_recompute_mismatch_count": rule_mismatch,
        "yoy_percent_contract_violation_count": yoy_contract,
    }


# --------------------------------------------------------------- metrics

def trade_metrics(trades: list[dict[str, Any]], period_end: str) -> dict[str, Any]:
    realized = [row for row in trades if row.get("trade_status") == "REALIZED"]
    opened = [row for row in trades if row.get("trade_status") == "OPEN_AT_CUTOFF"]
    values = np.asarray([float(row["gross_return_pct"]) for row in realized], dtype=float)
    holding = [h for h in (_num(row.get("holding_krx_sessions")) for row in trades) if h is not None]
    terminal = et5._resolved_metrics(trades, period_end) if trades else {"exact_open_mark_count": 0, "unresolved_open_count": 0}
    result: dict[str, Any] = {
        "trade_count": len(trades),
        "realized_count": len(realized),
        "open_count": len(opened),
        "evaluable_count": len(realized) + int(terminal.get("exact_open_mark_count", 0)),
        "unresolved_count": int(terminal.get("unresolved_open_count", 0)),
        "mean_pct": float(values.mean()) if len(values) else None,
        "median_pct": float(np.median(values)) if len(values) else None,
        "win_rate_pct": float((values > 0).mean() * 100) if len(values) else None,
        "loss_rate_pct": float((values < 0).mean() * 100) if len(values) else None,
        "worst_pct": float(values.min()) if len(values) else None,
        "p10_pct": float(np.percentile(values, 10)) if len(values) else None,
        "mean_holding_sessions": float(np.mean(holding)) if holding else None,
        "median_holding_sessions": float(np.median(holding)) if holding else None,
        "terminal_mean_pct": terminal.get("mean_pct"),
        "terminal_median_pct": terminal.get("median_pct"),
        "terminal_win_rate_pct": terminal.get("positive_rate_pct"),
    }
    for threshold in (20, 50, 100):
        count = int((values >= threshold).sum()) if len(values) else 0
        result[f"ge_{threshold}_count"] = count
        result[f"ge_{threshold}_rate_pct"] = count / len(values) * 100 if len(values) else None
    return result


def control_parity(window_id: str, trades: list[dict[str, Any]], excluded: set[tuple[str, str]]) -> dict[str, Any]:
    frozen = pd.read_csv(ROOT / FROZEN_DIR[window_id] / "test_trade_ledger.csv",
                         dtype={"ticker": "string", "isu_cd": "string", "entry_signal_date": "string"})
    frozen = frozen.replace({np.nan: None}).to_dict("records")
    reference = [row for row in frozen if _identity(row) not in excluded]
    ref_by_key = {_key(row): row for row in reference}
    new_by_key = {_key(row): row for row in trades}
    mismatched_fields: Counter[str] = Counter()
    max_return_diff = 0.0
    for key in set(ref_by_key) & set(new_by_key):
        old, new = ref_by_key[key], new_by_key[key]
        for field in ("entry_execution_date", "exit_signal_date", "exit_execution_date", "trade_status"):
            if str(old.get(field) or "")[:10] != str(new.get(field) or "")[:10]:
                mismatched_fields[field] += 1
        for field in ("gross_return_pct", "mark_to_cutoff_gross_return_pct", "entry_reference_open"):
            a, b = _num(old.get(field)), _num(new.get(field))
            if (a is None) != (b is None):
                mismatched_fields[field] += 1
            elif a is not None and b is not None:
                diff = abs(a - b)
                if field == "gross_return_pct":
                    max_return_diff = max(max_return_diff, diff)
                if diff > EPS * max(1.0, abs(a)):
                    mismatched_fields[field] += 1
    result = {
        "frozen_trade_count": len(frozen),
        "frozen_removed_by_current_exclusions": len(frozen) - len(reference),
        "reference_trade_count": len(reference),
        "control_trade_count": len(trades),
        "reference_only_keys": len(set(ref_by_key) - set(new_by_key)),
        "control_only_keys": len(set(new_by_key) - set(ref_by_key)),
        "field_mismatch_counts": dict(mismatched_fields),
        "max_abs_gross_return_diff_pp": max_return_diff,
    }
    result["exact"] = bool(result["reference_only_keys"] == 0 and result["control_only_keys"] == 0 and not mismatched_fields)
    return result


def retention(control: list[dict[str, Any]], test: list[dict[str, Any]], evaluations: Mapping[tuple[str, str, str], Mapping[str, Any]]) -> dict[str, Any]:
    control_keys = {_key(row) for row in control}
    test_keys = {_key(row) for row in test}
    shared = control_keys & test_keys
    removed = control_keys - test_keys

    def removal_reason(key: tuple[str, str, str]) -> str:
        status = evaluations[key]["oi_status"]
        return "FILTER_FAIL" if status == FAIL else ("UNAVAILABLE" if status == UNAVAILABLE else
                                                     ("MISMATCH" if status == BASIS_OR_CURRENCY_MISMATCH else "PASS_BUT_LIFECYCLE_SHIFT"))

    winners = [row for row in control if row.get("trade_status") == "REALIZED" and float(row["gross_return_pct"]) >= 50]
    losers = [row for row in control if row.get("trade_status") == "REALIZED" and float(row["gross_return_pct"]) < 0]
    winners_kept = [row for row in winners if _key(row) in test_keys]
    losers_kept = [row for row in losers if _key(row) in test_keys]
    return {
        "control_trade_count": len(control_keys),
        "test_trade_count": len(test_keys),
        "shared_trade_count": len(shared),
        "retention_rate_pct": len(shared) / len(control_keys) * 100 if control_keys else None,
        "test_to_control_count_ratio_pct": len(test_keys) / len(control_keys) * 100 if control_keys else None,
        "test_only_trade_count": len(test_keys - control_keys),
        "removed_trade_count": len(removed),
        "removed_by_reason": dict(Counter(removal_reason(key) for key in removed)),
        "control_ge50_count": len(winners),
        "control_ge50_kept": len(winners_kept),
        "control_ge50_removed": len(winners) - len(winners_kept),
        "control_ge50_retention_pct": len(winners_kept) / len(winners) * 100 if winners else None,
        "control_ge50_removed_by_reason": dict(Counter(removal_reason(_key(row)) for row in winners if _key(row) not in test_keys)),
        "control_loss_count": len(losers),
        "control_loss_kept": len(losers_kept),
        "control_loss_removed": len(losers) - len(losers_kept),
        "control_loss_removal_pct": (len(losers) - len(losers_kept)) / len(losers) * 100 if losers else None,
        "control_loss_removed_by_reason": dict(Counter(removal_reason(_key(row)) for row in losers if _key(row) not in test_keys)),
    }


# ------------------------------------------------------------------ stages

def stage_evaluate(output: Path) -> None:
    start = _git_start((OUTPUT_ROOT.as_posix(),))
    loader, proof = make_projected_authority_loader()
    base._load_authorities = loader
    resolved, window = runner._resolve_window(ROOT, "P1")
    events, _, blocked, provenance = prepare_inputs(resolved)
    if blocked:
        raise RuntimeError("Pattern B authority discontinuity present")
    candidates = select_core_candidates(events)
    with network_guard():
        frame = evaluate_fundamentals(candidates)
    if len(frame) != len(candidates) or frame.duplicated(list(runner.SIGNAL_KEY)).any():
        raise RuntimeError("evaluation rows do not reconcile to CONTROL candidates")
    audit = audit_evaluations(frame)
    output.mkdir(parents=True, exist_ok=False)
    frame.to_csv(output / EVALUATION_FILE, index=False)
    _write_json(output / "oi_evaluation_metadata.json", {
        "study_id": STUDY_ID,
        "stage": "evaluate",
        "starting_git": start,
        "window_superset": window,
        "candidate_count": len(candidates),
        "status_counts": frame["oi_status"].value_counts().to_dict(),
        "reason_counts": frame["oi_reason"].value_counts().to_dict(),
        "integrity": audit,
        "authority_projection": proof,
        "exclusions": {k: v for k, v in provenance.items() if k not in {"intervals_by_component", "market_authority"}},
        "fundamentals_build_as_of": FUNDAMENTALS_BUILD_AS_OF,
        "pre_xbrl_signal_before": PRE_XBRL_SIGNAL_BEFORE,
        "network_guard": "socket connect blocked during evaluation",
        "evaluation_sha256": _sha256(output / EVALUATION_FILE),
    })
    print(json.dumps({"candidates": len(candidates), "status": frame["oi_status"].value_counts().to_dict(), "integrity": audit}, ensure_ascii=False))


def stage_backtest(output: Path) -> None:
    started = time.time()
    start = _git_start((OUTPUT_ROOT.as_posix(),))
    eval_meta = _json(output / "oi_evaluation_metadata.json")
    if _sha256(output / EVALUATION_FILE) != eval_meta["evaluation_sha256"]:
        raise RuntimeError("frozen evaluation file changed after review")
    if (output / "summary.json").exists():
        raise RuntimeError("refusing to rerun: backtest summary already exists")
    evaluations = pd.read_csv(output / EVALUATION_FILE, dtype={"ticker": "string", "isu_cd": "string", "entry_signal_date": "string"})
    eval_by_key = {_key(row): row for row in evaluations.replace({np.nan: None}).to_dict("records")}
    loader, proof = make_projected_authority_loader()
    base._load_authorities = loader
    excluded = current_exclusions()
    if runner.WORKERS != 10:
        raise RuntimeError("worker count is not 10")
    window_rows: list[dict[str, Any]] = []
    retention_rows: list[dict[str, Any]] = []
    group_rows: list[dict[str, Any]] = []
    unavailable_rows: list[dict[str, Any]] = []
    integrity_rows: list[dict[str, Any]] = []
    for window_id in WINDOW_IDS:
        resolved, window = runner._resolve_window(ROOT, window_id)
        start_day, end_day, support = window["effective_start"], window["effective_end"], window["execution_support"]
        events, samples, blocked, provenance = prepare_inputs(resolved)
        if blocked:
            raise RuntimeError(f"{window_id}: authority discontinuity")
        intervals_by_component = provenance.pop("intervals_by_component")
        control_candidates = select_core_candidates(events)
        missing = [row for row in control_candidates if _key(row) not in eval_by_key]
        if missing:
            raise RuntimeError(f"{window_id}: {len(missing)} CONTROL candidates lack a frozen evaluation")
        test_candidates = [row for row in control_candidates if eval_by_key[_key(row)]["oi_status"] == PASS]
        tickers = sorted({row["ticker"] for row in control_candidates})
        daily, ticker_audit, _ = runner._load_prices(ROOT, tickers, start_day, support)
        silent = sum(int(item.get("silent_inner_drop_count", 0) or 0) for item in ticker_audit.values())
        if silent:
            raise RuntimeError(f"{window_id}: Repository V2 silent inner drops={silent}")
        _, trading_dates, _ = base._load_authorities(ROOT)
        study = f"{STUDY_ID}_{window_id.replace('-', '_')}"
        print(f"{window_id}: CONTROL {len(control_candidates)} signals, TEST {len(test_candidates)} PASS signals", flush=True)
        control, control_events, _ = runner._simulate_scenario(
            "CONTROL", control_candidates, samples, daily, intervals_by_component,
            trading_dates, start_day, end_day, support, study)
        test, test_events, _ = runner._simulate_scenario(
            "TEST", test_candidates, samples, daily, intervals_by_component,
            trading_dates, start_day, end_day, support, study)
        validation_control = et5._validate_trades(window_id, control, control_events, events, trading_dates, start_day, end_day, support)
        validation_test = et5._validate_trades(window_id, test, test_events, events, trading_dates, start_day, end_day, support)
        parity = control_parity(window_id, control, excluded)
        non_pass_test = sum(eval_by_key[_key(row)]["oi_status"] != PASS for row in test)
        if non_pass_test:
            raise RuntimeError(f"{window_id}: TEST admitted {non_pass_test} non-PASS entries")
        if any(_identity(row) in excluded for row in control + test):
            raise RuntimeError(f"{window_id}: excluded identity traded")
        available_control = [row for row in control if eval_by_key[_key(row)]["oi_status"] in {PASS, FAIL}]
        window_eval = [eval_by_key[_key(row)] for row in control_candidates]
        status_counts = Counter(row["oi_status"] for row in window_eval)
        for scenario, trades in (("CONTROL", control), ("AVAILABLE_CONTROL", available_control), ("TEST", test)):
            group_rows.append({"window": window_id, "group": scenario, **trade_metrics(trades, end_day)})
        ret = retention(control, test, eval_by_key)
        retention_rows.append({"window": window_id, **ret})
        for reason, count in sorted(Counter(row["oi_reason"] for row in window_eval if row["oi_status"] == UNAVAILABLE).items()):
            unavailable_rows.append({"window": window_id, "reason": reason, "signal_count": count})
        window_rows.append({
            "window": window_id,
            "effective_start": start_day, "effective_end": end_day, "execution_support": support,
            "control_candidate_signals": len(control_candidates),
            "pass_signals": status_counts.get(PASS, 0),
            "fail_signals": status_counts.get(FAIL, 0),
            "unavailable_signals": status_counts.get(UNAVAILABLE, 0),
            "mismatch_signals": status_counts.get(BASIS_OR_CURRENCY_MISMATCH, 0),
            "control_trades": len(control),
            "available_control_trades": len(available_control),
            "test_trades": len(test),
            "control_parity_exact": parity["exact"],
        })
        integrity_rows.append({
            "window": window_id,
            **{f"parity_{k}": (json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v) for k, v in parity.items()},
            "test_non_pass_entries": non_pass_test,
            "control_validation": json.dumps(validation_control, ensure_ascii=False),
            "test_validation": json.dumps(validation_test, ensure_ascii=False),
            "repository_tickers": len(tickers),
            "permanent_exclusion_identity_count": provenance["permanent_exclusion_identity_count"],
        })
        relative = window_id.lower().replace("-", "_")
        out = output / relative
        out.mkdir(parents=True, exist_ok=False)
        for name, trades in (("control", control), ("test", test)):
            ledger = pd.DataFrame(trades)
            if len(ledger):
                ledger = ledger.merge(
                    evaluations[["ticker", "isu_cd", "entry_signal_date", "oi_status", "oi_reason", "latest_quarter",
                                 "current_operating_income", "prior_operating_income", "yoy_pct", "rule_branch"]],
                    on=["ticker", "isu_cd", "entry_signal_date"], how="left", validate="one_to_one")
            ledger.to_csv(out / f"{name}_trade_ledger.csv", index=False)
        pd.DataFrame(test_events).to_csv(out / "test_entry_signal_ledger.csv", index=False)
        print(json.dumps({"window": window_id, "control": len(control), "test": len(test), "parity": parity["exact"]}), flush=True)
        if not parity["exact"]:
            _write_json(output / "parity_failure.json", {"window": window_id, "parity": parity})
            raise RuntimeError(f"{window_id}: CONTROL parity failed; stopping before performance interpretation")

    pd.DataFrame(window_rows).to_csv(output / "window_signal_summary.csv", index=False)
    pd.DataFrame(group_rows).to_csv(output / "group_metrics.csv", index=False)
    pd.DataFrame(retention_rows).to_csv(output / "retention.csv", index=False)
    pd.DataFrame(unavailable_rows).to_csv(output / "unavailable_reasons.csv", index=False)
    pd.DataFrame(integrity_rows).to_csv(output / "integrity_audit.csv", index=False)
    _write_json(output / "summary.json", {
        "study_id": STUDY_ID,
        "control_strategy_id": STRATEGY_ID,
        "starting_git": start,
        "workers": runner.WORKERS,
        "authority_projection": proof,
        "evaluation_metadata_sha256": _sha256(output / "oi_evaluation_metadata.json"),
        "evaluation_sha256": eval_meta["evaluation_sha256"],
        "windows": window_rows,
        "group_metrics": group_rows,
        "retention": retention_rows,
        "elapsed_seconds": round(time.time() - started, 1),
        "auto_rerun": False,
    })


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("evaluate", "backtest"), required=True)
    args = parser.parse_args()
    output = ROOT / OUTPUT_ROOT
    if args.stage == "evaluate":
        stage_evaluate(output)
    else:
        stage_backtest(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
