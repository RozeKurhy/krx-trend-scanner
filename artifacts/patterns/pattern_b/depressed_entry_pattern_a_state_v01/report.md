# Pattern B DEPRESSED 진입 × Pattern A Stage 진단 V01

## 판정

판정: `PATTERN_B_PATTERN_A_ENTRY_FILTER_MIXED`

이번 진단은 진입 시점의 공식 Pattern A Stage가 이후 완성 월별 Pattern B 경로를 구분하는지, 그리고 기존 CONTROL 실현 거래 분포가 함께 달라지는지 본 사후 분류 분석이야. 판정은 혼합이지만, 회복 경로 가설을 확인할 단일 Stage 탐색 백테스트는 후속 과제로 검토할 근거가 있어.

## Pattern A 상태별 결과

| Pattern A | 신호 | NORMAL 선도달 | DEEP 선도달 | 둘 다 미도달 | 실현 거래 n | 미청산 n | 중앙 수익률 | 승률 | +50% | -30% 이하 | -50% 이하 | 중앙 MAE |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| WEAK | 14,157 | 51.8% | 40.0% | 5.2% | 7,811 | 1,061 | 8.1% | 72.4% | 5.6% | 5.3% | 1.8% | -12.1% |
| BASE | 2,063 | 71.3% | 25.2% | 1.5% | 1,788 | 81 | 5.1% | 69.9% | 1.6% | 3.7% | 1.4% | -8.5% |
| TRANSITION | 1,478 | 74.6% | 20.9% | 1.6% | 1,309 | 73 | 6.6% | 73.3% | 2.7% | 4.1% | 1.3% | -9.8% |
| EARLY_TREND | 3 | 66.7% | 0.0% | 0.0% | 2 | 0 | -11.9% | 50.0% | 0.0% | 50.0% | 0.0% | -31.9% |
| PROGRESSED | 835 | 70.9% | 19.9% | 4.6% | 737 | 86 | 11.5% | 76.7% | 6.1% | 6.9% | 2.8% | -10.8% |
| UNAVAILABLE | 1,540 | 46.9% | 40.2% | 7.9% | 807 | 155 | 9.6% | 74.0% | 7.4% | 9.0% | 4.0% | -12.2% |

수익률·승률·MFE·MAE·보유기간은 기존 CONTROL 원장의 실현 거래 기준이야. 미청산은 별도 open-position 집계로 `pattern_a_stage_summary.csv`에 남겼어. 경로 비율의 분모는 해당 Stage의 모든 raw DEPRESSED 신규 진입 신호야.

## 해석

회복 경로는 Pattern A Stage로 구분되는 편이야. 표본이 충분한 분류 상태 가운데 `TRANSITION`의 NORMAL 선도달률이 74.6%로 가장 높고 DEEP 선도달률은 20.9%야. `PROGRESSED`는 DEEP 선도달률이 19.9%로 가장 낮아. 반면 `WEAK`는 NORMAL 51.8%, DEEP 40.0%로 회복 경로가 더 불리해. TRANSITION과 WEAK 사이 차이는 각각 22.8%p, 19.1%p야.

거래 성과는 한 Stage를 일관된 승자로 만들지 않아. `PROGRESSED`는 실현 거래 중앙 수익률 +11.5%, 승률 76.7%로 가장 높지만 -30% 이하 비율 6.9%, -50% 이하 2.8%로 손실 꼬리는 `BASE`보다 나빠. `BASE`는 중앙 MAE -8.5%, -30% 이하 3.7%, -50% 이하 1.4%로 손실 측면이 가장 완만하지만 회복률과 수익률은 더 낮아. `WEAK`는 B 경로가 불리한데도 실현 거래 중앙 수익률 +8.1%, 승률 72.4%라 수익 분포만으로 걸러야 한다고 말하기 어려워.

`EARLY_TREND`는 3건뿐이라 해석하지 않았고, `UNAVAILABLE` 1,540건(7.7%)은 공식 Stage 결측이라 별도 관리해야 해. 결측 신호는 insufficient data 1,010건과 Repository V2 일봉 자료 unavailable 530건이야.

Pattern B 상태 경로는 마지막 완성 월말 `2026-08-31`까지 관측했어. 최종 평가 기준일은 `2026-09-21`지만 2026년 9월은 기준일 현재 미완성 월이어서 9월 Pattern B 상태를 만들거나 보간하지 않았어. `NEITHER_BY_CUTOFF`는 완성 상태 관측 프론티어까지 두 target state가 없고 identity가 cutoff에 유효한 신호로 정의했어.

판정은 `PATTERN_B_PATTERN_A_ENTRY_FILTER_MIXED`야. Pattern A는 회복/DEEP 경로 분류에는 실제 정보가 있지만, 실현 수익과 손실 위험까지 포함하면 우위 Stage가 갈려. 다음 단계로 단 하나만 사전 지정한다면 회복률이 가장 높은 정확한 `TRANSITION` 상태 필터의 단순 백테스트를 탐색적으로 해볼 근거는 충분해. 다만 이는 후보 검증일 뿐이고 실제 필터 채택 근거로 쓰면 안 돼.

## 검증

- raw DEPRESSED 진입 신호 재구성/기존 원장 일치: 20,076건, 키 불일치 0건
- Pattern A `UNAVAILABLE`: 1,540건
- 중복 신호: 0건; NORMAL/DEEP 동시 선도달 충돌: 0건
- 기존 원장 링크: FILLED 13,910건, 억제 6,166건, 연결 누락 0건
- 재현 가능한 무작위 직접 검수: 20건, 통과 20건
- Pattern A 분류 worker: 10
- 기존 CONTROL 출처: `artifacts/patterns/pattern_b/pure_strategy_simple_v01`; 거래 원장 재생 없이 버전 고정 원장 재사용

## 산출물

- `pattern_a_stage_summary.csv`: Stage별 경로·거래 요약
- `signal_stage_path_trade_linkage.csv`: 신호 단위 전체 연결 결과
- `normal_first_outcomes.csv`, `deep_first_outcomes.csv`: 첫 경로 결과별 신호 목록
- `other_unevaluated_signals.csv`: 판정 불가 신호와 사유
- `pattern_a_stage_random_review_20.csv`: 무작위 PIT 직접 검수
- `summary.json`, `metadata.json`: 수치 요약과 데이터 계보
