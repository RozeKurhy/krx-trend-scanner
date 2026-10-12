# FAST Core V2 Alignment + 500B — P2-2 공식 실전형 포트폴리오 백테스트

- 작업 ID: `FAST_CORE_V2_ALIGNMENT_500B_P2_2_OFFICIAL_REALISTIC_PORTFOLIO_V01`
- 상태: `PLAN_SEALED_BEFORE_SAMPLE`
- 기준 브랜치/커밋: `main` / `ac40772e546addb31f9c39b9e6b9ad77f4440444`; 시작 시 `origin/main`과 일치 확인
- 범위: P2-2 단일 기간에서 동결 `PATTERN_A_FAST_FINAL_STRATEGY_V02` CONTROL과 월봉 정배열 + 신호일 시가총액 5,000억 원 이상 필터 후보를 같은 실전형 포트폴리오 계약으로 비교

## 목표와 제한

P2-2의 신호·실제 체결·현금 배분·일별 NAV/MDD 결과와 현재 공식 A~E 기준을 확인한다. 이전 P3 결과는 데이터 로딩·평가 방식의 참고 근거로만 쓰며 P2-2 결과에 합치거나 건수를 맞추지 않는다. P1/P2-1/P3 전체 재실행, 전략 튜닝, 5기간 채택 판정, 후보 채택·기본 전략 승격, 운영/웹 변경, 외부 API 요청은 하지 않는다. 현재 기본 전략 `PATTERN_A_FAST_FINAL_STRATEGY_V02`를 유지한다.

운영/전략 코드는 수정하지 않는다. 새 연구 경로에만 계획·계약·감사·실행 스크립트와 산출물을 저장한다. 사용자 소유의 기존 미추적 파일은 건드리지 않는다. 최종 결과는 저장소 보고서와 사용자가 지정한 `/Users/june/Documents/projects/r.md`에 기록한다.

## 평가 구간과 분모

- 달력 경계: `2021-01-01`~`2026-08-31`.
- rolling production KRX 달력에서 확인한 실제 평가일: `2021-01-04`~`2026-08-31`, 총 `1,387` 세션.
- `2026-09-01`은 8월 31일까지 이미 발생한 청산 신호의 익일 체결 확인만 지원한다. 신규 신호/진입, 지원일 손익·비용·NAV를 P2-2 성과에 포함하지 않는다.
- 후보 정배열 첫 신호의 60개 선행 완료 월봉은 `2016-01`~`2020-12`. 신호월은 MA 산출에서 제외한다. 월봉 결측/부족은 후보 신호 단위 `MA_UNAVAILABLE`로 거절한다.
- V2 자체 지표 예열은 동결 evaluator의 필요 이력(최대 200주 지표 및 월봉 특징)을 만족하도록 확보한다. P2-2의 60개월 MA 예열이 고정 기간 창보다 길며, 실제 bounded start는 각 정확한 COMMON identity의 유효 가격 첫 날과 PIT 구간, 60개월 예열을 함께 고려한다.

## 유니버스와 후보

- validated rolling merged PIT에서 P2-2와 겹치는 `COMMON` 구간만 사용하고, 신호일 `ticker + standard ISU_CD + market`이 정확히 하나일 때만 신호를 통과시킨다. 현재 상장사 생존자 필터·그 밖의 시총/유동성/펀더멘털 필터·임의 보유 상한은 두지 않는다.
- 현행 영구 제외 registry의 정확한 182 `(ticker, standard ISU_CD)` 쌍을 두 그룹의 신호 생성 전에 공통 적용한다. registry 원본 파일 hash와 `sorted_exact_pair_json_v01` canonical hash를 확인한다. 380440 / KR7380440008은 현행 공통 제외 정책에 포함되므로 P2-2 eligible universe에서 제외한다. registry 밖 종목은 가격 성과를 근거로 제외하지 않는다.
- CONTROL은 동결 V2 전체 진입·손실가드·PROGRESSED·Exit3/4·coverage·재진입 규칙 그대로 사용한다.
- 후보는 동일 evaluator에 외부 진입 필터만 적용한다: 신호일 Repository V2 adjusted close `> prior completed MA20 > prior completed MA60` (strict) 및 동일 날짜·동일 시장·정확한 PIT ticker의 KRX raw market cap `>= 500,000,000,000 KRW`. Missing/duplicate/zero/invalid market cap은 `MCAP_UNRESOLVED`로 거절한다. 후보 필터 거절은 V2 재진입 상태를 소비하지 않는다.

## 체결·비용·현금·평가

- 초기 현금 200,000,000원. 종목별 총 매수예산은 수수료 포함 5,000,000원 이하, 정수주 floor, 부분 체결 없음.
- 신호 다음 정확한 KRX 거래일 시가 체결. 매수/매도 슬리피지 각 0.1%, 양쪽 수수료 각 0.015%, 거래세 0%.
- 매도대금은 다음 정규 KRX 거래일부터 사용한다. 같은 시가에 발생한 매도대금은 신규 매수에 사용할 수 없다. 현금 부족은 전체 주문 `SKIPPED_CASH_UNAVAILABLE`; 신호/전략 상태를 재생성하지 않는다.
- 동시 진입 순서: `(ticker, standard ISU_CD, signal_date, execution_date, trade_id)` 오름차순. 종목별 동시 보유·피라미딩·동일 시가 청산 후 재진입 금지. 포트폴리오 이벤트는 단일 순차 결정적 재생으로 처리한다. 신호 평가는 10 workers.
- 일별 NAV = 가용 현금 + 미정산 매도대금 + 미수령 확정 현금 + 보유 정수주 × 그날의 유효 adjusted close. 정상 거래일 mark가 없으면 해당 날짜 전체 NAV를 unresolved로 둔다. 신뢰 가능한 비거래 placeholder에 대한 평가 전용 carry 외의 대체/보간은 금지한다. cutoff 미청산은 8월 31일 mark로 평가하고 가상 청산 비용을 부과하지 않는다.

## 실행 게이트와 순서

1. 본 계획, `execution_contract.json`, `preflight.json`, `source_manifest.json`을 hash로 봉인한 뒤에만 sample 실행을 시작한다.
2. P2-2 exact calendar, 182쌍 제외, PIT COMMON, adjusted/raw availability, 2016~2020 MA60 예열, 2026-09-01 지원 세션을 전수 preflight한다. Repository V2는 identity의 PIT/유효 가격 시작 경계부터 지원일까지 bounded load해 adjusted source가 먼저 끝난 뒤의 raw-only tail도 분류한다. raw placeholder를 adjusted 가격으로 대체하지 않는다. PIT 활성 세션별 양쪽 source 부재와 승인 placeholder는 exact-date audit에 남기고, projection 오류·실제 미해결 mark는 신호/포트폴리오 결과에 영향이 있는지 따로 판정한다.
3. 대표 30개 안팎을 실제 frozen V2 evaluator → candidate filter → 같은 portfolio replay → NAV 경로로 sample 실행한다. 2021 초반, PIT 경계, 재진입, 500B 주변/결측, 과거 bounded-load 문제, 029960·128940·003690 진단 대상과 preflight에서 확인된 모든 비-placeholder source-anomaly ticker를 포함한다. 벽시계/CPU/RSS와 전체 예상시간을 기록한다. 2시간 초과 또는 이상 병목이면 구체 병목과 최소 재사용/캐시 개선안을 먼저 기록하고 full run을 시작하지 않는다.
4. Preflight/sample이 통과하면 P2-2 전체의 signal evaluation을 10 workers로 정확히 1회 수행하고, CONTROL과 후보 포트폴리오를 각 1회 독립 순차 재생한다. 실패 후 자동 전체 재실행하지 않는다.
5. 두 결과 원장의 PIT·필터·비용·현금·T+1·정수주·미청산·NAV·hash를 독립 검산한다. 코엔텍과 과거 NAV 예외 종목은 P2-2 실제 신호/포지션 노출을 별도로 확인한다. 영향 가능한 기업행위/입력 문제가 남으면 임의 정산·대체·제외를 하지 않고 gate에 남긴다.
6. P2-2 A~E만 판정한다. 현금 부족률은 진단값이며 gate가 아니다. 5기간 채택 `NOT_FINAL_5WINDOW`, 후보 채택/기본 승격 `NOT_EVALUATED`로 남긴다.

## 보고와 보존

먼저 CRITICAL/MAJOR/MINOR 독립 문제 유형 수를 제시하고, 이어 실행 범위, PIT/입력 availability, A~E, CONTROL/후보/차이, 전체 필수 지표와 제한점을 한국어로 기록한다. 거래 수·승률·평균/중앙 순수익률·평균/중앙 보유 거래일·대형 승리/손실·최대/최저 수익률·Loss Guard·PROGRESSED·exit reason·cutoff 미청산을 포함한다. 수익률 분모와 관측 MDD/NAV coverage의 의미를 표시한다.

필수 결과는 이 폴더의 `report.md`, `metrics_comparison.csv`, `gate_results.json`, `integrity_audit.json`, `artifact_hashes.json`, sample/preflight/contract/manifests, 두 그룹별 거래·이벤트·현금·skip·일별 NAV·valuation·missing mark CSV, filter audit 및 실행 스크립트다. 이 연구 폴더만 commit/push하고 `git fetch` 후 `HEAD == origin/main`, tracked tree clean을 확인한다.
