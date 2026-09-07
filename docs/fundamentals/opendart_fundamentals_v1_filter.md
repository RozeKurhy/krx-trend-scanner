opendart_fundamentals_v1_filter.md
===================================

목적
----
F2 MultiPeriodFundamentalsResult와 F3 DerivedMetricsResult의 정본 관측값만
사용해 일반 기업(NON_FINANCIAL)의 Fundamentals Filter V1을 평가한다.
이 계층은 OpenDART, 네트워크, 스캐너, 리포트 생성기를 직접 호출하지 않는다.

적용 범위
----------
FINANCIAL 기업은 항상 NOT_APPLICABLE이며 passed=false이다. 금융업에 같은
매출/이익 기준을 적용하지 않는다. ROE, 부채비율, OCF, 전략 threshold는 이
필터의 조건이 아니다.

고정 조건
---------
NON_FINANCIAL 기업은 아래 네 조건을 모두 만족해야 PASS이다.

  1. F2의 latest_fy가 가리키는 최신 V1 usable FY revenue >= 50,000,000,000 KRW
  2. F2의 latest_quarter가 끝점인 최신 4개 연속 standalone quarter revenue의
     평균 >= 10,000,000,000 KRW
  3. F3가 이미 계산한 최신 TTM operating_income > 0
  4. F3가 이미 계산한 최신 TTM net_income > 0

매출 두 기준은 경계값을 포함하고, 영업이익/순이익은 0을 통과시키지 않는다.
최신 분기가 누락되면 이전 분기 네 개를 당겨 쓰지 않고 DATA_UNAVAILABLE이다.
분기 중간의 빈 identity도 압축하지 않는다.

정본 및 일관성 규칙
--------------------
  * FY와 분기 revenue는 F2의 latest_fy/latest_quarter 및 슬롯 상태를 따른다.
  * TTM 영업이익/순이익은 F3 metric_type=TTM 관측값만 읽는다. F4에서 분기
    합산이나 재계산을 하지 않는다.
  * revenue와 TTM 이익의 latest endpoint가 다르면 DATA_UNAVAILABLE이다.
  * F2/F3 requested_as_of가 다르거나 required 관측값이 READY가 아니거나,
    period/basis/currency/PIT 판정이 모호하면 DATA_UNAVAILABLE이다. 원본
    상태와 reason은 diagnostics에 보존한다.
  * 더 오래된 FY/분기 또는 다른 데이터 제공자에 대한 조용한 fallback은 없다.

상태와 사유
-----------
주 상태 우선순위는 다음과 같다.

  DATA_UNAVAILABLE > NOT_APPLICABLE > FILTERED_ANNUAL_REVENUE >
  FILTERED_QUARTERLY_REVENUE > FILTERED_OPERATING_LOSS > FILTERED_NET_LOSS > PASS

여러 조건이 동시에 실패하면 reasons에 모든 필터 사유를 보존하고 status에는
위 우선순위의 첫 상태를 기록한다. DATA_UNAVAILABLE이면 passed=false이다.

기본 설정
---------
  annual_revenue_min = 50,000,000,000
  quarterly_avg_revenue_min = 10,000,000,000
  require_positive_ttm_operating_income = true
  require_positive_ttm_net_income = true

검증 경계
---------
테스트는 PASS, 각 임계값의 미만/동일/초과, 양의 이익의 strict boundary,
연속 분기 누락/최신 분기 누락, endpoint mismatch, as-of mismatch, 비 READY
상태 보존, 금융업 NOT_APPLICABLE, 사용자 설정 및 JSON 직렬화를 고정한다.
