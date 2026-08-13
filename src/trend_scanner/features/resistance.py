"""장기 저항선/Range 내 위치 Feature 계산 함수."""

from __future__ import annotations


def distance_to_resistance(close: float, resistance: float) -> float:
    """저항선까지 남은 거리를 저항선 대비 비율로 계산한다. 값이 작을수록 저항에 근접."""
    return (resistance - close) / resistance


def range_position(close: float, low: float, high: float) -> float:
    """장기 Range(`low`~`high`) 내에서 현재가의 상대적 위치. 0.0=최하단, 1.0=최고점."""
    if high == low:
        return float("nan")
    return (close - low) / (high - low)
