# Pattern A FAST Trading Policy Entry v0.1 시가총액 상위 40개 대형주 사후 진단 가설 사전 등록서

================================================================================
1. 실험 개요 및 연구 성격
================================================================================
- **실험명**: Pattern A FAST Trading Policy Entry v0.1 대형주 사후 진단 평가
- **연구 분류 (Research Classification)**: `LARGE_CAP_40_RETROSPECTIVE_DIAGNOSTIC` (시가총액 상위 40개 대형주 사후 진단 연구)
- **사전등록 상태**: `PREREGISTERED_BEFORE_EVALUATION` (평가 실행 전 프로토콜 및 표본 확정)
- **데이터 기준일 (Data Cutoff)**: `2026-08-14` (절대적 상한 기준일)
- **신호 관찰 기간 (Signal Observation Window)**: `2021-08-14` ~ `2026-08-14` (5개년)

> **[주의] 연구 성격 명시**:
> 본 실험은 2026년 8월 14일 기준 시가총액 상위 40개 보통주를 사후적으로 추출하여 과거 구간을 평가하는 **사후 기술 진단(Retrospective Diagnostic)** 연구입니다. 생존 편향(Survivor / Current Constituent Selection)이 존재하므로 **독립 OOS(Out-of-Sample) 검증이나 전략 수익성 입증으로 해석하지 않으며**, 대형주 군에서의 진입 정책 특성을 관찰하기 위한 참고 연구로만 활용됩니다.

================================================================================
2. 대상 모집단 (Population Definition)
================================================================================
- **모집단 정의**: 2026년 8월 14일 기준 KRX 정규 주식 유니버스(KOSPI / KOSDAQ 보통주) 시가총액 순위 1위~40위 종목 (총 40개 표본 전수)
- **선택 소스 (Selection Source)**: `artifacts/patterns/pattern_a/production/investability/pattern_a_investability_universe_20260814.csv`
- **선택 매니페스트 (Selection Manifest)**: `artifacts/patterns/pattern_a_fast/research/large_cap40_v01/pattern_a_fast_large_cap40_selection_manifest_v01.csv`
- **표본 수**: 정확히 40개 (고유 종목 40개, 순위 1~40)

================================================================================
3. 고정 진입 정책 (Frozen Primary Entry Rule Contract)
================================================================================
기존 FAST Entry Policy v0.1의 진입 계약을 100% 수정 없이 동일하게 적용합니다.

- **Primary Entry Rule**:
  - `FAST Stage == "TRIGGER"`
  - `FAST Stage Status == "READY"`
  - `FAST Monthly Permission State == "PERMITTED_REGIME"`
  - `FAST Daily Risk State IN {"NORMAL", "ELEVATED"}`
  - `FAST Score Status IN {"READY", "PARTIAL"}`
- **진입 등급 (Entry Grades)**:
  - **Grade A**: Daily Risk `NORMAL`
  - **Grade B**: Daily Risk `ELEVATED`
- **비게이트 정책 (Non-Gate Policy)**:
  - FAST 숫자 점수 임계값(Score threshold) 없음
  - Pattern A 점수/국면/후보 상태 게이트 없음

================================================================================
4. 체결 및 성과 측정 계약 (Execution & Forward Horizon Contract)
================================================================================
1. **진입 단위**: 종목당 관찰 기간 내 **최초 1회 진입 (First Entry Only)**
2. **체결일 (Execution Date)**: 신호 주간(`signal_date`) 이후 첫 번째 로컬 거래일
3. **체결가 (Entry Price)**: 체결일의 정확한 **시가 (OPEN)** (신호 주간 종가 및 체결일 종가 사용 금지)
4. **Data Cutoff 직전 신호**: 2026-08-14에 신호가 발생하여 다음 거래일 시가가 cutoff 이후인 경우 미체결(`NO_EXECUTION_BEFORE_DATA_CUTOFF`) 처리
5. **성과 관측 기간 (Horizons)**: 4주(4W), 8주(8W), 12주(12W), 26주(26W) 완료 주봉 종가 기준 총수익률(Gross Follow-Up Return)
6. **Censoring**: horizon 완료일이 2026-08-14를 초과하면 해당 horizon은 `null` 및 `CENSORED` 처리
7. **MFE / MAE**: 체결일부터 horizon 완료일까지의 일봉 고가 최대치(MFE) 및 저가 최소치(MAE, 음수 부호 유지)

================================================================================
5. 비교 및 실험군 정의 (Comparative Variants)
================================================================================
1. **Trigger Any Control**: Monthly/Daily 필터 없이 `TRIGGER + READY + Score READY/PARTIAL`만 만족하는 첫 번째 이벤트
2. **Experimental Early Variant**: `TRIGGER + EARLY_REGIME + Non-Extreme Risk + Score READY/PARTIAL` 이벤트

================================================================================
6. 연구 한계 및 제약 사항
================================================================================
1. 본 실험은 사후 구성 종목 기반 진단이며 OOS 검증이 아님.
2. 수수료, 세금, 슬리피지, 시장 충격 비용 미포함.
3. 청산 정책(Exit Policy)은 평가 범위에 포함되지 않음.
4. 본 결과만으로 Production 승격이나 실전 매매 전략 승인을 진행하지 않음.
