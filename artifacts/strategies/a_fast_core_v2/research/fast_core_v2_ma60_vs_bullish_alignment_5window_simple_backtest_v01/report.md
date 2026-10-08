# FAST_CORE_V2_MA60_VS_BULLISH_ALIGNMENT_5WINDOW_SIMPLE_BACKTEST_V01

**상태: CHECK_REQUIRED**

## 결과 범위

5개 기간의 3전략 비교는 완결되지 않았어. P3-2는 exact-match가 확인된 저장 결과를 재사용했고, P1 CONTROL은 2,539개 종목 처리를 완료했어. P1 MA60은 2,539개 순회를 마쳤지만 worker 오류 1건 때문에 fail-closed 검증에서 중단됐어. 그 결과 P1 MA60 완전 원장/지표, P1 ALIGNMENT, P2-1, P2-2, P3-1 결과는 없어.

실패 세부 기록은 `failure.json`에 보존했어. 자동 재실행은 하지 않았어.

## 완료된 단독/재사용 결과

P1 CONTROL은 단독 산출물이므로 후보와 비교하지 않아.

| 기간/전략 | 거래 수 | 실현 | cutoff 미종료 | 순 terminal 평균 | 순 terminal 중앙값 | 실현 승률 | Loss Guard 비율 | MDD |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| P1 CONTROL | 826 | 783 | 43 | 9.50% | -15.37% | 28.35% | 63.44% | 산출 불가 |
| P3-2 CONTROL | 405 | 369 | 36 | 17.14% | -14.74% | 32.79% | 57.04% | 산출 불가 |
| P3-2 MA60 | 337 | 305 | 32 | 18.38% | -14.55% | 36.07% | 54.30% | 산출 불가 |
| P3-2 ALIGNMENT | 179 | 165 | 14 | 22.80% | -9.38% | 44.85% | 48.60% | 산출 불가 |

P3-2 단일 기간에서 MA60은 CONTROL 대비 terminal 평균 +1.24%p, ALIGNMENT은 +5.66%p야. 이 관찰만으로 여러 기간의 반복성을 판단하거나 전략 채택 결정을 내릴 수 없어.

## 중단 원인

P1 MA60 재생에서 `005300` / `KR7005300009` / KOSPI 종목의 적격 NEG40 날짜 **2017-11-02**에 Pattern A stage가 `UNAVAILABLE`이어서 공통 V2 엔진이 예외를 발생시켰어. 해당 예외를 무시하거나 대체 stage를 넣으면 기존 exit lifecycle이 달라지므로 원래 fail-closed 동작을 유지했어. 오류가 난 worker의 거래 결과는 완전한 MA60 원장에 포함할 수 없어.

- P1 CONTROL: worker 10, 2,539/2,539, 거래 826건, MCAP 감사 19,770건, worker 오류 0건
- P1 MA60: worker 10, 2,539/2,539 순회, 성공 worker의 진행 출력상 614 trade rows, worker 오류 1건. **614는 완전 원장/성과 수치가 아니야.**
- P1 ALIGNMENT, P2-1, P2-2, P3-1: 실행하지 않음
- P3-2: 저장된 CONTROL 405건 / MA60 337건 / ALIGNMENT 179건을 재사용

## 계약과 한계

매수/매도 수수료는 각각 0.015%, 매수/매도 슬리피지는 각각 0.1%를 적용했고 거래세는 반영하지 않았어. portfolio/현금 제약은 적용하지 않았어. 기존 simple trade-level 산출물에는 공통 equity series가 없어 MDD는 `NOT_AVAILABLE_IN_EXISTING_SIMPLE_TRADE_LEVEL_REPLAY`로 남겼어.

전략 채택이나 버전 승격 판단은 내리지 않았어. 상세 partial 지표는 `metrics_by_window_partial.csv`, threshold 집계는 `threshold_summary_partial.csv`, 실행 상태와 출처 해시는 각각 `window_execution_status.csv`, `partial_provenance.json`에 있어.

## 최종 결과 토큰

`FAST_CORE_V2_MA60_VS_BULLISH_ALIGNMENT_5WINDOW_SIMPLE_BACKTEST_V01_CHECK_REQUIRED`
