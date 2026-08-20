# FAST + Pattern A Coverage Hole Activation Validation v0.2D 사전등록서

================================================================================
1. 연구 목적 및 핵심 연구 질문
================================================================================
- **연구명**: FAST + Pattern A Coverage Hole Activation Validation v0.2D Evaluation
- **연구 분류 (Research Classification)**: `RETROSPECTIVE_COVERAGE_HOLE_ACTIVATION_VALIDATION`
- **연구 성격 명시**: `SAME_SAMPLE_RETROSPECTIVE_FOLLOWUP` (v0.1 동일 표본 후속 특성 연구, Fresh OOS / 독립 재현 검증 아님)
- **사전등록 상태**: `PREREGISTERED_BEFORE_EVALUATION` (평가 실행 전 프로토콜 및 가설 확정)
- **Production 상태**: `PRODUCTION_HOLD` (운영 불변, 연구 전용)
- **Production 영향도**: `NONE` (Production Code/Signal/Policy 일체 무영향)

> **[배경 및 연구 성격 명시]**:
> Combined v0.1 체계에서 Exit 4(PROGRESSED Score HWM - 15.0pt 하락 보호)는 진입 후 월봉에서 `EARLY_TREND → PROGRESSED` 직접 handoff가 관측된 경우(NORMAL_EARLY_TREND_HANDOFF, 약 270건)에만 활성화되었습니다. 이로 인해 `SKIPPED_EARLY_TREND_HANDOFF`(32건) 및 `PROGRESSED_WITHOUT_DIRECT_HANDOFF`(75건)의 총 107건(Coverage Hole)은 PROGRESSED 국면에 진입했음에도 Exit 4 보호 대상에서 제외되었습니다. 본 연구는 해당 107건에서 최초 PROGRESSED 관측 시점부터 frozen 15.0pt 보호를 활성화할 때의 수익 보호 효과, Peak Giveback 감소, Profit Capture 개선, 그리고 Right Tail Winner 손상 여부를 동일 표본 Paired Comparison으로 검증하는 사후 연구입니다.

#### 핵심 연구 질문
1. **Primary Question 1 (Coverage Hole Activation Effect)**:
   > "Coverage Hole 107건에서 최초 PROGRESSED 관측 시점부터 frozen 15.0pt Exit 4를 활성화(Policy C)할 때, 기존 Policy B 대비 실제 몇 건의 거래가 Exit 4로 보호되며 Terminal Return / Peak Giveback / Profit Capture는 어떻게 변화하는가?"
2. **Primary Question 2 (Right Tail Trade-off & Winner Preservation)**:
   > "Coverage Hole 활성화가 26W+ 장기 대형 상승 종목(Winner Tail: Return ≥ +50%, +100%)을 조기 청산하여 우측 꼬리를 과도하게 훼손하는가, 아니면 Peak Giveback을 유의미하게 방어하는가?"
3. **Primary Question 3 (Subgroup Consistency & Full System Impact)**:
   > "SKIPPED_EARLY_TREND_HANDOFF와 PROGRESSED_WITHOUT_DIRECT_HANDOFF 두 하위 그룹 간 성과 일관성이 유지되는가? 그리고 전체 553개 Combined Executable 거래 수준에서 왜곡 없는 무결한 영향이 확인되는가?"

================================================================================
2. 데이터 소스 및 무결성 원칙 (LOCAL CACHE ONLY)
================================================================================
1. **로컬 캐시 전용**: 기존 로컬 Parquet 일봉 캐시(`data/raw/stocks/`) 데이터만 100% 사용한다.
2. **외부 네트워크 호출 일체 금지**: `pykrx`, `requests`, API 호출, 캐시 refresh, 누락 데이터 자동 다운로드를 일체 수행하지 않는다.
3. **Data Cutoff**: `2026-08-14` (절대적 상한 기준일, 미래 데이터 사용 금지).
4. **대상 모집단 (Population)**: 2026-08-14 기준 Phase 10 투자 적격 보통주 유니버스(1,081개) 중 FAST v0.1 Entry 조건과 Pattern A Stage (`TRANSITION` 또는 `EARLY_TREND`) 조건을 동시에 충족한 Combined Executable Entry 표본 (예상 553건).

================================================================================
3. 정책 비교 설계 (Policy B vs Policy C)
================================================================================
1. **Anchor Entry Population (Frozen v0.1)**:
   - FAST v0.1 Qualifying Trigger + Monthly Regime PERMITTED + Daily Risk NORMAL/ELEVATED + FAST Score READY/PARTIAL.
   - Pattern A Stage at Entry: `TRANSITION` 또는 `EARLY_TREND`.
   - Entry Execution: 다음 로컬 거래일 시가 (NEXT LOCAL TRADING DAY OPEN).
2. **Lifecycle Cohort 정의 (v0.1 Frozen 4-way)**:
   - **`NORMAL_EARLY_TREND_HANDOFF`** (예상 270건): 진입 후 `EARLY_TREND → PROGRESSED` 직접 전이 관측.
   - **`SKIPPED_EARLY_TREND_HANDOFF`** (예상 32건): EARLY_TREND 없이 `TRANSITION → PROGRESSED` 직접 전이 관측.
   - **`PROGRESSED_WITHOUT_DIRECT_HANDOFF`** (예상 75건): PROGRESSED가 관측되었으나 직접 handoff가 아닌 간접 경로.
   - **`NEVER_PROGRESSED`** (예상 176건): 진입 후 관찰 기간 동안 PROGRESSED가 전혀 관측되지 않음.
   - **PRIMARY Coverage Hole Cohort**: `SKIPPED_EARLY_TREND_HANDOFF` + `PROGRESSED_WITHOUT_DIRECT_HANDOFF` (총 107건).
3. **Comparator: Policy B (Combined Exit 3 + Exit 4 v0.1 Frozen)**:
   - `NORMAL_EARLY_TREND_HANDOFF`에서만 Exit 4 활성화 (HWM - 15.0pt 하락 시 익일 시가 청산).
   - Coverage Hole 107건에서는 Exit 4 비활성화 (Exit 3 또는 Cutoff Open 유지).
4. **Experimental: Policy C (POLICY_C_COVERAGE_ACTIVATED)**:
   - `NORMAL_EARLY_TREND_HANDOFF` 및 `NEVER_PROGRESSED`: Policy B와 100% 동일 (Exit 결과 일치 필수).
   - **Coverage Hole 107건**: 최초 completed monthly `PROGRESSED` 스냅샷 관측 시 Exit 4 arm.
   - Initial HWM = 최초 PROGRESSED 스냅샷의 Pattern A Score.
   - PROGRESSED 국면 유지 중: `HWM = max(HWM, current Pattern A Score)`.
   - Trigger Rule: `HWM - current Pattern A Score >= 15.0` (정확히 15.0pt, frozen).
   - Execution: Signal 발생 월 익월 첫 로컬 거래일 시가 (NEXT LOCAL TRADING DAY OPEN).
   - Terminal Exit: `min(Exit 3, Exit 4)` 또는 Cutoff 시점 Open 유지.

================================================================================
4. 필수 평가 지표 및 비교 분석 체계
================================================================================
1. **Coverage Hole 107건 대상 Paired Comparison**:
   - Terminal Return, MFE, MAE, Peak Giveback, Profit Capture Ratio, Holding Period (Weeks/Days).
   - Paired Deltas (Policy C - Policy B): Return Delta, Giveback Delta, Profit Capture Delta, Holding Weeks Delta (N, Mean, Median, P25, P75).
   - Trade-level Better / Equal / Worse 분포 (Return 기준 및 Giveback 기준).
2. **Exit 4 Activation Coverage 및 Timing 분석**:
   - First PROGRESSED Observed N, Policy C Exit 4 Armed N, Triggered N, Executed N, Open at cutoff N.
   - Lead Time & Timing: Days/Weeks from first PROGRESSED to Exit 4 Trigger/Execution.
   - Score Drawdown at Trigger (Assert `drawdown >= 15.0`).
3. **Right Tail Winner 손상 및 Winner Preservation 분석**:
   - Policy B Terminal Return ≥ +50%, ≥ +100% 중 Policy C에서 조기 청산되어 수익이 감소한 비율 및 건수.
   - Policy C Terminal Return ≥ +20%, ≥ +50%, ≥ +100% 보존율.
4. **하방 실패 보호 (Failure Protection)**:
   - Terminal Return < 0, Return ≤ -20%, Return ≤ -30% 비율 비교.
5. **Subgroup별 분리 평가**:
   - `SKIPPED_EARLY_TREND_HANDOFF` vs `PROGRESSED_WITHOUT_DIRECT_HANDOFF` 각각의 독립 지표 산출.
6. **Full 553 Executable Combined 전체 시스템 영향도**:
   - 전체 553건 Paired Comparison 및 변경 발생 거래수(Changed Trade Count) 산출.
   - Invariant: Changed Trade Count ≤ Coverage Hole Count (107건), NORMAL 및 NEVER_PROGRESSED 변경수 = 0건.

================================================================================
5. 결론 판정 원칙 (Decision Evaluation Rules)
================================================================================
임의의 사후 threshold 생성이나 단일 지표에 의한 기계적 판정을 금지하고, 아래 4개 기준 중 하나로 최종 평가한다:
- **`COVERAGE_ACTIVATION_SUPPORTED`**: Coverage Hole에서 의미 있는 수의 거래가 활성화되고, Peak Giveback 감소 및 Profit Capture 개선이 확인되며, Median Return이 보존/개선되고 우측 꼬리(Right Tail) 손상이 제한적인 경우.
- **`COVERAGE_ACTIVATION_MIXED`**: Giveback은 감소하나 Return 및 Right Tail 손상이 크거나, 두 하위 그룹 간 결과가 상반되는 경우.
- **`COVERAGE_ACTIVATION_NOT_SUPPORTED`**: Coverage는 증가하나 Return 악화, Giveback 개선 미미, Profit Capture 악화가 나타나는 경우.
- **`INSUFFICIENT_COVERAGE_SAMPLE`**: 표본수가 부족하여 통계적 판단이 불가능한 경우.

================================================================================
6. 연구 한계 및 불변 사항 (No Tuning & Production Invariant)
================================================================================
1. **운영 정책 불변**: 본 연구 결과가 SUPPORTED이더라도 즉시 Production에 적용하지 않으며 `PRODUCTION_HOLD`를 유지한다.
2. **Threshold Sweep 금지**: 15.0pt 외에 10pt, 20pt, 25pt 등의 사후 탐색을 일체 수행하지 않는다.
3. **Entry 및 Gate 불변**: v0.2A~v0.2C 결과와 혼합하여 Entry Gate나 FAST 조건을 변경하지 않는다.
