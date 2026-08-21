# Stock Report Contract v0.1 (Historical Frozen Baseline)

================================================================================
1. 개요 및 목적 (Overview & Purpose)
================================================================================
Stock Report Contract v0.1은 KRX 상장 개별 종목에 대해 외부 네트워크 요청 없이(Zero Network Request), 로컬 시세 및 정본 아티팩트만을 조회하여 해당 종목의 **현재 기술적 국면(Pattern A Score & Stage)**, **투자 유동성 조건(Phase 10 Investability)**, **과거 월별 점수/국면 변화 추이(Historical Monthly Flow)**, **외국인 수급 확증(Phase 11 Foreign Flow)**, **거래대금 추세(Trading Value Trend)**, **Pattern A FAST 주별 조기 신호(Experimental / Early Signal, HIERARCHICAL_V01)**를 하나의 통일된 데이터 구조(JSON) 및 사람이 읽을 수 있는 문서(Markdown)로 제공하기 위한 공통 인터페이스 규약이다.

본 규약은 향후 다음 시스템의 단일 진실 공급원(Single Source of Truth)으로 사용된다:
1. **Local CLI**: 개발 및 운영 환경에서의 즉시 종목 리포트 추출
2. **Web API**: 웹 백엔드 서비스의 종목 리포트 JSON 엔드포인트
3. **Web Report Page**: 프론트엔드 종목 분석 및 차트 렌더링 화면
4. **AI Assistant Report Response**: 대화형 에이전트의 규칙 기반 종목 브리핑

--------------------------------------------------------------------------------
2. 핵심 불변 원칙 및 가드레일 (Core Principles & Guardrails)
--------------------------------------------------------------------------------
1. **Zero Network Request & Pure Local Execution**:
   - 리포트 생성 과정에서 KRX, pykrx, Yahoo, Naver 등 외부 네트워크 요청을 일절 수행하지 않는다.
   - 로컬 Parquet 일봉 캐시(`data/raw/stocks/{ticker}.parquet`)와 확정된 정본 아티팩트(`artifacts/patterns/pattern_a/production/investability`, `artifacts/patterns/pattern_a/production/flow`)만을 사용한다.
2. **Frozen Production Contract 재사용 (No Logic Mutation)**:
   - Pattern A Score v0.2, Stage v0.1, Phase 10 Investability, Phase 11 Foreign Flow 공식을 그대로 재사용하며, 리포트 생성을 위해 프로덕션 계산식을 수정하지 않는다.
3. **Point-In-Time (PIT) & Strict No-Lookahead**:
   - 과거 특정 시점($T_m$)의 Score/Stage snapshot을 산출할 때는 반드시 $T_m$ 시점 이하의 일봉 시계열만을 슬라이싱하여 평가하며, 미래 데이터를 일절 참조하지 않는다.
4. **Deterministic Rule-Based Explanation (No Free LLM Hallucination)**:
   - 수급 및 거래대금 설명문, 요약문은 동일한 수치 입력에 대해 항상 100% 동일한 문장이 생성되도록 결정론적 규칙(Deterministic Rule)으로 작성된다.
5. **Fail-Closed & Explicit Missing Data**:
   - 결측 데이터는 임의의 기본값(0 등)으로 대체하지 않고 명시적으로 `null` 및 `DATA_UNAVAILABLE`로 표기하며 결측 사유(`reason`)를 명시한다.
6. **Descriptive Baseline (Not Financial/Investment Advice)**:
   - 본 리포트는 종목의 기술적 구조와 수급 흐름을 데이터에 기반해 설명할 뿐, 매수/매도 추천, 목표가 제시, 수익률 보장을 일절 포함하지 않는다.

--------------------------------------------------------------------------------
3. JSON Data Schema Specification (v0.1)
--------------------------------------------------------------------------------
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "StockReport_v0.1",
  "type": "object",
  "required": [
    "report_version",
    "ticker",
    "name",
    "market",
    "requested_as_of",
    "reference_market_date",
    "header",
    "summary",
    "current_snapshot",
    "monthly_history",
    "foreign_flow",
    "trading_value_flow",
    "data_quality",
    "provenance"
  ],
  "properties": {
    "report_version": { "type": "string", "enum": ["0.1"] },
    "ticker": { "type": "string", "pattern": "^[0-9]{6}$" },
    "name": { "type": "string" },
    "market": { "type": "string", "enum": ["KOSPI", "KOSDAQ", "KONEX", "UNKNOWN"] },
    "requested_as_of": { "type": "string", "format": "date" },
    "reference_market_date": { "type": "string", "format": "date" },
    
    "header": {
      "type": "object",
      "properties": {
        "ticker": { "type": "string" },
        "name": { "type": "string" },
        "market": { "type": "string" },
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
    
    "monthly_history": {
      "type": "object",
      "properties": {
        "history_start_as_of": { "type": ["string", "null"] },
        "history_end_as_of": { "type": ["string", "null"] },
        "observation_count": { "type": "integer" },
        "recent_12m_observation_count": { "type": "integer" },
        "score_trend": { "type": "object" },
        "stage_transitions": { "type": "array" },
        "recent_12m_history": { "type": "array" },
        "full_monthly_history": { "type": "array" }
      }
    },
    
    "foreign_flow": { "type": "object" },
    "trading_value_flow": { "type": "object" },
    "data_quality": { "type": "object" },
    "provenance": { "type": "object" },
    "pattern_a_fast": { "type": "object" }
  }
}
```
