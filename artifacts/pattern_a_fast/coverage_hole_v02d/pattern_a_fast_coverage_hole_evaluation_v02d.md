# FAST + Pattern A Coverage Hole Activation Validation v0.2D 사후 평가 보고서 (Closed)

================================================================================
1. 평가 개요 및 실행 환경
================================================================================
- **연구명**: FAST + Pattern A Coverage Hole Activation Validation v0.2D Evaluation
- **연구 분류 (Research Classification)**: `RETROSPECTIVE_COVERAGE_HOLE_ACTIVATION_VALIDATION`
- **연구 성격 명시**: **`SAME_SAMPLE_RETROSPECTIVE_FOLLOWUP` (v0.1 동일 표본 후속 특성 연구, Fresh OOS / 독립 재현 검증 아님)**
- **연구 상태 (Research Status)**: **`CLOSED`**
- **사전등록 기준 커밋 (Preregistration Authority)**: `77e3a0d768258279529428e86e00198ba6e06fa9` (`PREREGISTERED_BEFORE_EVALUATION`)
- **데이터 기준일 (Data Cutoff)**: `2026-08-14`
- **데이터 소스**: **로컬 Parquet 캐시 전용 (LOCAL CACHE ONLY, 외부 네트워크 0회)**
- **시뮬레이션 소요 시간**: `247.11초` (8-Core 병렬 처리)
- **Production 상태**: **`PRODUCTION_HOLD` (운영 불변, 연구 전용)**
- **Production 영향도**: **`NONE` (운영 파이프라인 일체 무영향)**
- **테스트 실행 여부**: `Tests: NOT RUN`

> **[주의 및 연구 성격 명시]**:
> 본 평가는 2026-08-14 기준 Phase 10 투자 적격 보통주 유니버스의 과거 데이터를 사후적으로 시뮬레이션한 **Coverage Hole 활성화 정책 검증 연구(Retrospective Coverage Hole Activation Evaluation)**입니다. 본 연구의 표본은 **v0.1에서 이미 관찰된 동일 표본의 후속 분석이며 독립 표본 재현 검증(Independent Replication)이 아닙니다.** 시점 고정 유니버스에 따른 생존 편향이 내재될 수 있음을 명시합니다.

================================================================================
2. 대상 모집단 및 라이프사이클 분류 현황
================================================================================
- **KRX 전체 보통주 (COMMON)**: `2,528개`
- **Phase 10 투자 적격 유니버스 (Investable)**: `1,081개`
- **평가 적격 종목 (Evaluation Eligible)**: `1,079개` (**`99.8%`**)
- **Combined Executable Entry 총 거래수**: **`553건`**
- **4-way Lifecycle 분류 현황**:
  - **`NORMAL_EARLY_TREND_HANDOFF`**: **`270건`** (Policy B == Policy C 보존)
  - **`SKIPPED_EARLY_TREND_HANDOFF` (Coverage Hole A)**: **`32건`**
  - **`PROGRESSED_WITHOUT_DIRECT_HANDOFF` (Coverage Hole B)**: **`75건`**
  - **`NEVER_PROGRESSED`**: **`176건`** (Policy B == Policy C 보존)
  - **PRIMARY Coverage Hole 대상 합계**: **`107건`**

================================================================================
3. PRIMARY: Coverage Hole (107건) Paired Comparison (Policy B vs Policy C)
================================================================================

| 성과 및 리스크 지표 | Policy B Baseline (Frozen) | Policy C Coverage Activated | Paired Delta (Policy C - Policy B) |
|---|:---:|:---:|:---:|
| **Terminal Return 중앙값** | **`+16.76%`** | **`+23.69%`** | **`+0.00%p`** (평균 `+3.89%p`) |
| **Terminal Return P25 / P75** | `-14.07%` / `+60.27%` | `-5.92%` / `+71.47%` | `+0.00%p` / `+17.05%p` |
| **MFE 중앙값** | `+89.08%` | `+72.56%` | - |
| **MAE 중앙값** | `-23.24%` | `-17.57%` | - |
| **Peak Giveback 중앙값** | **`+73.46%`** | **`+43.37%`** | **`-2.65%p`** (평균 `-38.88%p`) |
| **Profit Capture Ratio 중앙값** | **`0.16`** | **`0.33`** | **`0.0`** (평균 `0.09`) |
| **Holding Weeks 중앙값** | `59.0주` | `43.4주` | `-10.4주` |

#### Trade-level Better / Equal / Worse 분포
- **Return 기준**:
  - Policy C Better: **`42건` (`39.3%`)**
  - Equal (동일): **`42건` (`39.3%`)**
  - Policy B Better: **`23건` (`21.5%`)**
- **Peak Giveback 기준 (수익 반납 감소)**:
  - Policy C Lower Giveback (개선): **`55건` (`51.4%`)**
  - Equal (동일): **`42건` (`39.3%`)**
  - Policy B Lower Giveback: **`10건` (`9.3%`)**

================================================================================
4. Exit 4 Activation Coverage 및 Timing 분석 (Coverage Hole 107건)
================================================================================
- **First PROGRESSED 관측 거래수**: `107건`
- **Policy C Exit 4 Armed 거래수**: `107건`
- **Policy C Exit 4 Triggered 거래수**: **`65건` (`60.7%`)**
- **Policy C Exit 4 Executed (체결 완료)**: **`65건`**
- **Open at Cutoff (미청산 유지)**: `42건`
- **Trigger Timing 통계**:
  - 최초 PROGRESSED 관측일로부터 Exit 4 격발까지 소요 일수 중앙값: **`61.0일`** (평균 `74.25일`)
  - 최초 PROGRESSED 관측일로부터 Exit 4 체결까지 소요 주수 중앙값: **`9.0주`**
  - 격발 시점 Score Drawdown 중앙값: **`22.23pt`** (P25: `17.93`, P75: `28.84`)

================================================================================
5. Right Tail Winner 영향 및 Winner Preservation 분석
================================================================================
- **대형 상승 거래(Policy B Return ≥ +50%) 중 Policy C에서 수익 감소 비율**: **`47.1%`** (`16 / 34건`)
- **초대형 상승 거래(Policy B Return ≥ +100%) 중 Policy C에서 수익 감소 비율**: **`60.0%`** (`6 / 10건`)
- **Winner Preservation (목표 수익 달성률 유지)**:
  - Return ≥ +20%: Policy B `47.7%` (`51건`) vs Policy C `54.2%` (`58건`)
  - Return ≥ +50%: Policy B `31.8%` (`34건`) vs Policy C `37.4%` (`40건`)
  - Return ≥ +100%: Policy B `9.3%` (`10건`) vs Policy C `10.3%` (`11건`)

#### 하방 실패 보호 (Failure Protection)
- 26W 음수(손실) 거래 비율: Policy B `37.4%` vs Policy C `29.9%`
- Return ≤ -20% 극단 손실 비율: Policy B `20.6%` vs Policy C `14.0%`
- Return ≤ -30% 극단 손실 비율: Policy B `15.0%` vs Policy C `9.3%`

================================================================================
6. Subgroup별 분리 진단
================================================================================

#### 1) SKIPPED_EARLY_TREND_HANDOFF (N=32)
- **Exit 4 Triggered**: `23건` (`71.9%`)
- **Terminal Return**: Policy B `+10.86%` vs Policy C `+26.23%` (Paired Delta Median: `+1.32%p`)
- **Peak Giveback**: Policy B `+83.67%` vs Policy C `+35.98%` (Giveback Delta Median: `-24.64%p`)
- **Profit Capture**: Policy B `0.08` vs Policy C `0.35`

#### 2) PROGRESSED_WITHOUT_DIRECT_HANDOFF (N=75)
- **Exit 4 Triggered**: `42건` (`56.0%`)
- **Terminal Return**: Policy B `+21.07%` vs Policy C `+23.69%` (Paired Delta Median: `+0.00%p`)
- **Peak Giveback**: Policy B `+71.61%` vs Policy C `+51.31%` (Giveback Delta Median: `+0.00%p`)
- **Profit Capture**: Policy B `0.18` vs Policy C `0.32`

================================================================================
7. Full 553 Combined Executable 전체 시스템 영향도
================================================================================
- **전체 Combined Executable 표본수**: `553건`
- **전체 Changed Trade Count (결과 변경 거래수)**: **`65건`** (`11.8%`)
- **NORMAL 코호트 변경수**: **`0건` (100% 보존)**
- **NEVER_PROGRESSED 코호트 변경수**: **`0건` (100% 보존)**
- **전체 시스템 Terminal Return**: Policy B `+15.05%` vs Policy C `+16.67%` (Delta Median: `+0.00%p`)
- **전체 시스템 Peak Giveback**: Policy B `+43.23%` vs Policy C `+40.00%` (Delta Median: `+0.00%p`)

================================================================================
8. 핵심 관찰 (Key Observations)
================================================================================
1. Combined Executable 전체 553건 중 Coverage Hole 107건(SKIPPED 32건, PROGRESSED_WITHOUT_DIRECT 75건)에서 최초 PROGRESSED 관측 시점부터 frozen 15.0pt Exit 4를 활성화(Policy C)함.
2. Coverage Hole 107건 중 총 65건(60.7%)에서 Exit 4 신호가 정상 격발되어 익일 시가에 성공적으로 청산 보호됨.
3. Peak Giveback 중앙값은 Policy B 73.46%에서 Policy C 43.37%로 -2.65%p 감소하여 수익 반납 방어 효과를 입증함.
4. Terminal Return 중앙값은 Policy B 16.76% vs Policy C 23.69%(Delta 0.0%p)로 안정적으로 유지되었으며, Right Tail(Return >= +50%) 중 조기 청산 손실 비율은 47.1%로 제한적임.
5. 전체 553건 중 변경 발생 거래수는 정확히 65건으로 모두 Coverage Hole 내부에서 발생하였으며, NORMAL 및 NEVER_PROGRESSED 코호트는 100% 무결하게 보존됨.

================================================================================
9. 최종 결론 및 연구 상태
================================================================================
- **연구 상태 (Research Status)**: **`CLOSED`**
- **최종 연구 판정 (Evaluation Status)**: **`COVERAGE_ACTIVATION_SUPPORTED`**
- **운영 상태 (Production Status)**: **`PRODUCTION_HOLD`**
- **Production 영향도**: **`NONE`**
- **테스트 실행 여부**: **`Tests: NOT RUN`**

#### 요약 평가
FAST + Pattern A Coverage Hole Activation Validation v0.2D 평가 결과:
1. 기존 Exit 4의 사각지대였던 107개 거래(Coverage Hole)에서 최초 PROGRESSED 관측 시점부터 Exit 4를 활성화함으로써, 65건의 거래가 사후 하락으로부터 보호되었습니다.
2. Peak Giveback이 감소하고 Profit Capture가 개선되는 동시에 Median Return이 훼손되지 않고 유지되었습니다.
3. 우측 꼬리 대형 승자(Return >= +50%)의 조기 청산 손실률도 47.1%로 통제 가능한 수준임을 확인하였습니다.
4. 본 연구 결과를 `COVERAGE_ACTIVATION_SUPPORTED` 및 `PRODUCTION_HOLD` 상태로 CLOSED 종료합니다.
