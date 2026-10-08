# FAST Core V2 P2-1 단순 백테스트

| 레벨 | 개수 | 내용 |
|---|---:|---|
| CRITICAL | 0 | worker·데이터·무결성의 치명적 오류 없음; 후처리 예외는 MAJOR에 기록 |
| MAJOR | 1 | 공용 runner cleanup 예외 1건; 세 replay는 2451/2451·worker 오류 0건으로 완료됐고 저장 산출물 검증으로 복구했어 |
| MINOR | 1 | 포트폴리오 equity curve/MDD는 지시 범위 밖이므로 계산하지 않음 |

## 범위와 입력

- 기간: 2021-01-04–2025-05-30; execution support: 2025-06-02. cutoff 뒤 신규 진입은 제외했어.
- CONTROL, MA60 fail-closed, `signal_day_close > prior completed month MA20 > prior completed month MA60`을 같은 frozen identity/PIT, lifecycle, Repository V2, 비용, cutoff 계약으로 새 replay했어.
- 이전 P2-1, P1, P3-2 성과 파일은 입력 또는 비교에 사용하지 않았어. frozen merged PIT/calendar와 그 authority에 결합된 survivor identity roster만 입력 권한으로 썼어.
- 매수/매도 수수료 각 0.015%, 매수/매도 슬리피지 각 0.10%, 거래세 제외. 수익률은 비용 반영 net 기준이야.
- 단순 거래 단위 결과라 portfolio MDD와 자본/동시 보유 제약은 산출하지 않았어.

## 전략별 핵심 지표

| 전략 | 거래 | 실현 | 생애주기 정산 | cutoff 미종료 | 실현 승률 % | terminal 양수율 % | terminal 평균 % | terminal 중앙 % | realized 평균 % | realized 중앙 % | 보유 평균 일 | 보유 중앙 일 | PROGRESSED 건수/율 | Loss Guard 건수/율 | 최대 수익 % | 최대 손실 % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CONTROL | 355 | 291 | 0 | 64 (18.03%) | 26.12 | 36.62 | 4.28 | -15.09 | 0.03 | -15.50 | 172.67 | 95.00 | 118 (33.24%) | 197 (55.49%) | 210.28 | -49.71 |
| MA60 | 291 | 239 | 0 | 52 (17.87%) | 27.62 | 37.46 | 5.26 | -14.97 | 1.31 | -15.44 | 154.46 | 79.00 | 100 (34.36%) | 159 (54.64%) | 210.28 | -49.71 |
| ALIGNMENT | 146 | 116 | 0 | 30 (20.55%) | 28.45 | 41.10 | 6.72 | -14.72 | 2.72 | -15.42 | 140.29 | 81.50 | 44 (30.14%) | 80 (54.79%) | 190.41 | -49.71 |

## 대형 승리·손실

| 전략 | 구간 | 건수 | 전체 거래 대비 % |
|---|---|---:|---:|
| CONTROL | >=+20% | 83 | 23.38 |
| CONTROL | >=+50% | 38 | 10.70 |
| CONTROL | >=+100% | 11 | 3.10 |
| CONTROL | <=-10% | 215 | 60.56 |
| CONTROL | <=-15% | 183 | 51.55 |
| CONTROL | <=-20% | 22 | 6.20 |
| CONTROL | <=-30% | 8 | 2.25 |
| MA60 | >=+20% | 75 | 25.77 |
| MA60 | >=+50% | 31 | 10.65 |
| MA60 | >=+100% | 11 | 3.78 |
| MA60 | <=-10% | 172 | 59.11 |
| MA60 | <=-15% | 144 | 49.48 |
| MA60 | <=-20% | 18 | 6.19 |
| MA60 | <=-30% | 7 | 2.41 |
| ALIGNMENT | >=+20% | 41 | 28.08 |
| ALIGNMENT | >=+50% | 17 | 11.64 |
| ALIGNMENT | >=+100% | 6 | 4.11 |
| ALIGNMENT | <=-10% | 84 | 57.53 |
| ALIGNMENT | <=-15% | 70 | 47.95 |
| ALIGNMENT | <=-20% | 11 | 7.53 |
| ALIGNMENT | <=-30% | 4 | 2.74 |

## CONTROL 대비 변화

| 후보 | 거래수 Δ | 거래 감소 % | 승률 Δ %p | terminal 평균 Δ %p | terminal 중앙 Δ %p | realized 평균 Δ %p | realized 중앙 Δ %p | 평균 보유 Δ 일 | 중앙 보유 Δ 일 | Loss Guard Δ %p | PROGRESSED Δ %p | 최대 수익 Δ %p | 최대 손실 Δ %p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| MA60 | -64 | 18.03 | 1.50 | 0.98 | 0.13 | 1.28 | 0.06 | -18.20 | -16.00 | -0.85 | 1.12 | 0.00 | 0.00 |
| ALIGNMENT | -209 | 58.87 | 2.33 | 2.44 | 0.37 | 2.69 | 0.08 | -32.37 | -13.50 | -0.70 | -3.10 | -19.87 | 0.00 |

### 대형 승리·손실 비율 변화

| 후보 | 구간 | 건수 Δ | 전체 거래 대비 비율 Δ %p |
|---|---|---:|---:|
| MA60 | >=+20% | -8 | 2.39 |
| MA60 | >=+50% | -7 | -0.05 |
| MA60 | >=+100% | 0 | 0.68 |
| MA60 | <=-10% | -43 | -1.46 |
| MA60 | <=-15% | -39 | -2.06 |
| MA60 | <=-20% | -4 | -0.01 |
| MA60 | <=-30% | -1 | 0.15 |
| ALIGNMENT | >=+20% | -42 | 4.70 |
| ALIGNMENT | >=+50% | -21 | 0.94 |
| ALIGNMENT | >=+100% | -5 | 1.01 |
| ALIGNMENT | <=-10% | -131 | -3.03 |
| ALIGNMENT | <=-15% | -113 | -3.60 |
| ALIGNMENT | <=-20% | -11 | 1.34 |
| ALIGNMENT | <=-30% | -4 | 0.49 |

## Exit reason 분포

| 전략 | exit_type | 건수 |
|---|---|---:|
| CONTROL | LOSS_GUARD_CLOSE_LE_NEG_15 | 197 |
| CONTROL | EXIT4_SCORE_DRAWDOWN_GE_15 | 86 |
| CONTROL | NO_PROGRESSED_BEFORE_CUTOFF | 40 |
| CONTROL | NO_EXIT_BEFORE_CUTOFF | 24 |
| CONTROL | EXIT3_PROGRESSED_TO_TRANSITION | 7 |
| CONTROL | EXIT3_PROGRESSED_TO_WEAK | 1 |
| MA60 | LOSS_GUARD_CLOSE_LE_NEG_15 | 159 |
| MA60 | EXIT4_SCORE_DRAWDOWN_GE_15 | 74 |
| MA60 | NO_PROGRESSED_BEFORE_CUTOFF | 32 |
| MA60 | NO_EXIT_BEFORE_CUTOFF | 20 |
| MA60 | EXIT3_PROGRESSED_TO_TRANSITION | 5 |
| MA60 | EXIT3_PROGRESSED_TO_WEAK | 1 |
| ALIGNMENT | LOSS_GUARD_CLOSE_LE_NEG_15 | 80 |
| ALIGNMENT | EXIT4_SCORE_DRAWDOWN_GE_15 | 34 |
| ALIGNMENT | NO_PROGRESSED_BEFORE_CUTOFF | 22 |
| ALIGNMENT | NO_EXIT_BEFORE_CUTOFF | 8 |
| ALIGNMENT | EXIT3_PROGRESSED_TO_TRANSITION | 1 |
| ALIGNMENT | EXIT3_PROGRESSED_TO_WEAK | 1 |

## PROGRESSED 집계

`first_progressed_effective_trading_date`가 non-null인 원시 수와 날짜 경계를 적용한 authoritative 수를 분리했어. `p2_1_strategy_metrics.csv`는 원시 non-null 수(비권위), `p2_1_strategy_metrics_reconciled.csv`는 날짜 검증 후 공식 집계야.


| 전략 | non-null 원시 수(비권위) | 날짜 경계 적용 수(권위) | 차이 |
|---|---:|---:|---:|
| CONTROL | 167 | 118 | 49 |
| MA60 | 145 | 100 | 45 |
| ALIGNMENT | 63 | 44 | 19 | 실현 거래는 entry execution ≤ event ≤ exit signal, cutoff 미종료는 entry execution ≤ event ≤ 2025-05-30 범위로 검증했어. LIFECYCLE_SETTLED가 있으면 정산일을 상한으로 별도 반영했고 건수도 분리했어.


## 실행 정리 예외와 산출물 복구

공용 runner는 CONTROL·MA60·Alignment 결과 CSV를 모두 저장한 뒤 마지막 메모리 정리에서 이미 삭제된 `ma60_result`를 다시 삭제하려다 `UnboundLocalError`가 났어. 세 worker 로그는 모두 2451/2451, errors=0이었어. 자동 재실행은 하지 않았고, 기존 ledger·signal audit·시총 audit만으로 parity, 필터, 수익 재계산, 가격/PIT 해시를 독립 검증해 최종 보고서를 만들었어. 원본 예외는 `p2_1_replay_cleanup_exception.json`에 보존했어.

## 검증과 provenance

- Worker: 10; worker error: 0; 처리 ticker: 2451; P2-1 identity key: 2451; PIT segment: 2451.
- Trade key 중복: 0; candidate accepted signal↔trade parity: True; net terminal 재계산 mismatch: 0.
- MA60 필터·fail-closed: True; Alignment 식·fail-closed: True; cutoff 신규 진입 위반: 0.
- Frozen PIT/calendar/survivor/source hash와 adjusted/raw partition 검증: PASS; 네트워크 호출: 0; 완전한 결과만 최종 보고에 사용했어.
- Frozen PIT SHA-256: `6747f26368369bc2ff5d20d695daed702c577bab34dd79640d41fbc862950bd1`; calendar SHA-256: `cf9560da17674c866c57906b4b8e21ce956a0e7a0a9a3ccd1779d1a83a7111c2`; survivor identity authority SHA-256: `313bca3d5dbc28672cb505c18b61af40a9b4b827c11af56b30f45160cdba1506`.
- P1 성과 방향 비교는 해당 성과 자료를 읽지 말라는 이번 실행 경계를 지켜 생략했어. P1/P3 성과와 합쳐 채택 판단을 내리지 않았어.

## 산출물

- 결과 폴더에는 raw/reconciled metrics, 세 trade ledger, execution audit, provenance가 있어. MKTCAP·MA60·Alignment·price audit는 gzip 저장했고 원본 SHA-256과 압축 해제 SHA-256이 일치해.
- 결과 토큰: `FAST_CORE_V2_P2_1_MA60_VS_BULLISH_ALIGNMENT_SIMPLE_BACKTEST_V01_PASS`
