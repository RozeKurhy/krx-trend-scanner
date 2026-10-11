# FAST Core V2 Alignment + 500B — P3-2 포트폴리오 검증 계획

- 작업 ID: `FAST_CORE_V2_ALIGNMENT_500B_P3_2_OFFICIAL_REALISTIC_PORTFOLIO_V01`
- 봉인일: 2026-10-12 (Asia/Seoul)
- 기준 커밋: 실행 시 `preflight.json`의 HEAD 및 `origin/main`
- 범위: P3-2 한 기간, 공식 V2 CONTROL 대 Alignment + signal-date KRX market cap 500B 이상 후보
- 상태: `PLAN_SEALED_SAMPLE_PENDING`

## 질문과 제약

P3-2에서 월간 정배열과 신호일 시가총액 필터를 추가한 후보를 공식 V2 CONTROL과 실전형 자금 원장으로 비교한다. 이 한 기간 결과만으로 전략을 공식 채택하거나 기본전략으로 승격하지 않는다. 기존 A FAST Core V2는 공식 기본 전략으로 유지한다.

운영 전략 코드·실시간 신호·Strategy Monitor·웹·공식 V2 규칙은 수정하지 않는다. 기존 산출물을 덮어쓰지 않고 이 디렉터리에 연구 코드와 결과만 추가한다. KRX/API 호출 없이 승인된 로컬 Repository V2, rolling PIT/calendar authority 및 exact-date KRX raw partitions를 사용한다. 비밀값은 읽거나 출력하지 않는다.

## 평가 범위

- 평가 및 신규 진입 신호 마감: 2022-01-03 ~ 2026-08-31
- 체결 지원일: 2026-09-01. 8월 31일까지 발생한 exit 신호의 후속 체결만 지원한다.
- 거래일 및 PIT 분모: 현행 rolling authority에서 검증한 KRX 달력 및 각 날짜 COMMON interval
- 양쪽 공통 제외: 현재 승인된 정확한 `(ticker, standard ISU_CD)` permanent identity exclusions만 적용. 실행 시 개수와 소스를 재확인한다.
- 비교군은 두 개뿐이다: (1) unrestricted V2 CONTROL, (2) V2 신호일의 `adjusted close > prior completed monthly MA20 > prior completed monthly MA60` 및 exact signal-date KRX `MKTCAP >= KRW 500,000,000,000`을 모두 충족한 후보.
- MA는 신호월을 제외한 직전 완료 월봉 조정종가 20/60개로 산출한다. 창의 월봉이 누락/부족하면 후보 진입을 거부하고 이유를 기록한다.
- 시총은 exact signal date, market, PIT ticker+ISU identity로만 찾는다. 미싱/중복/비정상 값은 대체하지 않고 `MCAP_UNRESOLVED` 등으로 기록한다.
- 후보 필터 탈락은 공식 V2 재진입 상태를 소비하지 않는다. V2 evaluator의 외부 `entry_signal_filter`를 사용해 체결 신호 전에 필터링한다.

## 공통 실전형 자금 계약

- 초기 자본 KRW 200,000,000; 종목당 총 매수예산(수수료 포함) KRW 5,000,000; 정수주식; 수익금 재투자; 포지션 수 상한 없음.
- 매수·매도는 다음 exact KRX 거래일 시가. 매수/매도 슬리피지 각각 0.1%, 수수료 각 0.015%, 세금 0%.
- 매도대금은 다음 정상 거래일부터 가용. 동일 종목 중복보유, 피라미딩, 동일 시가 청산 후 재진입은 금지한다.
- 동시 진입 순서: ticker, 표준 ISU_CD, signal date, execution date, trade ID 오름차순. 포트폴리오 이벤트 처리는 단일 순차 결정론으로 실행한다.
- 거래 신호 원장은 자금 배분 전에 확정한다. 현금 부족 skip 후 신호를 재생성하지 않는다.
- 일별 equity는 현금+결제대기 매도대금+보유주식 평가액. 허용된 raw placeholder 근거가 없는 가격 결측은 임의 이월하지 않고 전체 해당일 NAV를 관측 제외한다.
- 기준 A~E는 현재 `official_strategy_adoption_criteria.md`를 따른다. P3-2 MDD는 -40% 이상, 후보 상대 MDD 악화폭은 `CONTROL MDD - candidate MDD < 5.0%p`; cash shortage는 판정 게이트가 아닌 진단치다.

## 기존 CONTROL 재사용 판정

`v2_official_adoption_revalidation_mdd_closure_v02`의 계약은 제외정책 변경, 당시 permanent exclusion count 109, delta 66, fallback identity 138 및 survivorship fallback 사용을 기록한다. 이는 이번 P3-2에 적용할 현재 승인된 정확한 181 identity 쌍의 정책 및 unrestricted PIT 분모와 일치하지 않는다. 과거 CONTROL 수치를 새 비교 기준으로 사용하지 않고, 과거 공식 판정은 보존한 채 이번 CONTROL을 후보와 동일한 현대 계약으로 재생한다. 세부 증거는 `control_reuse_audit.json`에 고정한다.

## 실행 순서 및 중단 기준

1. 이 계획·실행 계약·preflight·재사용 판정의 hash를 별도 commit/push한다.
2. 대표 종목의 CONTROL/후보 동일 실행 경로 샘플로 Repository V2 로딩, V2 신호와 필터, 체결·현금·NAV를 확인하고 RSS/CPU/시간을 측정한다.
3. 샘플 처리량으로 전체 2,552개 identity의 예상 시간을 계산한다. 예상 2시간 초과 시 관측 병목과 최소 조치만 확인하고 대규모 실행 전 상태를 기록한다.
4. 사전 기준 및 샘플 무결성이 통과하면 P3-2 전체를 worker 10으로 전략 프레임 생성하고, 포트폴리오 현금/체결은 단일 결정적 순서로 재생한다. 오류 후 자동 전체 재실행하지 않는다.
5. 거래·필터·체결·비용·현금·NAV·valuation carry·cutoff·source hash를 독립 검증하고 A~E 기간별 예비 판정 및 CONTROL 비교표를 만든다.
6. 전체 5기간 평가는 하지 않았으므로 후보 공식 채택/기본 승격은 `NOT_EVALUATED`로 남긴다.
7. 결과를 이 경로와 사용자 지정 `r.md`에 기록한다. 이 산출물 및 필요한 최소 V2 README 링크만 commit/push하고 `HEAD == origin/main`, tracked clean을 확인한다. 기존 unrelated untracked 파일은 stage하지 않는다.

## 필요한 결과물

`report.md`, `summary.json`, `execution_contract.json`, `preflight.json`, `control_reuse_audit.json`, `source_manifest.json`, `candidate_signal_filter_audit.csv`, CONTROL/후보 거래 및 포트폴리오 이벤트·일별 equity·skip·valuation 감사 CSV, `metrics_comparison.csv`, `gate_results.json`, `integrity_audit.json`, `artifact_hashes.json`, 실행 스크립트 및 샘플·전체 실행 로그 요약.

