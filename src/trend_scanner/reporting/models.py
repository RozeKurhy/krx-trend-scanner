"""Stock Report Data Models (Contract v0.1).

종목 리포트의 JSON 직렬화 및 구조 정의 데이터 클래스를 제공한다.
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


@dataclass
class ReportSummary:
    headline: str
    bullet_points: list[str]
    combined_narrative: str


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

    def to_dict(self) -> dict[str, Any]:
        """Convert report to JSON-serializable dictionary."""
        return asdict(self)
