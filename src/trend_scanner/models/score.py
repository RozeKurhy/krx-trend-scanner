"""패턴 점수 이력 및 Score Momentum 계산."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class ScoreSnapshot:
    ticker: str
    as_of: date
    score: float


def score_momentum(current_score: float, past_score: float) -> float:
    """일정 기간 전 대비 점수 변화량. 완성된 고득점보다 개선 속도를 보기 위한 값."""
    return current_score - past_score
