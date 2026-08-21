"""Pattern A Stage Label Audit Freeze manifest.

`PatternAStage`(base/transition/early_trend/progressed/weak)는 지금까지
Score 계산 결과에서 파생된 provisional 값이었고, 자동 분류 threshold는
구현된 적이 없다(`pattern_a_feature_set.py`의 `PatternAStage` docstring).
이 manifest는 그 classifier가 맞춰야 할 manual ground-truth Stage 라벨
46건을 freeze한다 — classifier 구현(threshold/rule)은 아직 포함하지
않는다.

**Score와의 독립성**: 여기 `audited_stage`/`stage_reason`은 전부
`build_historical_snapshot(..., include_incomplete_periods=False)`로 계산한
raw `FeatureRow` 값만 근거로 판정했다. `score_pattern_a()`/`base_score`/
`transition_score`/`balanced_core_score`/`alignment_bonus`/
`confirmation_bonus`/`progressed_penalty` 등 Score 파생 값은 판정에
전혀 쓰지 않았다.

**stage_reason vs notes**: `stage_reason`은 snapshot 시점까지의 Feature
값만 근거로 든다("이후" 같은 forward-looking 표현 금지). `notes`는
원본 dataset(selection_reason/audit_note/negative_control label)의
맥락을 provenance로만 인용한다 — Stage 판정 근거로 쓰지 않는다.

**Source dataset 4개**(신규 KRX fetch 없음, 전부 기존 캐시 재사용):
    OOS2_v0.2_manifest        - oos_v02_manifest.py, 22건
                                 (trajectory/boundary 20건 + WEAK 보강 2건)
    OOS_v0.1_stage_audit      - oos_v01_manifest.py OOS_V01_STAGE_AUDIT, 13건
                                 (애매한 경계 "/" 표기 2건 제외)
    negative_control_compare  - score_v02_candidate_compare.py
                                 NEGATIVE_CONTROL_SNAPSHOTS, 8건
                                 (outcome 기반 label은 쓰지 않고 raw Feature로
                                 독립 재분류)
    holdout_early_trend_compare - score_v02_candidate_compare.py
                                 HOLDOUT_SNAPSHOTS 중 label=early_trend, 3건
                                 (EARLY_TREND 표본 보강용)

자세한 정의/방법론/boundary 처리는 docs/patterns/pattern_a/validation/stage_label_audit_freeze.md
참고.
"""

from __future__ import annotations

from dataclasses import dataclass

from trend_scanner.patterns.pattern_a_feature_set import PatternAStage

STAGE_MANIFEST_DATASET_VERSION = "pattern_a_stage_v0.1_audit"


@dataclass(frozen=True)
class StageLabelSpec:
    ticker: str
    name: str
    snapshot_date: str
    audited_stage: PatternAStage
    stage_reason: str
    source_dataset: str
    notes: str


PATTERN_A_STAGE_LABELS: tuple[StageLabelSpec, ...] = (
    # ============================================================
    # Source: OOS2_v0.2_manifest (22)
    # ============================================================
    StageLabelSpec(
        "042700", "한미반도체", "2019-12-31", PatternAStage.BASE,
        "range_position=0.333로 박스 중간대, ma24_slope=-0.057로 core가 "
        "아직 음전환 상태, weekly_ma12_slope=+0.037로 미미한 양전환 "
        "신호만 있음, distance_to_resistance=0.413로 저항선까지 여유.",
        "OOS2_v0.2_manifest",
        "원 case_group=positive_pre_breakout.",
    ),
    StageLabelSpec(
        "105560", "KB금융", "2023-12-31", PatternAStage.BASE,
        "range_position=0.530 중간대, ma24_slope=-0.005로 거의 평탄, "
        "weekly_ma12_slope=-0.022로 음수 — 두 slope 축 모두 전환 신호 없음.",
        "OOS2_v0.2_manifest",
        "원 case_group=positive_pre_breakout.",
    ),
    StageLabelSpec(
        "086790", "하나금융지주", "2023-12-31", PatternAStage.BASE,
        "range_position=0.522 중간대, ma24_slope=-0.002/weekly_ma12_slope"
        "=-0.003로 둘 다 거의 평탄 — 전환 조짐 없음.",
        "OOS2_v0.2_manifest",
        "원 case_group=positive_pre_breakout.",
    ),
    StageLabelSpec(
        "001040", "CJ", "2023-12-31", PatternAStage.TRANSITION,
        "ma24_slope=+0.006로 core가 막 양전환, weekly_ma12_slope=+0.029도 "
        "동반 양전환 — 둘 다 아직 미약하지만 방향이 같이 돌기 시작한 "
        "초기 전환 신호.",
        "OOS2_v0.2_manifest",
        "원 case_group=positive_pre_breakout.",
    ),
    StageLabelSpec(
        "000880", "한화", "2024-12-31", PatternAStage.BASE,
        "range_position=0.432 중간대, ma24_slope=+0.007로 거의 평탄, "
        "weekly_ma12_slope=-0.023로 음수 — core/weekly 방향이 엇갈려 "
        "아직 확인된 전환이 아님.",
        "OOS2_v0.2_manifest",
        "원 case_group=positive_pre_breakout.",
    ),
    StageLabelSpec(
        "042700", "한미반도체", "2020-11-30", PatternAStage.EARLY_TREND,
        "ma24_slope=+0.030, weekly_ma12_slope=+0.054로 둘 다 뚜렷한 "
        "양전환, range_position=0.829로 상단 근접, distance_to_resistance"
        "=0.106로 저항선 코앞. avg_price_change_12m=0.278로 아직 큰 "
        "확장 전.",
        "OOS2_v0.2_manifest",
        "원 case_group=positive_early_trend.",
    ),
    StageLabelSpec(
        "105560", "KB금융", "2024-02-29", PatternAStage.TRANSITION,
        "ma24_slope=0.0000으로 core는 전혀 안 돌았음, weekly_ma12_slope"
        "=+0.085로 weekly만 강하게 먼저 양전환 — price/weekly가 leads, "
        "core(trend)가 lags하는 전형적 TRANSITION 프로필.",
        "OOS2_v0.2_manifest",
        "원 case_group=positive_early_trend. 086790(같은 날짜) EARLY_TREND"
        "와의 경계 사례 — 086790 참고.",
    ),
    StageLabelSpec(
        "086790", "하나금융지주", "2024-02-29", PatternAStage.EARLY_TREND,
        "ma24_slope=+0.012로 core가 이미 양전환, weekly_ma12_slope=+0.121"
        "로 강한 확인, distance_to_resistance=0.057로 저항선 코앞 — "
        "105560(같은 날짜, ma24_slope=0.0000)과 달리 core가 실제로 돌았다.",
        "OOS2_v0.2_manifest",
        "원 case_group=positive_early_trend. 105560(같은 날짜)과 stage "
        "경계 — 판별축은 ma24_slope 양전환 여부(0.0000 vs +0.012)와 "
        "distance_to_resistance.",
    ),
    StageLabelSpec(
        "001040", "CJ", "2024-03-31", PatternAStage.EARLY_TREND,
        "range_position=0.959로 저항선 근접, ma24_slope=+0.037, "
        "weekly_ma12_slope=+0.061로 둘 다 뚜렷한 양전환, "
        "distance_to_resistance=0.023로 사실상 저항선 도달.",
        "OOS2_v0.2_manifest",
        "원 case_group=positive_early_trend.",
    ),
    StageLabelSpec(
        "000880", "한화", "2025-02-28", PatternAStage.EARLY_TREND,
        "ma24_slope=+0.026, weekly_ma12_slope=+0.120로 둘 다 뚜렷한 "
        "양전환, range_position=0.625로 아직 최상단은 아니나 "
        "distance_to_resistance=0.220로 좁혀지는 중.",
        "OOS2_v0.2_manifest",
        "원 case_group=positive_early_trend(fast_mover 성격, range_position"
        "은 다른 EARLY_TREND 사례보다 낮지만 두 slope 축 확인은 뚜렷함).",
    ),
    StageLabelSpec(
        "042700", "한미반도체", "2023-12-31", PatternAStage.PROGRESSED,
        "avg_price_change_12m=+1.780로 극단적 확장, ma_spread=0.486로 "
        "이평선 넓게 벌어짐, ma24_slope=+0.249, range_position=0.896 — "
        "core 확인은 이미 끝나고 확장 국면.",
        "OOS2_v0.2_manifest",
        "원 case_group=positive_trend_progressed.",
    ),
    StageLabelSpec(
        "105560", "KB금융", "2025-12-31", PatternAStage.PROGRESSED,
        "avg_price_change_12m=+0.325, ma_spread=0.201, ma24_slope=+0.104, "
        "range_position=0.837 — 확장이 상당히 진행됨.",
        "OOS2_v0.2_manifest",
        "원 case_group=positive_trend_progressed.",
    ),
    StageLabelSpec(
        "086790", "하나금융지주", "2025-12-31", PatternAStage.PROGRESSED,
        "avg_price_change_12m=+0.315, ma_spread=0.209, ma24_slope=+0.100, "
        "range_position=0.891 — 확장이 상당히 진행됨.",
        "OOS2_v0.2_manifest",
        "원 case_group=positive_trend_progressed.",
    ),
    StageLabelSpec(
        "214150", "클래시스", "2023-12-31", PatternAStage.PROGRESSED,
        "avg_price_change_12m=+0.769, ma_spread=0.343, ma24_slope=+0.105, "
        "range_position=0.827 — 큰 폭 확장.",
        "OOS2_v0.2_manifest",
        "원 case_group=positive_trend_progressed.",
    ),
    StageLabelSpec(
        "000810", "삼성화재", "2024-06-30", PatternAStage.PROGRESSED,
        "range_position=0.979로 최상단, avg_price_change_12m=+0.387, "
        "ma_spread=0.185, ma24_slope=+0.080 — 확인+확장 모두 뚜렷.",
        "OOS2_v0.2_manifest",
        "원 case_group=positive_trend_progressed.",
    ),
    StageLabelSpec(
        "015760", "한국전력", "2025-11-30", PatternAStage.PROGRESSED,
        "range_position=0.958, avg_price_change_12m=+0.514, ma_spread"
        "=0.271, ma24_slope=+0.137 — 확장 국면.",
        "OOS2_v0.2_manifest",
        "원 case_group=positive_trend_progressed.",
    ),
    StageLabelSpec(
        "015760", "한국전력", "2023-12-31", PatternAStage.BASE,
        "월봉 이동평균 구조가 이미 상당히 수렴했고(ma_spread=0.095, "
        "비교군 중 좁은 편), 하락 속도도 완만해지는 중(ma24_slope=-0.022"
        "는 가파른 하락으로 보기 어려운 수준, ma24_slope_acceleration"
        "=+0.012로 계속 감속)이며, weekly_ma12_slope=+0.019로 단기 "
        "방향도 이미 양전환 — 절대 range_position(0.241)은 낮지만, "
        "여러 구조 신호가 함께 활성 하락이 더 이상 지배적이지 않고 "
        "베이스 형성 쪽으로 수렴하고 있음을 가리켜 현재 episode의 BASE"
        "로 판단.",
        "OOS2_v0.2_manifest",
        "원 case_group=downtrend_reversal_boundary. 재감사 전에는 "
        "range_position 단독 기준으로 WEAK였다. docs/validation/"
        "pattern_a_stage.md의 diagnostic checklist(가파름/방향/가속/"
        "수렴)로 처음 재검토했고, 이후 gate 형태가 global rule처럼 "
        "읽힌다는 지적을 반영해 질적 lifecycle 판단(활성 하락이 구조를 "
        "지배하는지 여부)으로 다시 확인 — 결론(BASE)은 동일하게 유지됨.",
    ),
    StageLabelSpec(
        "034220", "LG디스플레이", "2020-12-31", PatternAStage.TRANSITION,
        "ma24_slope=-0.012로 아직 약한 음수지만, weekly_ma12_slope=+0.031"
        "로 weekly가 먼저 뚜렷하게 양전환 — price leads/core lags 구조. "
        "range_position=0.390, distance_to_resistance=0.450로 고점까지는 "
        "여전히 멀다.",
        "OOS2_v0.2_manifest",
        "원 case_group=downtrend_reversal_boundary.",
    ),
    StageLabelSpec(
        "011210", "현대위아", "2019-12-31", PatternAStage.BASE,
        "avg_price_change_12m=+0.012로 사실상 보합(비교 대상 9건 중 "
        "유일하게 플러스), ma_spread=0.050로 비교 대상 9건 중 가장 좁음"
        "(가장 수렴), ma24_slope_acceleration=+0.018로 감속, "
        "range_position_52w=0.642가 36개월 range_position(0.421)보다 "
        "뚜렷하게 높음 — 9건 재감사에서 가장 뚜렷한 BASE 사례.",
        "OOS2_v0.2_manifest",
        "원 case_group=downtrend_reversal_boundary. BASE/WEAK 재감사 "
        "9건 비교에서도 재확인됨(변경 없음).",
    ),
    StageLabelSpec(
        "023530", "롯데쇼핑", "2025-05-31", PatternAStage.TRANSITION,
        "ma24_slope=-0.020로 약한 음수지만, weekly_ma12_slope=+0.065로 "
        "weekly가 뚜렷하게 양전환 — 034220(2020-12-31)과 같은 "
        "price-leads/core-lags 프로필. range_position=0.491, "
        "distance_to_resistance=0.271.",
        "OOS2_v0.2_manifest",
        "원 case_group=downtrend_reversal_boundary.",
    ),
    StageLabelSpec(
        "023530", "롯데쇼핑", "2023-12-31", PatternAStage.BASE,
        "하락 속도가 완만해지는 중(ma24_slope=-0.025는 가파른 하락으로 "
        "보기 어려운 수준, ma24_slope_acceleration=+0.023로 감속)이고 "
        "weekly_ma12_slope=+0.021로 단기 방향도 양전환 — "
        "range_position=0.143로 비교군 중 가장 낮은 절대 위치이고 "
        "ma_spread=0.160도 완전히 좁혀진 수준은 아니라서, 이번 BASE "
        "10건 중 가장 근거가 얇은 경계 사례다. 그럼에도 활성 하락이 "
        "구조를 지배한다고 보기보다는 낮은 위치에서 새로운 베이스를 "
        "만들어가는 초기 단계로 판단해 BASE 유지.",
        "OOS2_v0.2_manifest",
        "원 case_group=hard_negative_false_turn. Stage 라벨 목적으로만 "
        "재사용 — 이 snapshot의 Score 결과 자체는 이번 manifest와 "
        "무관하다. 재감사 전에는 range_position 단독 기준으로 WEAK였다. "
        "diagnostic checklist로 먼저 재검토했고, checklist가 global "
        "rule처럼 읽힌다는 지적을 반영해 질적 lifecycle 판단으로 다시 "
        "확인 — 결론(BASE, 다만 가장 얇은 근거)은 동일하게 유지됨.",
    ),
    StageLabelSpec(
        "034220", "LG디스플레이", "2020-09-30", PatternAStage.WEAK,
        "weekly_ma12_slope=+0.107과 ma24_slope_acceleration=+0.026로 "
        "방향 전환/감속 조짐은 있지만, ma24_slope=-0.049는 여전히 가파른 "
        "하락 수준이라 활성 하락이 아직 가격 구조를 지배한다고 본다 — "
        "베이스가 충분히 형성됐다고 보기엔 이르다. range_position"
        "=0.262.",
        "OOS2_v0.2_manifest",
        "원 case_group=weak_core_strong_support. Stage 라벨 목적으로만 "
        "재사용(WEAK 표본 보강). 011170(2023-01-31, ma24_slope=-0.0475)"
        "과 ma24_slope가 거의 동일해 재감사에서 직접 비교한 사례 — "
        "diagnostic checklist와 질적 lifecycle 판단 양쪽 모두 두 종목 "
        "다 WEAK로 일치함(011170도 동일하게 WEAK 재분류, 아래 참고). "
        "즉 이 쌍의 결론은 '034220을 BASE로 올린다'가 아니라 '011170을 "
        "WEAK로 내린다'임.",
    ),
    # ============================================================
    # Source: OOS_v0.1_stage_audit (13)
    # ============================================================
    StageLabelSpec(
        "010620", "HD현대미포", "2023-12-31", PatternAStage.BASE,
        "range_position=0.569 중간대, ma24_slope=+0.010로 거의 평탄, "
        "weekly_ma12_slope=-0.029로 음수 — core/weekly 모두 확인된 "
        "전환 없음.",
        "OOS_v0.1_stage_audit",
        "원 audited_stage_label=PRE_BREAKOUT.",
    ),
    StageLabelSpec(
        "010620", "HD현대미포", "2024-12-31", PatternAStage.PROGRESSED,
        "range_position=0.901, avg_price_change_12m=+0.175, ma_spread"
        "=0.212, ma24_slope=+0.054 — 확인+확장 모두 뚜렷.",
        "OOS_v0.1_stage_audit",
        "원 audited_stage_label=TREND_PROGRESSED.",
    ),
    StageLabelSpec(
        "012450", "한화에어로스페이스", "2021-12-31", PatternAStage.TRANSITION,
        "ma24_slope=+0.027로 core가 이미 양전환됐지만 weekly_ma12_slope"
        "=-0.036로 음수라 weekly 확인이 아직 안 됨 — core leads/weekly "
        "lags 구조. avg_price_change_12m=+0.723로 이미 상당히 올라온 "
        "상태라 순수 BASE로 보기는 어려움.",
        "OOS_v0.1_stage_audit",
        "원 audited_stage_label=PRE_BREAKOUT. avg_price_change_12m이 이미 "
        "높아 원 라벨(PRE_BREAKOUT)과 달리 TRANSITION으로 재분류함 — "
        "raw Feature 기준 재검토.",
    ),
    StageLabelSpec(
        "012450", "한화에어로스페이스", "2022-12-31", PatternAStage.PROGRESSED,
        "range_position=0.817, avg_price_change_12m=+0.354, ma_spread"
        "=0.234, ma24_slope=+0.117 — 확장 국면.",
        "OOS_v0.1_stage_audit",
        "원 audited_stage_label=TREND_PROGRESSED.",
    ),
    StageLabelSpec(
        "012450", "한화에어로스페이스", "2024-06-30", PatternAStage.PROGRESSED,
        "range_position=0.970, avg_price_change_12m=+0.841, ma_spread"
        "=0.312, ma24_slope=+0.212 — 극단적 확장.",
        "OOS_v0.1_stage_audit",
        "원 audited_stage_label=TREND_PROGRESSED.",
    ),
    StageLabelSpec(
        "079550", "LIG넥스원", "2020-12-31", PatternAStage.BASE,
        "range_position=0.332로 박스 중간대, ma24_slope=-0.018, "
        "weekly_ma12_slope=-0.029로 둘 다 음수 — 아직 core가 돌지 않은 "
        "박스권.",
        "OOS_v0.1_stage_audit",
        "원 audited_stage_label=PRE_BREAKOUT.",
    ),
    StageLabelSpec(
        "079550", "LIG넥스원", "2021-12-31", PatternAStage.PROGRESSED,
        "range_position=0.925, avg_price_change_12m=+0.585, ma_spread"
        "=0.216, ma24_slope=+0.083 — 확장 국면.",
        "OOS_v0.1_stage_audit",
        "원 audited_stage_label=TREND_PROGRESSED.",
    ),
    StageLabelSpec(
        "079550", "LIG넥스원", "2023-12-31", PatternAStage.PROGRESSED,
        "이번 snapshot 자체의 Feature(avg_price_change_12m=+0.029, "
        "ma_spread=0.072, range_position=0.861)만 보면 EARLY_TREND와도 "
        "구분이 어렵다. 하지만 이 snapshot 이전(2021-12-31: "
        "avg_price_change_12m=+0.585/ma_spread=0.216)에 이미 큰 폭의 "
        "breakout+expansion을 통과한 lifecycle 경로가 있고, Stage를 "
        "lifecycle 개념으로 정의하기로 한 이번 라운드 결정(docs/"
        "validation/pattern_a_stage.md 'Stage semantic' 참고)에 따라 "
        "그 경로를 근거로 PROGRESSED를 유지한다 — '한 번 확장에 진입한 "
        "종목이 잠시 쉬어간다고 EARLY_TREND로 되돌아가지 않는다'는 "
        "원칙의 대표 사례.",
        "OOS_v0.1_stage_audit",
        "원 audited_stage_label=TREND_PROGRESSED. snapshot_date "
        "이전(<=2023-12-31)의 같은 티커 과거 이력만 근거로 썼으므로 "
        "look-ahead가 아니다(2024년 이후 데이터는 쓰지 않음). Stage를 "
        "current-state로 정의했다면 이 사례는 재라벨링이 필요했을 것 — "
        "그 모순을 남기지 않기 위해 이번 라운드에서 semantic을 lifecycle"
        "로 명시적으로 확정함.",
    ),
    StageLabelSpec(
        "005490", "POSCO홀딩스", "2022-12-31", PatternAStage.TRANSITION,
        "ma24_slope=+0.016, weekly_ma12_slope=+0.076로 둘 다 막 "
        "양전환 시작 — range_position=0.512 중간대.",
        "OOS_v0.1_stage_audit",
        "원 audited_stage_label=PRE_BREAKOUT.",
    ),
    StageLabelSpec(
        "005490", "POSCO홀딩스", "2023-03-31", PatternAStage.EARLY_TREND,
        "range_position=0.826, ma24_slope=+0.020, weekly_ma12_slope"
        "=+0.055로 둘 다 뚜렷한 양전환, distance_to_resistance=0.110로 "
        "저항선 근접.",
        "OOS_v0.1_stage_audit",
        "원 audited_stage_label=EARLY_TREND — 원 라벨과 raw Feature "
        "재분류 결과가 일치.",
    ),
    StageLabelSpec(
        "005490", "POSCO홀딩스", "2023-07-31", PatternAStage.PROGRESSED,
        "avg_price_change_12m=+0.192, ma_spread=0.154, ma24_slope=+0.045, "
        "range_position=0.790 — 확장 진행.",
        "OOS_v0.1_stage_audit",
        "원 audited_stage_label=TREND_PROGRESSED.",
    ),
    StageLabelSpec(
        "042660", "한화오션", "2024-10-31", PatternAStage.TRANSITION,
        "ma24_slope=+0.067로 core는 이미 상당히 양전환됐지만 "
        "weekly_ma12_slope=+0.002로 거의 평탄 — core leads/weekly "
        "lags 구조. range_position=0.394, distance_to_resistance=0.397"
        "로 아직 고점과는 거리가 있음.",
        "OOS_v0.1_stage_audit",
        "원 audited_stage_label=PRE_BREAKOUT.",
    ),
    StageLabelSpec(
        "042660", "한화오션", "2025-07-31", PatternAStage.PROGRESSED,
        "range_position=0.974, avg_price_change_12m=+1.110, ma_spread"
        "=0.338, ma24_slope=+0.193 — 극단적 확장.",
        "OOS_v0.1_stage_audit",
        "원 audited_stage_label=TREND_PROGRESSED.",
    ),
    # ============================================================
    # Source: negative_control_compare (8)
    # 기존 outcome 기반 label(failed_*)은 Stage 판정에 쓰지 않고
    # raw Feature로 독립 재분류했다.
    # ============================================================
    StageLabelSpec(
        "003550", "LG", "2020-12-31", PatternAStage.TRANSITION,
        "range_position=0.808로 상단권이지만 ma24_slope=+0.010, "
        "weekly_ma12_slope=+0.013로 둘 다 방금 막 양전환한 수준(강한 "
        "확인 아님) — 구조적으로는 TRANSITION 프로필.",
        "negative_control_compare",
        "원 label=failed_breakout(outcome 기반, Stage 판정에 미사용). "
        "outcome이 실패였다고 해서 snapshot 시점 구조까지 WEAK로 두지 "
        "않음.",
    ),
    StageLabelSpec(
        "010130", "고려아연", "2022-06-30", PatternAStage.TRANSITION,
        "ma24_slope=+0.052로 core는 뚜렷한 양수지만 weekly_ma12_slope"
        "=-0.024로 음수(단기 되돌림) — 두 축이 엇갈린 전환 구간. "
        "avg_price_change_12m=+0.312로 이미 어느 정도 올라온 상태.",
        "negative_control_compare",
        "원 label=failed_breakout(outcome 기반, Stage 판정에 미사용).",
    ),
    StageLabelSpec(
        "011170", "롯데케미칼", "2023-01-31", PatternAStage.WEAK,
        "여러 구조 신호가 함께 활성 하락이 여전히 지배적임을 가리킨다 "
        "— avg_price_change_12m=-0.276(비교 대상 9건 중 최대 낙폭), "
        "ma_spread=0.263(비교 대상 9건 중 최대, 이동평균 가장 발산), "
        "ma24_slope=-0.048(가파른 하락), ma24_slope_acceleration=-0.021"
        "(비교 대상 9건 중 유일하게 하락이 오히려 가속). "
        "weekly_ma12_slope=+0.074로 단기 반등은 있지만, 월봉 구조/낙폭/"
        "가속 세 축이 전부 일관되게 활성 하락을 가리켜 이 반등을 구조적 "
        "안정화가 아니라 하락 중 일시 반등으로 판단 — WEAK.",
        "negative_control_compare",
        "원 label=failed_higher_low(outcome 기반, Stage 판정에 미사용). "
        "재감사 전에는 range_position=0.318이 높다는 이유로 BASE였다. "
        "diagnostic checklist로 먼저 재검토했고, checklist가 global "
        "rule처럼 읽힌다는 지적을 반영해 단일 지표가 아니라 낙폭/spread/"
        "가속 세 축이 모두 일치하는지로 다시 확인 — 결론(WEAK)은 동일. "
        "034220(2020-09-30)과 ma24_slope가 거의 동일한 쌍으로 직접 "
        "비교됨.",
    ),
    StageLabelSpec(
        "009150", "삼성전기", "2022-12-31", PatternAStage.WEAK,
        "acceleration 한 지표만으로 내린 판단이 아니다 — 세 가지가 함께 "
        "월봉 구조가 아직 안정화되지 않았음을 가리킨다. (1) ma_spread"
        "=0.250로 이동평균이 넓게 벌어진 채(비교 대상 9건 중 2번째로 "
        "넓음) 아직 수렴하지 않았고, (2) range_position_52w=0.282가 "
        "36개월 range_position(0.345)보다 오히려 낮아 최근 1년이 3년 "
        "구간 대비 개선되지 않고 상대적으로 더 저점 쪽으로 밀렸으며"
        "(비교 대상 9건 중 유일한 역전), (3) avg_price_change_12m"
        "=-0.200으로 최근 12개월 낙폭 자체도 여전히 크다. "
        "ma24_slope=-0.019 자체는 완만하고 ma24_slope_acceleration"
        "=-0.016(하락이 소폭 재가속)은 세 신호 중 하나일 뿐 — 다만 "
        "이동평균 미수렴+52주 역전+큰 낙폭이 함께 나타나 활성 하락이 "
        "여전히 구조를 지배한다고 판단, WEAK 유지.",
        "negative_control_compare",
        "원 label=failed_momentum(outcome 기반, Stage 판정에 미사용). "
        "재감사 전에는 range_position=0.345 기준으로 BASE였다. "
        "diagnostic checklist로 먼저 재검토했고, checklist가 global "
        "rule처럼 읽힌다는 지적을 반영해 acceleration 단일 신호가 아니라 "
        "ma_spread/52주 gap/낙폭 세 축을 함께 다시 확인 — 결론(WEAK)은 "
        "동일.",
    ),
    StageLabelSpec(
        "018260", "삼성에스디에스", "2023-07-31", PatternAStage.WEAK,
        "ma24_slope=-0.051로 비교 대상 9건 중 가장 가파른 하락(가파른 "
        "하락 기준 -0.045를 크게 상회) — ma24_slope_acceleration=+0.008"
        "로 감속 신호는 있지만 미미해 하락 속도 자체를 뒤집지 못함.",
        "negative_control_compare",
        "원 label=failed_breakout(outcome 기반, Stage 판정에 미사용). "
        "BASE/WEAK 재감사 9건 비교에서도 재확인됨(변경 없음) — 이번 "
        "9건 중 하락 속도가 가장 빠른 사례.",
    ),
    StageLabelSpec(
        "032830", "삼성생명", "2021-02-28", PatternAStage.BASE,
        "ma24_slope_acceleration=+0.026로 감속, range_position_52w"
        "=0.777이 36개월 range_position(0.480)보다 크게 높음(비교 대상 "
        "9건 중 두 번째로 큰 gap) — ma24_slope=-0.021로 가파른 하락 "
        "기준(대략 -0.045 이하)에 못 미침.",
        "negative_control_compare",
        "원 label=failed_ma24_turn(outcome 기반, Stage 판정에 미사용). "
        "라벨 이름과 달리 snapshot 시점 ma24_slope은 여전히 음수. "
        "BASE/WEAK 재감사 9건 비교에서도 재확인됨(변경 없음).",
    ),
    StageLabelSpec(
        "034730", "SK", "2020-12-31", PatternAStage.TRANSITION,
        "ma24_slope=-0.030로 여전히 음수지만 weekly_ma12_slope=+0.069로 "
        "weekly가 뚜렷하게 먼저 양전환 — price/weekly leads, core lags "
        "구조.",
        "negative_control_compare",
        "원 label=failed_weekly_turn(outcome 기반, Stage 판정에 미사용). "
        "라벨 이름과 달리 snapshot 시점엔 weekly가 실제로 양전환 상태.",
    ),
    StageLabelSpec(
        "011200", "HMM", "2024-10-31", PatternAStage.WEAK,
        "weekly_ma12_slope=-0.010로 비교 대상 9건 중 유일하게 음수 — "
        "단기 방향조차 아직 전환되지 않음. ma24_slope_acceleration"
        "=+0.039(비교 대상 9건 중 가장 강한 감속)와 ma_spread=0.039"
        "(가장 좁음)는 부분 안정화 신호지만, weekly가 아직 안 돈 것을 "
        "우선해 WEAK 유지.",
        "negative_control_compare",
        "원 label=failed_breakout(outcome 기반, Stage 판정에 미사용). "
        "BASE/WEAK 재감사 9건 비교에서도 재확인됨(변경 없음) — 감속/"
        "수렴 신호는 가장 강하지만 weekly 미전환이 결정적 판별축.",
    ),
    # ============================================================
    # Source: holdout_early_trend_compare (3, EARLY_TREND 보강)
    # ============================================================
    StageLabelSpec(
        "005380", "현대차", "2020-08-31", PatternAStage.EARLY_TREND,
        "range_position=0.953, distance_to_resistance=0.030로 저항선 "
        "코앞, ma24_slope=+0.007, weekly_ma12_slope=+0.195로 weekly가 "
        "특히 강하게 확인 — avg_price_change_12m=-0.058로 아직 확장 "
        "전 단계.",
        "holdout_early_trend_compare",
        "원 label=early_trend(development set). EARLY_TREND 표본 보강 "
        "목적으로 Stage 라벨링에만 재사용 — Score 성능 검증(OOS2)과는 "
        "무관.",
    ),
    StageLabelSpec(
        "051910", "LG화학", "2020-06-30", PatternAStage.EARLY_TREND,
        "range_position=0.898, distance_to_resistance=0.057, ma24_slope"
        "=+0.027, weekly_ma12_slope=+0.172로 core/weekly 모두 뚜렷한 "
        "양전환 — avg_price_change_12m=-0.035로 아직 확장 전.",
        "holdout_early_trend_compare",
        "원 label=early_trend(development set). Stage 라벨링에만 재사용.",
    ),
    StageLabelSpec(
        "000270", "기아", "2020-09-30", PatternAStage.EARLY_TREND,
        "range_position=0.885, distance_to_resistance=0.066, ma24_slope"
        "=+0.035, weekly_ma12_slope=+0.096로 core/weekly 모두 양전환 — "
        "avg_price_change_12m=-0.008로 거의 0, 아직 확장 전.",
        "holdout_early_trend_compare",
        "원 label=early_trend(development set). Stage 라벨링에만 재사용.",
    ),
)
