# Julia 공식 전략 검증 계획 V01

> **현재 결정 업데이트 (2026-09-17)**
>
> 이 문서의 Stage 4 사전 계획은 역사적 기준으로 보존한다. Stage 5 최종
> 비교는 `2021-01-01 ~ 2026-08-14` 기간에 완료되었고, Matched-entry
> `8,533`, Realistic 200M Portfolio는 V2 `58.8579%`, Julia `38.5329%`였다.
> 양쪽 Portfolio는 `PASS`, unresolved `0`, cash conservation `PASS`였다.
> 최종 결정은 Julia를 일반 종목 공식 전략으로 채택하지 않는 것이며, Julia의
> ETF 전용 가능성은 별도 검증 전까지 `DEFERRED`로 둔다. 추가 V3/V4 및
> exit-rule 연구는 현재 재개하지 않는다.

> 문서 상태: `STAGE_4_FROZEN / HISTORICAL_PLAN`
>
> 이 문서는 Julia 후보 전략의 공식 검증을 실행하기 전에 비교 조건과 판정
> 기준을 사전 고정한 문서다. 이 문서를 작성하는 단계에서는
> 백테스트, 결과 산출, 네트워크/API 호출, 전략 코드 변경 및 artifact 생성을
> 수행하지 않는다.

| 항목 | 값 |
|---|---|
| 후보 전략 | `JULIA_STRATEGY_V00` |
| 기준 전략 | `PATTERN_A_FAST_FINAL_STRATEGY_V02` |
| 계획 단계 | 전략 생애주기 4단계: 검증 계획 확정 완료 / 동결 (역사적 계획) |
| 작성 기준 HEAD | `c613dab1297c34b9826f1e35067d2fc32971bd5b` |
| 공통조건 확정 커밋 | `c613dab1297c34b9826f1e35067d2fc32971bd5b` |
| 공식 상태 | `STAGE_4_FROZEN` / Stage 4 완료·동결; Stage 5 최종 비교 완료 |
| 결과 artifact | repository official result artifact는 생성하지 않음; raw checkpoint는 외부 경로에 보존 |

## A. 목적과 공식 질문

이 검증의 핵심 질문은 다음과 같다.

> 개별 종목에서 V2의 사전 진행 단계 `-15% Loss Guard`를 제거하면 상승
> 기회를 충분히 보존하는가? 그 대가로 증가하는 손실 위험을 감수할 만큼의
> 개선인가?

여기서 Julia의 공식 전략 채택 여부 판단과 현재 기본 전략의 교체 여부는
서로 다른 결정이다. 이 계획의 첫 목적은 Julia를 공식 전략으로 채택할 수
있는지 판단하는 것이다. 기본 전략을 Julia로 교체하는 결정은 생애주기
11단계에서 별도로 다루며, 이 계획이나 실행 결과만으로 자동 승격하지 않는다.

검증은 평균 수익률 하나를 최적화하는 작업이 아니다. 상승 여력 보존,
큰 손실 및 꼬리위험, 보유·재진입 부작용, 기간 및 표본 강건성을 함께
확인한다.

## B. 비교 대상과 제외 범위

### B.1 공식 비교 쌍

- 기준군: `PATTERN_A_FAST_FINAL_STRATEGY_V02`
- 후보군: `JULIA_STRATEGY_V00`
- 후보군의 분류: `HISTORICAL_COMPARISON_CANDIDATE`
- 후보군의 현재 상태: `NOT ADOPTED / RETIRED AS GENERAL-STOCK OFFICIAL STRATEGY`

두 전략은 현재 V2 공식 규칙 문서와 Julia V00 계약을 기준으로 비교한다.
`docs/validation/pattern_a_fast_final_strategy_v02.md`는 과거 artifact
호환을 위한 redirect stub이며 규칙 기준 문서로 사용하지 않는다. 규칙
기준 문서는 다음 두 문서이다.

- `docs/patterns/pattern_a_fast/strategy/version_02/README.md`
- `artifacts/strategies/julia/v00/contract.json`

### B.2 비교에서 제외하는 연구

- FastCore V3 및 V4는 비교군, 모집단, 임계값의 근거로 사용하지 않는다.
- ETF 연구 및 `artifacts/research/etf_v3_julia_integrated_comparison_v01/`
  는 배경과 위험 사례 식별용 참고 자료일 뿐이다.
- ETF 연구의 모집단, 날짜, 표본 수, 기준값을 Julia 공식 검증에 복사하지
  않는다.
- 과거 Julia V00 불완전 PIT 연구와 proxy 시가총액 연구의 성과 수치를
  공식 결과로 재사용하지 않는다.
- 이번 공식 V2 ↔ Julia 검증에서는 Fundamentals Filter, fundamentals cutoff·
  threshold·score, 매출·이익 기반 제외 및 펀더멘털 우선순위를 사용하지 않는다.
  OpenDART Fundamentals V1과 production Fundamentals Filter 자체의 상태는
  변경하지 않는다.

## C. 단일 변경점과 규칙 동결

후보군의 유일한 의도된 변경점은 다음 하나이다.

| 규칙 | V2 기준군 | Julia 후보군 |
|---|---|---|
| 사전 진행 단계 손실 방어 | 일봉 완료 종가 수익률 `<= -15%`이면 익영업일 시가 청산 | 비활성화 |

다음 규칙은 두 군에서 동일해야 한다.

- 진입 단계: `TRANSITION`, `EARLY_TREND`
- FAST 신호: `TRIGGER` 및 `READY`
- 월봉 허용 상태: `PERMITTED_REGIME`
- 일봉 위험 상태: `NORMAL`, `ELEVATED`; `EXTREME`는 차단
- FAST 점수 상태: `READY`, `PARTIAL`
- 진입 체결: 신호 주간 다음 local trading day의 시가
- PROGRESSED 이후 Exit 3 및 Exit 4
- 재진입: 독립 진입 허용, 겹치는 포지션과 피라미딩 금지, 상태 전면 초기화
- 신호·청산·평가 cutoff, 투자적합성, 데이터 결측 및 불변 조건 처리

V2의 `-15%` guard 조건, 익영업일 시가 체결, PROGRESSED HWM 기반
`15.0pt` Exit 4는 기준군의 기존 규칙 그대로 사용한다. Julia 후보군은
이 guard 분기만 끈다. 손실 기준 변경, Exit 3/4 변경, 진입·재진입 변경,
추가 필터, 파라미터 sweep은 허용하지 않는다.

## D. 모집단과 종목 정의

### D.1 연구 모집단

공식 검증 대상은 KOSPI·KOSDAQ의 개별 보통주이다. 단일 현재 종목 목록을
역사 전체에 방송하지 않고, survivorship-safe 동결의 두 계층을 분리하여
사용한다.

- `Population Universe`: 역사 구간에서 한 번이라도 `COMMON`이었던 모든
  종목 식별 단위. 역사적 전체 후보 모집단의 기준이다.
- `Point-In-Time Common Denominator`: 각 역사적 거래일에 실제로 `COMMON`이었던
  종목 식별 단위. 날짜별 신호·투자적합성의 분모 기준이다.

두 기준 경로의 정확한 위치는 다음과 같다.

- Population: `artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01_spac_corrected_effective_authority/effective_historical_common_population.json`
- PIT denominator: `artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01_spac_corrected_effective_authority/effective_pit_common_denominator.json`
- loader: `src/trend_scanner/universe/survivorship_safe_denominator_freeze.py`
- 계약: `docs/architecture/survivorship_safe_denominator_freeze_v01.md`

과거 scanner의 `artifacts/patterns/pattern_a/production/scanner/pattern_a_universe_scan_20260814.csv`와 요약 JSON은 현재 시점 scanner의 역사 기록으로만
보존한다. 그 기록의 종목 수는 공식 historical denominator나 Stage 5의
목표 처리 개수가 아니다.

현재 비교 runner의 기존 입력 경로(`UNIVERSE_PATH`)는
`artifacts/patterns/pattern_a/production/investability/pattern_a_investability_universe_20260814.csv`이다. 이 파일과 과거 scanner 기록은 실행
출처 기록으로만 남길 수 있으며, 공식 Stage 5 실행에서는 위 Population/PIT
기준 경로를 사용하여 종목 식별 단위와 날짜별 분모를 봉인한다. 새로운
종목 선정 필터나 연구자 임의 표본은 추가하지 않는다.

### D.2 ETF·ETN 및 기타 유형

ETF·ETN은 개별 보통주 검증 모집단에 포함하지 않는다. ETF·ETN 여부와
보통주 여부는 ticker 모양이나 종목명 substring이 아니라 KRX 공식
instrument metadata의 `AssetType` 분류로 판단한다. 관련 기준 경로는
`docs/architecture/instrument_metadata_authority.md`이며, 별도 ETF 연구의
모집단을 이 계획에 섞지 않는다.

SPAC, REIT, 우선주, 외국주권, 예탁증권 및 formal 분류 불능 유형도 동일한
분류 기준으로 제외하고, 분류 불능은 임의로 COMMON으로 복구하지 않는다.

### D.3 투자적합성 필터

기준군과 후보군 모두 V2의 기존 투자적합성 계약만 사용한다.

- Point-in-time 시가총액 `>= 100,000,000,000 KRW`
- 20일 평균 거래대금 `>= 300,000,000 KRW`
- historical market cap은 신호 기준일의 KRX PIT 원천 자료를 사용한다.
- 기준일 자료가 없거나 무결성·권위 검증에 실패하면 `fail-closed`한다.
- 현재 시가총액, 미래 시점 값, proxy 값으로 조용히 대체하지 않는다.

이는 Julia 후보군을 유리하게 만들기 위한 새 필터가 아니라 V2 기준군의
기존 투자적합성 조건이다. 양 전략에 동일하게 적용한다.

FastCore 전용 `Fundamentals Filter`, fundamentals cutoff·threshold·score,
펀더멘털 기반 종목 제외 및 FastCore 전용 종목 필터는 Julia V00에 자동으로
승계하지 않는다. 이러한 조건을 추가하면 `Loss Guard` ON/OFF만 다른 Julia
V00의 단일 변경점 동결을 깨뜨리므로, 이번 공식 검증에는 포함하지 않는다.

## E. 데이터 기준 경로와 시간 의미론

### E.1 가격 및 부가 데이터

공식 검증의 가격 데이터 기준 경로는 이미 production wiring에서
`MarketDataRepositoryV2`로 확정되어 있다. 비교 runner의 연결은 다음과 같다.

- Julia 실행 경로: `scripts/evaluate_julia_strategy_v00_comparison.py`
  `-> RepositoryV2DailyLoader`
- 기준군과 후보군: 모두 `MarketDataRepositoryV2` 사용
- 이전 방식인 `data/raw/stocks`: 공식 검증 기준 경로로 사용하지 않음
- 이전 방식 fallback: 없음
- wiring 근거: `artifacts/data/end_to_end_data_parity/v01/consumer_migration_finalization/v01/production_wiring_manifest.json`

Repository V2의 원천 기준 경로는 다음과 같다.

- adjusted OHLC: `AdjustedPriceStore` / Naver direct adjusted V02
- raw volume·trading value·market cap·listed shares: `KrxRawStockStore` /
  KRX Open API stock daily
- 기준 경로 설명: `docs/architecture/market_data_repository_v02.md`

두 전략에는 동일한 원천 자료, 날짜 집합, 거래일 투영 및 결측 의미론을
적용한다. 한 전략만 다른 경로로 바꾸거나 이전 방식 cache를 섞지 않는다.

### E.2 모집단·PIT 기준 경로

생존편향 방지를 위한 상위 계약은 다음을 기준으로 확인한다. 이 기준 경로
자체는 확정되어 있으며, Stage 5 전에 runner가 이를 소비하도록 연결하는
구현 조건만 남아 있다.

- Population Universe: `artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01_spac_corrected_effective_authority/effective_historical_common_population.json`
- PIT COMMON intervals: `artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01_spac_corrected_effective_authority/effective_pit_common_denominator.json`
- 기본 동결본: `artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01/historical_common_population_v01.json` 및 `pit_common_denominator_v01.json`
- loader: `src/trend_scanner/universe/survivorship_safe_denominator_freeze.py`
- 계약: `docs/architecture/survivorship_safe_denominator_freeze_v01.md`

역사적 날짜의 denominator는 현재 종목 목록을 과거 전체에 방송하지 않고
정확한 trading date의 PIT COMMON 종목 식별 단위를 사용한다. loader가 요구하는
동결 calendar 밖 날짜, 비영업일, 누락 interval은 nearest-date fallback
없이 `fail-closed`한다.

### E.3 Lookahead와 결측 처리

- 주봉·월봉은 `include_incomplete_periods=False`로 완성된 봉만 사용한다.
- 각 신호 주간에는 해당 주간까지 자른 일봉만 사용한다.
- entry execution 이후의 정보는 entry signal, investability, stage, score에
  사용하지 않는다.
- 결측 OHLC, 시장 데이터, metadata, PIT 시가총액은 보간·forward-fill·0-fill
  없이 unavailable 또는 fail-closed로 처리한다.
- 원천 날짜 집합 불일치, future row, duplicate row, SHA mismatch는 실행
  중단 또는 해당 사례 격리 사유로 기록한다.

## F. 검증 기간

### F.1 Stage 4 동결 구간

현재 branch의 Julia runner, production wiring의 동결 기준일 및 V2 공식
비교 경계를 대조한 결과, 다음 구간을 Stage 4 공식 동결 구간으로 사용한다.

| 역할 | 날짜 |
|---|---|
| Evaluation start | `2021-01-01` |
| Signal cutoff | `2026-08-14` |
| Evaluation end | `2026-08-14` |
| Execution support end | `2026-08-14` |
| Final valuation | `2026-08-14` CLOSE |
| 초기 포지션 | `FLAT` |

근거는 사용자 승인으로 확정된 공식 비교기간과 `DATA_CUTOFF=2026-08-14`,
동일 cutoff의 production wiring이다. ETF 또는 별도 200M portfolio 연구의
지원 종료일을 이 계획의 평가 종료일로 복사하지 않는다. 2021년 이전
데이터는 rolling feature와 signal lookback에 사용할 수 있지만, 평가 거래로
포함하지 않는다.

이 구간은 결과를 보기 전에 동결한 공식 기간이다. 신호 cutoff 이후의 새
신호는 포함하지 않으며, cutoff까지 지원되는 다음 거래일이 없는 신호는
진입 거래로 만들지 않는다. Stage 4 동결 이후 결과를 보고 기간을 바꾸지
않는다.

## G. 동일 조건 비교 설계

### G.1 공통 실행 조건

다음 항목은 비교 두 군에서 byte-level 또는 의미론적으로 동일해야 한다.

- identity universe와 시장·자산 유형 분류
- 가격·거래량·거래대금 원천과 날짜 집합
- historical PIT market cap 원천 및 투자적합성 threshold
- entry signal, entry open, signal cutoff, execution support end
- monthly/weekly completed-period semantics
- re-entry, overlapping position, state reset 정책
- exit execution 및 final valuation 규칙
- 거래비용·슬리피지 모델
- 현실적 포트폴리오의 `C0`, `q`, `N`, 현금·슬롯·매도대금 재사용 및 PIT
  시가총액 우선순위

이 중 하나라도 다르면 `ONE_DELTA_ONLY`를 통과하지 못한 것으로 분류하고
공식 비교를 실행하지 않는다.

### G.2 두 가지 비교표본

1. **Matched-entry comparison**: 동일한 signal/entry execution/투자적합성
   조건으로 짝을 만든다. 기준군 guard의 발동 여부와 후보군의 대응 경로를
   같은 entry에서 비교하여 Loss Guard 하나의 효과를 분리한다.
2. **Sequential comparison**: 각 전략이 실제로 종료한 뒤 같은 재진입 규칙에
   따라 다음 독립 진입을 검색한다. guard 때문에 종료 시점이 달라져 이후
   entry 수가 달라지는 효과까지 포함한다.

두 표본의 거래 수가 다르면 어느 한쪽을 임의로 삭제하지 않는다. matched와
sequential 결과를 분리하고, 공통 entry 수·전략별 추가/누락 entry·open-at-
cutoff를 각각 보고한다.

### G.3 현실적 2억 포트폴리오 비교

동일 진입 비교와 순차 비교에 더해, 두 전략을 현실적 공통조건의 별도
포트폴리오 결과축으로 비교한다. 이 결과를 matched 또는 sequential의 단일
수치로 합치지 않는다.

- 초기자본 `C0`: `200,000,000 KRW`
- 종목당 총 매수 현금예산 `q`: `5,000,000 KRW`
- 최대 동시 보유 `N`: `40`
- 종목별 최대 비중: 초기자본의 `2.5%`
- 매수·매도 수수료: 각 `0.015%`
- 매수·매도 슬리피지: 각 `0.10%` 방향 반영
- 역사적 매도 거래세: 실제 매도 체결일·시장별 확정 세율
- 부분 체결 없음, 같은 시가 매도대금 재사용 없음, 다음 평가 가능한 로컬
  거래일 시가부터 재사용
- 동일 시가 신규 신호가 현금·슬롯을 초과하면 신호 확정일 PIT 시가총액
  내림차순, 동률 종목코드 오름차순
- PIT 결측 시 현재값·미래값·nearest-date·proxy를 사용하지 않고
  `UNRESOLVED`·fail-closed 의미론을 따른다.
- KOSPI 지수 `1001`과 KOSDAQ 지수 `2001`을 시장별로 비교하며, 혼합 단일
  benchmark는 만들지 않는다.

identity lifecycle이 global final valuation 이전에 종료된
`OPEN_AT_CUTOFF` 포지션은 identity의 정확한 `cutoff_date` 종가에서 terminal
valuation한다. 이는 전략 청산이나 매도 체결이 아니므로 매도 수수료·세금·
슬리피지, realized return 및 turnover에 포함하지 않는다. 평가금액은 현금으로
전환하거나 재투자하지 않고 `locked terminal value`로 global final까지
carry하며, equity·invested market value·exposure·cash conservation에
포함한다. 실제 처분이 없으므로 position slot을 유지하되, 이후 같은 short
ticker의 새 identity 진입은 허용할 수 있다. 정확한 cutoff 종가가 없거나
Sequential의 `cutoff_valuation_price`와 일치하지 않으면 nearest-date나
post-lifecycle 가격을 사용하지 않고 `UNRESOLVED`·fail-closed로 처리한다.

세 결과축의 의미는 다음과 같이 고정한다.

- `Matched-entry`: 같은 진입에서 Loss Guard ON/OFF의 순수 청산 규칙 효과
- `Sequential`: 각 전략의 청산 차이가 이후 독립 재진입 경로에 미치는 효과
- `Realistic portfolio`: 자본·슬롯·비용·보유기간·회전율을 포함한 운용 효과

## H. 사전 등록 지표

모든 지표는 기준군·후보군·차이(`Julia - V2`)를 같은 정의로 산출한다.

### H.1 Return

- 총 성과와 CAGR: 확정된 현실적 공통 실행조건을 동일하게 적용하고, 공식
  비교기간과 Population/PIT 기준을 사용한다.
- 거래별 평균·중앙 terminal return
- 양의 terminal return 비율
- matched entry별 terminal return 차이

Julia는 확정된 전략 중립 공통 실행조건을 V2와 동일하게 적용한다. 여기에는
historical PIT 사용 방식, 가격·시장 데이터 authority, 신호 이후 체결 시점
의미론, 거래비용·세금·슬리피지, 포트폴리오 자금배분·position sizing·동시
보유·현금 부족 처리, 평가 종료, equity curve, 총수익률·CAGR·MDD·exposure·
turnover 및 benchmark 비교의 전략 중립적 산출 의미론이 포함된다.

Fundamentals Filter와 그 cutoff·threshold·score·종목 제외, FastCore 전용
ranking·종목 선택, 새로운 시장 국면 제한, 진입·보유·청산·재진입 조건 및
전략 threshold는 위 공통 실행조건에 포함되지 않으며 Julia에 자동 승계하지
않는다. Julia V00의 전략 차이는 계속 Pre-PROGRESSED Loss Guard ON/OFF
하나로 제한한다.

`scripts/run_fastcore_vs_julia_portfolio_v01.py` 및 과거 200M 비교 계약은
공식 실행계약이 아닌 구현 참고 자료로만 보존한다. 현재 공식 조건은
`realistic_backtest_common_conditions_v01.md`의 `C0=200,000,000 KRW`,
`q=5,000,000 KRW`, `N=40`, 비용·세금·슬리피지 및 현금 처리 계약을
사용한다. 과거 `GROSS / NO_COST_MODEL` 조건과 `mcap-only` gate, proxy
fallback은 공식 Julia 검증에 사용하지 않는다.

### H.2 Risk

- Maximum Drawdown
- 거래별 MAE 평균·중앙값 및 분포
- terminal return 기준 큰 손실 건수·비율
- 기존 공식 경계의 손실 bucket: `< 0`, `<= -10%`, `<= -15%`, `<= -20%`,
  `<= -30%`
- open-at-cutoff 손실 및 해당 거래의 MAE

`-15%`는 V2 guard trigger이자 기존 경계이다. `-20%`, `-30%`는 기존
Pattern A/FastCore 공식 위험 보고에서 사용한 tail 경계이다. 새 손실
임계값은 결과를 본 뒤 추가하지 않는다.

### H.3 Upside

- MFE 평균·중앙값 및 분포
- 기존 winner 경계의 terminal return bucket: `>= +20%`, `>= +30%`,
  `>= +50%`, `>= +100%`
- V2에서 Loss Guard로 종료되었지만 Julia에서 회복된 matched entry
- Julia에서만 장기 추세 또는 큰 상승으로 이어진 entry
- V2가 조기 종료하여 Julia의 상승 경로를 보존한 사례

`+20%`, `+30%`, `+50%`, `+100%`는 기존 공식 right-tail 보고 경계이며,
새 winner threshold를 튜닝하지 않는다.

### H.4 Trading 및 holding

- 거래 수와 고유 ticker 수
- 평균·중앙 보유기간
- 일별 invested market value / equity 기반 exposure 비율
- 확정된 공통조건의 turnover 정의 및 initial capital 대비 turnover ratio
- cutoff 시점 open position 수와 금액
- guard 종료, Exit 3, Exit 4, cutoff open 등 exit type 분포

## I. 실패 사례와 부작용 점검

결과표에는 다음 사례군을 개별 row와 재현 가능한 identity로 포함한다.

- Julia에서만 발생하는 `<= -20%`, `<= -30%` 손실과 깊은 MAE
- V2는 guard로 종료했지만 Julia에서 손실이 확대된 matched entry
- V2 guard 종료 후 Julia가 상승을 회복한 matched entry
- Julia에서 PROGRESSED에 도달하지 못하거나 장기 capital lock-up이 발생한
  entry
- 큰 손실 상태로 cutoff까지 열려 있는 position
- V2의 조기 종료가 Julia의 `>= +20%`, `>= +50%`, `>= +100%` winner를
  훼손한 사례
- period, market, sector, ticker별 거래·손실·winner 집중
- 동일 ticker의 재진입이 손실 tail 또는 exposure를 비정상적으로 키우는 사례

사례 분석은 규칙을 고치기 위한 즉시 튜닝이 아니다. 특정 부작용을 해결하려면
Julia V00을 사후 수정하지 않고 새 후보 ID와 새 검증 계획으로 생애주기
2~4단계를 다시 거친다.

## J. 필요한 최소 강건성 검증

파라미터 sweep, 새 threshold 탐색, 별도 market regime 모델, winner 제거
실험은 수행하지 않는다. 이번 공식 검증의 강건성 범위는 다음으로 고정한다.

1. **연도별**: 2021, 2022, 2023, 2024, 2025, 2026 YTD(`2026-08-14`까지)
2. **시장별**: KOSPI / KOSDAQ
3. **종목 집중도**: 동일 종목의 모든 독립 거래 손익을 합산한 누적 손익
   기여 상위 10개 종목의 전체 손익 기여도
4. **대형 수익 거래 집중도**: 개별 종료 거래 기준 수익 기여 상위 10개
   거래의 총이익 기여도
5. **대형 손실 거래 집중도**: 개별 종료 거래 기준 손실 기여가 가장 큰
   10개 거래의 총손실 기여도
6. **세 결과축 분리**: 동일 진입, 순차 운용, 현실적 포트폴리오 결과를
   하나로 합치지 않고 각각 보고한다.

기존 tail-risk 진단의 `<= -20%`, `<= -30%`, MAE, winner bucket 및
Loss Guard 회복 사례는 유지한다. 최근 하위 구간, 강세·약세·횡보 국면
분해, extreme winner 제거는 추가하지 않는다.

## K. 사전 동결 판정 기준

판정 기준은 결과표를 보기 전에 동결한다. 단일 평균, 단일 winner, 단일
ticker를 근거로 판정하지 않는다. 현재 V2 canonical authority인
`docs/patterns/pattern_a_fast/strategy/version_02/README.md`의
`LARGE_LOSS_MINIMIZATION` 우선 및 `PRESERVE_SUFFICIENT_UPSIDE` 차순위
투자 원칙을 Julia에도 그대로 적용한다.

1. `Return <= -30%` 발생률
2. `Return <= -20%` 발생률
3. MAE deep tail 및 최악 MAE
4. Adverse Excursion P75/P90
5. Peak Giveback
6. Terminal Return
7. Winner Truncation 비용

이 순서는 새 숫자 threshold가 아니다. 위험 판단은 V2 canonical authority의
투자 원칙과 손실 규모 우선 원칙을 따르며, 과거
`docs/patterns/pattern_a_fast/validation_plan/strategy_finalization_v01.md`는
역사적 배경 자료로만 참고한다. 현재 V2 규칙 authority를 이 과거 문서로
대체하지 않는다.

### K.1 채택 (`ADOPT`) — 적용 결과: 일반 종목 채택하지 않음

다음 조건을 모두 만족할 때만 Julia의 공식 전략 채택을 검토한다. 최종
비교 결과 이 문서의 risk-first 기준에서 Julia는 일반 종목 공식 전략으로
채택하지 않는다.

1. 데이터 기준 경로, PIT, 미래 정보 유입, 동일 조건, 재현성 및 강건성 gate에
   중대한 실패가 없다.
2. matched와 sequential 비교 모두에서 Loss Guard 제거가 핵심 질문의
   상승 여력 보존 측면에서 재현 가능한 개선을 보인다.
3. `MFE`, winner bucket, guard 회복 및 장기 추세 사례가 소수 extreme
   winner 하나에만 의존하지 않는다.
4. 위에 고정한 risk-first 우선순위로 `<= -20%`, `<= -30%`, MAE, MDD,
   open-at-cutoff 및 장기 자금 묶임을 검토한 결과를 함께 설명할 수 있다.
5. 상승 여력 보존이 `Return <= -20%`, `Return <= -30%`, Deep MAE 또는
   Worst MAE의 구조적 악화를 대가로 얻은 것이 아니며, 기존 V2의
   risk-first mandate를 충족한다.

새 숫자 threshold가 필요해지는 경우에는 `검토 필요`로 남기고 현 실행에서
적용하지 않는다. 단일 수익률 지표만으로 채택하지 않으며, 단일 위험 지표
하나만으로 자동 폐기하지도 않는다.

### K.2 수정 후 재검증 (`REVISE_AND_RERUN`)

아이디어 자체는 유망하지만 데이터 기준 경로 불일치, 명확한 계약 결함,
또는 사전에 정의한 특정 부작용을 해결하기 위해 규칙 변경이 필요할 때
사용한다. V00을 덮어쓰지 않고 새 후보 ID, 새 단일 변경점, 새 계획을 만든다.

### K.3 보류 (`HOLD`)

PIT 커버리지, 가격 기준 경로, 포트폴리오 집계, execution support,
재현성 또는 강건성 증거가 완결되지 않거나 결과 방향이 혼재하여 공식
채택·폐기를 정당화할 수 없을 때 보류한다.

### K.4 폐기 (`DISCARD`)

상승 여력 보존의 재현 가능한 개선이 없거나, 기존 V2 risk-first 우선순위에
비추어 Julia의 `Return <= -20%`, `Return <= -30%`, Deep MAE 또는 Worst MAE가
구조적으로 악화되면 폐기한다. MDD의 소폭 악화나 일반 손실 거래 수 증가만으로
자동 폐기하지 않으며, 단일 위험 지표 하나만으로도 결정하지 않는다.
matched·sequential·강건성 결과를 함께 확인한다. 폐기하더라도 V2 기본 전략은
별도 정책 변경 전까지 유지한다.

Julia 전용 위험 허용 예외나 별도 사용자 결정 절차는 만들지 않는다. 기존 V2
`LARGE_LOSS_MINIMIZATION` 및 `PRESERVE_SUFFICIENT_UPSIDE` mandate를 변경하려면
이 검증과 별도의 정책 변경이 필요하며, 현재 Julia 검증에서는 mandate 예외를
적용하지 않는다.

## L. 과거 연구의 사용 한계

다음 자료는 연구 배경과 실패 모드 확인에만 사용한다.

- `docs/strategies/julia/v00.md`: 공식 PIT가 완성되지 않은 중단 연구
- `docs/strategies/julia/proxy_market_cap_v01.md`: 예상 시가총액 proxy 연구
- 과거 KODEX 200, 시장 ETF, sector ETF 및 21 ETF 비교
- 기존 Julia 관련 결과 artifact 및 과거 실행 요약

이 자료는 공식 Julia 결과, 공식 임계값, 공식 기간, 모집단, adoption
판정의 근거로 사용하지 않는다. 과거 수치는 이번 계획서에 재계산하거나
재삽입하지 않는다.

## M. 예정 산출물과 제출 경계

Stage 4가 완료·동결되고 별도 실행 지시가 있을 때만 아래 artifact를
정해진 폴더에 생성한다. 현재 작업에서는 폴더나 파일을 생성하지 않는다.

`artifacts/strategies/julia/official_validation_v01/`

1. `execution_contract.json`: source, population, PIT, period, identical
   conditions, cost/slippage, aggregation 및 hash
2. `aggregate_summary.json`: 전체 지표와 `Julia - V2` 차이
3. `matched_entry_comparison.csv`: 공통 entry paired comparison
4. `sequential_comparison.csv`: 전략별 실제 재진입 경로 비교
5. `failure_and_big_loss_cases.csv`: 실패·큰 손실·winner 보존 사례
6. `validation_report.md`: 결과, 제한, 강건성 및 사전 판정

### Stage 4 확정 상태

다음 항목은 Stage 4에서 최종 동결됐다.

- 공식 기간: `2021-01-01` ~ `2026-08-14`, final valuation은 `2026-08-14` CLOSE
- 기준 전략: `PATTERN_A_FAST_FINAL_STRATEGY_V02`
- 후보 전략: `JULIA_STRATEGY_V00`
- 단일 전략 차이: Pre-PROGRESSED `-15% Loss Guard` ON/OFF
- 데이터 authority: `MarketDataRepositoryV2`, historical Population/PIT,
  `fail-closed` 결측 의미론
- 비교축: `Matched-entry`, `Sequential`, `Realistic 200M Portfolio`
- 현실적 공통조건: `realistic_backtest_common_conditions_v01.md`의 확정값
- Fundamentals: 이번 공식 V2 ↔ Julia 검증 범위에서 제외. production 기능은
  변경하지 않는다.

이 문서의 공식 상태는 `STAGE_4_FROZEN`이며, Stage 4는 완료·동결됐다. 이는
Julia 공식 전략 채택이나 기본 전략 승격을 의미하지 않는다.

### Stage 5 실행 전 구현 조건 (역사적 계획 기록)

1. **PIT runner 연결 구현**: 생존편향 방지 effective Population/PIT 기준
   경로는 확정되어 있다. 현재 Julia 비교 runner가 이를 직접 소비하도록
   연결하고, current-list broadcast나 nearest-date fallback이 없음을
   실행 contract와 무결성 gate로 확인해야 한다. 이번 작업에서는 runner를
   수정하지 않는다. 이 항목은 Stage 4의 실행조건 미확정과 구분되는 Stage 5
   실행 전 구현 조건이다.

당시 Stage 5 실행 전에는 runner가 survivorship-safe effective Population/PIT
authority를 직접 소비하도록 연결하고, current-list broadcast와
nearest-date fallback이 없음을 execution contract와 무결성 gate로 확인한다.
이 항목은 Stage 4 미완료 사유가 아니다.

이 문단은 Stage 5 실행 전의 통제 조건을 보존한 것이다. 실제 Stage 5 최종
비교는 위의 현재 결정 업데이트에 기록된 범위로 완료되었으며, Julia의 일반
종목 공식 채택이나 V2 기본 전략 승격은 이루어지지 않았다.
