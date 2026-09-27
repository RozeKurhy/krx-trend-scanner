# KRX Pattern B × Pattern A 진입 필터 단순 백테스트 V01

최종 판정: `PATTERN_B_PATTERN_A_ENTRY_FILTER_MIXED`

## 핵심 비교

| 전략 | 후보/필터통과 | 체결 | 실현 | 미청산 | 중앙 gross | 승률 | +50% | -30% 이하 | -50% 이하 | 미청산 -30% | DEEP 도달 | 평균/중앙 보유 KRX 세션 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| CONTROL | 20,076/20,076 | 13,910 | 12,454 | 1,456 | 7.6% | 72.5% | 608 (4.9%) | 657 (5.3%) | 234 (1.9%) | 397 (32.9%) | 4,416 (31.7%) | 179.7회/81.0회 |
| TRANSITION | 1,478/1,478 | 1,467 | 1,384 | 83 | 6.7% | 73.1% | 41 (3.0%) | 58 (4.2%) | 18 (1.3%) | 33 (55.9%) | 321 (21.9%) | 157.1회/60.0회 |
| PROGRESSED | 835/835 | 832 | 746 | 86 | 11.5% | 76.4% | 45 (6.0%) | 53 (7.1%) | 21 (2.8%) | 30 (43.5%) | 183 (22.0%) | 193.8회/57.0회 |

실현 수익률 분모는 realized 거래, 미청산 수익률 분모는 cutoff 종가로 정확히 평가된 포지션이야. 수익률은 gross 기준이고, 같은 비용 계약의 매수·매도 수수료/슬리피지/역사 매도세 반영 결과도 summary와 원장에 별도 보존했어.

## 미청산과 DEEP 악화

- **CONTROL**: cutoff 정확 평가 1,205건, 미해결 251건; 미청산 평균/중앙 -20.2%/-13.2%, -30% 이하 397 (32.9%), -50% 이하 231 (19.2%); 현재 B 상태: DEEP_DEPRESSED 411, DEPRESSED 1,034, EXTREME_OVERHEATED 3, OVERHEATED 8. 보유 중 DEEP 4,416건, 그중 실현 승률 35.8%, 실현 평균/중앙 -6.0%/-7.0%, 평균/중앙 MAE -44.2%/-40.8%.
- **TRANSITION**: cutoff 정확 평가 59건, 미해결 24건; 미청산 평균/중앙 -33.2%/-34.5%, -30% 이하 33 (55.9%), -50% 이하 17 (28.8%); 현재 B 상태: DEEP_DEPRESSED 32, DEPRESSED 51. 보유 중 DEEP 321건, 그중 실현 승률 29.9%, 실현 평균/중앙 -8.6%/-11.4%, 평균/중앙 MAE -49.9%/-47.7%.
- **PROGRESSED**: cutoff 정확 평가 69건, 미해결 17건; 미청산 평균/중앙 -27.7%/-21.4%, -30% 이하 30 (43.5%), -50% 이하 25 (36.2%); 현재 B 상태: DEEP_DEPRESSED 29, DEPRESSED 55, OVERHEATED 2. 보유 중 DEEP 183건, 그중 실현 승률 17.7%, 실현 평균/중앙 -20.9%/-20.5%, 평균/중앙 MAE -61.7%/-61.9%.

## 연도별 반복성

연도별 전체 수치는 `annual_entry_year_stats.csv`에 있고, 아래는 후보별 중앙 gross 수익률이 CONTROL보다 높았던 비교 연도 수야.
- **TRANSITION**: 비교 가능 14개 연도 중 중앙값 개선 2개; 판정 `MIXED`.
- **PROGRESSED**: 비교 가능 14개 연도 중 중앙값 개선 12개; 판정 `MIXED`.

## 시점·실행 검증

- CONTROL 원장은 `5dcfe79f40800ed8ac17558bad6dc600a91fd653` 기준 커밋의 고정 산출물과 해시/행 수/상태 수/성과 요약을 대조했고 재실행하지 않았어.
- 모든 raw Pattern B 신호 20,076건이 exact entry-date Pattern A linkage와 1:1 대응해.
- TEST A/B는 각자의 exact Stage 신호만 독립 상태머신에 넣었고 CONTROL 거래 사후 필터링은 하지 않았어.
- Pattern A 요청일과 진입 신호일 일치, no-lookahead, 체결은 다음 정확 KRX 시가, 보유 중 DEEP 계속 보유, 최초 NORMAL 후 다음 합법 시가 청산, 동일 ISU 중복 보유 0을 검사했어.
- lifecycle 직접 검수는 각 TEST에서 무작위 20건씩 수행했어. 상세는 `lifecycle_spot_checks.csv`.
- Pattern B 상태 관측 프론티어는 2026-08-31; cutoff 2026-09-21의 9월 미완성 상태는 추정하지 않았어.
- 비용 계약: 매수/매도 수수료 0.015%씩, 매수 슬리피지 +0.10%, 매도 슬리피지 -0.10%, 기존 역사 매도세율표.

## 결론

- 최종 판정: `PATTERN_B_PATTERN_A_ENTRY_FILTER_MIXED`.
- Pattern A 진입 필터가 기존 Pattern B 순수 전략보다 실질적으로 나은가? **전체적으로는 아직 아니야.** PROGRESSED의 실현 수익성은 높아졌지만 실현·미청산·DEEP 손실 꼬리가 악화됐고, TRANSITION도 미청산 손실이 더 컸어. 그래서 판정은 MIXED야.
- 다음 단계로 넘길 단일 후보가 있는가? **PROGRESSED**를 위험 검증 단계에 한해 추천해. 미청산·DEEP 손실 꼬리가 악화돼 채택 승격 뜻은 아니고, 후속 작업은 별도 지시가 있어야 시작해.

## 파일

- `control_vs_tests.csv`: CONTROL/TRANSITION/PROGRESSED 통합 비교.
- `transition_trade_ledger.csv`, `progressed_trade_ledger.csv`: 독립 TEST 원장.
- `transition_open_positions.csv`, `progressed_open_positions.csv`: TEST 미청산 목록.
- `transition_entry_signal_ledger.csv`, `progressed_entry_signal_ledger.csv`: 필터 통과 신호 및 억제/체결 상태.
- `signal_stage_filter_audit.csv`: 전체 raw 신호의 exact Pattern A stage와 필터 통과 여부.
- `deep_depressed_analysis.csv`, `annual_entry_year_stats.csv`, `open_position_state_distribution.csv`, `lifecycle_spot_checks.csv`, `summary.json`, `metadata.json`.
