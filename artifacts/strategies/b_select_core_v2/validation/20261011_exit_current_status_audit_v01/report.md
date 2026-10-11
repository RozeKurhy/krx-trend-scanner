| CRITICAL | MAJOR | MINOR |
|---:|---:|---:|
| 0 | 0 | 0 |

# B Select Core V2 청산 조건·현재 상태 독립 전수 감사 V01

- 최종 판정: **PASS**
- 기준일: requested_as_of **2026-10-11**, 마지막 인증 KRX 거래일 **2026-10-08**
- 감사 방식: 승인 원장과 production status를 읽기 전용으로 두고, Repository V2와 공식 Pattern B 평가기를 직접 호출해 현재 OPEN을 재평가했어.
- 범위 준수: 외부 API, Phase 1~4, scanner/report 재생성, 전략·원장·가격 데이터 수정, 주문 실행은 없었어. 기준일 뒤 가격은 조회하지 않았어.

## 1. 청산 조건 최종 판정

| 평가일 | NORMAL | DEPRESSED | DEEP_DEPRESSED | OVERHEATED | EXTREME_OVERHEATED | UNAVAILABLE | 평가 건수 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2026-10-06 | 0 | 29 | 8 | 0 | 0 | 0 | 37/37 |
| 2026-10-07 | 0 | 29 | 8 | 0 | 0 | 0 | 37/37 |
| 2026-10-08 | 0 | 29 | 8 | 0 | 0 | 0 | 37/37 |

- **매도 조건 충족 0건**이라고 판정해. 세 날짜에 걸친 현재 OPEN 37건은 모두 READY였고 111/111 평가 성공, 판단 불가 0건이야.
- 평가 근거 날짜: 월봉 마지막 날짜 2026-09-30, 주봉 마지막 날짜 2026-10-02. 평가 기준일은 각각 10/06, 10/07, 10/08이며 reason code는 모두 비어 있어.
- EXIT 신호 0종목, pending EXIT 0건, 누락 EXIT 0건, 평가/identity 예외 0건.
- 10/09는 휴장, 10/10–11은 주말로 공식 merged calendar에 없고, 달력 인증 frontier는 10/08이야. 10/08 신호가 있으면 pending이어야 하지만 이날 NORMAL이 없었어. 10/12 가격은 조회하지 않았어.

## 2. OPEN 37개 전수표

수익률은 Repository V2 조정 종가(10/08) ÷ 원장 진입가 − 1로 재계산했어. PUBLIC은 현재 공개 COMMON 1,459개에 포함된 exact identity, HISTORICAL_ONLY는 공개 아이템 밖에서도 canonical OPEN으로 계속 추적되는 identity야.

| 티커 / 회차 | 종목명 | ISU_CD | 시장 | 범위 | 진입 신호 → 시가 체결 | 진입가 | 10/08 종가 | 수익률 | 10/06 | 10/07 | 10/08 | EXIT / 다음 행동 | 원천·검증 |
|---|---|---|---|---|---|---:|---:|---:|---|---|---|---|---|
| 001380 / 3 | SG글로벌 | KR7001380005 | KOSPI | PUBLIC | 2025-04-30 → 2025-05-02 | 4,317.00 | 1,016.00 | -76.47% | DEEP_DEPRESSED | DEEP_DEPRESSED | DEEP_DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 001740 / 1 | SK네트웍스 | KR7001740000 | KOSPI | PUBLIC | 2026-08-31 → 2026-09-01 | 6,570.00 | 6,120.00 | -6.85% | DEPRESSED | DEPRESSED | DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 010820 / 1 | 퍼스텍 | KR7010820009 | KOSPI | PUBLIC | 2026-06-30 → 2026-07-01 | 6,260.00 | 5,780.00 | -7.67% | DEPRESSED | DEPRESSED | DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 011210 / 1 | 현대위아 | KR7011210002 | KOSPI | PUBLIC | 2026-09-30 → 2026-10-01 | 52,800.00 | 51,000.00 | -3.41% | DEPRESSED | DEPRESSED | DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 011690 / 1 | 와이투솔루션 | KR7011690005 | KOSPI | PUBLIC | 2026-06-30 → 2026-07-01 | 3,720.00 | 3,615.00 | -2.82% | DEPRESSED | DEPRESSED | DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 012860 / 1 | 모베이스전자 | KR7012860003 | KOSDAQ | PUBLIC | 2026-06-30 → 2026-07-01 | 2,600.00 | 2,450.00 | -5.77% | DEPRESSED | DEPRESSED | DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 014940 / 1 | 오리엔탈정공 | KR7014940001 | KOSDAQ | PUBLIC | 2026-06-30 → 2026-07-01 | 4,895.00 | 4,300.00 | -12.16% | DEPRESSED | DEPRESSED | DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 017960 / 1 | 한국카본 | KR7017960006 | KOSPI | PUBLIC | 2026-09-30 → 2026-10-01 | 20,350.00 | 19,260.00 | -5.36% | DEPRESSED | DEPRESSED | DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 025620 / 1 | 차AI헬스케어 | KR7025620006 | KOSPI | HISTORICAL_ONLY | 2026-06-30 → 2026-07-01 | 7,090.00 | 5,610.00 | -20.87% | DEPRESSED | DEPRESSED | DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 032350 / 2 | 롯데관광개발 | KR7032350001 | KOSPI | PUBLIC | 2026-09-30 → 2026-10-01 | 11,660.00 | 11,070.00 | -5.06% | DEPRESSED | DEPRESSED | DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 039740 / 2 | 한국정보공학 | KR7039740006 | KOSDAQ | PUBLIC | 2026-06-30 → 2026-07-01 | 3,015.00 | 3,050.00 | +1.16% | DEPRESSED | DEPRESSED | DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 042940 / 1 | 상지건설 | KR7042940007 | KOSDAQ | HISTORICAL_ONLY | 2025-06-30 → 2025-07-01 | 11,660.00 | 5,320.00 | -54.37% | DEEP_DEPRESSED | DEEP_DEPRESSED | DEEP_DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 048410 / 1 | 현대바이오 | KR7048410005 | KOSDAQ | HISTORICAL_ONLY | 2026-06-30 → 2026-07-01 | 8,140.00 | 6,900.00 | -15.23% | DEPRESSED | DEPRESSED | DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 056080 / 2 | 유진로봇 | KR7056080005 | KOSDAQ | HISTORICAL_ONLY | 2026-06-30 → 2026-07-01 | 15,100.00 | 12,690.00 | -15.96% | DEPRESSED | DEPRESSED | DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 064260 / 3 | 다날 | KR7064260003 | KOSDAQ | PUBLIC | 2026-09-30 → 2026-10-01 | 4,340.00 | 4,445.00 | +2.42% | DEPRESSED | DEPRESSED | DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 069640 / 1 | 한세엠케이 | KR7069640001 | KOSPI | HISTORICAL_ONLY | 2021-09-30 → 2021-10-01 | 9,320.00 | 1,353.00 | -85.48% | DEPRESSED | DEPRESSED | DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 075580 / 1 | 세진중공업 | KR7075580001 | KOSPI | PUBLIC | 2026-09-30 → 2026-10-01 | 9,750.00 | 9,310.00 | -4.51% | DEPRESSED | DEPRESSED | DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 077970 / 1 | STX엔진 | KR7077970002 | KOSPI | PUBLIC | 2026-07-31 → 2026-08-03 | 22,800.00 | 20,800.00 | -8.77% | DEPRESSED | DEPRESSED | DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 079960 / 1 | 동양이엔피 | KR7079960001 | KOSDAQ | PUBLIC | 2026-06-30 → 2026-07-01 | 20,000.00 | 16,420.00 | -17.90% | DEPRESSED | DEPRESSED | DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 082270 / 1 | 젬백스 | KR7082270000 | KOSDAQ | PUBLIC | 2026-04-30 → 2026-05-04 | 24,200.00 | 10,650.00 | -55.99% | DEEP_DEPRESSED | DEEP_DEPRESSED | DEEP_DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 090710 / 1 | 휴림로봇 | KR7090710005 | KOSDAQ | HISTORICAL_ONLY | 2026-07-31 → 2026-08-03 | 6,270.00 | 6,070.00 | -3.19% | DEPRESSED | DEPRESSED | DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 100090 / 1 | SK오션플랜트 | KR7100090000 | KOSPI | PUBLIC | 2026-06-30 → 2026-07-01 | 15,220.00 | 12,030.00 | -20.96% | DEPRESSED | DEPRESSED | DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 100790 / 1 | 미래에셋벤처투자 | KR7100790005 | KOSDAQ | PUBLIC | 2026-06-30 → 2026-07-01 | 19,420.00 | 16,990.00 | -12.51% | DEPRESSED | DEPRESSED | DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 105550 / 1 | 엣지파운드리 | KR7105550008 | KOSDAQ | HISTORICAL_ONLY | 2025-07-31 → 2025-08-01 | 12,800.00 | 1,631.00 | -87.26% | DEEP_DEPRESSED | DEEP_DEPRESSED | DEEP_DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 125210 / 1 | 아모그린텍 | KR7125210005 | KOSDAQ | PUBLIC | 2026-06-30 → 2026-07-01 | 6,400.00 | 6,730.00 | +5.16% | DEPRESSED | DEPRESSED | DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 148150 / 2 | 세경하이테크 | KR7148150006 | KOSDAQ | PUBLIC | 2025-10-31 → 2025-11-03 | 5,720.00 | 3,830.00 | -33.04% | DEPRESSED | DEPRESSED | DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 156100 / 1 | 엘앤케이바이오 | KR7156100000 | KOSDAQ | HISTORICAL_ONLY | 2026-04-30 → 2026-05-04 | 7,320.00 | 7,360.00 | +0.55% | DEPRESSED | DEPRESSED | DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 174900 / 1 | 앱클론 | KR7174900001 | KOSDAQ | HISTORICAL_ONLY | 2026-06-30 → 2026-07-01 | 27,850.00 | 25,200.00 | -9.52% | DEPRESSED | DEPRESSED | DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 227610 / 2 | 아우딘퓨쳐스 | KR7227610003 | KOSDAQ | HISTORICAL_ONLY | 2023-08-31 → 2023-09-01 | 4,670.00 | 1,051.00 | -77.49% | DEPRESSED | DEPRESSED | DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 251370 / 1 | 와이엠티 | KR7251370003 | KOSDAQ | PUBLIC | 2026-06-30 → 2026-07-01 | 10,820.00 | 10,060.00 | -7.02% | DEPRESSED | DEPRESSED | DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 290670 / 1 | 대보마그네틱 | KR7290670009 | KOSDAQ | HISTORICAL_ONLY | 2023-08-31 → 2023-09-01 | 43,650.00 | 5,450.00 | -87.51% | DEEP_DEPRESSED | DEEP_DEPRESSED | DEEP_DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 298380 / 1 | 에이비엘바이오 | KR7298380007 | KOSDAQ | HISTORICAL_ONLY | 2026-07-31 → 2026-08-03 | 65,400.00 | 48,150.00 | -26.38% | DEPRESSED | DEPRESSED | DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 317690 / 1 | 퀀타매트릭스 | KR7317690006 | KOSDAQ | HISTORICAL_ONLY | 2024-10-31 → 2024-11-01 | 7,310.00 | 2,375.00 | -67.51% | DEEP_DEPRESSED | DEEP_DEPRESSED | DEEP_DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 321820 / 1 | 아티스트컴퍼니 | KR7321820003 | KOSDAQ | HISTORICAL_ONLY | 2025-06-30 → 2025-07-01 | 8,570.00 | 4,190.00 | -51.11% | DEEP_DEPRESSED | DEEP_DEPRESSED | DEEP_DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 322310 / 2 | 오로스테크놀로지 | KR7322310004 | KOSDAQ | HISTORICAL_ONLY | 2026-06-30 → 2026-07-01 | 22,600.00 | 16,180.00 | -28.41% | DEPRESSED | DEPRESSED | DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 418420 / 1 | 라온텍 | KR7418420006 | KOSDAQ | HISTORICAL_ONLY | 2026-06-30 → 2026-07-01 | 4,350.00 | 3,945.00 | -9.31% | DEPRESSED | DEPRESSED | DEPRESSED | 미충족 / HOLD | RepoV2·READY |
| 900250 / 1 | 크리스탈신소재 | KYG2115T1076 | KOSDAQ | HISTORICAL_ONLY | 2023-10-31 → 2023-11-01 | 6,732.00 | 1,222.00 | -81.85% | DEEP_DEPRESSED | DEEP_DEPRESSED | DEEP_DEPRESSED | 미충족 / HOLD | RepoV2·READY |

- 공개 OPEN 20건, historical-only OPEN 17건. 37건 모두 세션별 PIT COMMON identity가 하나씩 유효했어.
- 모든 OPEN의 Pattern B 상태는 10/06·07·08 세 날에 동일하게 29건 DEPRESSED, 8건 DEEP_DEPRESSED였어. NORMAL은 0건이라 모두 HOLD야.
- 진입 시가 mismatch 0, 10/08 종가 결측 0, canonical 수익률 mismatch 0.

## 3. 진입일부터 10/02까지의 봉인된 이전 감사

10/03 승인 status의 봉인된 전수 감사가 현재 OPEN identity 37/37을 포함해. 결과는 B_SELECT_CORE_V02_TRADE_HISTORY_AUDIT_PASS; 실행 가능한 NORMAL 청산 누락 0건, pending EXIT 0건, 종가 결측 0건, valuation mismatch 0건이었어.

- audit report SHA-256: 38b6e6751a978a3e5224d1a92a40a98841037f31be46f6ccdaa59cf75e30d28d
- audit summary SHA-256: 035377c2700cc73fd20648a16be3e4616a3f2f8824c594ef7c4551fe41b4e866
- lifecycle CSV SHA-256: 8e4e805dfd721567821268e755d40d68d65620ee59fe5868a8674e1085a8f931

## 4. 원장·현재 상태·웹 대조

- Canonical history **488 = REALIZED 451 + OPEN 37**. 10/03 승인본과 exact key set 일치 True; 기존 REALIZED 변경 0건.
- OPEN key: 승인 원장 37, 현재 canonical OPEN 37, open projection 37의 1:1 일치 True. 고유 identity 399, historical-only 148, pending event 0.
- Strategy Monitor 거래 이력: status 488행, monitor 488행, 필드 mismatch 0건.
- 공개 COMMON 전체: status 1459 = stock-index 1459 = B monitor 1459 = stock report SHA 대조 1459개. exact key 누락·추가 0.
- 재계산 bucket: ENTRY 0, HOLD 20, EXIT 0, WATCH 1289, UNAVAILABLE 150 (합계 1459). status와 monitor counts mismatch 0.
- 1:1 대조 mismatch: status↔monitor item 0, 리포트 identity 0, Pattern B state/date 0, 시장 0, 종가/date 0.
- 공개 HOLD 20건은 모두 HOLD / POSITION_OPEN_PATTERN_B_NOT_NORMAL. historical-only 17건은 웹 카드가 없어도 canonical과 monitor 거래 이력에 남아 있어.

### UNAVAILABLE 150건

- 75건은 exact 영구 제외로 NOT_APPLICABLE. 제외 authority는 181쌍이며 현재 OPEN과 겹치는 종목은 0건이야.
- 나머지 75건은 공식 Pattern B evaluator 결과가 UNAVAILABLE이야. 모두 OPEN/canonical_position이 아니고 current_trade 및 pending도 없어. OPEN이 UNAVAILABLE 집합에 숨어 있는 건 0건.
- Pattern B 결측 reason code 출현은 36개월 range bars 부족 75, 월간 MA24 bars 부족 44, 52주 range bars 부족 14야. 한 종목에 복수 이유가 있을 수 있어. 이들을 READY/NO EXIT로 취급하지 않고 명시적으로 UNAVAILABLE에 남겼어.
- 공개 리포트 전체에서 report_status DATA_UNAVAILABLE은 90건이지만 그중 Pattern B 평가 READY인 행도 있어. 리포트의 Pattern B evaluator status/state를 직접 대조했고 mismatch는 0건이야.

## 5. 데이터 권위와 시점 무결성

- merged PIT frontier 2026-10-08; content digest 9fd0a2a508c961f66c85489954e80decaae6deafd779289da0e4f44785f77bf9.
- merged KRX calendar frontier 2026-10-08; content digest c370d6b19e6007b66ad03bebc6585f327ad605ad53766816f6e3981a1e5e568a. 10/06·07·08은 exact KRX 세션이고, 10/09·10·11은 달력에 없어.
- rolling manifest certified-through 2026-10-11; manifest SHA-256 980881df0d9ec88937740b62a2f24ec19473282ef3ee8f19f0c1a5c789205773. 미래 가격 조회는 없었어.
- 10/03 승인 원장·10/11 status·Strategy Monitor·stock-index·주식 리포트·PIT·calendar를 읽기 전용으로 검증했어. 운영 산출물과 원천 데이터 변경 0, network request 0.

### 주요 입력 SHA-256

| 원천 | SHA-256 |
|---|---|
| 10/03 승인 status (artifacts/strategies/b_select_core_v2/production/20261003/status.json) | de19d19c48d3d2388fd6ecb3968429d4e4a33fac5ddcf8f4ac46645f8618e03e |
| 10/11 복구 status (artifacts/strategies/b_select_core_v2/production/20261011/status.json) | 6e033e40f50dca47840c084191b5be505871ddc090ee332aec7b0697d94db06f |
| 10/11 Strategy Monitor (web/data/strategy-monitor.json) | 48f50300cd985c5d583aaccf9744bf3a154b162ea2fed59ea773991cd8d2c406 |
| 10/11 stock-index (web/data/stock-index.json) | 4c29f7085f1f85975c71de8acc68b4deace4d1493a8f1d40b409282d69e4061f |
| merged PIT (data/market/rolling_authority/merged_pit_intervals.json) | d93a958d7bbae9142ef1fa5aded36080d1d107739e777eb4ec3b6566fea90654 |
| merged KRX calendar (data/market/rolling_authority/merged_trading_calendar.json) | ab7635de160e06d538d9d0dc7225c8e1b307f191f54f2584d4c79e47a94a7480 |
| rolling authority manifest (data/market/rolling_authority/manifest.json) | 5c4a9e346d7460c4a28b30a3cd9ab19c9c17527f1c4409282206e8ec2a731570 |
| 공식 V2 전략 규칙 (docs/patterns/pattern_b/strategy/PATTERN_B_SELECT_CORE_V02.md) | d81444c363031130ab2699cb9abc92182879f1f2007877410d58c6e5a8cb2d64 |
| 공식 Pattern B evaluator (src/trend_scanner/patterns/pattern_b_evaluator.py) | 07471f62074b87bd00f8281aec1bbcfd6370d0bad41abedb8c867cd9d6c58b72 |
| Repository V2 (src/trend_scanner/data/repository_v2.py) | c252835604b0fd8f2e839d438052670d9700e773f1c34cb83582c5c29a198215 |

전체 입력 파일 hash는 source_manifest.csv, 공개 리포트별 hash는 public_report_sha256.csv에 기록했어.

## 6. 실행·테스트·Git

- 감사 실행: PYTHONDONTWRITEBYTECODE=1 .venv/bin/python artifacts/strategies/b_select_core_v2/validation/20261011_exit_current_status_audit_v01/audit_current_open_status.py — PASS, 37종목 / 111세션.
- 관련 테스트: test_b_select_core_v2_status.py, test_daily_update_phase4d_v01.py, open display exact identity, trade history parity — **32 passed**.
- 전체 web UI suite는 이번 감사에서 실행하지 않았어. 이전 작업에서 확인된 UI source-contract 실패 4건은 이번 데이터 감사와 별도 이슈로 분리했어. 이번에는 UI 코드를 수정하지 않았어.
- 감사 시작 Git: main, HEAD 6bbfd8b77a0246f1d76258b47902eb78d88f99ec, origin/main 6bbfd8b77a0246f1d76258b47902eb78d88f99ec. PASS 산출물인 이 validation 폴더만 커밋·푸시하고, 최종 HEAD == origin/main을 확인했어.

## 7. 산출물

- audit_current_open_status.py: 재현용 read-only 감사기
- summary.json: 판정·요약·hash·진단
- open_positions.csv: OPEN 37개 전수표
- open_session_evaluations.csv: 37 × 3 세션 평가와 evaluator reason·feature evidence
- canonical_trade_parity.csv: 488개 거래의 원장/monitor key 대조
- public_status_audit.csv: 공개 COMMON 1,459개 상태/action/reason/date/card 대조
- unavailable_status_audit.csv: UNAVAILABLE/N/A 150건 사유 전수
- source_manifest.csv, public_report_sha256.csv: 입력과 공개 리포트 hash manifest
