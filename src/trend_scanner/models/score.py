"""패턴 점수 이력, Score Momentum 계산, 종목 단위 스캔 결과."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from trend_scanner.patterns.pattern_a import PatternAResult


@dataclass
class ScoreSnapshot:
    ticker: str
    as_of: date
    score: float


def score_momentum(current_score: float, past_score: float) -> float:
    """일정 기간 전 대비 점수 변화량. 완성된 고득점보다 개선 속도를 보기 위한 값."""
    return current_score - past_score


@dataclass
class ScanResult:
    """종목 신원(ticker/name)과 패턴별 평가 결과를 합친 스캐너 출력.

    Pattern evaluator(pattern_a.evaluate_pattern_a 등)는 종목 신원을 모르는
    순수 함수로 유지하고, 신원 정보는 여기서 합친다. Pattern B/C가 생기면
    이 dataclass에 필드를 추가하면 된다.
    """

    ticker: str
    name: str
    pattern_a: PatternAResult
