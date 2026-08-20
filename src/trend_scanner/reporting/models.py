"""Stock Report Data Models (Contract v0.2).

종목 리포트의 JSON 직렬화 및 구조 정의 데이터 클래스를 제공한다.
v0.2에서는 A FAST Core V2 전략 상태(a_fast_core) 섹션이 최상위 필드로 추가된다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class ReportStatus(str, Enum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"


class FlowState(str, Enum):
    FLOW_ACCUMULATION = "FLOW_ACCUMULATION"
    FLOW_RECENT_RECOVERY = "FLOW_RECENT_RECOVERY"
    FLOW_RECENT_WEAKENING = "FLOW_RECENT_WEAKENING"
    FLOW_DISTRIBUTION = "FLOW_DISTRIBUTION"
    FLOW_MIXED = "FLOW_MIXED"
    FLOW_UNAVAILABLE = "FLOW_UNAVAILABLE"


class TradingValueState(str, Enum):
    TRADING_VALUE_EXPANDING = "TRADING_VALUE_EXPANDING"
    TRADING_VALUE_STABLE = "TRADING_VALUE_STABLE"
    TRADING_VALUE_WEAKENING = "TRADING_VALUE_WEAKENING"
    TRADING_VALUE_MIXED = "TRADING_VALUE_MIXED"
    TRADING_VALUE_UNAVAILABLE = "TRADING_VALUE_UNAVAILABLE"


@dataclass
class ReportHeader:
    ticker: str
    name: str
    market: str
    requested_as_of: str
    reference_market_date: str
    effective_as_of: str | None
    cache_present: bool
    cache_last_date: str | None
    report_status: ReportStatus
    asset_type: str = "COMMON"


@dataclass
class ReportSummary:
    headline: str
    bullet_points: list[str]
    combined_narrative: str
    strategy_headline: str | None = None


@dataclass
class CurrentSnapshot:
    pattern_a_score: float | None
    official_stage: str
    candidate_state: str
    is_candidate: bool
    market_cap_eok: float | None
    avg_trading_value_20d_eok: float | None
    investability_status: str
    investability_reason: str
    is_investable: bool


@dataclass
class MonthlyObservation:
    as_of: str
    score: float | None
    stage: str
    candidate_state: str
    data_available: bool
    close: float | None = None
    reason: str | None = None


@dataclass
class StageTransition:
    as_of: str
    from_stage: str
    to_stage: str


@dataclass
class ScoreTrend:
    current_score: float | None
    score_1m_ago: float | None
    score_3m_ago: float | None
    score_6m_ago: float | None
    score_12m_ago: float | None
    change_1m: float | None
    change_3m: float | None
    change_6m: float | None
    change_12m: float | None


@dataclass
class MonthlyHistorySection:
    history_start_as_of: str | None
    history_end_as_of: str | None
    observation_count: int
    recent_12m_observation_count: int
    score_trend: ScoreTrend
    stage_transitions: list[StageTransition]
    recent_12m_history: list[MonthlyObservation]
    full_monthly_history: list[MonthlyObservation]
    first_pattern_a_available_as_of: str | None = None
    pattern_a_available_observation_count: int = 0


@dataclass
class ForeignFlowSection:
    data_status: str
    flow_state: FlowState
    explanation: str
    foreign_net_buy_value_1d_krw: float | None
    foreign_net_buy_value_5d_krw: float | None
    foreign_net_buy_value_20d_krw: float | None
    foreign_net_buy_value_60d_krw: float | None
    foreign_flow_intensity_5d: float | None
    foreign_flow_intensity_20d: float | None
    foreign_flow_intensity_60d: float | None
    foreign_positive_days_5d: int | None
    foreign_positive_days_20d: int | None
    foreign_positive_days_60d: int | None


@dataclass
class TradingValueFlowSection:
    trading_value_state: TradingValueState
    explanation: str
    avg_trading_value_5d_eok: float | None
    avg_trading_value_20d_eok: float | None
    avg_trading_value_60d_eok: float | None
    ratio_5d_to_20d: float | None
    ratio_20d_to_60d: float | None


@dataclass
class DataQualitySection:
    cache_present: bool
    cache_first_date: str | None
    cache_last_date: str | None
    daily_rows_count: int
    completed_month_count: int
    quality_status: str
    quality_flags: list[str] = field(default_factory=list)


@dataclass
class ProvenanceSection:
    stock_price_source: str
    score_contract: str
    stage_contract: str
    investability_contract: str
    foreign_flow_contract: str
    network_requests: int


@dataclass
class PatternAFastWeeklyObservation:
    """Pattern A FAST(HIERARCHICAL_V01) 주별 관측치. Experimental / Early Signal."""

    week_ending: str
    close: float | None
    fast_score: float | None
    score_availability: str
    fast_stage: str | None
    stage_availability: str
    monthly_regime: str | None
    daily_risk: str | None
    interpretation: str


@dataclass
class PatternAFastCurrentSignal:
    """Pattern A FAST 현재 시점 요약. Pattern A와 합산/비교 우열을 계산하지 않는다."""

    as_of: str | None
    fast_score: float | None
    score_availability: str
    fast_stage: str | None
    stage_availability: str
    monthly_regime: str | None
    daily_risk: str | None
    interpretation: str


@dataclass
class PatternAFastSection:
    """Pattern A FAST(HIERARCHICAL_V01) 주별 History section. Additive, Experimental."""

    status: str
    label: str
    contract: str
    lifecycle_status: str
    current: PatternAFastCurrentSignal
    weekly_history: list[PatternAFastWeeklyObservation]
    history_start_as_of: str | None
    history_end_as_of: str | None
    observation_count: int


# ==============================================================================
# A FAST Core V2 Strategy Section Data Models (Stock Report v0.2)
# ==============================================================================


@dataclass
class AFastCoreEntryConditions:
    instrument_eligible: bool
    investability_pass: bool
    pattern_a_stage_eligible: bool
    fast_trigger_ready: bool
    monthly_regime_permitted: bool
    daily_risk_allowed: bool
    fast_score_status_allowed: bool
    no_open_position: bool
    all_conditions_met: bool
    pattern_a_stage: str | None = None
    fast_stage: str | None = None
    fast_stage_status: str | None = None
    monthly_regime: str | None = None
    daily_risk: str | None = None
    fast_score_status: str | None = None
    failed_conditions: list[str] = field(default_factory=list)


@dataclass
class AFastCoreCurrentTrade:
    trade_id: str
    trade_sequence: int
    entry_signal_date: str
    entry_execution_date: str
    entry_open: float
    entry_pattern_a_stage: str
    previous_exit_type: str | None
    previous_exit_execution_date: str | None
    first_progressed_date: str | None
    first_progressed_effective_trading_date: str | None
    lifecycle_class: str
    current_close: float
    current_return_pct: float
    trade_status: str
    pending_exit_type: str | None = None
    pending_exit_signal_date: str | None = None


@dataclass
class AFastCoreProtectionState:
    phase: str
    loss_guard_state: str
    loss_guard_threshold_pct: float | None
    first_progressed_date: str | None
    first_progressed_effective_trading_date: str | None
    lifecycle_class: str | None
    exit3_state: str
    exit4_state: str
    progressed_hwm_score: float | None
    current_pattern_a_score: float | None
    score_drawdown_from_hwm_pt: float | None


@dataclass
class AFastCoreReentryState:
    enabled: bool = True
    cooldown: str = "NONE"
    maximum_reentries: str = "NONE"
    pyramiding: bool = False
    overlapping_position: bool = False
    same_open_exit_and_reentry: bool = False
    completed_trade_count: int = 0
    current_trade_sequence: int | None = None
    next_entry_sequence: int = 1


@dataclass
class AFastCoreTradeHistoryItem:
    trade_id: str
    trade_sequence: int
    entry_signal_date: str
    entry_execution_date: str
    entry_open: float
    entry_pattern_a_stage: str
    exit_type: str
    exit_signal_date: str | None
    exit_execution_date: str | None
    exit_price: float | None
    trade_status: str
    return_pct: float
    previous_exit_type: str | None = None
    lifecycle_class: str | None = None


@dataclass
class AFastCoreProvenance:
    strategy_contract: str = "PATTERN_A_FAST_FINAL_STRATEGY_V02"
    strategy_contract_path: str = "docs/validation/pattern_a_fast_final_strategy_v02.md"
    architecture_authority_commit: str = "89df82a938dba1961c2342064db2dc0061a5f2ca"
    calendar_authority_commit: str = "88d54d85bdee1f2121bec9b27a250cbc1cb9f98f"
    trade_generation_authority_commit: str = "b9ba613be973906915e5081a0e5828dd6e1350d6"
    evidence_closure_authority_commit: str = "36273d97ae6d4f5b1dbc72cca186bc6009b5fa51"
    network_requests: int = 0


@dataclass
class AFastCoreSection:
    strategy_id: str = "PATTERN_A_FAST_FINAL_STRATEGY_V02"
    strategy_version: str = "V02"
    strategy_alias: str = "A FAST Core"
    strategy_status: str = "FINAL_STRATEGY_FROZEN"
    production_status: str = "PRODUCTION_DECISION_SUPPORT"
    fresh_oos_status: str = "NOT_EXECUTED"
    as_of: str = ""
    applicability: str = "APPLICABLE"
    strategy_state: str = "WAIT"
    canonical_position: str = "FLAT"
    action: str = "WAIT"
    action_reason: str = "ENTRY_CONDITIONS_NOT_MET"
    execution_timing: str | None = None
    entry_conditions: AFastCoreEntryConditions | None = None
    current_trade: AFastCoreCurrentTrade | None = None
    protection_state: AFastCoreProtectionState | None = None
    reentry_state: AFastCoreReentryState | None = None
    trade_history: list[AFastCoreTradeHistoryItem] = field(default_factory=list)
    interpretation: str = ""
    provenance: AFastCoreProvenance = field(default_factory=AFastCoreProvenance)


@dataclass
class StockReport:
    report_version: str
    ticker: str
    name: str
    market: str
    requested_as_of: str
    reference_market_date: str
    header: ReportHeader
    summary: ReportSummary
    current_snapshot: CurrentSnapshot
    monthly_history: MonthlyHistorySection
    foreign_flow: ForeignFlowSection
    trading_value_flow: TradingValueFlowSection
    data_quality: DataQualitySection
    provenance: ProvenanceSection
    pattern_a_fast: PatternAFastSection
    a_fast_core: AFastCoreSection
    asset_type: str = "COMMON"

    def to_dict(self) -> dict[str, Any]:
        """Convert report to JSON-serializable dictionary."""
        return asdict(self)
