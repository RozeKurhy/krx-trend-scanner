# A FAST Core V2 최근 1Q 영업이익 20억 5-window 연구 V01

## 검수 수준

| 레벨 | 개수 |
|---|---:|
| CRITICAL | 0 |
| MAJOR | 2 |
| MINOR | 14469 |

## 5개 표준 기간 CONTROL vs TEST20 PRIMARY 비교

| 기간 | 그룹 | 거래 수 | TEST 보존율 | 평균 % | 중앙값 % | 승률 % | 손실률 % | >=50% 건수/비율 | 최악 % | p10 % |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P1 | CONTROL | 4589 | — | 9.42 | -15.29 | 30.01 | 69.88 | 692 / 15.08 | -95.94 | -19.29 |
| P1 | TEST20 | 1130 | 18.20 | 10.58 | -14.95 | 34.69 | 65.04 | 175 / 15.49 | -74.64 | -18.21 |
| P2-1 | CONTROL | 1667 | — | 3.88 | -15.19 | 31.97 | 67.97 | 175 / 10.50 | -72.53 | -18.90 |
| P2-1 | TEST20 | 769 | 38.21 | 2.94 | -15.13 | 32.90 | 66.97 | 73 / 9.49 | -72.53 | -18.22 |
| P2-2 | CONTROL | 2206 | — | 8.08 | -15.18 | 30.51 | 69.36 | 310 / 14.05 | -82.04 | -18.66 |
| P2-2 | TEST20 | 1052 | 39.26 | 9.36 | -15.04 | 33.17 | 66.54 | 151 / 14.35 | -74.64 | -18.17 |
| P3-1 | CONTROL | 1069 | — | 0.41 | -15.30 | 28.81 | 71.09 | 96 / 8.98 | -65.06 | -18.92 |
| P3-1 | TEST20 | 547 | 44.25 | 0.41 | -15.21 | 31.44 | 68.37 | 50 / 9.14 | -57.24 | -18.19 |
| P3-2 | CONTROL | 1644 | — | 6.56 | -15.26 | 27.92 | 71.90 | 231 / 14.05 | -82.04 | -18.57 |
| P3-2 | TEST20 | 841 | 43.37 | 8.41 | -15.14 | 31.99 | 67.66 | 126 / 14.98 | -67.33 | -18.14 |

## 1. PIT coverage / PASS·FAIL·UNAVAILABLE

- AFAST 조건을 만족하고 entry 날짜·정보 날짜·익일 체결일의 PIT COMMON 검사를 통과한 원시 신호: 24007건.
- 전체 PIT 판정: PASS 4992건, FAIL 4546건, UNAVAILABLE 14469건.
- 재사용 판정기의 BASIS_OR_CURRENCY_MISMATCH 15건은 비교 불가로 보고 UNAVAILABLE에 포함해 진입을 차단했다. 원본 status는 PIT 평가 파일과 trade ledger에 보존했다.
- PIT audit: future disclosure 0건, same-quarter YoY mismatch 0건, rule arithmetic mismatch 0건, YoY contract mismatch 0건, prior-quarter fallback 0건.
- UNAVAILABLE은 진입 불가로 fail-closed 처리했다.

| 기간 | PASS | FAIL | UNAVAILABLE | CONTROL 실제 진입 시도 | TEST20 실제 진입 시도 |
|---|---:|---:|---:|---:|---:|
| P1 | 4992 | 4546 | 14469 | 4589 | 19370 |
| P2-1 | 3270 | 2932 | 1000 | 1667 | 4326 |
| P2-2 | 4644 | 4256 | 1187 | 2206 | 5833 |
| P3-1 | 2375 | 1745 | 682 | 1069 | 2648 |
| P3-2 | 3749 | 3069 | 869 | 1644 | 4202 |

## 2. CONTROL의 >=50% winner 보존

| 기간 | CONTROL winner | TEST20 보존 | 보존율 |
|---|---:|---:|---:|
| P1 | 692 | 131 | 18.93% |
| P2-1 | 175 | 61 | 34.86% |
| P2-2 | 310 | 127 | 40.97% |
| P3-1 | 96 | 43 | 44.79% |
| P3-2 | 231 | 107 | 46.32% |

## 3. CONTROL 손실 거래 제거

| 기간 | CONTROL 손실 거래 | TEST20에서 제거 | 제거율 |
|---|---:|---:|---:|
| P1 | 3207 | 2659 | 82.91% |
| P2-1 | 1133 | 705 | 62.22% |
| P2-2 | 1530 | 951 | 62.16% |
| P3-1 | 760 | 430 | 56.58% |
| P3-2 | 1182 | 692 | 58.54% |

## 4. 기간별 특이점

- P1: TEST20은 CONTROL과 정확히 같은 진입 키 835건을 보존했고, 별도 진입 295건이 발생했다. 미해결 terminal 수는 0건.
- P2-1: TEST20은 CONTROL과 정확히 같은 진입 키 637건을 보존했고, 별도 진입 132건이 발생했다. 미해결 terminal 수는 0건.
- P2-2: TEST20은 CONTROL과 정확히 같은 진입 키 866건을 보존했고, 별도 진입 186건이 발생했다. 미해결 terminal 수는 0건.
- P3-1: TEST20은 CONTROL과 정확히 같은 진입 키 473건을 보존했고, 별도 진입 74건이 발생했다. 미해결 terminal 수는 0건.
- P3-2: TEST20은 CONTROL과 정확히 같은 진입 키 713건을 보존했고, 별도 진입 128건이 발생했다. 미해결 terminal 수는 0건.

## 5. 전체 해석

이 결과는 A FAST Core V2의 공식 규칙과 lifecycle을 유지하고, entry 시점 PIT 영업이익 조건 하나만 추가한 연구 비교다. 중앙값·승률·손실률·p10은 5개 기간 모두 개선됐지만 평균은 3개 기간만 개선됐고 P2-1은 하락, P3-1은 사실상 보합이다. CONTROL의 >=50% winner 보존은 18.9–46.3%에 그친 반면 CONTROL 손실은 56.6–82.9% 제거됐다. loser-filter 성격은 보이지만 큰 winner도 상당수 제거해 일관 우위로 판정할 수 없다. 공식 전략 변경·승격 결론은 내리지 않는다.

- 시작 HEAD: 6612a3fe3c3586826edc44974451d8ccd0f78d34
- 기존 공식 V2 구현 재현 확인: ACCEPT (783 authority / 783 reproduced trades). 이 parity는 2026-08-14 투자 가능 종목 universe와 legacy raw cache 범위다.
- 기존 공식 원장과 이번 P1은 직접 같은 범위가 아니다: 공식 783건/551종목, 이번 P1 4589건/1693종목. 이번 지시서의 무시총·무거래대금 조건 및 Repository V2 데이터 기준을 우선해 별도 비교했으며, 두 거래 수를 직접 parity로 해석하지 않았다.
- 공식 원장과 P1의 descriptive `(ticker, entry_signal_date)` 교집합은 554건이며, 서로 다른 universe·market data·기간이므로 이 건수도 parity 판정이 아니다.
- PIT authority digest: 24f5e71c90be9adcd981eee7817e8e1b7bc1e8db31d9b071e89f63bee1f6d066.
- Permanent exclusion: 174 identities, 177 COMMON segments; CONTROL/TEST20 동일 적용.
- Market-data source: MarketDataRepositoryV2; signal cutoff 2026-08-31, exit execution support is the next KRX session.
- Local Repository V2 data gaps: 146 ticker identities; see data_availability.csv.
- External requests 0건. 공식 전략 코드와 공식 문서는 변경하지 않았다.
