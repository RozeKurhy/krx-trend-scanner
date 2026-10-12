# FAST Core V2 Alignment + 500B — P2-2 전수 실전형 포트폴리오 V02 계획

- 작업 ID: FAST_CORE_V2_ALIGNMENT_500B_P2_2_OFFICIAL_FULL_RUN_V02
- 기준: main @ 5ffb83968c1c94f167c0e849427d7c3e1a2313b5 (실행 전 origin/main 재확인)
- 기간: P2-2, 2021-01-04~2026-08-31, 1,387개 정확한 KRX 평가 세션; 2026-09-01은 cutoff 전 신호의 다음 세션 체결 지원만 허용
- 그룹: CONTROL, ALIGNMENT_MCAP_500B; 각 그룹의 전수 신호 원장과 전체 현금 경로를 처음부터 산출
- 승인 범위: 이 연구 폴더 산출물 생성, 결과를 /Users/june/Documents/projects/r.md에 기록, 이 폴더만 커밋·푸시

## 목표와 고정 제약

공식 A FAST Core V2와 후보 Alignment + signal-day market cap ≥ KRW 500B를 동일한 데이터·현금·비용 계약으로 전수 비교한다. 전체 결과를 전수 단일 기간 공식 A~E 기준으로 판정한다. 후보 채택·기본 전략 승격·5기간 최종 채택을 결정하지 않는다. 공식 기본 전략 PATTERN_A_FAST_FINAL_STRATEGY_V02를 유지한다.

P3-1/P3-2와 동일한 동결 V2 평가기, 진입·청산·재진입 상태, 200,000,000원 시작 현금, 종목당 수수료 포함 5,000,000원 총 매수 예산, 정수주, 0.1% 불리한 슬리피지, 매수·매도 각 0.015% 수수료, 거래세 0%, 매도대금 T+1, 동시보유 상한 없음, ticker/ISU/signal/execution/trade ID 결정 순서, 10 평가 worker 및 단일 순차 포트폴리오 재생을 사용한다. 후보 필터는 진입 전에 strict signal_close > prior completed MA20 > prior completed MA60와 정확한 신호일·시장·PIT identity의 KRX raw 시가총액 ≥500B만 적용한다.

전략·필터·비용·신호 순서·A~E 임계값·유니버스 기준은 바꾸지 않는다. 거래 결과를 보고 종목을 제외하지 않는다. KRX/OpenDART 등 외부 API는 호출하지 않는다. P1, P2-1, P3, production, 웹/운영 코드는 다시 실행하거나 수정하지 않는다.

## V01 증거 재사용 및 V02 실행 순서 변경

V01 표본은 32종목을 각각 독립적으로 2억원 현금 경로에 넣었기 때문에 CONTROL에서 029960의 558주 표본 포지션을 매수했고, 주식교환·상장폐지 뒤 297개 NAV 일자가 미해결이었다. 이 77.58% 표본 coverage는 표본만의 자금 배분 산물이며 전체 유니버스의 현금 경로 결과를 대표하지 않는다. 따라서 V02는 이 표본 coverage 하나만 전수 실행의 차단 조건에서 제외한다.

실행 전에 preflight_reuse_audit.json에서 V01 preflight, V01 최종 source manifest 및 sample artifact hash, 2,573 adjusted file hash, 2,776 raw date-market partition hash, rolling PIT/calendar source, exact 182개 permanent identity exclusions, 해당 평가기의 기간별 유니버스를 다시 확인한다. sample benchmark 32/32 available, 10 workers, 0 worker errors, 191.241초 실측, 4,601.332초 예상, sample validation의 모든 check 중 정확히 control_nav_coverage_at_least_90_percent 하나만 false임을 확인한다. 표본을 다시 실행하지 않고, 거래·현금·비용·신호 원장은 표본에서 전수 결과로 복사하지 않는다.

전수 실행 전 이 문서, execution_contract.json, preflight.json, preflight_reuse_audit.json, source_manifest.json을 봉인한다. Runner는 확인된 유일한 sample check 실패가 CONTROL sample NAV coverage인지 검사한다. 다른 sample check가 하나라도 실패하면 실행하지 않는다. 이는 실행 허가 순서만 바꾸며 official E 기준을 변경하지 않는다. 실제 전수 E coverage는 100% EXACT, 90% 이상~100% 미만 OBSERVED, 90% 미만 CHECK_REQUIRED로 판정한다.

봉인된 기준이 재검증된 직후 전체 2,573 ticker 신호 평가를 기존 10-worker evaluator로 정확히 1회 실행한다. 이후 양쪽 전수 원장을 고정하고 CONTROL 및 후보의 순차 자금 재생을 각각 정확히 1회 수행한다. Worker 오류가 발생하면 결과·오류를 저장하고 자동 재실행하지 않는다. 현금 부족은 원장을 재생성하지 않고 전량 SKIPPED_CASH_UNAVAILABLE로 기록한다. 코엔텍 때문에 NAV 평가가 결측이어도 실제 full-run 체결·skip·현금·보유·노출 원장은 보존한다. 근거 없는 교부금·예정 입금·가상 매도는 넣지 않는다.

## 입력 권한과 해시

원문을 실행 전 직접 읽었고 source_manifest.json에 파일 SHA-256을 저장한다.

| 근거 | SHA-256 |
|---|---|
| docs/validation/backtest_common_rules.md | e8783958064ddfc54f57bef3500ad41de6d3b6bc853fce2464845f9c4cc4d06b |
| docs/validation/official_strategy_adoption_criteria.md (A~E 단일 권한) | 380f34cd7e24fd9881d7a154000d9b51512d905d7c7ef24b1940f5fa4e22cb88 |
| docs/strategies/strategy_lifecycle.md | c89bad3f56b95a9bac3284fb9817067940534b52c87c29f57f3009ea5a1e25e8 |
| docs/patterns/pattern_a_fast/strategy/version_02/README.md | d353afec7e26ad4adb296dc14e337a78c88466d3ddcee887932ef1fd58f295ef |
| P3-1 execution_contract.json | 1d9b833cd99bd045cf4d7e8f079c0477f7ad42da76ccd600d9c429e3a2c3b089 |
| P3-1 run_official_realistic_replay.py | 3d7f573bb908b904758427e59967d698fc471cf3af0de699815aa5516ab9705b |
| P2-2 V01 preflight.json | b38683bb0dcd659136aaf7cb6b7d139c20fe4c4c1a4cf43ca49c12e295e6753f |
| P2-2 V01 sample_benchmark.json | b6f1a328a91741184f5dcda5037155f1c4748273c4f9876d7ca9dbb646bc6be4 |
| P2-2 V01 sample_validation.json | 153d192a653576de11416c7b2eced2e36221c83edd67e373d6e42aa817c33eff |
| Current W instruction | 3ca40eb71333ffe100e0ac15cc1a2d09b60f1c3fe68f5deaab08c6c99f016ac7 |

P3-1 bounded-load/NAV closure, P3-2 official run/readjudication/data closure, V01 preflight/sample outputs and source manifests, current repository/evaluator sources, raw partition manifest, rolling authority, all adjusted-price file hashes and all full-window raw-partition hashes are also listed and verified in source_manifest.json / preflight_reuse_audit.json. V01의 기존 출력은 읽기 전용 역사 기록으로 보존한다.

## 포트폴리오·평가 계약

- Signal: exact COMMON PIT identity, no current-survivor broadcasting, exact ticker/ISU/market; 182 exact excluded (ticker, standard ISU_CD) pairs before group split; (380440, KR7380440008) excluded. CONTROL has no market-cap bound.
- Candidate entry: prior 20/60 completed month adjusted-close arithmetic means, signal month excluded, 60 months required; missing/invalid history rejects that candidate signal as MA_UNAVAILABLE; exact signal-date KRX raw market cap ≥500B; unresolved cap rejects with exact audit reason.
- Portfolio: 200M initial cash; each entry total buy cost ≤5M including fee; integer shares; no partial fills, max-position limit, same-ticker overlap, pyramiding, same-open exit/re-entry or same-open reuse of unsettled sale proceeds. Sell proceeds settle next exact KRX session.
- Valuation: exact adjusted close, available cash + pending proceeds + only contractually evidenced receivables + held integer shares. An unresolved normal-trading-day mark makes the whole day’s NAV unresolved. Carry is only for repository/market-authorized non-trading placeholders and valuation only. No imputation or hypothetical cutoff liquidation.
- Missing marks in 003690/128940 and any other identity are categorized by raw activity, adjusted-source row and composed portfolio mark. No ad hoc exclusions or fixes.
- Koentec (029960, KR7029960002) is audited using full-run outputs. Sample’s 558 shares are never assumed to be full-run exposure. If exposed, report exact signal/entry order, cash before/after, shares, 2025-05-30 event, 2025-06-16 delisting, cutoff holdings and missing NAV. No 9,000원 payment or 2025-06-20 expected deposit is recognized without actual accounting evidence.

## 공식 판정 및 보고

A~E는 전수 P2-2 결과만으로 독립 재검산한다. A includes identity/PIT/future/source/lifecycle/ledger/cash/position integrity. B verifies fees/slippage for every filled side and zero transaction tax. C requires both total return and CAGR >0. D requires both MDD ≥−40%; candidate fails when CONTROL MDD − candidate MDD >= +5.0pp. E uses the unchanged 1,387-session denominator and official coverage tiers above. If cutoff value is not reliable, no estimated C/D pass. Cash-shortage rate is a diagnostic, never a gate.

Report first counts CRITICAL / MAJOR / MINOR, then both groups’ ending equity, returns/CAGR, Exact/Observed MDD and dates, NAV coverage, A~E status/evidence, comparison deltas, entry/skip/fill/exit/open/support counts, trade win/return/holding distributions, return tails, max gain/loss, Loss Guard, PROGRESSED, exits by reason, capital utilization, concurrency, turnover, costs and any concentration needed to explain. Include the full Koentec exposure audit, ticker/date breakdown for unresolved marks, worker/runtime counts, exact calendar/PIT/universe/input hashes and independent ledger checks.

Regardless of P2-2 outcome, this one period remains NOT_FINAL_5WINDOW; candidate adoption and default promotion are NOT_EVALUATED; PATTERN_A_FAST_FINAL_STRATEGY_V02 remains the default. No result number from the V01 sample is represented as a full-run number.

## 저장·Git

All execution and reporting outputs go only under this directory. Record the Korean result in /Users/june/Documents/projects/r.md. Before commit, stage only this new directory; preserve all pre-existing untracked research files. Commit and push to origin/main; fetch afterward and confirm HEAD == origin/main, tracked worktree clean, then report the commit and final decision status.
