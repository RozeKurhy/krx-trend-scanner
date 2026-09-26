# 종목 리포트 계약 v0.2 (기반 계약)

## 1. 목적

이 계약은 KRX 상장 개별 종목의 다음 정보를 기계가 읽는 JSON과 사람이 읽는
Markdown으로 함께 제공하기 위한 공통 규약이다. 리포트는 외부 네트워크 요청
없이 로컬 가격 데이터와 확정된 정본 산출물만 조회해 만든다.

1. 현재 기술적 국면 (Pattern A 점수와 단계)
2. 투자 유동성 조건 (Phase 10 투자 적격성)
3. A FAST Core V2 공식 전략의 상태와 행동
4. Pattern A FAST 주별 조기 신호
5. 과거 월별 점수·국면 변화
6. 외국인 수급 확증 (Phase 11)
7. 거래대금 추세

이 문서는 현재 종목 리포트 계약의 기반이다. 이후 버전은 이 계약을 바꾸지
않고 섹션을 더한다. v0.3은 시장 RS, v0.4는 업종 RS, v0.5는 펀더멘털을
추가한다. 전체 구성과 읽는 순서는 [종목 리포트 안내](README.md)에서 확인한다.

v0.2에서 정한 사항은 다음과 같다.

- 공식 전략 `PATTERN_A_FAST_FINAL_STRATEGY_V02`(A FAST Core V2, 패스트 코어
  V2)의 현재 상태, 가상 전략 포지션, 다음 거래일 행동, 진입 조건 점검표,
  보호 상태, 재진입 상태, 전략 이력을 최상위 섹션 `a_fast_core`로 제공한다.
- 리포트 노출 상태를 의사결정 지원 운영 상태(`PRODUCTION_DECISION_SUPPORT`)로
  정한다. 자동 매매가 아니라 의사결정을 돕는 리포트다.

## 2. 핵심 원칙

1. **외부 네트워크 요청 없음**: 리포트 생성 중 KRX, PyKRX, Yahoo, Naver 등
   외부 네트워크를 요청하지 않는다. 로컬 가격 데이터와 확정된 정본 산출물만
   사용한다. 가격 데이터 원천은 [v0.4 계약](contract_v04.md)을 따른다.
2. **공식 전략 규칙 재사용**: `PATTERN_A_FAST_FINAL_STRATEGY_V02`의 동결
   규칙(진입, -15% 손실 방어, Exit 3, Exit 4, Coverage, 재진입, 상태 초기화)을
   그대로 적용하며 리포트 전용 규칙을 만들지 않는다.
3. **시점 기준(PIT)과 미래 정보 차단**: 분석 기준일(`requested_as_of`) 이하의
   시계열만 잘라 평가하며 미래 거래일, 미래 시가, 미래 월봉을 참조하지 않는다.
4. **가상 전략 포지션 명시**: 전략 포지션은 사용자의 실제 계좌 잔고가 아니라
   A FAST Core V2 규칙을 따른 가상 전략 경로(`Canonical Strategy Position`)임을
   명시한다.
5. **규칙 기반 서술**: 요약문과 해석 문구는 상태·사유 코드에 따른 고정
   템플릿으로 만들어 같은 입력에서 항상 같은 결과를 낸다. 자유 생성 문장을
   쓰지 않는다.
6. **결측 명시**: 결측 데이터는 `null` 또는 `DATA_UNAVAILABLE`로 표기하고
   결측 사유를 적는다.
7. **의사결정 지원 한정**: 매수·매도 추천, 목표가, 수익 보장 표현을 쓰지 않고
   전략 의사결정을 돕는 정보만 제공한다.

## 3. JSON 스키마 (v0.2)

아래 블록은 v0.2 JSON 구조를 사람이 읽기 위한 사본이다. 기계 검증용 스키마는
[schema_v02.json](schema_v02.json)이다.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "StockReport_v0.2",
  "type": "object",
  "required": [
    "report_version",
    "ticker",
    "name",
    "market",
    "asset_type",
    "requested_as_of",
    "reference_market_date",
    "header",
    "summary",
    "current_snapshot",
    "a_fast_core",
    "pattern_a_fast",
    "monthly_history",
    "foreign_flow",
    "trading_value_flow",
    "data_quality",
    "provenance"
  ],
  "properties": {
    "report_version": { "type": "string", "enum": ["0.2"] },
    "ticker": { "type": "string", "pattern": "^[0-9A-Z]{6}$" },
    "name": { "type": "string" },
    "market": { "type": "string", "enum": ["KOSPI", "KOSDAQ", "KONEX", "UNKNOWN"] },
    "asset_type": { "type": "string", "enum": ["COMMON", "PREFERRED", "SPAC", "REIT", "ETF", "ETN", "OTHER", "UNKNOWN"] },
    "requested_as_of": { "type": "string", "format": "date" },
    "reference_market_date": { "type": "string", "format": "date" },
    
    "header": {
      "type": "object",
      "required": ["ticker", "name", "market", "asset_type", "requested_as_of", "reference_market_date", "cache_present", "report_status"],
      "properties": {
        "ticker": { "type": "string", "pattern": "^[0-9A-Z]{6}$" },
        "name": { "type": "string" },
        "market": { "type": "string", "enum": ["KOSPI", "KOSDAQ", "KONEX", "UNKNOWN"] },
        "asset_type": { "type": "string", "enum": ["COMMON", "PREFERRED", "SPAC", "REIT", "ETF", "ETN", "OTHER", "UNKNOWN"] },
        "requested_as_of": { "type": "string" },
        "reference_market_date": { "type": "string" },
        "effective_as_of": { "type": ["string", "null"] },
        "cache_present": { "type": "boolean" },
        "cache_last_date": { "type": ["string", "null"] },
        "report_status": { "type": "string", "enum": ["READY", "PARTIAL", "DATA_UNAVAILABLE"] }
      }
    },
    
    "summary": {
      "type": "object",
      "properties": {
        "headline": { "type": "string" },
        "strategy_headline": { "type": ["string", "null"] },
        "bullet_points": { "type": "array", "items": { "type": "string" } },
        "combined_narrative": { "type": "string" }
      }
    },
    
    "current_snapshot": {
      "type": "object",
      "required": ["official_stage", "candidate_state", "is_candidate", "investability_status", "investability_reason", "is_investable"],
      "properties": {
        "pattern_a_score": { "type": ["number", "null"] },
        "official_stage": { "type": "string", "enum": ["WEAK", "BASE", "TRANSITION", "EARLY_TREND", "PROGRESSED", "UNAVAILABLE"] },
        "candidate_state": { "type": "string", "enum": ["candidate", "watch", "late", "blocked", "insufficient_data"] },
        "is_candidate": { "type": "boolean" },
        "market_cap_eok": { "type": ["number", "null"] },
        "avg_trading_value_20d_eok": { "type": ["number", "null"] },
        "investability_status": { "type": "string", "enum": ["INVESTABLE", "FILTERED_MARKET_CAP", "FILTERED_LIQUIDITY", "DATA_UNAVAILABLE"] },
        "investability_reason": { "type": "string" },
        "is_investable": { "type": "boolean" },
        "market_cap_effective_date": { "type": ["string", "null"] },
        "market_cap_source": { "type": ["string", "null"] }
      }
    },
    
    "a_fast_core": {
      "type": "object",
      "required": [
        "strategy_id",
        "strategy_version",
        "strategy_alias",
        "strategy_status",
        "production_status",
        "fresh_oos_status",
        "as_of",
        "applicability",
        "strategy_state",
        "canonical_position",
        "action",
        "action_reason",
        "interpretation",
        "provenance",
        "metadata_provenance_mode"
      ],
      "properties": {
        "strategy_id": { "type": "string", "enum": ["PATTERN_A_FAST_FINAL_STRATEGY_V02"] },
        "strategy_version": { "type": "string", "enum": ["V02"] },
        "strategy_alias": { "type": "string", "enum": ["A FAST Core"] },
        "strategy_status": { "type": "string", "enum": ["FINAL_STRATEGY_FROZEN"] },
        "production_status": { "type": "string", "enum": ["PRODUCTION_DECISION_SUPPORT"] },
        "fresh_oos_status": { "type": "string", "enum": ["NOT_EXECUTED"] },
        "as_of": { "type": "string", "format": "date" },
        "applicability": { "type": "string", "enum": ["APPLICABLE", "NOT_APPLICABLE", "DATA_UNAVAILABLE"] },
        "strategy_state": { "type": "string", "enum": ["ENTRY", "HOLD_PRE_PROGRESSED", "HOLD_PROGRESSED", "EXIT", "WAIT", "NOT_APPLICABLE", "DATA_UNAVAILABLE"] },
        "canonical_position": { "type": "string", "enum": ["FLAT", "OPEN", "NOT_APPLICABLE", "DATA_UNAVAILABLE"] },
        "action": { "type": "string", "enum": ["ENTER_NEXT_OPEN", "HOLD", "EXIT_NEXT_OPEN", "WAIT", "NONE"] },
        "action_reason": { "type": "string" },
        "execution_timing": { "type": ["string", "null"] },
        "interpretation": { "type": "string" },
        "entry_conditions": { "type": ["object", "null"] },
        "current_trade": { "type": ["object", "null"] },
        "protection_state": { "type": ["object", "null"] },
        "reentry_state": { "type": ["object", "null"] },
        "metadata_provenance_mode": { "type": "string", "enum": ["CURRENT_VERIFIED", "HISTORICAL_LEGACY_RESEARCH", "DATA_UNAVAILABLE"] },
        "trade_history": { "type": "array" },
        "provenance": { "type": "object" }
      }
    },
    
    "pattern_a_fast": { "type": "object" },
    "monthly_history": { "type": "object" },
    "foreign_flow": { "type": "object" },
    "trading_value_flow": { "type": "object" },
    "data_quality": { "type": "object" },
    "provenance": { "type": "object" }
  }
}
```

## 4. Markdown 구성 (v0.2)

v0.2 리포트 Markdown은 다음 순서의 절로 구성한다. 절 제목은 생성 코드가
출력하는 문구 그대로 적었으며, `(신호 라벨)` 자리에는 실제 신호 라벨이
들어간다. 이후 버전에서 추가된 절을 포함한 전체 목차는
[종목 리포트 안내](README.md)에서 확인한다.

1. `0. 핵심 요약 (Executive Summary)`
2. `1. 현재 기술적 국면 & 투자 적격성 스냅샷 (Current Snapshot)`
3. `2. 패스트 코어 V2 전략 상태 (A FAST Core V2 Strategy State)`
4. `3. Pattern A FAST 현재 신호 (신호 라벨)`
5. `4. Pattern A Monthly History — 최근 12개월 월별 추이 (Recent 12M Trajectory)`
6. `5. Pattern A 국면 전환 이력 (Stage Transition History)`
7. `6. Pattern A FAST Weekly History (신호 라벨)`
8. `7. 외국인 수급 확증 (Foreign Flow Analysis - Phase 11)`
9. `8. 거래대금 추세 분석 (Trading Value Flow)`
10. `9. Pattern A 전체 월별 이력 (Full Monthly History)`
11. `10. 데이터 품질 및 신원 (Data Quality & Provenance)`

## 5. 전략 운영 상태와 메타데이터 신뢰 모드

`a_fast_core`에는 의미가 다른 상태 필드 두 개가 함께 있다. 둘을 혼동하지
않는다.

**`production_status`**는 전략 자체의 운영 단계다.
`PATTERN_A_FAST_FINAL_STRATEGY_V02`가 개발·백테스트 단계를 지나 실제 의사결정
지원 용도로 승격됐다는 사실을 나타낸다. 값은 항상
`"PRODUCTION_DECISION_SUPPORT"`이며, 개별 리포트가 아니라 전략의 속성이다.

**`metadata_provenance_mode`**는 개별 리포트가 사용한 종목 메타데이터의 신뢰
근거다. 값은 세 가지다.

- **현재 검증됨 (`CURRENT_VERIFIED`)**: `requested_as_of` 시점의 종목
  메타데이터가 KRX 공식 원천으로 검증됐다(`classification_authority ==
  asset_type_source == "FORMAL_SECURITY_TYPE"`). 이 리포트는 현재 의사결정
  지원에 쓸 수 있는 메타데이터 근거를 가진다.
- **과거 연구용 (`HISTORICAL_LEGACY_RESEARCH`)**: 해당 시점 메타데이터가 공식
  검증되지 않았지만(`LEGACY_UNVERIFIED`), 과거 시점을 명시적으로 조회하는 회고
  질의로 인정되어 전략 상태를 계산했다. **회고 연구 전용이며, 이 과거 리포트는
  의사결정 지원 근거가 아니다.**
- **판단 불가 (`DATA_UNAVAILABLE`)**: 메타데이터가 없거나(`UNKNOWN`), 공식
  검증도 과거 동결 PIT 스냅샷도 아닌 다른 근거(`LEGACY_HEURISTIC`,
  `NAME_BASED_HEURISTIC` 등)이거나, `asset_type`이 `UNKNOWN`이라 신뢰 근거가
  부족하다.

**중요**: `production_status = "PRODUCTION_DECISION_SUPPORT"`이면서
`metadata_provenance_mode = "HISTORICAL_LEGACY_RESEARCH"`인 리포트가 정상적으로
있을 수 있다. 이 경우 **그 과거 리포트는 투자 판단 근거가 아니다.**
`production_status`는 전략이 성숙했다는 사실만 말한다. 개별 리포트를 지금 매매
판단에 쓸 수 있는지는 `metadata_provenance_mode`가 결정한다.
`production_status`만 보고 개별 리포트를 현재 사용할 수 있는 신호로 해석하지
않는다.
