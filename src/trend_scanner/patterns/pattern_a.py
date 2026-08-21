"""Pattern A: 장기 베이스 수렴형.

Feature Set Freeze v0.1과 Score Design v0.1(둘 다 docs/patterns/pattern_a/spec/production_authority.md
참고)이 끝났다. Score 구조/가중치/soft threshold는
`pattern_a_score.py`(`PatternAResult`, `score_pattern_a`)에 있다 — 이전에
여기 있던 5영역 100점 배점(`PATTERN_A_WEIGHTS`, 구 `PatternAResult`)은
검증되지 않은 초기 가설이었고 Score Design v0.1로 완전히 대체돼 삭제했다.

`evaluate_pattern_a`는 여전히 구현하지 않는다. `score_pattern_a`는
FeatureRow(또는 같은 속성을 가진 객체)를 입력받는 순수 함수이고, Score
Design v0.1은 기존 validation snapshot(FeatureRow)에 대해서만 검증했다.
raw 일봉 OHLCV -> 월봉/주봉 리샘플 -> FeatureRow 조립까지 잇는 것은 실제
스캐너 진입점을 만드는 작업이라 이번 라운드 스코프 밖이다(전체 시장 스캔
금지와 맞물린 경계).
"""

from __future__ import annotations

import pandas as pd

from trend_scanner.patterns.pattern_a_score import PatternAResult


def evaluate_pattern_a(daily: pd.DataFrame) -> PatternAResult:
    """일봉 OHLCV DataFrame을 받아 Pattern A 점수를 계산한다.

    아직 구현되지 않았다: daily -> 월봉/주봉 -> FeatureRow 조립 경로가
    아직 없다. FeatureRow가 이미 있다면 `pattern_a_score.score_pattern_a`를
    바로 쓸 수 있다.
    """
    raise NotImplementedError(
        "raw daily OHLCV로부터 FeatureRow를 조립하는 경로가 아직 없습니다. "
        "FeatureRow가 있다면 pattern_a_score.score_pattern_a()를 쓰세요. "
        "docs/patterns/pattern_a/spec/production_authority.md 참고."
    )
