# A FAST Core V2 Alignment 500B

## 식별과 상태

- 공식 전략 ID: `PATTERN_A_FAST_FINAL_STRATEGY_V02_ALIGNMENT_MCAP_500B`
- 공식 표시명: `A FAST Core V2 Alignment 500B`
- 연구 group ID: `ALIGNMENT_MCAP_500B` (운영 Strategy ID가 아님)
- 승격 승인일: 2026-10-13
- 운영 상태: 미활성. 운영 `effective_signal_date`와 발행 활성화 승인을 기다린다.
- 기존 동결 V2: `PATTERN_A_FAST_FINAL_STRATEGY_V02`; 과거 거래·문서·자료의 원래 ID를 보존한다.

공식 채택과 기본 전략 교체 승인은 이미 기록되어 있다. 실제 적용 신호일 및 운영
발행은 별도 승인이 필요하다. 승인 전 설정은 `enabled=false`,
`effective_signal_date=PENDING_USER_APPROVAL`이며 현재 런타임 기본값은 기존 V2다.

공식 채택의 원자료는 [185쌍 공식 5기간 재심사](../../../../../artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_exclusion185_five_window_official_adoption_review_v01/report.md)와
동일 디렉터리의 `decision_recommendation.json`, `source_evidence_manifest.json`이다.
이 구현 문서는 공식 백테스트 결과를 다시 계산하거나 수정하지 않는다.

## 변경 범위

V2의 기존 진입 8조건을 통과한 **신규 진입 신호**에 아래 항목을 추가한다.

1. 실제 `entry_signal_date` 조정종가 `>` 그 신호가 속한 월을 뺀 직전 완료월
   60개의 조정 월봉 종가에서 계산한 MA20 `>` 같은 기준의 MA60. 정확히
   60개월이 연속으로 존재해야 하며, 불충분·공백·잘못된 값은
   `REJECT_MA_UNAVAILABLE`이다.
2. 정확한 신호일의 정확한 시장 partition에서 읽은 KRX raw 시가총액이
   `500,000,000,000`원 이상이어야 한다. PIT 키는 `(ticker, standard ISU_CD,
   market, signal_date)`다. 최신·인접일·normalized 표시용 값으로 대체하지 않는다.
3. 영구 제외는 정확한 `(ticker, standard ISU_CD)` 185쌍에만 적용한다. 정책
   원본은 `src/trend_scanner/universe/permanent_identity_exclusions.py`이고,
   canonical scheme `sorted_exact_pair_json_v01`의 SHA-256은
   `c0089f72ed390a2a1df9048d0dac1f309259422e3ff9e77c4f6d986517a5163c`다.

`REJECT_MA_ALIGNMENT`, `REJECT_MA_UNAVAILABLE`, `REJECT_MCAP_BELOW_500B`,
`REJECT_MCAP_UNRESOLVED`, `REJECT_IDENTITY_UNRESOLVED`,
`REJECT_PERMANENT_EXCLUSION`은 별도 사유로 기록한다. PIT·partition·manifest/hash의
구조 오류는 gate integrity 오류로 승격해 staging을 중단한다.

변경은 진입 허가에만 한정한다. Loss Guard, PROGRESSED, Exit3/Exit4, 독립
재진입과 다음 거래일 시가 체결 등 V2의 position lifecycle은 그대로 쓴다.
기존 보유와 과거 거래에는 필터를 소급 적용하지 않는다.

## 거래 계보와 cutover

| 실제 entry signal date | 거래 ID와 동작 |
|---|---|
| `< effective_signal_date` | V2 ID와 동결된 V2 lifecycle 유지. 체결일이 cutover 뒤여도 V2다. |
| `>= effective_signal_date` | 새 gate 통과 거래만 Alignment 500B ID를 기록한다. |

cutover 전에 열린 V2 거래는 V2 진입 ID와 기존 V2 청산 규칙을 유지한다. 거래별
`entry_signal_date`, `strategy_id`, `entry_strategy_id`, `exit_strategy_id`를
보존한다. 현재 FAST 섹션의 top-level ID는 그 조회일의 활성 버전이고, 거래 이력
ID는 각 거래의 진입 신호일에 따른다.

## 운영 설정과 rollback

`artifacts/patterns/pattern_a_fast/production/alignment_mcap_500b_operational_config.json`
은 명시적 토글이다. 현재 운영 값은 비활성 및 `PENDING_USER_APPROVAL`이다.
enabled를 켜려면 사용자 승인, 유효한 정확한 신호일, operational activation
승인 값이 모두 필요하다. 테스트에서는 운영 설정과 분리된 고정 가상 날짜를 쓴다.

실제 전환 전에는 shadow staging에서 source hash, exact PIT identity, 500B
경계, 월봉 가용성, report/simulator/action/monitor 일치와 기존 V2 golden을
확인해야 한다. 운영 적용 구간은
`artifacts/patterns/pattern_a_fast/production/alignment_mcap_500b_activation_history.json`
에 append-only로 기록한다. 시작일은 포함하고 `rollback_effective_signal_date`는
V2 복귀일로 제외한다. 각 구간에는 승인 상태와 참조를 보존한다. 현재 enabled
설정은 원장의 유일한 열린 구간과 시작일이 일치해야 하며, 비활성 설정에는 열린
구간이 없어야 한다. 모순되면 재생과 발행을 fail-closed 한다.

rollback 뒤에도 과거 승인 구간의 동일한 alignment·정확 PIT 시총 gate와 V2
lifecycle을 재생한다. rollback일 이후 신규 신호만 V2로 진입한다. 요청일이
rollback 뒤면 FAST top-level ID는 V2이고, monitor의 한 FAST 행은 과거 개선판
거래와 신규 V2 거래를 함께 보존한다. 거래 ID, 순서, 신호·체결일, OPEN/EXIT,
손익 및 진입·청산 전략 ID가 원장 기준과 다르면 추정으로 복구하지 않고 중단한다.
초기 원장은 `intervals: []`이며 현재 운영 설정은 계속 비활성이다. 테스트는
운영 설정과 분리된 임시 원장만 사용한다.

보조 runner의 1조원 threshold는 이 전략의 운영 근거가 아니며 수정하지 않는다.
공식 다섯 기간은 과거 비교 자료다. P2-1에서 총수익률은 31.1454%로 CONTROL의
40.9378%보다 낮았고 CAGR도 6.3564% 대 8.1115%였다. 후보의 최악 단일 거래는
모든 기간에서 CONTROL보다 더 낮은 -44.3903%였다. NAV는 관측치로 보고하고
완전 청산 성과로 표현하지 않는다. P2-1과 P3-1 기간은 P2-2에 포함되는 등
기간이 겹치므로 다섯 개 독립 표본으로 보지 않는다.
