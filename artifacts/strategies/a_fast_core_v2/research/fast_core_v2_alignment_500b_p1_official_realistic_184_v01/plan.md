# FAST Core V2 Alignment + 500B — P1 공식 실전형 포트폴리오 계획 V01

- 작업 ID: `FAST_CORE_V2_ALIGNMENT_500B_P1_OFFICIAL_REALISTIC_184_V01`
- 저장소: `RozeKurhy/krx-trend-scanner`
- 시작 기준 HEAD / `origin/main`: `d2b9dd6a6ae7ee3eee4e1840c3b41068d72237c6` (실행 직전 재확인)
- 입력 지시서: `/Users/june/Documents/projects/w.md`
- 출력: `artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p1_official_realistic_184_v01/`

## 목표와 범위

P1 한 기간만 대상으로 동결 `PATTERN_A_FAST_FINAL_STRATEGY_V02` CONTROL과 같은 V2에 진입 조건으로 월봉 정배열 및 당일 KRX 시가총액 500B 하한을 추가한 `ALIGNMENT_MCAP_500B` 후보를 비교한다. P2/P3 replay, 운영·웹 수정, 다섯 기간 종합 채택 및 기본 전략 승격은 실행하지 않는다.

## 실행 전에 확인할 기준

실제 저장소 버전의 백테스트 공통 원칙 §2.1–2.6, §3.1, §4–5, 공식 A~E 기준, V2 생애주기·동결 전략 문서, frozen evaluator, 영구 제외 registry와 P3/P2 공식 선행 계약 및 산출물을 읽고 SHA-256을 기록한다. 충돌이 있거나 P1 기간/원천 범위를 확인할 수 없으면 전수 replay 전에 원인과 영향 범위를 기록하고 `CHECK_REQUIRED`로 멈춘다.

## 기간과 전략

- 달력 범위: 2014-01-01~2026-08-31. 실제 시작일 및 정확한 세션 수는 검증된 rolling KRX 거래 달력으로 결정한다.
- 신호/NAV cutoff: 2026-08-31. 기존 포지션의 cutoff 이전 청산 신호만 2026-09-01 시가로 체결 지원한다. 신규 진입과 지원일 손익·비용은 P1 성과에서 제외한다.
- 두 군 모두 같은 PIT COMMON 분모와 정확 184개 `(ticker, standard ISU_CD)` 영구 제외를 적용한다. registry 외 성과 기반 제외는 금지한다.
- CONTROL은 동결 V2 원형이다. 후보는 진입 허가 단계에서만 신호일 조정종가 `> 이전 완료 월봉 MA20 > 이전 완료 월봉 MA60` 및 동일 날짜·정확 PIT identity의 KRX `MKTCAP >= 500,000,000,000 KRW`를 요구한다. MA60 입력 부족은 그 신호만 거절한다.
- P1 초기 자본 200,000,000원, 주문별 총예산 5,000,000원(매수 수수료 포함), 양쪽 슬리피지 0.1%, 양쪽 수수료 0.015%, 공식 거래세 0. 매수 정수주, 주문 전액 현금 부족 시 전량 생략, 매도대금 T+1 사용, 인위적 보유 수 제한 없음.

## 실행 순서

1. 원격 기준선, 문서·전략·registry hash, 184쌍 canonical hash, P1 exact KRX calendar와 cutoff 지원일을 확인한다.
2. rolling PIT COMMON, 조정 Repository V2, KRX raw 날짜×시장 시총 자료의 실제 첫·마지막 사용 가능 날짜와 원천 해시를 전수 점검한다. 2014년을 검증할 수 없으면 기간을 임의로 바꾸지 않고 근거와 영향을 보고한다.
3. 별도 P1 디렉터리에 계약, 계획, preflight와 입력 manifest를 먼저 봉인한다. 동결 V2·P1 후보 필터·포트폴리오 코드 경로의 소스 해시와 기존 P2/P3 contract 동일성을 저장한다.
4. 약 30개 결정적 표본을 같은 evaluator/portfolio 경로에서 끝까지 실행한다. 초기 MA60 미가용, 정확 identity 이력/시장 이전, 제외 pair leakage, 가격 원천 예외 및 시총 필터 경계를 포함한다. worker, 전략 상태, 체결, 비용, 현금, T+1, 거래/NAV 원장 invariant 및 예상 전수 시간을 검증한다. P2-1 runner의 `available_count` 선할당 오류를 재사용하지 않는다.
   첫 표본은 3.455시간으로 추정돼 실행시간 규칙의 2시간 점검선을 넘었다. 실제 프로파일에서 같은 ticker/context/month의 완료 월봉 snapshot과 Pattern A 평가가 CONTROL·후보 및 후속 거래 구간에 반복 생성되는 것을 확인했다. P1 실행기에서만 동일한 ticker/context/month의 순수 결과를 memoize했고 첫 의미 산출물 23개 hash가 전부 일치했지만 예상시간은 3.206시간이었다. Python thread worker의 CPU 병렬성이 낮은 것도 측정돼, 동일한 10 worker 한도를 유지하면서 불변 Repository V2/PIT/calendar context를 copy-on-write로 상속하는 프로세스 worker로 바꾸고 다시 표본 검증한다. 전략 계산, 상태 전이, 입력값 및 순차 portfolio replay는 바꾸지 않는다.
5. 표본 구조 검증과 실행시간 gate가 통과하면 CONTROL/후보 각각 P1 전체 신호 원장을 만든 뒤 단일 순차 시간순 portfolio replay를 각 1회 수행한다. 전수 worker 오류나 무결성 실패 시 자동 재실행하지 않는다.
6. 두 그룹의 A~E, P1 절대 MDD -55%, 후보 상대 MDD 악화 5.0%p 경계, NAV coverage와 미해결 mark·기업행위 영향을 독립 계산한다. PASS를 만들기 위한 source 대체, 필터 추가, 평가기간 단축은 하지 않는다.
7. 거래·portfolio·cash·NAV·valuation·missing mark·skip 원장, report, gate, integrity 및 artifact hash를 검증해 저장한다. 결과만 이 P1 디렉터리에 커밋/푸시하며 선행·무관한 로컬 산출물은 포함하지 않는다. 완료 내역은 `/Users/june/Documents/projects/r.md`에 이어 쓴다.

## 보고와 판정

보고서는 원인별 CRITICAL/MAJOR/MINOR, 실제 평가 경계와 세션 수, 2014 장기 원천·MA60 예열 가능 범위, 184쌍 적용, 양 그룹 성과·MDD/NAV·거래·현금/비용 및 A~E 상태를 포함한다. P1 판정과 최종 다섯 기간 채택/기본 전략 승격은 분리하고, 후자는 `NOT_EVALUATED`로 기록한다. 기본 전략은 V2를 유지한다.
