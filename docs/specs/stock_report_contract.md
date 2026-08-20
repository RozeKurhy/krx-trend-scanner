# Stock Report Contract v0.2

================================================================================
1. 개요 및 목적 (Overview & Purpose)
================================================================================
Stock Report Contract v0.2는 KRX 상장 개별 종목에 대해 외부 네트워크 요청 없이(Zero Network Request), 로컬 시세 및 정본 아티팩트만을 조회하여 해당 종목의:
1. **현재 기술적 국면 (Pattern A Score & Stage)**
2. **투자 유동성 조건 (Phase 10 Investability)**
3. **A FAST Core V2 공식 전략 상태 및 행동 (A FAST Core V2 Strategy State & Action)**
4. **Pattern A FAST 주별 조기 신호 (Pattern A FAST Early Signal)**
5. **과거 월별 점수/국면 변화 추이 (Historical Monthly Flow)**
6. **외국인 수급 확증 (Phase 11 Foreign Flow)**
7. **거래대금 추세 (Trading Value Trend)**

를 하나의 통일된 기계 판독 데이터 구조(JSON) 및 사람이 읽을 수 있는 문서(Markdown)로 제공하기 위한 공통 인터페이스 규약이다.

v0.2의 핵심 승격 사항:
- 공식 확정 전략인 **`PATTERN_A_FAST_FINAL_STRATEGY_V02` (A FAST Core V2 / 패스트 코어 V2)**의 현재 상태, 가상 전략 포지션(Canonical Strategy Position), 다음 거래일 행동, 진입 조건 체크리스트, 보호 상태, 재진입 상태, 전략 이력을 리포트 최상위 섹션(`a_fast_core`)으로 제공한다.
- 프로덕션 노출 상태를 **`PRODUCTION_DECISION_SUPPORT`**로 공식 승격한다 (의사결정 지원 리포트, 자동 매매 아님).

--------------------------------------------------------------------------------
2. 핵심 불변 원칙 및 가드레일 (Core Principles & Guardrails)
--------------------------------------------------------------------------------
1. **Zero Network Request & Pure Local Execution**:
   - 리포트 생성 과정에서 KRX, pykrx, Yahoo, Naver 등 외부 네트워크 요청을 일절 수행하지 않는다.
   - 로컬 Parquet 일봉 캐시(`data/raw/stocks/{ticker}.parquet`)와 확정된 정본 아티팩트만을 사용한다.
2. **Frozen Production Strategy Contract 재사용 (No Logic Mutation)**:
   - `PATTERN_A_FAST_FINAL_STRATEGY_V02`의 동결 규칙(진입, -15% 손실가드, Exit 3, Exit 4, Coverage, 재진입, 상태 리셋)을 100% 동일하게 적용하며, 리포트 전용 임의 규칙을 생성하지 않는다.
3. **Point-In-Time (PIT) & Strict No-Lookahead**:
   - 임의의 분석 기준일(`requested_as_of`)에 대해 해당 시점 이하의 시계열만을 슬라이싱하여 평가하며, 미래 거래일, 미래 시가, 미래 월봉을 일절 참조하지 않는다.
4. **Canonical Strategy Position 명시**:
   - 전략 포지션은 사용자의 실제 계좌 잔고가 아닌, 패스트 코어 V2 규칙에 따른 가상 전략 경로(`Canonical Strategy Position`)임을 명시한다.
5. **Deterministic Rule-Based Narrative (No Free LLM Hallucination)**:
   - 요약문과 해석 문구는 상태 및 사유 코드에 기반한 결정론적 템플릿으로 작성되어 100% 재현성을 보장한다.
6. **Fail-Closed & Explicit Missing Data**:
   - 결측 데이터는 `null` 또는 `DATA_UNAVAILABLE`로 표기하며 결측 사유를 명시한다.
7. **Descriptive Decision Support (Not Financial Advice)**:
   - 매수/매도 추천, 목표가 제시, 수익 보장 표현을 일절 금지하며 순수 전략 의사결정 지원 정보만을 제공한다.

--------------------------------------------------------------------------------
3. JSON Data Schema Specification (v0.2)
--------------------------------------------------------------------------------
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
      "properties": {
        "pattern_a_score": { "type": ["number", "null"] },
        "official_stage": { "type": "string", "enum": ["WEAK", "BASE", "TRANSITION", "EARLY_TREND", "PROGRESSED", "UNAVAILABLE"] },
        "candidate_state": { "type": "string", "enum": ["candidate", "watch", "late", "blocked", "insufficient_data"] },
        "is_candidate": { "type": "boolean" },
        "market_cap_eok": { "type": ["number", "null"] },
        "avg_trading_value_20d_eok": { "type": ["number", "null"] },
        "investability_status": { "type": "string", "enum": ["INVESTABLE", "FILTERED_MARKET_CAP", "FILTERED_LIQUIDITY", "DATA_UNAVAILABLE"] },
        "investability_reason": { "type": "string" },
        "is_investable": { "type": "boolean" }
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
        "provenance"
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
        "entry_conditions": { "type": ["object", "null"] },
        "current_trade": { "type": ["object", "null"] },
        "protection_state": { "type": ["object", "null"] },
        "reentry_state": { "type": ["object", "null"] },
        "trade_history": { "type": "array" },
        "interpretation": { "type": "string" },
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

--------------------------------------------------------------------------------
4. Markdown Document Structure (v0.2)
--------------------------------------------------------------------------------
1. **0. 핵심 요약 (Executive Summary)**
2. **1. 현재 기술적 국면 & 투자 적격성 스냅샷 (Current Snapshot)**
3. **2. 패스트 코어 V2 전략 상태 (A FAST Core V2 Strategy State)**
4. **3. Pattern A FAST 현재 신호 (Pattern A FAST Early Signal)**
5. **4. Pattern A Monthly History — 최근 12개월 월별 추이 (Recent 12M Trajectory)**
6. **5. Pattern A 국면 전환 이력 (Stage Transition History)**
7. **6. Pattern A FAST Weekly History**
8. **7. 외국인 수급 확증 (Foreign Flow Analysis - Phase 11)**
9. **8. 거래대금 추세 분석 (Trading Value Flow)**
10. **9. Pattern A 전체 월별 이력 (Full Monthly History)**
11. **10. 데이터 품질 및 신원 (Data Quality & Provenance)**
