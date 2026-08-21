# Artifacts Authority Index

이 문서는 `artifacts/` 디렉터리 내 산출물의 공식 분류, 역할(Role), 수명주기(Lifecycle) 및 권한(Authority)을 안내하는 단일 기준점(Single Source of Truth)이다.

`artifacts/`의 디렉터리 구조는 **PATH MUST EXPRESS AUTHORITY / LIFECYCLE** 원칙에 따라 구성되어 있으며, 경로만으로 해당 산출물이 Production 신호인지, Validation/Hold 상태인지, 활성 연구인지, 폐기된 Archive인지를 즉시 식별할 수 있다.

---

## 1. Directory Structure Overview

```text
artifacts/
├── README.md                                # 본 Authority Index
│
├── patterns/
│   ├── pattern_a/
│   │   ├── production/                      # 현재 공식 Production 산출물 및 Runtime Source
│   │   │   ├── scanner/                     # Full Universe Scanner 결과
│   │   │   ├── investability/               # Investability 필터 결과 및 PIT Snapshot (source/)
│   │   │   └── flow/                        # 외국인 수급 지표 및 원본 (source/)
│   │   │
│   │   ├── validation/                      # 공식 검증, 감사 및 Hold 상태 인프라
│   │   │   ├── closure/                     # Pattern A Final Closure 감사 결과
│   │   │   ├── chart_review/                # 수동 차트 리뷰 데이터셋 (Closure 입력)
│   │   │   ├── investability_history/       # KRX 시총 백필 데이터 (row-level sha256)
│   │   │   ├── relative_strength/           # RS 인프라 (Phase 12 HOLD_RELATIVE_STRENGTH_INFRA)
│   │   │   ├── stage_v03_research/          # Stage v0.3 분류기 연구 검증 (결정론적 재생성)
│   │   │   └── stage_v04_multi_year_research/ # Stage v0.4 다년도 연구 검증 (결정론적 재생성)
│   │   │
│   │   └── research/                        # 완료된 또는 진행 중인 연구 산출물
│   │       ├── analysis/                    # Stage 필터 감사 연구
│   │       └── investability_threshold_design/ # Investability 기준값 설계 연구
│   │
│   └── pattern_a_fast/
│       ├── production/                      # A FAST 공식 전략 및 Contract Prototype
│       │   ├── contract_prototype/          # Runtime 로드 Score/Stage Contract Prototype
│       │   ├── strategy_v01/                # A FAST Core V1 (HISTORICAL_FROZEN_BASELINE)
│       │   ├── strategy_v02/                # A FAST Core V2 (공식 Current Strategy)
│       │   ├── strategy_finalization_v01/   # PIT 보정 V1 Finalization Evidence
│       │   └── core_v02_reentry/            # V1 → V2 REENTRY_ONLY Delta 증빙
│       │
│       ├── validation/                      # OOS 및 인간 검증 Ground Truth
│       │   ├── ground_truth/                # Human Review / Blind Review Charts (240 PNG)
│       │   ├── human_anchors/                # Phase 13 인간 앵커 샘플
│       │   ├── oos/                         # Phase 13H OOS 검증 산출물
│       │   └── investable_oos/              # Phase 13J Investable OOS 검증 산출물 (Seal 보호)
│       │
│       ├── research/                        # A FAST 파생 연구
│       │   ├── feature_role/                # Phase 13H Feature Role 연구
│       │   ├── progressed_downside_v01/     # Progressed Downside 연구
│       │   ├── large_cap40_v01/             # 대형주 40종목 가설 연구
│       │   └── trading_policy_v01/          # 트레이딩 정책 연구
│       │
│       └── archive/                         # 대체/폐기된 과거 연구 체크포인트 (Superseded)
│           ├── entry_gate_v02a/
│           ├── coverage_hole_v02d/
│           ├── unavailable_v02c/
│           ├── weak_reversal_v02b/
│           ├── combined_exit_v01/
│           ├── architecture_v03/
│           ├── fresh_oos_v03/
│           └── strategy_finalization_v01_legacy/
│
├── reporting/
│   └── stock_reports/                       # 종목별 리포트 산출물 (Pattern 독립 계층)
│       ├── 20260814/                        # Current v0.2 리포트
│       └── archive/v0.1/20260814/           # Superseded v0.1 리포트
│
└── shared/
    └── cache_population/                    # 공용 데이터 인프라 (캐시 적재 로그/감사)
```

> **참고**: `strategies/` 디렉터리는 현재 존재하지 않으며, Julia Strategy 등 Pattern 독립 전략의 첫 번째 실제 산출물이 생성되는 시점에 신설된다.

---

## 2. Classification & Lifecycle Rules

### A. Current Production Evidence (`production/`)
- 현재 운영(Production) 및 스캐닝, 리포팅 런타임에서 직접 신뢰하고 소비하거나 산출하는 canonical 증빙 데이터.
- **Pattern A**:
  - `scanner/`: 2,528개 전종목 Full Universe Scan canonical 산출물.
  - `investability/`: Phase 10 투자 적합성 필터 결과 및 `source/` PIT 스냅샷 (런타임 로드).
  - `flow/`: Phase 11 외국인 수급 확인 지표 및 원본 `source/`.
- **Pattern A FAST**:
  - `contract_prototype/`: Stock Report / A FAST Report 런타임이 직접 로드하는 score/stage 계약 프로토타입 JSON.
  - `strategy_v02/`: 현재 공식 A FAST Core V2 전략 산출물.
  - `strategy_finalization_v01/`: PIT 보정 적용 canonical V1 finalization.
  - `core_v02_reentry/`: V1 대비 V2의 유일한 변경점인 REENTRY_ONLY delta 공식 증거.

### B. Current Validation & Hold (`validation/`)
- 시스템 무결성, 회귀 검증, 인간 감사 및 Closure 체인의 일부로 사용되는 공식 검증 데이터.
- **Relative Strength (Phase 12)**:
  - **공식 상태**: `HOLD_RELATIVE_STRENGTH_INFRA`
  - Market-relative RS 인프라는 동작하나 Sector RS Arithmetic Parity 및 Sector Mapping Contract 미해결로 인해 현재 **Validation**에 위치한다.
  - Phase 12 Final Closure 완료 후에만 별도 작업을 통해 `production/relative_strength`로 승격될 수 있다.
- **Pattern A Closure & Review**:
  - `closure/`: `pattern_a_final_closure.py`가 실행 시마다 작성하는 10-gate 클로저 감사 결과.
  - `chart_review/`: 인간 수동 차트 리뷰 결과 (Final Closure의 필수 입력).
  - `investability_history/`: 과거 시총 백필 검증 데이터 (row-level sha256).
  - `stage_v03_research/`, `stage_v04_multi_year_research/`: 결정론적 재생성이 보장된 Stage 분류기 연구 증거.
- **Pattern A FAST Validation**:
  - `ground_truth/`: Blind review 차트 240개 PNG 및 라벨 데이터셋.
  - `oos/`, `investable_oos/`: Phase 13H/13J OOS 검증 산출물 및 explicit sha256 seal.

### C. Historical Baselines (`production/strategy_v01/` 등)
- 공식 과거 버전과의 비교 기준(Baseline)으로 영구 보존되는 데이터.
- `pattern_a_fast/production/strategy_v01/`는 A FAST Core V1의 `HISTORICAL_FROZEN_BASELINE`으로, **Archive 대상이 아니다**.

### D. Active Research (`research/`)
- 완료되었거나 후속 작업에 참고되는 유효한 연구 산출물 (폐기 대상 아님).
- Pattern A: `analysis/`, `investability_threshold_design/`
- Pattern A FAST: `feature_role/`, `progressed_downside_v01/`, `large_cap40_v01/`, `trading_policy_v01/`

### E. Archive (`archive/`)
- `Archive != Old`. 단순히 오래된 것이 아니라, **명시적으로 대체(Superseded)되었거나 채택되지 않은 연구 산출물**을 의미한다.
- A FAST V0.2 연구 체크포인트 6종 (`entry_gate_v02a`, `coverage_hole_v02d`, `unavailable_v02c`, `weak_reversal_v02b`, `combined_exit_v01`, `architecture_v03`), `fresh_oos_v03`, PIT 보정 이전 백업인 `strategy_finalization_v01_legacy`.
- Archive 이동 시에도 파일 내용(Content)은 100% 보존된다.

### F. Reporting Outputs (`reporting/`)
- 최종 소비자용 리포트 산출물 계층으로 Pattern과 독립적으로 운영된다.
- `reporting/stock_reports/20260814/` (Current v0.2), `reporting/stock_reports/archive/v0.1/20260814/` (v0.1 archive).

### G. Shared Infrastructure (`shared/`)
- 특정 Pattern이나 전략에 종속되지 않는 공용 인프라 산출물 (`shared/cache_population/`).

---

## 3. Integrity & Preservation Policy

1. **Content Identity**: 본 재배치는 디렉터리 경로만 변경(DIRECTORY MOVE FIRST)하며, 기존 artifact 데이터 내용(Payload)은 단 1바이트도 수정하지 않는다.
2. **Duplicate Elimination**: `strategy_finalization_v01_corrected_pit/` 4개 파일은 canonical `strategy_finalization_v01/`와 byte-identical 중복임이 확인되어 STEP 2에서 단일화 후 제거(REMOVE_DUPLICATE)되었다.
3. **No In-Place Regeneration**: 산출물의 수치나 점수, 판정 로직을 재계산하거나 수정하지 않는다.
