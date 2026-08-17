# Stock Report Contract v0.1

================================================================================
1. 개요 및 목적 (Overview & Purpose)
================================================================================
Stock Report Contract v0.1은 KRX 상장 개별 종목에 대해 외부 네트워크 요청 없이(Zero Network Request), 로컬 시세 및 정본 아티팩트만을 조회하여 해당 종목의 **현재 기술적 국면(Pattern A Score & Stage)**, **투자 유동성 조건(Phase 10 Investability)**, **과거 월별 점수/국면 변화 추이(Historical Monthly Flow)**, **외국인 수급 확증(Phase 11 Foreign Flow)**, **거래대금 추세(Trading Value Trend)**를 하나의 통일된 데이터 구조(JSON) 및 사람이 읽을 수 있는 문서(Markdown)로 제공하기 위한 공통 인터페이스 규약이다.

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
   - 로컬 Parquet 일봉 캐시(`data/raw/stocks/{ticker}.parquet`)와 확정된 정본 아티팩트(`artifacts/investability`, `artifacts/flow`)만을 사용한다.
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
        "score_trend": {
          "type": "object",
          "properties": {
            "current_score": { "type": ["number", "null"] },
            "score_1m_ago": { "type": ["number", "null"] },
            "score_3m_ago": { "type": ["number", "null"] },
            "score_6m_ago": { "type": ["number", "null"] },
            "score_12m_ago": { "type": ["number", "null"] },
            "change_1m": { "type": ["number", "null"] },
            "change_3m": { "type": ["number", "null"] },
            "change_6m": { "type": ["number", "null"] },
            "change_12m": { "type": ["number", "null"] }
          }
        },
        "stage_transitions": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "as_of": { "type": "string" },
              "from_stage": { "type": "string" },
              "to_stage": { "type": "string" }
            }
          }
        },
        "recent_12m_history": { "type": "array", "items": { "$ref": "#/definitions/MonthlyObservation" } },
        "full_monthly_history": { "type": "array", "items": { "$ref": "#/definitions/MonthlyObservation" } }
      }
    },
    
    "foreign_flow": {
      "type": "object",
      "properties": {
        "data_status": { "type": "string", "enum": ["READY", "PARTIAL", "DATA_UNAVAILABLE", "NOT_EVALUATED"] },
        "flow_state": { "type": "string", "enum": ["FLOW_ACCUMULATION", "FLOW_RECENT_RECOVERY", "FLOW_RECENT_WEAKENING", "FLOW_DISTRIBUTION", "FLOW_MIXED", "FLOW_UNAVAILABLE"] },
        "explanation": { "type": "string" },
        "foreign_net_buy_value_1d_krw": { "type": ["number", "null"] },
        "foreign_net_buy_value_5d_krw": { "type": ["number", "null"] },
        "foreign_net_buy_value_20d_krw": { "type": ["number", "null"] },
        "foreign_net_buy_value_60d_krw": { "type": ["number", "null"] },
        "foreign_flow_intensity_5d": { "type": ["number", "null"] },
        "foreign_flow_intensity_20d": { "type": ["number", "null"] },
        "foreign_flow_intensity_60d": { "type": ["number", "null"] },
        "foreign_positive_days_5d": { "type": ["integer", "null"] },
        "foreign_positive_days_20d": { "type": ["integer", "null"] },
        "foreign_positive_days_60d": { "type": ["integer", "null"] }
      }
    },
    
    "trading_value_flow": {
      "type": "object",
      "properties": {
        "trading_value_state": { "type": "string", "enum": ["TRADING_VALUE_EXPANDING", "TRADING_VALUE_STABLE", "TRADING_VALUE_WEAKENING", "TRADING_VALUE_MIXED", "TRADING_VALUE_UNAVAILABLE"] },
        "explanation": { "type": "string" },
        "avg_trading_value_5d_eok": { "type": ["number", "null"] },
        "avg_trading_value_20d_eok": { "type": ["number", "null"] },
        "avg_trading_value_60d_eok": { "type": ["number", "null"] },
        "ratio_5d_to_20d": { "type": ["number", "null"] },
        "ratio_20d_to_60d": { "type": ["number", "null"] }
      }
    },
    
    "data_quality": {
      "type": "object",
      "properties": {
        "cache_present": { "type": "boolean" },
        "cache_first_date": { "type": ["string", "null"] },
        "cache_last_date": { "type": ["string", "null"] },
        "daily_rows_count": { "type": "integer" },
        "completed_month_count": { "type": "integer" },
        "quality_status": { "type": "string" },
        "quality_flags": { "type": "array", "items": { "type": "string" } }
      }
    },
    
    "provenance": {
      "type": "object",
      "properties": {
        "stock_price_source": { "type": "string" },
        "score_contract": { "type": "string" },
        "stage_contract": { "type": "string" },
        "investability_contract": { "type": "string" },
        "foreign_flow_contract": { "type": "string" },
        "network_requests": { "type": "integer", "enum": [0] }
      }
    }
  },
  "definitions": {
    "MonthlyObservation": {
      "type": "object",
      "properties": {
        "as_of": { "type": "string", "format": "date" },
        "score": { "type": ["number", "null"] },
        "stage": { "type": "string" },
        "candidate_state": { "type": "string" },
        "data_available": { "type": "boolean" },
        "reason": { "type": ["string", "null"] }
      }
    }
  }
}
```

--------------------------------------------------------------------------------
4. Rule-Based Interpretation Engines
--------------------------------------------------------------------------------
### 4.1. Foreign Flow Interpretation Rules
- **FLOW_ACCUMULATION**: `5D > 0 AND 20D > 0 AND 60D > 0`
  - "최근 5일, 20일, 60일 모두 외국인 누적 순매수가 플러스를 유지하며 중단기 전 구간에서 순매수 우위(매집) 기조입니다."
- **FLOW_RECENT_RECOVERY**: `5D > 0 AND 20D > 0 AND 60D <= 0`
  - "최근 5일과 20일 외국인 수급은 순매수로 개선되었으나 60일 누적으로는 순매도 상태로, 단기 수급 반등 및 회복 국면입니다."
- **FLOW_RECENT_WEAKENING**: `5D < 0 AND 20D > 0 AND 60D > 0`
  - "20일 및 60일 누적 기준 외국인 순매수 기조는 유지되고 있으나, 최근 5일은 순매도로 전환되어 단기 수급이 다소 둔화된 상태입니다."
- **FLOW_DISTRIBUTION**: `5D < 0 AND 20D < 0 AND 60D < 0`
  - "5일, 20일, 60일 모두 외국인 누적 순매도 상태로, 중단기 외국인 수급은 전반적인 매도 우위(이탈) 흐름입니다."
- **FLOW_MIXED**: 상기 조건 외
  - "외국인 수급이 기간별로 엇갈리는 혼조세 흐름입니다."
- **FLOW_UNAVAILABLE**: 데이터 결측 시
  - "외국인 수급 데이터가 준비되지 않아 수급 분석을 제공할 수 없습니다."

### 4.2. Trading Value Trend Interpretation Rules
- **TRADING_VALUE_EXPANDING**: `5D > 20D AND 20D > 60D`
  - "최근 거래대금이 지속 확대되는 흐름입니다. 5일 평균 거래대금이 20일 및 60일 평균을 상회하고 있습니다."
- **TRADING_VALUE_WEAKENING**: `5D < 20D AND 20D < 60D`
  - "최근 거래대금이 지속 감소(둔화)하는 흐름입니다. 5일 평균 거래대금이 20일 및 60일 평균을 밑돌고 있습니다."
- **TRADING_VALUE_STABLE**: `|5D/20D - 1| <= 0.1 AND |20D/60D - 1| <= 0.1`
  - "최근 거래대금이 급격한 변동 없이 일정 범위를 안정적으로 유지하고 있습니다."
- **TRADING_VALUE_MIXED**: 상기 조건 외
  - "최근 거래대금이 특정 방향성 없이 기간별로 혼조세를 나타내고 있습니다."
- **TRADING_VALUE_UNAVAILABLE**: 데이터 결측 시
  - "거래대금 시계열 데이터가 부족하여 분석을 제공할 수 없습니다."

--------------------------------------------------------------------------------
5. Markdown Rendering Structure
--------------------------------------------------------------------------------
Markdown 종목 리포트는 JSON contract의 속성만을 사용하여 렌더링되며 다음 구조를 따른다:
```markdown
# [종목명 (Ticker)] 종목 리포트

> **핵심 요약 (Executive Summary)**
> [Combined Narrative 3~6 sentences]

## 1. Current Technical & Investability Snapshot
- **Pattern A Score**: 97.45 (Stage: `EARLY_TREND`, Candidate: `YES`)
- **Investability**: `INVESTABLE` (시총: 1,542.92억, 20D 평균 거래대금: 14.00억)

## 2. Recent 12M Score & Stage Trajectory
| 기준일 (As-Of) | Pattern A Score | Stage | Candidate State |
| :--- | :--- | :--- | :--- |
| 2025-08-29 | 60.01 | BASE | watch |
...

## 3. Stage Transition Events
- 2026-07-31: `TRANSITION` -> `EARLY_TREND`
...

## 4. Foreign Investor Flow (Phase 11)
- **수급 상태**: `FLOW_ACCUMULATION`
- **해석**: 최근 5일, 20일, 60일 모두 외국인 누적 순매수가 플러스를 유지하며...
- **세부 수치**: 1D(+0.37억), 5D(+6.86억), 20D(+11.26억), 60D(+16.86억)

## 5. Trading Value Trend
- **거래대금 상태**: `TRADING_VALUE_EXPANDING`
- **해석**: 최근 거래대금이 지속 확대되는 흐름입니다...
- **세부 수치**: 5D 평균(20.64억), 20D 평균(14.00억), 60D 평균(22.12억)

## 6. Full Monthly History
...

## 7. Data Quality & Provenance
- Local Parquet Cache: Present (1,222 rows)
- Source Contracts: Score v0.2, Stage v0.1, Phase 10 Investability, Phase 11 Flow
- Network Requests: 0

---
*Disclaimer: 본 리포트는 기술적 국면 분석 및 유동성/수급 통계 데이터이며 투자 권유나 매수 추천이 아닙니다.*
```
