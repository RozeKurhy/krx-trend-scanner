"""Entry-only promotion gate for A FAST Core V2 Alignment 500B.

The production configuration is deliberately disabled until an effective
signal date and operational activation are explicitly approved. Existing V2
exits and positions continue to be replayed by the frozen V2 simulator.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd

from trend_scanner.data.krx_raw_stock_store import (
    DEFAULT_RAW_STOCK_ROOT,
    KrxRawStockStore,
)
from trend_scanner.data.rolling_market_data_refresh import (
    DEFAULT_ROLLING_AUTHORITY_DIR,
    load_rolling_authority,
    validate_merged_authority_coherence,
)
from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS


V2_STRATEGY_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02"
PROMOTED_STRATEGY_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02_ALIGNMENT_MCAP_500B"
PROMOTED_STRATEGY_NAME = "A FAST Core V2 Alignment 500B"
RESEARCH_GROUP_ID = "ALIGNMENT_MCAP_500B"
PENDING_USER_APPROVAL = "PENDING_USER_APPROVAL"
MARKET_CAP_THRESHOLD_KRW = 500_000_000_000
EXPECTED_EXCLUSION_COUNT = 185
EXPECTED_EXCLUSION_SHA256 = "c0089f72ed390a2a1df9048d0dac1f309259422e3ff9e77c4f6d986517a5163c"
DEFAULT_CONFIG_RELATIVE_PATH = Path(
    "artifacts/patterns/pattern_a_fast/production/alignment_mcap_500b_operational_config.json"
)
DEFAULT_ACTIVATION_HISTORY_RELATIVE_PATH = Path(
    "artifacts/patterns/pattern_a_fast/production/alignment_mcap_500b_activation_history.json"
)
ACTIVATION_HISTORY_SCHEMA = "a_fast_core_alignment_mcap_500b_activation_history_v01"


class AlignmentGateIntegrityError(RuntimeError):
    """Structural authority/hash errors that must abort staging."""


@dataclass(frozen=True)
class PromotionConfig:
    enabled: bool = False
    effective_signal_date: str = PENDING_USER_APPROVAL
    operational_activation_approved: bool = False

    @property
    def active(self) -> bool:
        return (
            self.enabled
            and self.operational_activation_approved
            and self.effective_signal_date != PENDING_USER_APPROVAL
        )

    @property
    def effective_date(self) -> pd.Timestamp | None:
        if not self.active:
            return None
        return pd.Timestamp(date.fromisoformat(self.effective_signal_date)).normalize()


@dataclass(frozen=True)
class ActivationInterval:
    """An approved, immutable signal-date interval for the promoted entry gate.

    ``rollback_effective_signal_date`` is exclusive: that signal date and later
    dates use V2.  Closed intervals are append-only history; an open interval
    must agree with the currently enabled operational config.
    """

    activation_id: str
    effective_signal_date: str
    rollback_effective_signal_date: str | None
    approval_reference: str

    def contains(self, signal_date: Any) -> bool:
        value = pd.Timestamp(signal_date).strftime("%Y-%m-%d")
        return (
            value >= self.effective_signal_date
            and (self.rollback_effective_signal_date is None or value < self.rollback_effective_signal_date)
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "activation_id": self.activation_id,
            "effective_signal_date": self.effective_signal_date,
            "rollback_effective_signal_date": self.rollback_effective_signal_date,
        }


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reason_code: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self, signal_date: Any) -> dict[str, Any]:
        return {
            "signal_date": pd.Timestamp(signal_date).strftime("%Y-%m-%d"),
            "allowed": self.allowed,
            "reason_code": self.reason_code,
            "strategy_id": V2_STRATEGY_ID if self.reason_code.startswith("PASS_V2") else PROMOTED_STRATEGY_ID,
            "details": dict(self.details),
        }


def load_promotion_config(repo_root: Path) -> PromotionConfig:
    path = Path(repo_root) / DEFAULT_CONFIG_RELATIVE_PATH
    if not path.is_file():
        return PromotionConfig()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AlignmentGateIntegrityError(f"PROMOTION_CONFIG_INVALID:{path}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != "a_fast_core_alignment_mcap_500b_operational_config_v01":
        raise AlignmentGateIntegrityError("PROMOTION_CONFIG_SCHEMA_INVALID")
    if payload.get("strategy_id") != PROMOTED_STRATEGY_ID or payload.get("research_group_id") != RESEARCH_GROUP_ID:
        raise AlignmentGateIntegrityError("PROMOTION_CONFIG_IDENTITY_MISMATCH")
    enabled = payload.get("enabled")
    approved = payload.get("operational_activation_approved")
    effective = payload.get("effective_signal_date")
    if not isinstance(enabled, bool) or not isinstance(approved, bool) or not isinstance(effective, str):
        raise AlignmentGateIntegrityError("PROMOTION_CONFIG_FIELDS_INVALID")
    if effective != PENDING_USER_APPROVAL:
        try:
            if date.fromisoformat(effective).isoformat() != effective:
                raise ValueError
        except ValueError as exc:
            raise AlignmentGateIntegrityError("PROMOTION_EFFECTIVE_SIGNAL_DATE_INVALID") from exc
    if enabled and (effective == PENDING_USER_APPROVAL or not approved):
        raise AlignmentGateIntegrityError("PROMOTION_ACTIVATION_NOT_APPROVED_OR_DATE_PENDING")
    if payload.get("permanent_exclusion_pair_count") != EXPECTED_EXCLUSION_COUNT:
        raise AlignmentGateIntegrityError("PROMOTION_CONFIG_EXCLUSION_COUNT_MISMATCH")
    if payload.get("permanent_exclusion_canonical_sha256") != EXPECTED_EXCLUSION_SHA256:
        raise AlignmentGateIntegrityError("PROMOTION_CONFIG_EXCLUSION_HASH_MISMATCH")
    return PromotionConfig(enabled=enabled, effective_signal_date=effective, operational_activation_approved=approved)


def load_activation_history(
    repo_root: Path,
    config: PromotionConfig,
) -> tuple[ActivationInterval, ...]:
    """Load and validate the append-only approved activation/rollback ledger."""
    path = Path(repo_root) / DEFAULT_ACTIVATION_HISTORY_RELATIVE_PATH
    if not path.is_file():
        if config.active:
            raise AlignmentGateIntegrityError("PROMOTION_ACTIVATION_HISTORY_MISSING")
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AlignmentGateIntegrityError(f"PROMOTION_ACTIVATION_HISTORY_INVALID:{path}") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != ACTIVATION_HISTORY_SCHEMA
        or payload.get("strategy_id") != PROMOTED_STRATEGY_ID
        or not isinstance(payload.get("intervals"), list)
    ):
        raise AlignmentGateIntegrityError("PROMOTION_ACTIVATION_HISTORY_SCHEMA_INVALID")

    intervals: list[ActivationInterval] = []
    activation_ids: set[str] = set()
    previous_end: str | None = None
    for raw in payload["intervals"]:
        if not isinstance(raw, dict) or raw.get("approval_status") != "APPROVED":
            raise AlignmentGateIntegrityError("PROMOTION_ACTIVATION_HISTORY_APPROVAL_INVALID")
        activation_id = raw.get("activation_id")
        start = raw.get("effective_signal_date")
        end = raw.get("rollback_effective_signal_date")
        approval_reference = raw.get("approval_reference")
        if (
            not isinstance(activation_id, str) or not activation_id.strip()
            or activation_id in activation_ids
            or not isinstance(approval_reference, str) or not approval_reference.strip()
            or not isinstance(start, str)
            or (end is not None and not isinstance(end, str))
        ):
            raise AlignmentGateIntegrityError("PROMOTION_ACTIVATION_HISTORY_FIELDS_INVALID")
        try:
            if date.fromisoformat(start).isoformat() != start:
                raise ValueError
            if end is not None and date.fromisoformat(end).isoformat() != end:
                raise ValueError
        except ValueError as exc:
            raise AlignmentGateIntegrityError("PROMOTION_ACTIVATION_HISTORY_DATE_INVALID") from exc
        if end is not None and end <= start:
            raise AlignmentGateIntegrityError("PROMOTION_ACTIVATION_HISTORY_INTERVAL_INVALID")
        if previous_end is None and intervals:
            raise AlignmentGateIntegrityError("PROMOTION_ACTIVATION_HISTORY_OVERLAP_OR_OPEN_INTERVAL_NOT_LAST")
        if previous_end is not None and start < previous_end:
            raise AlignmentGateIntegrityError("PROMOTION_ACTIVATION_HISTORY_OVERLAP_OR_ORDER_INVALID")
        interval = ActivationInterval(
            activation_id=activation_id,
            effective_signal_date=start,
            rollback_effective_signal_date=end,
            approval_reference=approval_reference,
        )
        intervals.append(interval)
        activation_ids.add(activation_id)
        previous_end = end

    open_intervals = [interval for interval in intervals if interval.rollback_effective_signal_date is None]
    if config.active:
        if (
            len(open_intervals) != 1
            or open_intervals[0].effective_signal_date != config.effective_signal_date
        ):
            raise AlignmentGateIntegrityError("PROMOTION_ACTIVATION_HISTORY_CONFIG_MISMATCH")
    elif open_intervals:
        raise AlignmentGateIntegrityError("PROMOTION_ACTIVATION_HISTORY_OPEN_WHILE_CONFIG_INACTIVE")
    return tuple(intervals)


def canonical_exclusion_sha256(pairs: Any) -> str:
    normalized = sorted((str(ticker).zfill(6), str(isu_cd).strip().upper()) for ticker, isu_cd in pairs)
    payload = {"schema": "sorted_exact_pair_json_v01", "pairs": [list(pair) for pair in normalized]}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def verify_permanent_exclusion_registry() -> dict[str, Any]:
    pairs = set(PERMANENT_IDENTITY_EXCLUSIONS)
    actual_count = len(pairs)
    actual_hash = canonical_exclusion_sha256(pairs)
    if actual_count != EXPECTED_EXCLUSION_COUNT or actual_hash != EXPECTED_EXCLUSION_SHA256:
        raise AlignmentGateIntegrityError(
            f"PERMANENT_EXCLUSION_REGISTRY_HASH_MISMATCH:count={actual_count}:sha256={actual_hash}"
        )
    return {"pair_count": actual_count, "canonical_sha256": actual_hash}


def monthly_alignment_decision(daily: pd.DataFrame, signal_date: Any) -> GateDecision:
    """Compare signal-day adjusted close with MA20/MA60 from prior full months."""
    signal = pd.Timestamp(signal_date).normalize()
    if daily is None or daily.empty or "close" not in daily.columns:
        return GateDecision(False, "REJECT_MA_UNAVAILABLE", {"cause": "ADJUSTED_CLOSE_MISSING"})
    frame = daily.copy()
    index = pd.DatetimeIndex(pd.to_datetime(frame.index, errors="coerce")).normalize()
    if index.isna().any() or index.duplicated().any():
        raise AlignmentGateIntegrityError("ADJUSTED_PRICE_DATE_INDEX_INVALID")
    frame.index = index
    frame = frame.sort_index()
    day_rows = frame.loc[frame.index == signal, "close"]
    if len(day_rows) != 1:
        return GateDecision(False, "REJECT_MA_UNAVAILABLE", {"cause": "SIGNAL_DATE_CLOSE_MISSING_OR_DUPLICATED"})
    signal_close = pd.to_numeric(day_rows, errors="coerce").iloc[0]
    if pd.isna(signal_close) or not math.isfinite(float(signal_close)) or float(signal_close) <= 0:
        return GateDecision(False, "REJECT_MA_UNAVAILABLE", {"cause": "SIGNAL_DATE_CLOSE_INVALID"})

    prior = frame.loc[frame.index < signal.to_period("M").start_time, "close"]
    prior = pd.to_numeric(prior, errors="coerce").dropna()
    monthly = prior.groupby(prior.index.to_period("M"), sort=True).last().sort_index()
    expected = pd.period_range(end=signal.to_period("M") - 1, periods=60, freq="M")
    missing = expected.difference(monthly.index)
    if len(missing) or len(monthly.index.intersection(expected)) != 60:
        return GateDecision(False, "REJECT_MA_UNAVAILABLE", {
            "cause": "PRIOR_COMPLETED_MONTHS_INSUFFICIENT_OR_GAPPED",
            "required_months": 60,
            "available_months": int(len(monthly.index.intersection(expected))),
            "missing_months": [str(value) for value in missing[:5]],
        })
    closes = pd.to_numeric(monthly.reindex(expected), errors="coerce")
    if closes.isna().any() or not closes.map(math.isfinite).all() or (closes <= 0).any():
        return GateDecision(False, "REJECT_MA_UNAVAILABLE", {"cause": "PRIOR_MONTHLY_CLOSE_INVALID"})
    ma20 = float(closes.iloc[-20:].mean())
    ma60 = float(closes.mean())
    details = {
        "signal_close_adjusted": float(signal_close),
        "ma20_prior_completed_months": ma20,
        "ma60_prior_completed_months": ma60,
        "last_completed_month": str(expected[-1]),
    }
    if float(signal_close) <= ma20 or ma20 <= ma60:
        return GateDecision(False, "REJECT_MA_ALIGNMENT", details)
    return GateDecision(True, "PASS_ALIGNMENT", details)


class AlignmentMcap500BGate:
    """Validated point-in-time identity and exact raw market-cap gate."""

    def __init__(
        self,
        repo_root: Path,
        config: PromotionConfig,
        *,
        identity_resolver: Callable[[str, str, str], tuple[str, str] | None] | None = None,
        market_cap_resolver: Callable[[str, str, str], int | None] | None = None,
        activation_intervals: tuple[ActivationInterval, ...] | None = None,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.config = config
        if activation_intervals is None and config.active:
            raise AlignmentGateIntegrityError("PROMOTION_ACTIVATION_HISTORY_REQUIRED")
        self.activation_intervals = activation_intervals if activation_intervals is not None else ()
        self._validate_activation_intervals()
        open_intervals = [interval for interval in self.activation_intervals if interval.rollback_effective_signal_date is None]
        if config.active:
            if len(open_intervals) != 1 or open_intervals[0].effective_signal_date != config.effective_signal_date:
                raise AlignmentGateIntegrityError("PROMOTION_ACTIVATION_HISTORY_CONFIG_MISMATCH")
        elif open_intervals:
            raise AlignmentGateIntegrityError("PROMOTION_ACTIVATION_HISTORY_OPEN_WHILE_CONFIG_INACTIVE")
        self._identity_resolver = identity_resolver
        self._market_cap_resolver = market_cap_resolver
        self._pit_by_ticker: dict[str, list[dict[str, Any]]] = {}
        self._pit_frontier: str | None = None
        self._raw_partitions: dict[tuple[str, str], pd.DataFrame | None] = {}
        self._decision_cache: dict[tuple[str, str, str], GateDecision] = {}
        self.registry_audit: dict[str, Any] | None = None
        if config.active or self.activation_intervals:
            self.registry_audit = verify_permanent_exclusion_registry()
            if identity_resolver is None:
                self._load_validated_pit()

    def strategy_id_for_signal(self, signal_date: Any) -> str:
        return PROMOTED_STRATEGY_ID if self.is_promoted_signal(signal_date) else V2_STRATEGY_ID

    def is_promoted_signal(self, signal_date: Any) -> bool:
        day = pd.Timestamp(signal_date).normalize()
        return any(interval.contains(day) for interval in self.activation_intervals)

    def effective_signal_date_for_signal(self, signal_date: Any) -> str | None:
        day = pd.Timestamp(signal_date).normalize()
        matches = [interval for interval in self.activation_intervals if interval.contains(day)]
        if len(matches) > 1:
            raise AlignmentGateIntegrityError("PROMOTION_ACTIVATION_HISTORY_OVERLAP")
        return matches[0].effective_signal_date if matches else None

    def has_promoted_signal_on_or_before(self, as_of: Any) -> bool:
        day = pd.Timestamp(as_of).normalize()
        return any(pd.Timestamp(interval.effective_signal_date) <= day for interval in self.activation_intervals)

    def public_activation_intervals(self) -> list[dict[str, Any]]:
        return [interval.to_public_dict() for interval in self.activation_intervals]

    def strategy_id_for_as_of(self, as_of: Any) -> str:
        return self.strategy_id_for_signal(as_of)

    def _validate_activation_intervals(self) -> None:
        previous_end: str | None = None
        for index, interval in enumerate(self.activation_intervals):
            if interval.rollback_effective_signal_date is None and index != len(self.activation_intervals) - 1:
                raise AlignmentGateIntegrityError("PROMOTION_ACTIVATION_HISTORY_OPEN_INTERVAL_NOT_LAST")
            if previous_end is None and index:
                raise AlignmentGateIntegrityError("PROMOTION_ACTIVATION_HISTORY_OVERLAP")
            if previous_end is not None and interval.effective_signal_date < previous_end:
                raise AlignmentGateIntegrityError("PROMOTION_ACTIVATION_HISTORY_OVERLAP")
            previous_end = interval.rollback_effective_signal_date

    def _load_validated_pit(self) -> None:
        authority_dir = self.repo_root / DEFAULT_ROLLING_AUTHORITY_DIR
        try:
            manifest = load_rolling_authority(authority_dir)
            pit_payload, _ = validate_merged_authority_coherence(manifest, authority_dir)
        except Exception as exc:
            raise AlignmentGateIntegrityError(f"ROLLING_PIT_AUTHORITY_INVALID:{exc}") from exc
        frontier = str(pit_payload.get("pit_frontier") or "")[:10]
        if not frontier:
            raise AlignmentGateIntegrityError("ROLLING_PIT_FRONTIER_MISSING")
        self._pit_frontier = frontier
        intervals = pit_payload.get("intervals")
        if not isinstance(intervals, list):
            raise AlignmentGateIntegrityError("ROLLING_PIT_INTERVALS_INVALID")
        for raw in intervals:
            if not isinstance(raw, dict):
                raise AlignmentGateIntegrityError("ROLLING_PIT_INTERVAL_INVALID")
            if str(raw.get("state", "")).upper() != "COMMON":
                continue
            ticker = str(raw.get("ticker", "")).strip().zfill(6)
            isu_cd = str(raw.get("isu_cd", "")).strip().upper()
            market = str(raw.get("market", "")).strip().upper()
            start = str(raw.get("effective_from", ""))[:10]
            end = str(raw.get("effective_to", ""))[:10]
            if not ticker or not isu_cd or not market or len(start) != 10 or len(end) != 10 or start > end:
                raise AlignmentGateIntegrityError("ROLLING_PIT_INTERVAL_FIELDS_INVALID")
            self._pit_by_ticker.setdefault(ticker, []).append({
                "ticker": ticker, "isu_cd": isu_cd, "market": market,
                "effective_from": start, "effective_to": end,
            })

    def _resolve_pit_identity(self, ticker: str, market: str, signal_date: str) -> tuple[str, str] | None:
        if self._pit_frontier is not None and signal_date > self._pit_frontier:
            return None
        matches = [
            row for row in self._pit_by_ticker.get(ticker, [])
            if row["market"] == market and row["effective_from"] <= signal_date <= row["effective_to"]
        ]
        if len(matches) > 1:
            raise AlignmentGateIntegrityError(f"PIT_IDENTITY_OVERLAP:{ticker}:{market}:{signal_date}")
        if not matches:
            return None
        return matches[0]["isu_cd"], matches[0]["market"]

    def _load_raw_partition(self, market: str, signal_date: str) -> pd.DataFrame | None:
        key = (market, signal_date)
        if key in self._raw_partitions:
            return self._raw_partitions[key]
        raw_root = self.repo_root / DEFAULT_RAW_STOCK_ROOT
        manifest_path = raw_root / "manifest.sqlite3"
        if not manifest_path.is_file():
            self._raw_partitions[key] = None
            return None
        try:
            connection = sqlite3.connect(manifest_path.resolve().as_uri() + "?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            try:
                row = connection.execute(
                    "SELECT * FROM raw_snapshot_manifest WHERE market=? AND date=?",
                    (market, signal_date),
                ).fetchone()
            finally:
                connection.close()
        except sqlite3.Error as exc:
            raise AlignmentGateIntegrityError(f"RAW_KRX_MANIFEST_READ_FAILED:{market}:{signal_date}") from exc
        if row is None or row["status"] != "COMPLETE":
            self._raw_partitions[key] = None
            return None
        store = object.__new__(KrxRawStockStore)
        store.root = raw_root
        try:
            frame = store._verify_complete_row(dict(row))
        except Exception as exc:
            raise AlignmentGateIntegrityError(f"RAW_KRX_PARTITION_INTEGRITY_ERROR:{market}:{signal_date}:{exc}") from exc
        if str(row["market"]).upper() != market or str(row["date"])[:10] != signal_date:
            raise AlignmentGateIntegrityError(f"RAW_KRX_PARTITION_KEY_MISMATCH:{market}:{signal_date}")
        self._raw_partitions[key] = frame
        return frame

    def _resolve_market_cap(self, ticker: str, market: str, signal_date: str) -> int | None:
        if self._market_cap_resolver is not None:
            value = self._market_cap_resolver(ticker, market, signal_date)
        else:
            frame = self._load_raw_partition(market, signal_date)
            if frame is None:
                return None
            matches = frame.loc[frame["ticker"].astype(str).str.zfill(6).eq(ticker)]
            if len(matches) > 1:
                raise AlignmentGateIntegrityError(f"RAW_KRX_TICKER_DUPLICATE:{ticker}:{market}:{signal_date}")
            if matches.empty:
                return None
            value = matches.iloc[0].get("market_cap")
        try:
            amount = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(amount) or amount <= 0 or not amount.is_integer():
            return None
        return int(amount)

    def evaluate(
        self,
        ticker: str,
        market: str,
        daily: pd.DataFrame,
        signal_date: Any,
    ) -> GateDecision:
        signal = pd.Timestamp(signal_date).normalize()
        signal_str = signal.strftime("%Y-%m-%d")
        ticker = str(ticker).strip().zfill(6)
        market = str(market).strip().upper()
        if not self.is_promoted_signal(signal):
            return GateDecision(True, "PASS_V2_INACTIVE_OR_PRE_CUTOVER", {"strategy_id": V2_STRATEGY_ID})
        cache_key = (ticker, market, signal_str)
        if cache_key in self._decision_cache:
            return self._decision_cache[cache_key]
        if self._identity_resolver is None:
            identity = self._resolve_pit_identity(ticker, market, signal_str)
        else:
            identity = self._identity_resolver(ticker, market, signal_str)
        if identity is None:
            decision = GateDecision(False, "REJECT_IDENTITY_UNRESOLVED", {"market": market, "signal_date": signal_str})
            self._decision_cache[cache_key] = decision
            return decision
        isu_cd, identity_market = str(identity[0]).strip().upper(), str(identity[1]).strip().upper()
        if not isu_cd or identity_market != market:
            decision = GateDecision(False, "REJECT_IDENTITY_UNRESOLVED", {
                "market": market, "resolved_market": identity_market, "signal_date": signal_str,
            })
            self._decision_cache[cache_key] = decision
            return decision
        if (ticker, isu_cd) in PERMANENT_IDENTITY_EXCLUSIONS:
            decision = GateDecision(False, "REJECT_PERMANENT_EXCLUSION", {"ticker": ticker, "isu_cd": isu_cd})
            self._decision_cache[cache_key] = decision
            return decision
        alignment = monthly_alignment_decision(daily, signal)
        if not alignment.allowed:
            self._decision_cache[cache_key] = alignment
            return alignment
        market_cap = self._resolve_market_cap(ticker, market, signal_str)
        if market_cap is None:
            decision = GateDecision(False, "REJECT_MCAP_UNRESOLVED", {
                "ticker": ticker, "isu_cd": isu_cd, "market": market, "signal_date": signal_str,
                "partition_lookup": "EXACT_DATE_AND_MARKET_ONLY",
            })
            self._decision_cache[cache_key] = decision
            return decision
        details = {
            **dict(alignment.details), "ticker": ticker, "isu_cd": isu_cd,
            "market": market, "signal_date": signal_str, "market_cap_krw": market_cap,
            "market_cap_threshold_krw": MARKET_CAP_THRESHOLD_KRW,
            "market_cap_partition": {"market": market, "date": signal_str},
        }
        if market_cap < MARKET_CAP_THRESHOLD_KRW:
            decision = GateDecision(False, "REJECT_MCAP_BELOW_500B", details)
        else:
            decision = GateDecision(True, "PASS_ALIGNMENT_MCAP_500B", details)
        self._decision_cache[cache_key] = decision
        return decision


@lru_cache(maxsize=8)
def get_production_alignment_gate(repo_root: str) -> AlignmentMcap500BGate:
    root = Path(repo_root).resolve()
    config = load_promotion_config(root)
    history = load_activation_history(root, config)
    return AlignmentMcap500BGate(root, config, activation_intervals=history)
