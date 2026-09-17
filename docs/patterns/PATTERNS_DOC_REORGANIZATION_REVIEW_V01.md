# `patterns/` 문서 재정리 검토 V01

## 1. 요약

`docs/patterns/` 아래 Markdown 72개를 전수 확인하고 현재 역할을 분류했다.
이번 단계에서는 문서 이동·삭제 없이 현재 기준 문서와 분류표를 보정한다.

| 분류 | 건수 | 원칙 |
|---|---:|---|
| `KEEP` | 10 | 현재 기준·탐색에 직접 필요한 문서와 정리 통제 문서 |
| `ARCHIVE` | 62 | 종료된 연구·검증·사전등록·후보 전략·과거 실행 기록 |
| `DELETE_CANDIDATE` | 0 | 네 가지 삭제 조건을 모두 만족한다고 확인된 문서 없음 |

`strategy_finalization_v01.md`와 `investable_out_of_sample_v01.md`는 특별 검토
대상으로 확인했다. 둘 다 현재 실행 지시가 아닌 과거 사전등록 기록이므로
`ARCHIVE`로 분류한다.

현재 기준은 `PATTERN_A_FAST_FINAL_STRATEGY_V02`이며, V1도 현행 전략 폴더에
남길 실질적 이유가 없어 archive 대상이다. V3와 V4 역시 현재 기본 전략이
아닌 종료된 후보 기록이다. 투자 적합성 현재 기준은 새
`pattern_a/spec/investability_policy.md`, 재사용 가능한 백테스트 공통 기준은
`docs/validation/backtest_common_rules.md`에서 확인한다.

## 2. `KEEP`

| 파일 경로 | 문서 역할 | 현재 필요한가 | 근거 | 목표 위치 | 현재 기준 문서와 관계 | 가독성 문제 |
|---|---|---|---|---|---|---|
| `docs/patterns/README.md` | 패턴 영역 탐색 안내 | 예 | 현재 패턴과 전략 연결을 안내한다. | 현재 위치 | Pattern A·A FAST 진입점 | 없음 |
| `docs/patterns/pattern_a/README.md` | Pattern A 안내 | 예 | 현재 공식 패턴의 상태와 권위 문서 위치를 안내한다. | 현재 위치 | `spec/production_authority.md`의 탐색 안내 | 역사 기록 링크가 현재 문서와 가까이 노출됨 |
| `docs/patterns/pattern_a/spec/production_authority.md` | 현재 Pattern A 공식 규격 | 예 | 현재 Score·공식 lifecycle Stage·규칙·구현 위치만 남기고 과거 근거는 별도 문서 링크로 연결한다. | 현재 위치 | Pattern A의 최상위 현재 권위 문서 | 역사 근거 링크를 현재 계약과 혼동하지 않게 유지해야 함 |
| `docs/patterns/pattern_a/spec/investability_policy.md` | 현재 투자 적합성 정책 | 예 | 1,000억·3억·가격필터 없음·`DATA_UNAVAILABLE`과 PIT 판정 순서를 한 문서에서 제공한다. | 현재 위치 | Pattern A 후단 필터의 현재 기준 | 없음 |
| `docs/patterns/pattern_a_fast/README.md` | Pattern A FAST 안내 | 예 | 현재 기준, 문서 구조, V2와 과거 버전의 관계를 안내한다. | 현재 위치 | FAST 명세·전략 안내의 상위 입구 | 현재 문서와 역사 문서의 시각적 분리 보완 필요 |
| `docs/patterns/pattern_a_fast/specification/README.md` | Pattern A FAST 정의 | 예 | FAST의 의미, 상태, 시간축, PIT 원칙을 정의한다. | 현재 위치 | FAST 패턴의 개념 권위 문서 | 설명과 이력의 길이가 길어 핵심 계약을 더 앞에 둘 수 있음 |
| `docs/patterns/pattern_a_fast/specification/weekly_lifecycle.md` | FAST 주봉 생애주기 계약 | 예 | WATCH부터 EXTENDED까지의 현재 lifecycle 의미론을 정의한다. | 현재 위치 | FAST 정의의 세부 계약 | 영어 상태 토큰과 일반 설명의 혼용 밀도 개선 여지 |
| `docs/patterns/pattern_a_fast/strategy/README.md` | FAST 전략 탐색 안내 | 예 | V1~V4의 역할과 현재 V2를 한눈에 구분한다. | 현재 위치 | V2 전략 계약의 상위 입구 | V3·V4 이동 후 링크 갱신 필요 |
| `docs/patterns/pattern_a_fast/strategy/version_02/README.md` | 현재 일반 종목 기본 전략 계약 | 예 | `PATTERN_A_FAST_FINAL_STRATEGY_V02`의 현재 규칙·상태·제한을 정의한다. | 현재 위치 | 현재 전략의 최상위 권위 문서 | 없음 |
| `docs/patterns/PATTERNS_DOC_REORGANIZATION_REVIEW_V01.md` | 문서 재정리 통제·검토 기록 | 예 | 현재 단계의 분류와 다음 archive 실행 계획을 기록한다. | 현재 위치 | 현재 문서 구조 정리의 작업 기준 | 정리 완료 후 역사 기록 전환 여부 재검토 |

## 3. `ARCHIVE`

### 3.1 Pattern A 연구·검증 기록

| 파일 경로 | 문서 역할 | 현재 필요한가 | 근거 | 목표 위치 | 현재 기준 문서와 관계 | 가독성 문제 |
|---|---|---|---|---|---|---|
| `docs/patterns/pattern_a/research/stage_v04_multi_year.md` | 종료된 다년 특성 연구 | 아니오 | V0.4 연구 종료 기록이며 현재 공식 산식이 아니다. | `docs/patterns/pattern_a/archive/research/stage_v04_multi_year.md` | 공식 규격의 과거 연구 근거 | 영어·실험 보고서 형식 |
| `docs/patterns/pattern_a/validation/evaluator_v01.md` | Evaluator 통합 검증 결과 | 아니오 | 종료된 통합 검증 기록이며 현재 계약은 코드·권위 문서에서 확인한다. | `docs/patterns/pattern_a/archive/validation/evaluator_v01.md` | Pattern A 권위 규격의 과거 검증 | 제목과 본문에 영어가 많음 |
| `docs/patterns/pattern_a/validation/final_production_closure.md` | Pattern A 운영 확정 당시 기록 | 아니오 | 운영 확정 시점의 역사적 closure와 다음 단계 기록이다. | `docs/patterns/pattern_a/archive/validation/final_production_closure.md` | 현재 공식 규격을 뒷받침한 역사 증거 | 과거 계획 상태가 현재 문서처럼 보일 수 있음 |
| `docs/patterns/pattern_a/validation/flow_confirmation_infrastructure_v01.md` | Phase 11 수급 확인 검증 | 아니오 | 종료된 인프라 검증 보고서다. | `docs/patterns/pattern_a/archive/validation/flow_confirmation_infrastructure_v01.md` | Pattern A 이후 축의 과거 검증 | 구분선 기반 옛 보고서 형식 |
| `docs/patterns/pattern_a/validation/full_universe_scanner_v01.md` | Phase 8 전수 스캐너 통합 검증 | 아니오 | 당시 전체 유니버스 통합 결과를 보존한다. | `docs/patterns/pattern_a/archive/validation/full_universe_scanner_v01.md` | 현재 운영 경로의 과거 검증 근거 | `Followup Revision`과 과거 상태 노출 |
| `docs/patterns/pattern_a/validation/full_universe_stage_filter_audit_20260814.md` | Phase 10 투자 적합성 감사 | 아니오 | 특정 기준일의 종료된 분포·필터 감사다. | `docs/patterns/pattern_a/archive/validation/full_universe_stage_filter_audit_20260814.md` | 투자 적합성의 과거 실측 | 구분선·표 ASCII 형식 |
| `docs/patterns/pattern_a/validation/investability_distribution_v01.md` | Phase 10A 분포 감사 | 아니오 | 후속 임계값 설계를 위한 종료된 분석이다. | `docs/patterns/pattern_a/archive/validation/investability_distribution_v01.md` | 투자 적합성 정책의 과거 근거 | 영어 용어와 과거 다음 단계 혼재 |
| `docs/patterns/pattern_a/validation/investability_integration_v01.md` | Phase 10C 후단 통합 검증 | 아니오 | 운영 스캐너 연결을 확인한 과거 결과다. | `docs/patterns/pattern_a/archive/validation/investability_integration_v01.md` | 현재 투자 적합성 구현의 과거 검증 | 긴 영문 제목·상태 토큰 |
| `docs/patterns/pattern_a/validation/investability_threshold_design_v01.md` | Phase 10B 임계값 설계 검증 | 아니오 | 종료된 임계값 비교·정책 권고 기록이다. | `docs/patterns/pattern_a/archive/validation/investability_threshold_design_v01.md` | 현재 필터의 과거 설계 근거 | 보고서형 제목과 영어 혼용 |
| `docs/patterns/pattern_a/validation/market_relative_strength_completion_v01.md` | Market RS 완료 기록 | 아니오 | Pattern A 주변 축의 과거 완료 기록이다. | `docs/patterns/pattern_a/archive/validation/market_relative_strength_completion_v01.md` | 현재 RS 영역의 과거 통합 근거 | 제목·본문의 역할이 파일명만으로 불명확 |
| `docs/patterns/pattern_a/validation/negative_control_v01.md` | 음성 대조군 검증 | 아니오 | Score 검증 당시의 종료된 대조군 기록이다. | `docs/patterns/pattern_a/archive/validation/negative_control_v01.md` | Pattern A 규격의 과거 검증 | 과거 분석 용어가 많음 |
| `docs/patterns/pattern_a/validation/oos2.md` | Pattern A Score v0.2 OOS2 결과 | 아니오 | 종료된 Score OOS·실패 메커니즘 분석이다. | `docs/patterns/pattern_a/archive/validation/oos2.md` | 공식 Score v0.2의 역사적 검증 근거 | 문서가 길고 섹션 구조가 불균일함 |
| `docs/patterns/pattern_a/validation/real_candidate_chart_review_v01.md` | 실후보 차트 검토 기록 | 아니오 | 종료된 수동 차트 검토와 Phase 9 기록이다. | `docs/patterns/pattern_a/archive/validation/real_candidate_chart_review_v01.md` | Pattern A 후보 품질의 과거 근거 | 영어·과거 backlog가 현재처럼 보임 |
| `docs/patterns/pattern_a/validation/relative_strength_infrastructure_v01.md` | 상대강도 인프라 검증 | 아니오 | 종료된 RS 인프라 검증 보고서다. | `docs/patterns/pattern_a/archive/validation/relative_strength_infrastructure_v01.md` | 현재 RS 축의 과거 검증 | 영어 보고서 형식 |
| `docs/patterns/pattern_a/validation/score_momentum_v01.md` | Score Momentum 연구·검증 | 아니오 | 후속 연구로 남은 과거 분석이며 현재 공식 규칙이 아니다. | `docs/patterns/pattern_a/archive/validation/score_momentum_v01.md` | Pattern A 공식 규격의 비채택 연구 | 문서 작성 당시 다음 단계 노출 |
| `docs/patterns/pattern_a/validation/stage_classifier_v01.md` | Stage Classifier 통합 검증 | 아니오 | 종료된 classifier 검증 결과다. | `docs/patterns/pattern_a/archive/validation/stage_classifier_v01.md` | 현재 Stage 계약의 과거 검증 | 영어 섹션과 과거 상태 혼재 |
| `docs/patterns/pattern_a/validation/stage_label_audit_freeze.md` | Stage 라벨 감사 봉인 | 아니오 | 과거 라벨 감사와 미구현 후보를 보존한다. | `docs/patterns/pattern_a/archive/validation/stage_label_audit_freeze.md` | 공식 Stage 의미론의 역사 근거 | 긴 감사 문서와 계획이 혼재 |
| `docs/patterns/pattern_a/validation/stage_oos_v01.md` | Stage OOS 사전등록·truth set | 아니오 | 종료된 OOS 설계와 당시 다음 단계 기록이다. | `docs/patterns/pattern_a/archive/validation/stage_oos_v01.md` | Stage 결과 문서의 사전등록 근거 | 과거 `NEXT` 상태 노출 |
| `docs/patterns/pattern_a/validation/stage_oos_v01_result.md` | Stage OOS 실행 결과 | 아니오 | 종료된 OOS 결과와 당시 판정을 보존한다. | `docs/patterns/pattern_a/archive/validation/stage_oos_v01_result.md` | Stage 계약의 과거 결과 근거 | 긴 결과 보고서 형식 |
| `docs/patterns/pattern_a/validation/universe_quality_v01.md` | 유니버스·데이터 품질 감사 | 아니오 | 특정 시점의 종료된 품질 감사다. | `docs/patterns/pattern_a/archive/validation/universe_quality_v01.md` | 현재 유니버스 기준의 과거 감사 | 기준일·상태 토큰이 현재처럼 보일 수 있음 |

### 3.2 이미 archive에 있는 Pattern A FAST 기록

| 파일 경로 | 문서 역할 | 현재 필요한가 | 근거 | 목표 위치 | 현재 기준 문서와 관계 | 가독성 문제 |
|---|---|---|---|---|---|---|
| `docs/patterns/pattern_a_fast/archive/research/architecture_v03.md` | V0.3 전략 아키텍처 동결 기록 | 아니오 | 이미 archive에 있는 종료 후보 아키텍처다. | 현재 archive 위치 유지 | V3/V4 후보의 역사적 설계 근거 | 영어 용어·실험 정책이 많음 |
| `docs/patterns/pattern_a_fast/archive/validation_plan/coverage_hole_activation_v02d.md` | Coverage Hole 사전등록 | 아니오 | 종료된 후보 검증 계획이다. | 현재 archive 위치 유지 | V1~V4 연구의 과거 계획 | 구분선·영문 제목 |
| `docs/patterns/pattern_a_fast/archive/validation_plan/entry_gate_incremental_value_v02a.md` | Entry Gate 증분 가치 사전등록 | 아니오 | 종료된 연구 질문과 계획이다. | 현재 archive 위치 유지 | FAST 후보 연구의 과거 근거 | 구분선·영문 용어 |
| `docs/patterns/pattern_a_fast/archive/validation_plan/fresh_out_of_sample_v03.md` | V0.3 Fresh OOS 사전등록 | 아니오 | 종료된 후보 검증 계획이다. | 현재 archive 위치 유지 | V3 후보 아키텍처의 과거 계획 | 구분선·영어 과다 |
| `docs/patterns/pattern_a_fast/archive/validation_plan/out_of_sample_v01.md` | Phase 13I-1 OOS 사전등록 | 아니오 | 후속 seal·evaluation 문서로 이어진 종료 기록이다. | 현재 archive 위치 유지 | OOS 평가 결과의 선행 계획 | 구분선 기반 옛 형식 |
| `docs/patterns/pattern_a_fast/archive/validation_plan/unavailable_decomposition_v02c.md` | UNAVAILABLE 분해 사전등록 | 아니오 | 종료된 후보 검증 계획이다. | 현재 archive 위치 유지 | FAST와 Pattern A 결합 연구의 과거 근거 | 구분선·영어 혼용 |
| `docs/patterns/pattern_a_fast/archive/validation_plan/weak_early_reversal_v02b.md` | WEAK 조기 반전 사전등록 | 아니오 | 종료된 후보 검증 계획이다. | 현재 archive 위치 유지 | FAST 후보 연구의 과거 근거 | 구분선·영어 혼용 |

### 3.3 Pattern A FAST 연구 기록

| 파일 경로 | 문서 역할 | 현재 필요한가 | 근거 | 목표 위치 | 현재 기준 문서와 관계 | 가독성 문제 |
|---|---|---|---|---|---|---|
| `docs/patterns/pattern_a_fast/research/daily_timing_features_v01.md` | 일봉 타이밍 특성 연구 | 아니오 | 종료된 연구 기록이며 현재 FAST 계약이 아니다. | `docs/patterns/pattern_a_fast/archive/research/daily_timing_features_v01.md` | FAST 명세의 과거 연구 근거 | 문서가 길고 제목 구조가 약함 |
| `docs/patterns/pattern_a_fast/research/feature_selection_role_assignment_v01.md` | Feature 역할 배정 연구 | 아니오 | 종료된 feature 설계 연구다. | `docs/patterns/pattern_a_fast/archive/research/feature_selection_role_assignment_v01.md` | FAST 규격의 과거 설계 근거 | 영어 용어가 많음 |
| `docs/patterns/pattern_a_fast/research/monthly_regime_features_v01.md` | 월봉 국면 feature 연구 | 아니오 | 후보 feature 연구 결과이며 현재 계약이 아니다. | `docs/patterns/pattern_a_fast/archive/research/monthly_regime_features_v01.md` | FAST 명세의 과거 연구 근거 | 연구 보고서 형식 |
| `docs/patterns/pattern_a_fast/research/next_candidate_design_direction_v01.md` | 다음 후보 설계 방향 | 아니오 | V2 이후 보류·종료된 후보 방향 기록이다. | `docs/patterns/pattern_a_fast/archive/research/next_candidate_design_direction_v01.md` | V3/V4 후보의 배경 기록 | 현재 `다음 단계`로 오인 가능 |
| `docs/patterns/pattern_a_fast/research/next_candidate_rule_spec_v01.md` | 다음 후보 규칙 정의 | 아니오 | V4 후보 규칙의 역사적 정의이며 현재 규칙이 아니다. | `docs/patterns/pattern_a_fast/archive/research/next_candidate_rule_spec_v01.md` | V4 역사 기록의 세부 근거 | 규칙 문서처럼 현재 권위로 보일 수 있음 |
| `docs/patterns/pattern_a_fast/research/score_stage_contract_prototype_v01.md` | Score·Stage 계약 시제품 | 아니오 | 시제품 연구이며 현재 계약으로 채택되지 않았다. | `docs/patterns/pattern_a_fast/archive/research/score_stage_contract_prototype_v01.md` | FAST 초기 설계의 과거 근거 | prototype 상태가 제목에서 약함 |
| `docs/patterns/pattern_a_fast/research/vs_pattern_a_lead_time_failure_analysis_v01.md` | Pattern A 대비 lead-time 실패 분석 | 아니오 | 종료된 비교·실패 분석이다. | `docs/patterns/pattern_a_fast/archive/research/vs_pattern_a_lead_time_failure_analysis_v01.md` | FAST 보조 패턴 판단의 과거 근거 | 영어 보고서 형식 |
| `docs/patterns/pattern_a_fast/research/weekly_trigger_features_v01.md` | 주봉 Trigger feature 연구 | 아니오 | 종료된 후보 feature 연구다. | `docs/patterns/pattern_a_fast/archive/research/weekly_trigger_features_v01.md` | FAST 주봉 명세의 과거 연구 근거 | 문서가 매우 길고 연구·결론 혼재 |

### 3.4 Pattern A FAST 종료 전략

| 파일 경로 | 문서 역할 | 현재 필요한가 | 근거 | 목표 위치 | 현재 기준 문서와 관계 | 가독성 문제 |
|---|---|---|---|---|---|---|
| `docs/patterns/pattern_a_fast/strategy/version_01/README.md` | 공식 과거 비교 기준선 | 아니오 | 현재 일반 종목 기본 전략은 V2이며, V2에서 archive의 V1로 링크하면 현재 전략 폴더에 남길 실질적 이유가 없다. | `docs/patterns/pattern_a_fast/archive/strategy/version_01/README.md` | V2의 역사적 비교 근거 | 역사 기준선임을 archive 위치로 명확히 할 필요 |
| `docs/patterns/pattern_a_fast/strategy/version_03/README.md` | 종료된 V3 후보 전략 계약 | 아니오 | V3는 공식 기본 전략으로 채택되지 않은 종료 후보다. | `docs/patterns/pattern_a_fast/archive/strategy/version_03/README.md` | V2와 비교된 역사적 후보 | 현재 전략 폴더에서 권위 문서처럼 보일 수 있음 |
| `docs/patterns/pattern_a_fast/strategy/version_04/README.md` | 종료된 V4 후보 전략 계약 | 아니오 | V4는 종료된 후보이며 현재 실행 대상이 아니다. | `docs/patterns/pattern_a_fast/archive/strategy/version_04/README.md` | V2/V3 후속 후보의 역사적 규칙 | 문서가 길고 후보 규칙이 현재처럼 보일 수 있음 |

### 3.5 Pattern A FAST 검증 결과

| 파일 경로 | 문서 역할 | 현재 필요한가 | 근거 | 목표 위치 | 현재 기준 문서와 관계 | 가독성 문제 |
|---|---|---|---|---|---|---|
| `docs/patterns/pattern_a_fast/validation/human_ground_truth_v01.md` | Human Ground Truth 준비·봉인 기록 | 아니오 | 종료된 Phase 13C-1 준비 기록이다. | `docs/patterns/pattern_a_fast/archive/validation/human_ground_truth_v01.md` | FAST Human 검증의 역사 근거 | 과거 상태와 현재 상태 구분 필요 |
| `docs/patterns/pattern_a_fast/validation/human_outcome_annotation_v01.md` | Human Outcome annotation 기록 | 아니오 | 종료된 Human annotation 결과다. | `docs/patterns/pattern_a_fast/archive/validation/human_outcome_annotation_v01.md` | FAST OOS 검증의 역사 근거 | 표·영어 상태가 많음 |
| `docs/patterns/pattern_a_fast/validation/human_point_in_time_annotation_checkpoint_v01.md` | PIT annotation checkpoint | 아니오 | Outcome 이전 PIT 판단을 보존하는 종료 checkpoint다. | `docs/patterns/pattern_a_fast/archive/validation/human_point_in_time_annotation_checkpoint_v01.md` | Human ground truth의 선행 무결성 근거 | 구분선 기반 형식 |
| `docs/patterns/pattern_a_fast/validation/human_positive_anchor_v01.md` | Human positive anchor 기록 | 아니오 | OOS metric에 사용하지 않는 질적 참고 anchor다. | `docs/patterns/pattern_a_fast/archive/validation/human_positive_anchor_v01.md` | FAST Human 검증의 보조 역사 근거 | 간결하지만 현재 규칙으로 오인 가능 |
| `docs/patterns/pattern_a_fast/validation/investable_out_of_sample_evaluation_v01.md` | Phase 13J-4 Investable OOS 결과 | 아니오 | 종료된 평가 결과이며 현재 공식 전략을 뜻하지 않는다. | `docs/patterns/pattern_a_fast/archive/validation/investable_out_of_sample_evaluation_v01.md` | FAST OOS 검증의 역사 결과 | 짧은 옛 보고서 형식 |
| `docs/patterns/pattern_a_fast/validation/investable_out_of_sample_human_ground_truth_v01.md` | Investable OOS Human 결과 | 아니오 | 종료된 PASS B 결과·ground truth 봉인 기록이다. | `docs/patterns/pattern_a_fast/archive/validation/investable_out_of_sample_human_ground_truth_v01.md` | Phase 13J OOS 결과의 역사 근거 | 구분선·영어 표 형식 |
| `docs/patterns/pattern_a_fast/validation/investable_out_of_sample_human_stage_freeze_v01.md` | Investable OOS Stage freeze | 아니오 | 종료된 PASS A stage freeze 기록이다. | `docs/patterns/pattern_a_fast/archive/validation/investable_out_of_sample_human_stage_freeze_v01.md` | Phase 13J OOS 결과의 선행 근거 | 과거 관문이 현재 대기처럼 보일 수 있음 |
| `docs/patterns/pattern_a_fast/validation/out_of_sample_evaluation_v01.md` | Phase 13I-2 OOS 평가 결과 | 아니오 | 종료된 Reserved OOS 평가 결과다. | `docs/patterns/pattern_a_fast/archive/validation/out_of_sample_evaluation_v01.md` | FAST OOS 검증의 역사 결과 | 구분선·영문 제목 |
| `docs/patterns/pattern_a_fast/validation/out_of_sample_ground_truth_seal_v01.md` | Reserved OOS ground truth seal | 아니오 | 종료된 Human ground truth 봉인 기록이다. | `docs/patterns/pattern_a_fast/archive/validation/out_of_sample_ground_truth_seal_v01.md` | OOS evaluation의 입력 무결성 근거 | 구분선·표 형식 |
| `docs/patterns/pattern_a_fast/validation/out_of_sample_outcome_blind_review_v01.md` | Outcome blind review 안내·기록 | 아니오 | 종료된 PASS B review 기록이다. | `docs/patterns/pattern_a_fast/archive/validation/out_of_sample_outcome_blind_review_v01.md` | OOS ground truth의 과정 기록 | 영어 안내문과 표 혼재 |
| `docs/patterns/pattern_a_fast/validation/out_of_sample_stage_blind_review_v01.md` | Stage blind review 안내·기록 | 아니오 | 종료된 PASS A review 기록이다. | `docs/patterns/pattern_a_fast/archive/validation/out_of_sample_stage_blind_review_v01.md` | OOS ground truth의 과정 기록 | 영어 안내문과 표 혼재 |
| `docs/patterns/pattern_a_fast/validation/phase_13_final_synthesis_v01.md` | Phase 13 최종 종합 | 아니오 | 종료된 Human/OOS 검증 종합 기록이다. | `docs/patterns/pattern_a_fast/archive/validation/phase_13_final_synthesis_v01.md` | FAST 검증 생애주기의 역사 요약 | 과거 상태와 다음 단계 노출 |
| `docs/patterns/pattern_a_fast/validation/strategy_finalization_v01_evaluation.md` | V1 후보 선택 평가 결과 | 아니오 | V1 후보의 과거 평가이며 V2가 현재 기본 전략이다. | `docs/patterns/pattern_a_fast/archive/validation/strategy_finalization_v01_evaluation.md` | V1 역사 기준선의 선택 근거 | `READY_FOR_PREREGISTRATION`이 현재처럼 보일 수 있음 |
| `docs/patterns/pattern_a_fast/validation/version_03_matched_ab_failure_review.md` | V3 A/B 실패 사례 검토 | 아니오 | 종료된 V3 후보 실패 분석이다. | `docs/patterns/pattern_a_fast/archive/validation/version_03_matched_ab_failure_review.md` | V3 종료 판단의 역사 근거 | 현재 V2와의 관계를 먼저 설명해야 읽힘 |

### 3.6 Pattern A FAST 검증 계획·백테스트 기록

| 파일 경로 | 문서 역할 | 현재 필요한가 | 근거 | 목표 위치 | 현재 기준 문서와 관계 | 가독성 문제 |
|---|---|---|---|---|---|---|
| `docs/patterns/pattern_a_fast/validation_plan/combined_exit_policy_v01.md` | 종료된 결합 청산 정책 사전등록 | 아니오 | 과거 후보 청산 정책 평가 계획이다. | `docs/patterns/pattern_a_fast/archive/validation_plan/combined_exit_policy_v01.md` | FAST 후보 연구의 과거 계획 | 영문 정책명과 구분선 |
| `docs/patterns/pattern_a_fast/validation_plan/investable_out_of_sample_v01.md` | Phase 13J-1 Investable OOS 사전등록 | 아니오 | 특별 검토 결과 현재 실행 지시가 아닌 종료된 사전등록이다. | `docs/patterns/pattern_a_fast/archive/validation_plan/investable_out_of_sample_v01.md` | Investable OOS 결과의 선행 계획 | 구분선·영어 본문이 많음 |
| `docs/patterns/pattern_a_fast/validation_plan/large_cap40_entry_hypothesis_v01.md` | 대형주 40개 사후 진단 가설 | 아니오 | 종료된 사후 진단 사전등록이며 일반 전략 기준이 아니다. | `docs/patterns/pattern_a_fast/archive/validation_plan/large_cap40_entry_hypothesis_v01.md` | FAST 진입 연구의 과거 진단 | 생존편향 caveat가 본문에 분산됨 |
| `docs/patterns/pattern_a_fast/validation_plan/realistic_backtest_common_conditions_v01.md` | 현실적 백테스트 공통조건 | 아니오 | 완료된 백테스트·V2 비교의 역사적 실행조건이다. | `docs/patterns/pattern_a_fast/archive/validation_plan/realistic_backtest_common_conditions_v01.md` | V2 비교의 과거 공통 기준 | 현재 실행계약으로 오인 가능 |
| `docs/patterns/pattern_a_fast/validation_plan/realistic_backtest_decision_proposal_v01.md` | 과거 백테스트 조건 결정안 | 아니오 | 당시 사용자 검토용 제안이며 현재 승인 문서가 아니다. | `docs/patterns/pattern_a_fast/archive/validation_plan/realistic_backtest_decision_proposal_v01.md` | 공통조건 확정의 선행 제안 | 구분선·과거 검토 상태 |
| `docs/patterns/pattern_a_fast/validation_plan/realistic_backtest_final_approval_proposal_v01.md` | 과거 백테스트 최종 승인안 | 아니오 | 당시 승인 결과를 보존하는 역사 기록이다. | `docs/patterns/pattern_a_fast/archive/validation_plan/realistic_backtest_final_approval_proposal_v01.md` | 공통조건 확정의 승인 근거 | 승인 완료와 현재 실행을 혼동할 수 있음 |
| `docs/patterns/pattern_a_fast/validation_plan/strategy_finalization_v01.md` | V1 후보 선택 사전등록 | 아니오 | 특별 검토 결과 종료된 과거 사전등록이며 현재 실행 지시가 아니다. | `docs/patterns/pattern_a_fast/archive/validation_plan/strategy_finalization_v01.md` | V1 평가 결과의 선행 계획 | 구분선·영어 과다 |
| `docs/patterns/pattern_a_fast/validation_plan/trading_policy_entry_v01.md` | FAST 진입 정책 사전등록 | 아니오 | 종료된 진입 신호 품질 평가 계획이다. | `docs/patterns/pattern_a_fast/archive/validation_plan/trading_policy_entry_v01.md` | FAST 진입 연구의 과거 근거 | 구분선·영어 제목 |
| `docs/patterns/pattern_a_fast/validation_plan/version_03_matched_ab_validation.md` | V3 동일 진입 A/B 계획 | 아니오 | V3 후보 검증을 위한 종료된 계획이다. | `docs/patterns/pattern_a_fast/archive/validation_plan/version_03_matched_ab_validation.md` | V3 실패 검토의 선행 계획 | 계획 상태가 현재처럼 보일 수 있음 |
| `docs/patterns/pattern_a_fast/validation_plan/version_04_matched_ab_validation.md` | V4 동일 진입 A/B 계획 | 아니오 | V4 후보 검증을 위한 종료된 계획이다. | `docs/patterns/pattern_a_fast/archive/validation_plan/version_04_matched_ab_validation.md` | V4 역사 규칙의 검증 계획 | 문서가 길고 후보 승인 조건이 현재처럼 보일 수 있음 |

## 4. `DELETE_CANDIDATE`

현재 지정 없음. 확인한 문서들은 대부분 현재 기준은 아니지만 고유한 표본,
수치, 봉인, 실패 메커니즘, 사전등록 또는 역사적 의사결정 근거를 가진다.
특히 이미 `archive/`에 있는 문서는 중복처럼 보여도 원본 계획·봉인·결과의
관계를 확인하기 전에는 삭제 후보로 만들지 않는다. 후속 이동 단계에서 링크와
아티팩트 참조를 확인한 뒤에만 독립 근거가 없는 중간 복사본을 별도로 재검토한다.

## 5. Archive 이동 제안 구조

이번 단계에서는 실제 이동하지 않는다. 다음 단계에서 `git mv`와 링크 검증을
별도로 수행한다.

```text
docs/patterns/
├── README.md                                      KEEP
├── pattern_a/
│   ├── README.md                                  KEEP
│   ├── spec/production_authority.md               KEEP
│   ├── spec/investability_policy.md               KEEP: 현재 투자 적합성 정책
│   └── archive/
│       ├── research/                              Pattern A 연구 기록
│       └── validation/                            Pattern A 검증 기록
└── pattern_a_fast/
    ├── README.md                                  KEEP
    ├── specification/                             KEEP
    ├── strategy/
    │   ├── README.md                              KEEP
    │   └── version_02/README.md                   KEEP: 현재 기본 전략
    └── archive/
        ├── strategy/version_01/                   공식 과거 비교 기준선
        ├── strategy/version_03/                   종료 후보 전략
        ├── strategy/version_04/                   종료 후보 전략
        ├── research/                              FAST 연구 기록
        ├── validation/                            FAST 검증 결과·Human 기록
        └── validation_plan/                       FAST 사전등록·백테스트 계획
```

기존 `pattern_a_fast/archive/` 문서는 제안 구조와 이미 일치하므로 우선
그대로 보존한다. 실제 이동 시에는 `README.md`의 링크를 먼저 또는 같은
커밋에서 갱신하고, 과거 문서의 artifact·commit·경로 참조는 삭제하지 않는다.

## 6. KEEP 문서 중 가독성 개선 필요 목록

이번 단계에서 본문은 수정하지 않는다. 다음 정리 단계의 후보만 기록한다.

1. `pattern_a/spec/production_authority.md` — 현재 공식 규격과 역사 근거의
   링크 경계를 유지하고, 과거 원문을 다시 본문에 복사하지 않는다.
2. `pattern_a_fast/README.md` 및 `strategy/README.md` — 현재 문서와 archive로
   이동할 역사 문서의 연결을 한눈에 보이게 한다.
3. `pattern_a_fast/specification/README.md` — 핵심 정의·상태·PIT 계약을 문서
   앞부분에서 더 빠르게 찾을 수 있게 한다.
4. `pattern_a_fast/specification/weekly_lifecycle.md` — 영어 상태 토큰은
   유지하되 첫 설명과 일반 문장을 한글 중심으로 정리한다.
5. `pattern_a/spec/investability_policy.md` 및
   `docs/validation/backtest_common_rules.md` — 핵심 현재 기준을 짧게
   유지하고 역사 보고서와 중복 서술하지 않는다.

V1 전략 README는 현재 전략 폴더에서 제외하고 archive 대상으로 재분류했다.
과거 비교 기준선이라는 역할은 archive 경로와 V2 문서의 링크로 충분히
보존한다.

## 7. 다음 실행 단계

1. 이 검토 문서를 기준으로 archive 이동 대상과 링크 변경 목록을 확정한다.
2. `git mv`로 종료 문서를 제안 구조에 이동하고 README 링크를 함께 갱신한다.
3. 이동 후 `rg`로 이전 경로·깨진 링크·현재 문서의 `NEXT`, `PENDING`,
   `IN_PROGRESS` 노출을 점검한다.
4. 그 결과를 별도 셀프 리뷰한 뒤, 중복 근거가 확인된 경우에만
   `DELETE_CANDIDATE`를 다시 판정한다.
5. 이번 단계의 범위 밖인 본문 한글화, 코드·아티팩트 수정, 백테스트, 테스트,
   외부 API 호출은 별도 지시가 있을 때까지 수행하지 않는다.
