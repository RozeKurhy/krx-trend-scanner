# Julia V00 ETF 전용 공식 전략 채택 심사 V01

- 판정: **OFFICIAL_STRATEGY_ADOPTED**
- 심사일: 2026-09-30
- 기준 HEAD: 8db83df396c9469fb7f169431822272afea5d4eb
- 범위: JULIA_STRATEGY_V00 / 공식 ETF 36 / 초기자본 250,000,000원 / 종목당 한도 15,000,000원
- 기준: 현행 공식 A~E 절대 기준, 5개 표준 window. V2 상대 MDD 기준은 적용하지 않았어.

## 공식 A~E gate

| Window | A 무결성 | B 비용 | C 수익성 | D MDD | E 결과 유효성 |
|---|---|---|---|---|---|
| P1 | PASS | PASS | PASS | PASS | PASS |
| P2-1 | PASS | PASS | PASS | PASS | PASS |
| P2-2 | PASS | PASS | PASS | PASS | PASS |
| P3-1 | PASS | PASS | PASS | PASS | PASS |
| P3-2 | PASS | PASS | PASS | PASS | PASS |

A~E 총 25개 gate가 모두 PASS야. 채택 판정은 15M 주 시나리오로 했고 CASH_SKIP과 25M 결과는 진단 전용이야.

## 15M 공식 시나리오 성과

| Window | Final equity | Total Return | CAGR | MDD / 기준 | MDD peak → trough → recovery | 평가 coverage |
|---|---:|---:|---:|---:|---|---:|
| P1 | 545,580,535원 | 118.23% | 6.36% | -30.12% / ≥ -55% | 2018-01-29 → 2020-03-23 → 2020-12-02 | 100.0% (3,107/3,107) |
| P2-1 | 281,217,632원 | 12.49% | 2.71% | -19.26% / ≥ -40% | 2021-06-07 → 2022-10-13 → 2024-10-29 | 100.0% (1,082/1,082) |
| P2-2 | 417,987,183원 | 67.19% | 9.51% | -19.26% / ≥ -40% | 2021-06-07 → 2022-10-13 → 2024-10-29 | 100.0% (1,387/1,387) |
| P3-1 | 262,766,201원 | 5.11% | 1.47% | -14.62% / ≥ -40% | 2023-07-25 → 2023-10-31 → 2024-03-21 | 100.0% (834/834) |
| P3-2 | 406,003,565원 | 62.40% | 10.97% | -14.62% / ≥ -40% | 2023-07-25 → 2023-10-31 → 2024-03-21 | 100.0% (1,139/1,139) |

다섯 window 모두 Total Return과 CAGR이 양수야. MDD를 저장된 equity curve에서 다시 계산해 요약값과 일치시켰어. coverage 분모는 기준 cutoff까지의 표준 거래일이고 support date는 cutoff 이전 신호의 체결 지원일이야.

## 15M 운용·집중도 진단

| Window | 후보/체결 | CASH_SKIP 수·비율 | 실현/cutoff 미청산 | cutoff 미청산 비중 | 평균/최대 자본 활용 | 평균/최대 동시 보유 | 평균/중앙값/P90/최대 보유 세션 | Turnover |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| P1 | 52/45 | 7 (13.46%) | 29/16 | 35.56% | 51.11%/99.78% | 10.87/24 | 751.2/780.0/1365.8/2,086 | 5.45x |
| P2-1 | 38/27 | 11 (28.95%) | 9/18 | 66.67% | 80.60%/98.83% | 14.74/18 | 591.0/565.0/1046.0/1,072 | 2.32x |
| P2-2 | 45/32 | 13 (28.89%) | 18/14 | 43.75% | 80.45%/98.83% | 15.24/19 | 661.1/667.5/1323.0/1,377 | 3.66x |
| P3-1 | 30/19 | 11 (36.67%) | 2/17 | 89.47% | 71.40%/96.21% | 12.20/17 | 535.7/555.0/796.0/829 | 1.33x |
| P3-2 | 37/24 | 13 (35.14%) | 11/13 | 54.17% | 75.51%/99.81% | 13.42/18 | 637.2/775.0/1049.3/1,134 | 2.66x |

CASH_SKIP 분모는 사전 고정 certified signal ledger의 진입 후보 수고 모든 skip은 full-position 현금 부족이야. 공통 기준상 CASH_SKIP은 PASS/FAIL gate가 아니야. cutoff 미청산 비중은 체결된 포지션 중 기준 cutoff에 미청산인 비중이야. 평균 보유는 약 536~751 거래일이고 P90은 약 796~1,366 거래일이어서 자본이 오래 묶이는 약점이 있어.

| Window | MARKET_INDEX 손익 비중 | SECTOR_INDEX 손익 비중 | COMMODITY_RESOURCE 손익 비중 | 상위 1/3/5 ETF 순손익 기여 |
|---|---:|---:|---:|---:|
| P1 | 22.12% | 59.93% | 17.95% | 14.97%/34.20%/49.65% |
| P2-1 | 23.97% | 33.76% | 42.27% | 31.99%/82.64%/123.18% |
| P2-2 | 13.22% | 61.38% | 25.40% | 16.96%/43.87%/67.37% |
| P3-1 | 66.48% | -18.98% | 52.50% | 69.38%/176.64%/242.05% |
| P3-2 | 23.38% | 53.43% | 23.19% | 15.58%/44.55%/67.04% |

상위 ETF 비중은 순손익을 분모로 하므로 손실 종목의 상쇄로 100%를 넘을 수 있어. 특히 P3-1은 섹터 순손익이 음수라 top-3/top-5 기여율이 100%를 넘었어. 종목 제거 또는 재최적화는 하지 않았어.

## 25M sizing 민감도

| Window | Total Return | CAGR | MDD | CASH_SKIP | 평균 자본 활용 |
|---|---:|---:|---:|---:|---:|
| P1 | 111.90% | 6.11% | -40.98% | 21 (40.38%) | 59.48% |
| P2-1 | 11.81% | 2.56% | -26.73% | 20 (52.63%) | 91.10% |
| P2-2 | 62.60% | 8.97% | -26.73% | 23 (51.11%) | 87.35% |
| P3-1 | 11.99% | 3.38% | -14.94% | 17 (56.67%) | 81.68% |
| P3-2 | 66.39% | 11.55% | -14.94% | 20 (54.05%) | 83.60% |

25M 결과는 진단 전용이고 공식 판정에는 반영하지 않았어.

## 유니버스·가격·비용·원장 무결성

- 현행 repository universe와 ETF36 정확히 일치: 36/36, 그룹 MARKET 12 / SECTOR 19 / COMMODITY 5, 474800 제외, 중복 0.
- Effective span은 180행, 각 window당 36개를 보존했어. P2-1/P3-1의 449450, 453810은 고정 strategy-ready 날짜가 기간 종료 뒤라 평가 불가였고 ETF universe에서 제외하지 않았어.
- 기존 certified ledger 505건. 현실 포트폴리오 검증 PASS, worker 10개, 기존 실행 1회 기록. 이번 재심사에서는 replay·새 신호 생성·시장 재조회 없음.
- 양쪽 수수료 각 0.015%, 양쪽 슬리피지 각 0.10%, 공식 성과의 거래세 0.00% 제외. 실제 원장 가격/수수료 mismatch는 0, non-zero sell tax도 0.
- Entry/realized-exit/open-terminal 가격 mismatch는 0/0/0; holding close missing/invalid 0; synthetic/forward-fill 0; invalid OHLC 0.
- 일별 equity 날짜 누락 0, 음수 현금 0, leverage 0, duplicate identity 0, post-cutoff 진입 0, execution-support 위반 0. 평균·최대 자본 활용도와 평균·최대 동시 보유를 curve에서 다시 집계했고, 보유기간 평균·중앙값·최대도 체결 원장에서 재계산해 저장 요약과 일치시켰어. realized와 cutoff terminal 손익도 final equity에 재조정됐어.
- 기존 실행에서 기록한 입력 9개 SHA-256은 전부 현재 파일과 일치해. 세부 목록은 source_hashes.json에 있어.

### 보고 표기 불일치 — MINOR

기존 closure summary의 inline check map은 validation_replay_contract=false라고 적었지만, 현재 validation.json은 true이고 validator finalization도 errors 0으로 PASS야. finalizer가 기존 inline map을 다시 쓰지 않는 것으로 확인했어. 최신 구조화 JSON/finalizer를 authority로 사용했고 certified source artifact는 수정하지 않았어.

## 공식 상태 반영

- 일반 종목 상태: NOT ADOPTED / RETIRED AS GENERAL-STOCK OFFICIAL STRATEGY 유지.
- ETF 상태: OFFICIAL_STRATEGY_ADOPTED — ETF ONLY; 적용 universe는 OFFICIAL ETF 36.
- A FAST Core V2가 계속 기본 전략·CONTROL이고 B Select Core V1은 변경하지 않아.
- 공식 채택은 자동 주문 승인이나 종목 리포트/UI 연결을 의미하지 않아.

## 범위와 근거

- 새로 재구성한 파일은 report.md, validation.json, source_hashes.json이야. 규칙·과거 archive·certified evidence는 수정하지 않았어.
- 이번 작업은 저장된 CSV/JSON만으로 지표 집계, 해시, coverage, 원장 정산을 대조했어. full pytest, strategy replay, tuning, sizing sweep은 실행하지 않았어.
- gate별 상세 증거는 validation.json, source/input/output SHA-256은 source_hashes.json에 있어.
