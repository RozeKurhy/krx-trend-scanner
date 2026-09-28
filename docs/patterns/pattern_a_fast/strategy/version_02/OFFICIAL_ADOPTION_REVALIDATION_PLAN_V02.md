# A FAST Core V2 공식 전략 공통 채택 기준 재심사 계획 V02

작성일: 2026-09-28 KST
대상 전략: `PATTERN_A_FAST_FINAL_STRATEGY_V02`
계획 상태: 실행 전 봉인 문서. 본 계획만 별도 commit/push하고 SHA-256을 기록한 뒤 샘플·성과 계산을 시작한다. 결과를 확인한 뒤 조건을 고치지 않는다. 조건 변경이 필요하면 실행을 중단하고 새 계획 버전을 봉인한다.

## 1. 목표와 시작 상태

현재 기본 전략 V2를 공식 전략 공통 채택 기준 A~F로 다섯 표준 기간에 동일하게 재심사한다. 목표는 통과가 아니라 기준의 무예외 적용이다. V2 전략 규칙과 공통 기준은 수정하지 않는다.

| 항목 | 값 |
|---|---|
| 시작 `HEAD` | `bbe2dc15ef4cfbbd213e08a40f28ed11e996a733` |
| 시작 `origin/main` | `bbe2dc15ef4cfbbd213e08a40f28ed11e996a733` |
| 시작 worktree | tracked 파일 clean. V01 실험용 실행기 1개가 미추적이었으나 V02에서 사용하지 않아 계획 작성 전 제거 |
| 기준 브랜치 | `main` |

최종 판정은 아래 하나만 사용한다: `OFFICIAL_STRATEGY_ADOPTED`, `NOT_ADOPTED`, `HOLD`.

## 2. 권위 문서와 고정 전략 자료

기준일의 `main`에서 공통 계약·원천 인증에 다음 자료를 권위로 사용한다. V02는 고정 원장을 포트폴리오 입력으로만 사용하므로 FAST/Pattern A 평가기를 다시 실행하지 않는다.

| 자료 | SHA-256 |
|---|---|
| `docs/validation/official_strategy_adoption_criteria.md` | `a0ad65b46056507654dc8122de19c6a4df3b794f11489bd5f018c178e2ca1e7e` |
| `docs/validation/backtest_common_rules.md` | `d28aac7fdb4f60db0a250ccf2913c45354832b48abcdee9dfedb96cc877c349b` |
| `docs/strategies/strategy_lifecycle.md` | `d18f7c6f45703812fd31203030061e7bfcef6b9cf69b20f26cb30d1e3aa642ed` |
| `docs/patterns/pattern_a_fast/strategy/version_02/README.md` | `66689affada1bd41a11a7de7e307a8403c638086e317abc91d4952b4d0855c68` |
| permanent identity policy `src/trend_scanner/universe/permanent_identity_exclusions.py` | `45b88a22d677679d8a73e63dd030fd8c2bc2dff35e6e109d8f93a75a9e31fc24` |
| official Repository V2 loader `src/trend_scanner/data/repository_v2_loader.py` | `d5c2333022acf5b777f38bfd024c7540aaae8bc16f455c1a7e779c60c510a97d` |
| Repository V2 price/session authority `src/trend_scanner/data/repository_v2.py` | `c252835604b0fd8f2e839d438052670d9700e773f1c34cb83582c5c29a198215` |
| KRX raw daily store `src/trend_scanner/data/krx_raw_stock_store.py` | `43b491cf74d6b3c41d02f7877d006199a9e5419901f0b8e8a6a50d1c5ad6e95e` |

V2 재진입과 거래 결과는 아래 사전 인증 CONTROL 원장의 불변 기록을 따른다. 이번 portfolio-only 심사에서 frozen evaluator를 호출하지 않는다. 영구 제외는 위 현재 승인 정책만 적용하며, 성과를 본 뒤 제외를 추가하지 않는다.

## 3. 표준 기간과 CONTROL 입력

모든 기간은 공통 거래 달력의 달력 경계를 따른다. 실제 거래일은 각 원장 및 Repository V2 거래 달력에서 다음처럼 고정하고 실행 계약에서 다시 확인한다. 일치하지 않으면 성과 계산 전에 중단한다. 종료일 다음 정상 거래일은 종료일 전에 발생한 청산 신호의 체결 지원에만 사용할 수 있으며, 지원일 신호나 신규 진입은 금지한다.

| 기간 | 달력 평가 구간 | 지정 CONTROL 원장 | 원천 행 수 → 영구 제외 적용 후 | 원장 SHA-256 | 원천 인증 근거 |
|---|---|---|---:|---|---|
| P1 | 2014-01-01~2026-08-31 | `artifacts/backtests/p1_neg40_weak_protect_v01/run_20260925_standard_full_worker10_v01/raw_only_exclusion_closure_v02/control_trades.csv` | 4,983 → 4,983 | `0edcb9b87ccdc1e290c3431fb6e7e395bda910cf6dd69fa2d94426b7011eaeb0` | closure manifest `6658bed4dee907f4cf0d82a28688f21dfa7c14b759cb9aaa91e907842ff78098`; raw-only cert `bf4319a0f1d9b9f443f2563b07779a3ea7dd4a8d5b2cd5daf2c808547e6d248c`; P1 summary `99b6af6db16ed52c197343e4858bbc316021f42e281033e4363952ccd7d68f08` |
| P2-1 | 2021-01-01~2025-05-31 | `artifacts/backtests/p2_1_neg40_weak_protect_v01/run_20260925_corrective_full_recert_v02/raw_only_lifecycle_closure_v01/control_trades.csv` | 1,801 → 1,801 | `47d49cfba42bb7d3f278f81227671f68ab7dc96a34b42a3976f591c2c5a8c790` | raw-only cert `2396c78b6f7c612d4fbbe6827c71cd0eb9f9ce543d542a7176ad02139af6481b`; parent manifest `d8490fa9bf1628042519d2b8abde016f699f4f1874580b64a2691c96ea0b7a86` |
| P2-2 | 2021-01-01~2026-08-31 | `artifacts/backtests/p2_2_neg40_weak_protect_v01/run_20260924_final_corrective_v01/control_trades.csv` | 2,424 → 2,394 | `b58b27d326b79625bbdce775ab155d52486a11b1bcccfe2acf203d55a1b675f1` | summary `cc04b7f1608d5e7a27e8f3739916f5d83aa9374100684d40f54a7ca1ab773409`; parent manifest `e025e852ba92605d3e68e6e9c5831f42daaa9f53975dddc02e5b650c19742a35` |
| P3-1 | 2022-01-01~2025-05-31 | `artifacts/backtests/p3_1_neg40_weak_protect_v01/run_20260925_worker10_replay_v01/control_trades.csv` | 1,174 → 1,161 | `333caeae854f69981d6ab3dd2d235eb798c25c7e1086ba7d4ea7d3da109c5b1e` | summary `6d2757f521130f2455b1489361bab3c40f224b8025458be2d45d040dd990b156`; parent manifest `9ab02c8d4914acc67e992fc7b0d7fa9869711d5cebe11f3850909fdb3d894c4a` |
| P3-2 | 2022-01-01~2026-08-31 | `artifacts/backtests/p3_2_neg40_weak_protect_v01/run_20260925_p3_2_worker10_corrective_v01/control_trades.csv` | 1,805 → 1,785 | `b905b601f36195e8a1666454f90f442e65c653857cda5e4fdc79a362b2776e16` | summary `d500be2806e0a6555389797f9d5035076dd4176774b49db25f70110949e325bf`; parent manifest `dc39a7e0500ad9fbe121e586ee846a2b87e913250cb8640219727bd4d8e5b2ae` |

| 기간 | 실제 시작 | 평가 종료 | 체결 지원 종료 |
|---|---|---|---|
| P1 | 2014-01-02 | 2026-08-31 | 2026-09-01 |
| P2-1 | 2021-01-04 | 2025-05-30 | 2025-06-02 |
| P2-2 | 2021-01-04 | 2026-08-31 | 2026-09-01 |
| P3-1 | 2022-01-03 | 2025-05-30 | 2025-06-02 |
| P3-2 | 2022-01-03 | 2026-08-31 | 2026-09-01 |

P1에서 부모 실행 manifest `0126175233cadd2133ea90c70dc0e741c620eb853c9be3bbcfaf55eedb916d9d`는 Candidate soft-event 문제로 `CHECK_REQUIRED`다. 이 재심사에는 부모 전체 결과를 사용하지 않고, 지정 경로의 독립 CONTROL raw-only closure만 사용한다. 해당 closure의 P1 CONTROL 인증은 `P1_CERTIFIED_PASS_WITH_AUTHORITATIVE_EXCLUSIONS`다.

P2-1의 지정 raw-only closure는 `P2_1_CERTIFIED_PASS_WITH_AUTHORITATIVE_EXCLUSIONS`다. P2-2에서는 지정 run의 CONTROL만 사용하고 Candidate의 `PROMISING` verdict는 공식 판단에 가져오지 않는다. P3-1/P3-2는 지정 summary의 CONTROL recertification 상태를 사용한다. P3-2 원본 원장 1,805행은 요약에 반영된 현행 영구 제외를 실행 입력 구성 단계에서 같은 정책으로 적용한다. 모든 원천 파일은 변경하지 않는다. 인증 파일, 상태 또는 입력 해시가 재확인 시 위와 다르면 성과 계산 전에 중단하고 계획을 수정하지 않은 채 `HOLD` 근거로 기록한다.

V2.1 Candidate와 2026-09-26 realistic market-cap 1조 이상 산출물은 공식 유니버스·판정 계산에 사용하지 않는다.

## 4. 유니버스와 데이터 계약

- 공식 Repository V2의 로컬 조정 일봉과 KRX 원자료를 사용한다. PIT 공통 분모, 완료 봉, 원천 필드 의미는 현재 공통 원칙과 지정 run의 권위 PIT에 따른다.
- Repository V2 / PIT / 거래 달력 근거: `data/market/rolling_authority/manifest.json` SHA-256 `722e4f3ee508b7ad7ac6c351afb7f4775cac7b93ac228aa3c85487a728582b74`; `merged_pit_intervals.json` SHA-256 `ff783168c56a4772a681e34b97b17d8855f28d1c13df25094bd65cedbc80cd26`; `merged_trading_calendar.json` SHA-256 `c9af2e5bd71ec387c73752eb4955c0d76f23e38cf30db71b49b01c04fe8538b8`.
- Repository V2 로더 `src/trend_scanner/data/repository_v2_loader.py` SHA-256 `d5c2333022acf5b777f38bfd024c7540aaae8bc16f455c1a7e779c60c510a97d`, 구현 `src/trend_scanner/data/repository_v2.py` SHA-256 `c252835604b0fd8f2e839d438052670d9700e773f1c34cb83582c5c29a198215`.
- 각 기간에 현재 영구 identity exclusion 정책을 정확한 `(ISU_CD, ticker)` 식별 기준으로 똑같이 적용한다. 시가총액 1조 이상, 최신 생존 종목, 현재 ticker 목록 필터는 넣지 않는다.
- 시장 가격은 해당 날짜의 실제 Repository V2 일봉만 사용한다. 근접일, 현재값, 앞 값 이월, 보간, 0 또는 대리값은 금지한다. 보유 종목의 어느 평가 거래일 또는 종료일 가격이 없으면 누락 ticker/날짜를 기록하고 임의 보정하지 않는다.

## 5. 포트폴리오와 비용 실행 계약

| 설정 | 고정값/처리 |
|---|---|
| 초기 자본 | 200,000,000원 |
| 종목당 총 매수 예산 | 5,000,000원 상한(매수 수수료 포함 실제 현금 유출 기준) |
| 수익금 재투자 | 허용 |
| 동시 보유 수 상한 | 없음 |
| 부분 체결 | 금지. 정수 주식 목표 주문 전체를 실행하거나 건너뜀 |
| 현금 부족 | 주문 전체 `SKIPPED_CASH_UNAVAILABLE`; 확정 원장 행은 건너뛰고 신호 재생성·상태 재생 없음 |
| 같은 ticker 동시 보유/피라미딩 | 금지 |
| 같은 시가 청산 후 재진입 | 금지 |
| 매도대금 가용 시점 | 매도 다음 정상 거래일. 당일 같은 시가 진입 자금으로 쓰지 않음 |
| 매수 수수료 | 체결금액의 0.015% |
| 매도 수수료 | 체결금액의 0.015% |
| 매수 슬리피지 | 기준 시가 대비 +0.1% |
| 매도 슬리피지 | 기준 시가 대비 -0.1% |
| 거래세/매도세 | 0%. 공식 산식과 현금 흐름에서 제외 |

매수 수량은 `floor(5,000,000 / (기준 시가 × 1.001 × 1.00015))`로 정해 총 매수 현금 예산을 넘지 않게 한다. 매수 체결가는 기준 시가에 1.001을 곱하고, 수수료는 체결금액에 부과한다. 매도 체결가는 기준 시가에 0.999를 곱하고 수수료를 차감한다. 모든 실제 체결에서 양방향 수수료·슬리피지가 빠짐없이 기록되어야 한다.

거래일마다 먼저 전 거래일 이전에 매도된 대기 대금을 정상 가용 현금으로 풀고, 당일 청산, 그 뒤 신규 진입 순서로 처리한다. 당일 매도대금은 다음 정상 거래일까지 pending 자산으로 보존한다. 당일 신규 진입은 `ticker` 오름차순, 이어 안정 신호 식별자 `(ISU_CD, signal date, execution date, trade ID)` 오름차순으로 처리한다. 결과·시가총액·수익률로 주문 순위를 정하지 않는다.

## 6. 사전 확정 CONTROL 원장과 기준 E 분모

공식 심사는 `전략 신호 생성 → 전략 원장 확정 → 포트폴리오 자금 배분` 순서로 고정한다. V02는 지정된 인증 CONTROL 원장을 그대로 재사용하고, 현금 부족 발생 여부와 무관하게 전체 전략 신호 생성·종목 상태·거래 수를 다시 계산하지 않는다. 지정 CONTROL 원장에 현재 승인된 영구 identity 제외만 정확한 `(ticker, ISU_CD)` 기준으로 적용한다. 원장에 없는 후속 신호나 현금 부족 중 반복된 구조의 신호를 새 시도로 추가하지 않는다.

```text
mode = EXISTING_STRATEGY_LEDGER_PORTFOLIO_ONLY
entry_signal_regeneration = false
strategy_evaluation_rerun = false
```

기준 E의 분모는 확정 CONTROL 원장에서 기간 내 진입 체결일이 유효하고, 정확한 체결 시가를 확인할 수 있으며, 고정 종목 예산에 정수 주식 1주 이상을 살 수 있어 다른 실행 실패 없이 실제 주문이 가능했던 행의 수다. 분자는 이 중 현금만 부족해 전체 주문을 건너뛴 행이다. 따라서 `cash_shortage_skip_rate = 현금 부족 건너뜀 수 / 사전 확정 원장의 적격 진입 시도 수`이며, 55% 미만만 PASS다. 0주 주문, 잘못된 원장, 체결가 누락/불일치 및 다른 현금 외 실패는 E 분자·분모에서 제외하고 원인별 실행 이슈로 별도 기록한다.

같은 identity가 사전 원장에 여러 독립 거래를 보유하면 각 원장 행을 한 번만 평가한다. 현금 부족 후 원장 재생성·evaluator 호출·새 거래 ID 발급은 금지한다. 완전 동적 자본 의존형 신호 재생은 이번 공식 심사와 분리된 별도 민감도 연구에서만 다룬다.

## 7. 일별 평가와 지표 산식

- 평가곡선은 평가 시작일부터 기준 종료일까지 거래 달력의 모든 정상 거래일을 기록한다. 자산가치는 가용 현금 + 다음 정상 거래일에 결제될 매도대금 + 보유 주식의 일별 평가가치다. 원칙적으로 실제 날짜의 Repository V2 종가를 쓰며, 해당 거래일의 공식 비거래 placeholder가 확인된 보유 종목에 한해서만 직전 정상 종가를 일별 자산가치/MDD 계산용으로 유지할 수 있다. 종료 시점 미청산 포지션은 허용된 평가가로만 표시하고 가상 매도·매도비용을 적용하지 않는다.
- 다음 정상 거래일 지원일은 종료일 이전 신호의 후속 청산 체결만 처리한다. 신규 신호/진입 및 평가곡선·수익률·CAGR·MDD는 기준 종료일 뒤로 연장하지 않는다.
- 총수익률은 `종료일 자산 / 200,000,000 - 1`이다. CAGR은 `((종료일 자산 / 200,000,000) ** (365.25 / (effective_end - effective_start).days) - 1)`이다. 일별 MDD는 시작 자본을 포함한 종료일까지의 정확한 일별 자산가치 최고점 대비 최대 하락률이다.
- MDD 기간은 최고점일, 저점일, 회복일 및 거래일 수를 기록한다. 종료일까지 회복되지 않으면 회복 미완료로 남긴다.
- 기준 E 분모·분자는 §6에 정의한 사전 확정 CONTROL 원장 적격 시도·현금 부족 건너뜀 행이다. 현금 부족 후 signal regeneration 또는 identity 재생으로 새로 생긴 시도는 공식 분모에 넣지 않는다.
- 자본 활용도는 일별 보유 시장가치 / 일별 총자산으로 정의한다. 회전율은 (매수 체결금액 + 매도 체결금액) / 초기 자본이다. 승률 및 꼬리 진단 수익률은 실현 포트폴리오 거래의 양방향 비용 반영 순수익률을 기준으로 하고, 미청산 거래는 실현 손익 꼬리에 넣지 않는다.
- 정확 종가가 없을 때는 공식 `MarketDataRepositoryV2`/KRX 원천의 같은 날짜·시장 `COMPLETE` 일별 partition에서 동일 ticker 행이 있고, Repository V2의 좁은 `NON_TRADING_PLACEHOLDER_V01` predicate(`open=high=low=0`, `close>0`, `volume=trading_value=0`)를 모두 만족하는 경우에만 공식 비거래로 인정한다. 직전 정상 조정 종가는 해당 날짜 일별 포트폴리오 평가와 MDD 계산에만 쓰고 신호, 전략 상태, 진입/청산 체결가 또는 체결 종료값에는 사용하지 않는다. 해당 ticker/ISU, 평가일, 사유, 근거 상태와 원천 manifest/path/file/content hash, 유지에 사용한 직전 가격 날짜·값을 `valuation_carry_audit.csv`에 남긴다.
- 날짜 partition, 종목 행 또는 비거래 predicate 증거가 없거나, 원자료에 실제 거래가 확인되는데 조정 종가가 무효/누락된 경우에는 carry하지 않고 `UNRESOLVED`로 남긴다. 수익률/CAGR/MDD를 신뢰할 수 없게 하는 공백은 F=`CHECK_REQUIRED`로 둔다.

## 8. 필수 기준 A~F와 최종 판정

각 기준을 다섯 기간 각각에 적용한다.

| 기준 | PASS 조건 |
|---|---|
| A 무결성 | PIT/미래정보/기준 종료일/identity/생애주기/현금 보존/중복 보유/숨은 보유 상한 위반 및 판정에 영향을 줄 구조 오류 없음 |
| B 비용 | 모든 공식 매수·매도 체결에 수수료 0.015% 및 각 방향 슬리피지 0.1% 적용; 거래세 제외 |
| C 수익성 | 총수익률 > 0 및 CAGR > 0 |
| D MDD | 일별 포트폴리오 MDD >= -35% |
| E 현금 부족 | 현금 부족 누락률 < 55% |
| F 결과 유효성 | 종료 평가·일별 자산가치·자료가 완결되어 핵심 성과를 신뢰할 수 있음. 단, §7에서 허용한 공식 비거래일의 평가용 직전 종가 유지와 해당 감사 기록은 허용 |

다섯 기간 모든 A~F가 PASS면 `OFFICIAL_STRATEGY_ADOPTED`. 모든 핵심 증거가 완결되고 하나 이상 기준이 FAIL이면 `NOT_ADOPTED`. 판정에 필요한 기준 중 하나라도 미해결/`CHECK_REQUIRED`면 `HOLD`를 우선한다. 기준이나 결과를 보고 뒤에 임계값·수수료·기간·유니버스를 바꾸지 않는다.

## 9. 보고 지표와 시장가치 1조 이상 참고 결과

기간별로 초기 자본, 종료 자산, 총수익률, CAGR, MDD와 기간, 현금 부족 수/분모/비율, 평균·최대 자본 활용도, 평균·최대 동시 보유, 체결 진입/실현 청산/미청산 수, 승률, 평균·중앙 보유기간, 회전율, 총 수수료, 총 슬리피지 영향, 미해결 수, A~F 상태를 보고한다. 실현 거래 수익 꼬리 `>= +50%`, `>= +100%`, `<= -30%`, `<= -40%`, `<= -50%`, `<= -60%`도 별도 진단한다.

아래 자료는 공식 게이트와 완전히 분리한 참고표에만 쓴다. 유니버스가 달라 성과 우열 판단이나 공식 기준 판정에 사용하지 않는다.

| 참고 기간 | 산출물 | SHA-256 |
|---|---|---|
| P2-1 | `artifacts/backtests/p2_1_neg40_weak_protect_v01/run_20260926_realistic_mcap1t_worker10_v01/summary.json` | `a996e716944b5b51939d579548398d5269a76bf96dd6a5158173c61e159dd1ac` |
| P2-2 | `artifacts/backtests/p2_2_neg40_weak_protect_v01/run_20260926_realistic_mcap1t_worker10_v01/summary.json` | `b01cff6b5b5ff5af77e78495c1254712e51e13061baf8661c9d5c7a0a22bef912` |
| P3-2 | `artifacts/backtests/p3_2_neg40_weak_protect_v01/run_20260926_realistic_mcap1t_worker10_v01/summary.json` | `437dd8bf44c57a92ee746145eac85c853f568958b0fdb26999c455a4412a93d9` |

중단된 V01 공식 재심사 샘플의 `94.242%`는 동적 신호 재생 방식의 역사 기록으로만 보존한다. 이 값은 V02 공식 현금 부족률·게이트·기간 판정에 사용하지 않는다.

## 10. 표본, 산출물, Git 절차

계획을 먼저 commit/push하고 그 SHA-256 및 commit SHA를 고정한다. 이후 P2-1의 첫 60거래일(2021-01-04~2021-03-31)을 표본으로 실행한다. 샘플에서는 Repository V2 일봉 로딩, CONTROL 원장의 기간 내 신호·체결 행, 정확한 체결 시가, 수수료·슬리피지·현금 보존, 사전 고정 원장 기준 E 분자/분모, 공식 raw placeholder로 입증된 평가 carry와 MDD 계산을 확인한다. 원천 hash/인증 불일치, 원장-체결 parity 오류, 현금 보존·이벤트 순서 위반이면 자동 재실행이나 전체 신호 재계산 없이 원인을 기록하고 중단한다. 단순 가격 결측은 보정하지 않고 unresolved 감사 및 F 상태로 남긴다. 표본은 공식 기간 판정으로 사용하지 않는다.

샘플 통과 후 5개 표준 기간을 모두 수행한다. 기간별 가격 프레임 로딩은 필요 시 worker 10개로 병렬화할 수 있으나, 일자별 현금/체결 이벤트 적용은 결정적 단일 순서로 실행한다. 전략 evaluator, 신호 생성, cash skip 뒤 종목별 상태 재생은 실행하지 않는다.

새 산출물은 기존 기록을 덮어쓰지 않고 다음에 저장한다.

```text
artifacts/patterns/pattern_a_fast/strategy/v2_official_adoption_revalidation_v02/
```

최소 파일: `report.md`, `summary.json`, `execution_contract.json`, `source_hashes.json`, `window_metrics.csv`, `gate_results.csv`, `cash_events_<window>.csv`, `valuation_carry_audit_<window>.csv`, `daily_equity_<window>.csv`, `portfolio_events_<window>.csv`. 각 기간의 실행 스크립트 실제 SHA-256, 계획 hash/commit, CONTROL 원장·인증·달력·PIT·Repository V2/KRX partition의 실제 사용 SHA-256, sample/full 실행 상태를 manifest에 기록한다. 미해결 평가 일자와 E의 분자/분모 계산 원장도 보존한다.

이 계획 문서만 별도 stage/commit/push하고, 그 뒤 계획 commit SHA를 산출물·V2 README에 기록한다. 최종 결과가 정해지면 README에는 재심사 사실, verdict, 결과 경로만 짧게 연결한다. 결과와 최소 필요한 코드/문서만 commit/push하고 `HEAD == origin/main` 및 clean worktree를 확인한다. 결과 보고는 대화와 사용자 지정 `r.md`에도 남긴다.
