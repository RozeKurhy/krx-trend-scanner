"""Pattern A Score v0.2 OOS2 validation manifest.

Score Design v0.2는 commit fffce85에서 freeze됐고, 재현성 tooling 후속도
commit 4501c3b까지 끝났다. 이 manifest는 v0.2 freeze **이후** 처음 보는
완전히 새로운 종목/snapshot 38건을 담는다 — 전부 raw 월봉/주봉 close
구조만 보고 골랐고(Score/Feature 값은 선정에 쓰지 않았다 —
`scripts/_oos2_fetch_and_inspect.py`가 그 증거다), Score 계산은 이
manifest가 commit된 **이후**에만 한다(별도 commit).

**development data와의 분리**: exploration/holdout/negative_control
(score_v02_candidate_compare.py의 EXPLORATION_SNAPSHOTS/HOLDOUT_SNAPSHOTS/
NEGATIVE_CONTROL_SNAPSHOTS)와 OOS v0.1 diagnostic 29건(oos_v01_manifest.py)
은 전부 이미 v0.2 설계에 영향을 준 종목이라 v0.2의 성능 검증에는 다시
쓰지 않는다. 이 38건의 ticker는 그 development ticker 전체 집합과
교집합이 없다(tests/test_oos_v02_manifest.py가 두 집합을 직접 import해서
빈 교집합을 assert한다 — 사람이 눈으로 대조한 목록이 아니라 코드로
검증한다).

**scouting 지표 표기 주의**: 아래 selection_reason에 나오는
`ma24_raw_slope_6m`/`ma12w_raw_slope_8w`/`position_36m_raw` 등은
`scripts/_oos2_fetch_and_inspect.py`가 pandas rolling으로 직접 계산한
raw 보조 지표이지, production Feature(`ma24_slope`/`weekly_ma12_slope`)
값이 아니다 — 계산 방식과 스케일이 다르므로 나중에 production Feature
계산 결과와 이 숫자가 다르다고 해서 오류가 아니다. Score/Feature 자체는
아직 계산하지 않았다.

**outcome-conditioned selection**: selection_reason은 snapshot 이후의
실제 가격 흐름(예: "이후 2024-12까지 지속 하락")을 근거로 들 수 있다
(case selection의 목적상 허용됨 — item 9). 하지만 이건 Stage Audit이
아니다. snapshot 시점까지만 보고 판정해야 하는 manual Stage Audit은
validation 단계(Commit B)에서 별도로 작성하고, 여기 selection_reason과
분리해서 기록한다.

**조회 구간**: `_oos2_fetch_and_inspect.py`의 OOS2_SELECTION_START/END로
2011-01-01~2025-12-31을 절대 고정했다(재실행해도 같은 구간). 종료일을
오늘 날짜가 아니라 2025-12-31로 고정한 이유는 두 가지: (1) 재실행 시점마다
구간이 밀리는 걸 막기 위해(OOS v0.1과 동일 원칙), (2) trend_progressed/
fast_mover 그룹의 snapshot을 2025-11~12로 잡았는데, 이 그룹들은 미래
outcome을 주장하지 않으므로(과거~snapshot까지의 흐름만 설명) forward
room이 필요 없다 — 반면 hard_negative/boundary 그룹은 snapshot 이후
outcome을 주장하므로 그 주장에 필요한 만큼 forward room이 있는 날짜만
썼다(전부 데이터 마지막 달인 2025-12보다 충분히 이전).
"""

from __future__ import annotations

from dataclasses import dataclass

OOS_V02_DATASET_VERSION = "oos_v0.2"


@dataclass(frozen=True)
class OOS2SnapshotSpec:
    ticker: str
    name: str
    snapshot_date: str
    case_group: str
    selection_reason: str
    expected_behavior: str


OOS_V02_VALIDATION_SNAPSHOTS: tuple[OOS2SnapshotSpec, ...] = (
    # --- A. positive_pre_breakout (5) ---
    OOS2SnapshotSpec(
        "042700", "한미반도체", "2019-12-31", "positive_pre_breakout",
        "2014~2019 대체로 2,500~5,925원 박스, 2019-12 종가 4,050원으로 "
        "여전히 박스 안(position_36m_raw=0.365, scouting). 24개월선 "
        "raw 6개월 변화율도 여전히 음(-0.083) — 아직 core가 돌지 않았다.",
        "pre_breakout_should_preserve_base_identity",
    ),
    OOS2SnapshotSpec(
        "105560", "KB금융", "2023-12-31", "positive_pre_breakout",
        "2017년 고점 63,400원 이후 2018~2023 대체로 43,000~55,900원 박스, "
        "2023-12 종가 54,100원(position_36m_raw=0.657)으로 옛 고점 아직 "
        "미돌파. ma24_raw_slope_6m=-0.004로 거의 평탄.",
        "pre_breakout_should_preserve_base_identity",
    ),
    OOS2SnapshotSpec(
        "086790", "하나금융지주", "2023-12-31", "positive_pre_breakout",
        "2017년 고점 49,800원 이후 박스권, 2023-12 종가 43,400원"
        "(position_36m_raw=0.638)으로 미돌파. ma24_raw_slope_6m=-0.015.",
        "pre_breakout_should_preserve_base_identity",
    ),
    OOS2SnapshotSpec(
        "001040", "CJ", "2023-12-31", "positive_pre_breakout",
        "2018~2022 장기 하락(171,148→83,400원) 이후 저점권 횡보, 2023-12 "
        "종가 94,400원(position_36m_raw=0.596). ma24_raw_slope_6m=-0.030 "
        "으로 여전히 약한 음.",
        "pre_breakout_should_preserve_base_identity",
    ),
    OOS2SnapshotSpec(
        "000880", "한화", "2024-12-31", "positive_pre_breakout",
        "2023~2024 대체로 25,000~31,200원 박스, 2024-12 종가 26,900원"
        "(position_36m_raw=0.487). ma24_raw_slope_6m=+0.015로 거의 평탄.",
        "pre_breakout_should_preserve_base_identity",
    ),
    # --- B. positive_early_trend (5) ---
    OOS2SnapshotSpec(
        "042700", "한미반도체", "2020-11-30", "positive_early_trend",
        "36개월 신고가 첫 돌파(position_36m_raw=1.000, 종가 6,100원). "
        "ma24_raw_slope_6m이 -0.083(2019-12)에서 +0.020으로 막 양전환.",
        "clean_early_trend_should_score_meaningfully_higher_than_pre_breakout",
    ),
    OOS2SnapshotSpec(
        "105560", "KB금융", "2024-02-29", "positive_early_trend",
        "종가 63,500원, 2017년 이후 처음 전고점(63,400원) 돌파"
        "(position_36m_raw=1.000). ma24_raw_slope_6m은 -0.004→-0.004"
        "(2024-01)에서 막 반전 준비 단계.",
        "clean_early_trend_should_score_meaningfully_higher_than_pre_breakout",
    ),
    OOS2SnapshotSpec(
        "086790", "하나금융지주", "2024-02-29", "positive_early_trend",
        "종가 56,600원, 2017년 고점(49,800원) 돌파(position_36m_raw=1.000). "
        "ma24_raw_slope_6m=+0.004로 막 양전환.",
        "clean_early_trend_should_score_meaningfully_higher_than_pre_breakout",
    ),
    OOS2SnapshotSpec(
        "001040", "CJ", "2024-03-31", "positive_early_trend",
        "종가 129,800원, 신고가 돌파(position_36m_raw=1.000). "
        "ma24_raw_slope_6m=+0.043.",
        "clean_early_trend_should_score_meaningfully_higher_than_pre_breakout",
    ),
    OOS2SnapshotSpec(
        "000880", "한화", "2025-02-28", "positive_early_trend",
        "2024-12 종가 26,900원에서 급등, 2025-02 종가 40,550원으로 신고가 "
        "돌파(position_36m_raw=1.000). ma24_raw_slope_6m=+0.038 — 매우 "
        "빠른 전환(fast_mover 성격도 겸함, 아래 H그룹 000880/015760/353200과 "
        "비교).",
        "fast_breakout_should_still_score_as_clean_early_trend",
    ),
    # --- C. positive_trend_progressed (6) ---
    OOS2SnapshotSpec(
        "042700", "한미반도체", "2023-12-31", "positive_trend_progressed",
        "2020-11 돌파(종가 6,100원) 이후 3년, 종가 61,700원(10배 이상). "
        "ma24_raw_slope_6m=+0.593(매우 강한 양) — 이미 많이 진행됨.",
        "progressed_should_receive_meaningful_penalty",
    ),
    OOS2SnapshotSpec(
        "105560", "KB금융", "2025-12-31", "positive_trend_progressed",
        "2024-02 돌파 이후 2년, 종가 124,700원(돌파 시점 63,500원 대비 "
        "2배 가까이). ma24_raw_slope_6m=+0.210.",
        "progressed_should_receive_meaningful_penalty",
    ),
    OOS2SnapshotSpec(
        "086790", "하나금융지주", "2025-12-31", "positive_trend_progressed",
        "종가 94,100원(2024-02 돌파 시점 56,600원 대비 66% 추가 상승). "
        "ma24_raw_slope_6m=+0.208.",
        "progressed_should_receive_meaningful_penalty",
    ),
    OOS2SnapshotSpec(
        "214150", "클래시스", "2023-12-31", "positive_trend_progressed",
        "2019년 돌파(종가 4,000원대→14,150원, 2019-12) 이후 4년, 종가 "
        "37,750원. ma24_raw_slope_6m=+0.200. (참고: 2017-08 월봉 close "
        "결측 1건이 있어 이 종목은 이 snapshot 1건만 쓴다 — 36개월 "
        "윈도우가 그 결측월을 포함하지 않는 유일하게 깨끗한 구간.)",
        "progressed_should_receive_meaningful_penalty",
    ),
    OOS2SnapshotSpec(
        "000810", "삼성화재", "2024-06-30", "positive_trend_progressed",
        "2023-07 돌파(종가 244,000원) 이후 11개월, 종가 389,000원. "
        "ma24_raw_slope_6m=+0.133.",
        "progressed_should_receive_meaningful_penalty",
    ),
    OOS2SnapshotSpec(
        "015760", "한국전력", "2025-11-30", "positive_trend_progressed",
        "2025-06 급등(아래 H그룹 참고) 이후, 종가 52,500원. "
        "ma24_raw_slope_6m=+0.265(매우 강한 양).",
        "progressed_should_receive_meaningful_penalty",
    ),
    # --- D. hard_negative_false_turn (4) ---
    OOS2SnapshotSpec(
        "015760", "한국전력", "2024-02-29", "hard_negative_false_turn",
        "일시적으로 position_36m_raw=0.890까지 반등(종가 24,800원)했지만 "
        "ma24_raw_slope_6m은 여전히 -0.031(core는 안 바뀜) — 실제로 "
        "2024-05 position_36m_raw=0.331로 되돌림, 진짜 추세 전환은 "
        "2025-06까지 오지 않았다.",
        "temporary_weekly_pop_should_not_sustain_high_score",
    ),
    OOS2SnapshotSpec(
        "023530", "롯데쇼핑", "2023-12-31", "hard_negative_false_turn",
        "종가 75,000원. ma24_raw_slope_6m=-0.072로 하락 지속 중 — 실제로 "
        "2024-12 종가 54,100원까지 계속 하락(진짜 반등 아님을 확인).",
        "persistent_decline_should_not_score_as_early_trend",
    ),
    OOS2SnapshotSpec(
        "001450", "현대해상", "2017-08-31", "hard_negative_false_turn",
        "신고가 돌파(position_36m_raw=1.000, 종가 46,200원), "
        "ma24_raw_slope_6m=+0.092로 core도 양전환한 것처럼 보였다 — "
        "하지만 2018년 내내 하락해 2019-12 종가 26,950원까지 되돌림"
        "(2015년 수준 재복귀).",
        "temporary_improvement_should_not_sustain_high_score",
    ),
    OOS2SnapshotSpec(
        "007070", "GS리테일", "2017-04-30", "hard_negative_false_turn",
        "ma24_raw_slope_6m=+0.113(강한 양), 종가 45,415원(position_36m_raw"
        "=0.694) — 하지만 2017년 내내 급락해 2017-10 종가 28,566원, "
        "2024년까지도 회복 못함(2024년 최근월 종가 16,500원).",
        "temporary_improvement_should_not_sustain_high_score",
    ),
    # --- E. downtrend_reversal_boundary (Pattern A/B 경계, 4) ---
    OOS2SnapshotSpec(
        "015760", "한국전력", "2023-12-31", "downtrend_reversal_boundary",
        "2016~2023 장기 하락(44,050→18,900원), 아직 반등 확인 전. "
        "ma24_raw_slope_6m=-0.055로 하락 지속 중 — 장기 박스가 아니라 "
        "장기 하락의 연장선.",
        "downtrend_still_declining_should_not_look_like_clean_pattern_a",
    ),
    OOS2SnapshotSpec(
        "034220", "LG디스플레이", "2020-12-31", "downtrend_reversal_boundary",
        "2018~2020 장기 하락(31,102→9,427원 저점) 이후 회복 중, 종가 "
        "17,145원(position_36m_raw=0.380). ma24_raw_slope_6m=-0.060으로 "
        "여전히 음이지만 개선 중 — 진짜 반전인지 아직 불확실한 경계 지점 "
        "(실제로는 2021-04 신고가까지 갔다가 2022년 다시 붕괴, 아래 F그룹 "
        "2021-12 항목 참고).",
        "ambiguous_reversal_should_not_be_scored_as_confidently_as_clean_base",
    ),
    OOS2SnapshotSpec(
        "011210", "현대위아", "2019-12-31", "downtrend_reversal_boundary",
        "2014~2018 장기 하락(223,000→29,600원 저점)에서 가격은 회복 중"
        "(종가 50,200원, position_36m_raw=0.510)이지만 ma24_raw_slope_6m"
        "=-0.090으로 여전히 큰 음수 — 24개월선이 하락을 못 따라잡은 "
        "상태. 실제로는 이후 2021년까지 진짜 반등(79,900원)했다가 2022"
        "~2024 다시 무너지는 다중 사이클을 보인다.",
        "ambiguous_reversal_should_not_be_scored_as_confidently_as_clean_base",
    ),
    OOS2SnapshotSpec(
        "023530", "롯데쇼핑", "2025-05-31", "downtrend_reversal_boundary",
        "2023-12(위 D그룹) 이후에도 계속 하락하다 2025년 들어 반등 시도, "
        "종가 80,600원(position_36m_raw=0.532). ma24_raw_slope_6m은 "
        "여전히 -0.076으로 크게 음수 — 가격만 반등하고 core는 아직 "
        "안 도는 전형적 경계 케이스.",
        "ambiguous_reversal_should_not_be_scored_as_confidently_as_clean_base",
    ),
    # --- F. strong_core_failure (한국타이어형, 5) ---
    OOS2SnapshotSpec(
        "011780", "금호석유화학", "2018-01-31", "strong_core_failure",
        "신고가 돌파(position_36m_raw=1.000, 종가 103,000원), "
        "ma24_raw_slope_6m=+0.115로 core가 뚜렷하게 강했다 — 하지만 "
        "2019-12 종가 77,500원까지 되돌림(고점 대비 25% 하락).",
        "strong_core_should_not_guarantee_future_persistence",
    ),
    OOS2SnapshotSpec(
        "004000", "롯데정밀화학", "2018-04-30", "strong_core_failure",
        "ma24_raw_slope_6m=+0.215(이 종목 시계열 중 최고치), 종가 "
        "68,600원(position_36m_raw=0.833, 이미 고점에서 살짝 밀린 "
        "상태) — 하지만 2018-12 종가 41,050원, 2019-12 45,150원까지 "
        "큰 폭 하락.",
        "strong_core_should_not_guarantee_future_persistence",
    ),
    OOS2SnapshotSpec(
        "006650", "대한유화", "2018-01-31", "strong_core_failure",
        "신고가 돌파(position_36m_raw=1.000, 종가 331,500원), "
        "ma24_raw_slope_6m=+0.106 — 하지만 2019-08 종가 117,500원까지 "
        "65% 폭락.",
        "strong_core_should_not_guarantee_future_persistence",
    ),
    OOS2SnapshotSpec(
        "240810", "원익IPS", "2021-03-31", "strong_core_failure",
        "신고가 돌파(position_36m_raw=1.000, 종가 51,700원), "
        "ma24_raw_slope_6m=+0.201(매우 강함) — 하지만 2022-12 종가 "
        "24,750원까지 52% 폭락.",
        "strong_core_should_not_guarantee_future_persistence",
    ),
    OOS2SnapshotSpec(
        "034220", "LG디스플레이", "2021-12-31", "strong_core_failure",
        "신고가 돌파(position_36m_raw=1.000, 종가 22,737원), "
        "ma24_raw_slope_6m=+0.099 — 하지만 2022-12 종가 11,507원까지 "
        "다시 붕괴(위 E그룹 2020-12 항목의 '경계'가 결국 실패로 끝난 "
        "사례).",
        "strong_core_should_not_guarantee_future_persistence",
    ),
    # --- G. weak_core_strong_support (SKC형, 4) ---
    OOS2SnapshotSpec(
        "353200", "대덕전자", "2025-08-31", "weak_core_strong_support",
        "ma24_raw_slope_6m=-0.105(core는 뚜렷하게 음), ma12w_raw_slope_8w"
        "=+0.305(주봉 12주선은 강하게 양) — core와 support가 크게 "
        "괴리된 지점. 종가 24,050원.",
        "weak_core_support_should_not_score_as_clean_early",
    ),
    OOS2SnapshotSpec(
        "240810", "원익IPS", "2019-10-31", "weak_core_strong_support",
        "ma24_raw_slope_6m=-0.052(core 음), ma12w_raw_slope_8w=+0.137"
        "(주봉은 양) — 종가 33,150원(position_36m_raw=0.820).",
        "weak_core_support_should_not_score_as_clean_early",
    ),
    OOS2SnapshotSpec(
        "240810", "원익IPS", "2020-07-31", "weak_core_strong_support",
        "ma24_raw_slope_6m=-0.007(core는 거의 평탄, 음도 양도 아님), "
        "ma12w_raw_slope_8w=+0.182(주봉은 뚜렷하게 강함) — 신고가 "
        "돌파(position_36m_raw=1.000, 종가 38,250원)와 동시에 발생. "
        "core는 flat인데 support/포지션만 앞서가는, SKC 실패 메커니즘과 "
        "가장 가까운 형태.",
        "weak_core_support_should_not_score_as_clean_early",
    ),
    OOS2SnapshotSpec(
        "034220", "LG디스플레이", "2020-09-30", "weak_core_strong_support",
        "ma24_raw_slope_6m=-0.120(core 뚜렷하게 음), ma12w_raw_slope_8w"
        "=+0.199(주봉은 양) — 종가 14,188원.",
        "weak_core_support_should_not_score_as_clean_early",
    ),
    # --- H. fast_mover (3) ---
    OOS2SnapshotSpec(
        "353200", "대덕전자", "2025-10-31", "fast_mover",
        "2025-09 종가 28,250원 → 2025-10 종가 37,950원, 한 달 만에 "
        "신고가 돌파(position_36m_raw=1.000). ma24_raw_slope_6m은 "
        "-0.042로 아직 완전히 양전환 전 — 매우 빠른 가격 전환.",
        "fast_transition_should_not_be_over_penalized_by_progressed_logic",
    ),
    OOS2SnapshotSpec(
        "015760", "한국전력", "2025-06-30", "fast_mover",
        "2025-04 종가 25,650원 → 2025-06 종가 39,300원, 2개월 만에 53% "
        "상승(position_36m_raw=1.000).",
        "fast_transition_should_not_be_over_penalized_by_progressed_logic",
    ),
    OOS2SnapshotSpec(
        "000880", "한화", "2025-06-30", "fast_mover",
        "2025-02 돌파(종가 40,550원) 이후 4개월 만에 종가 94,300원(2배 "
        "이상) — 위 B그룹 2025-02 항목의 빠른 돌파가 그대로 이어진 "
        "extension.",
        "fast_transition_should_not_be_over_penalized_by_progressed_logic",
    ),
    # --- I. insufficient_history (2) ---
    OOS2SnapshotSpec(
        "353200", "대덕전자", "2021-06-30", "insufficient_history",
        "일봉 데이터가 2020-05-21부터 시작 — 이 snapshot 시점까지 약 "
        "13개월 history뿐이라 36개월 range/24개월선 required anchor를 "
        "계산할 수 없다.",
        "insufficient_history_should_return_none",
    ),
    OOS2SnapshotSpec(
        "403870", "HPSP", "2023-12-31", "insufficient_history",
        "일봉 데이터가 2022-07-15부터 시작(상장 초기) — 이 snapshot "
        "시점까지 약 17개월 history뿐이라 마찬가지로 required anchor를 "
        "계산할 수 없다.",
        "insufficient_history_should_return_none",
    ),
)
