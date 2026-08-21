"""Pattern A Score OOS Case Validation v0.1 diagnostic set manifest.

이 29개 (ticker, snapshot_date)는 Score v0.1(commit 6e7cc95)을 얼려놓고
raw monthly close만 보고 골랐다(Feature/Score 값은 선정에 쓰지 않았다 —
`scripts/_oos_fetch_and_inspect.py`가 그 증거다). 자세한 방법론과 caveat은
docs/patterns/pattern_a/spec/production_authority.md의 "OOS Case Validation v0.1" 절 참고.

**재리뷰 후속(경계 고정)**: 이 29건은 이미 결과를 본 상태이므로 앞으로
Score v0.2를 설계/분석하는 데 재사용할 수는 있지만(development/diagnostic
set), v0.2의 성능 검증에는 다시 쓰지 않는다 — v0.2 검증은 아직 선정하지
않은 완전히 새로운 종목/날짜(OOS2)로 한다.

이 모듈은 종목/날짜/그룹/선정 근거만 담는 manifest다. `scripts/
oos_validate.py`가 이 상수를 그대로 가져다 쓴다(스크립트와 manifest가
서로 다른 목록을 갖는 drift를 방지). Feature/Score 값은 여기 없다 —
그건 매번 다시 계산한다.
"""

from __future__ import annotations

from dataclasses import dataclass

OOS_V01_DATASET_VERSION = "oos_v0.1"


@dataclass(frozen=True)
class OOSSnapshotSpec:
    ticker: str
    name: str
    snapshot_date: str
    original_group: str
    selection_reason: str


OOS_V01_DIAGNOSTIC_SNAPSHOTS: tuple[OOSSnapshotSpec, ...] = (
    # --- positive: 5종목 x 3시점(pre_breakout/early_trend/trend_progressed) ---
    OOSSnapshotSpec(
        "010620", "HD현대미포", "2023-12-31", "positive_pre_breakout",
        "2019~2023 대체로 4만~9만원대 박스, 아직 신고가 돌파 전",
    ),
    OOSSnapshotSpec(
        "010620", "HD현대미포", "2024-06-30", "positive_early_trend",
        "박스 상단(약 9만원대) 근접 재시도 시점, 다음 달(7월) 117,500으로 신고가 확정",
    ),
    OOSSnapshotSpec(
        "010620", "HD현대미포", "2024-12-31", "positive_trend_progressed",
        "7월 신고가 돌파 이후 추가 상승 지속(134,200), 2025년에도 계속 확장",
    ),
    OOSSnapshotSpec(
        "012450", "한화에어로스페이스", "2021-12-31", "positive_pre_breakout",
        "2018~2021 2만~5만원대 박스(2016년 고점 약 6.5만원은 아직 미회복)",
    ),
    OOSSnapshotSpec(
        "012450", "한화에어로스페이스", "2022-12-31", "positive_early_trend",
        "2016년 고점 포함 전 구간 신고가 돌파(74,972), 8월 급등 후 되돌림 있었음",
    ),
    OOSSnapshotSpec(
        "012450", "한화에어로스페이스", "2024-06-30", "positive_trend_progressed",
        "돌파 이후 추가로 3배 이상 상승(254,155), 2025년 백만원대까지 지속 확장",
    ),
    OOSSnapshotSpec(
        "079550", "LIG넥스원", "2020-12-31", "positive_pre_breakout",
        "2019~2020 코로나 저점 포함 2만~4만원대 박스",
    ),
    OOSSnapshotSpec(
        "079550", "LIG넥스원", "2021-12-31", "positive_early_trend",
        "박스 상단 돌파(68,600), 2017년 고점(83,400)에는 아직 미달",
    ),
    OOSSnapshotSpec(
        "079550", "LIG넥스원", "2023-12-31", "positive_trend_progressed",
        "돌파 이후 추가 상승 지속(130,500), 2024~2025년에도 계속 확장",
    ),
    OOSSnapshotSpec(
        "005490", "POSCO홀딩스", "2022-12-31", "positive_pre_breakout",
        "2018~2022 23만~29만원대 박스, 아직 돌파 전",
    ),
    OOSSnapshotSpec(
        "005490", "POSCO홀딩스", "2023-03-31", "positive_early_trend",
        "박스 상단(29만원대) 돌파 3개월차(368,000)",
    ),
    OOSSnapshotSpec(
        "005490", "POSCO홀딩스", "2023-07-31", "positive_trend_progressed",
        "돌파 이후 급등 정점(642,000, 이후 크게 반락)",
    ),
    OOSSnapshotSpec(
        "042660", "한화오션", "2024-10-31", "positive_pre_breakout",
        "2018~2024 1.2만~4.2만원대 박스(2023년 여름 실패한 반등 포함), 아직 돌파 전",
    ),
    OOSSnapshotSpec(
        "042660", "한화오션", "2025-01-31", "positive_early_trend",
        "2023년 여름 고점(41,533)을 넘는 신고가 갱신 초입(57,200)",
    ),
    OOSSnapshotSpec(
        "042660", "한화오션", "2025-07-31", "positive_trend_progressed",
        "돌파 이후 추가 상승 지속(112,300), 2014~2015년 고점권에 근접",
    ),
    # --- hard_negative_false_turn: 박스/기저 이후 반등 -> 이후 재하락 ---
    OOSSnapshotSpec(
        "036570", "엔씨소프트", "2023-11-30", "hard_negative_false_turn",
        "2023-09 저점(222,500)에서 반등(262,000) 중, 이후 2024년 내내 재하락(183,100까지)",
    ),
    OOSSnapshotSpec(
        "251270", "넷마블", "2023-11-30", "hard_negative_false_turn",
        "2023-10 저점(38,600)에서 급반등(59,400, +54%) 중, 이후 반등분 대부분 반납",
    ),
    OOSSnapshotSpec(
        "090430", "아모레퍼시픽", "2024-05-31", "hard_negative_false_turn",
        "2024-03 저점(121,400)에서 반등(194,200, +60%) 중, 이후 재하락(104,800까지)",
    ),
    OOSSnapshotSpec(
        "011790", "SKC", "2024-06-30", "hard_negative_false_turn",
        "2024-01 저점(72,187)에서 급반등(158,473, +120%) 중, 이후 급락(92,959까지)",
    ),
    OOSSnapshotSpec(
        "004020", "현대제철", "2023-09-30", "hard_negative_false_turn",
        "2022 저점(28,100) 대비 반등(38,050) 중, 이후 지속 하락(20,950까지)",
    ),
    OOSSnapshotSpec(
        "161390", "한국타이어앤테크놀로지", "2024-04-30", "hard_negative_false_turn",
        "박스권 상단 부근에서 반등(59,100) 중, 이후 재하락(35,300까지)",
    ),
    OOSSnapshotSpec(
        "069960", "현대백화점", "2021-05-31", "hard_negative_false_turn",
        "코로나 저점(53,700) 대비 반등(93,100) 중, 이후 다년간 추가 하락(46,350까지)",
    ),
    OOSSnapshotSpec(
        "000990", "DB하이텍", "2023-11-30", "hard_negative_false_turn",
        "2023-10 저점(48,400)에서 반등(61,900) 중, 이후 재하락(33,150까지)",
    ),
    # --- downtrend_reversal_boundary: 아직 base가 없는 하락 도중의 반등 ---
    OOSSnapshotSpec(
        "090430", "아모레퍼시픽", "2018-12-31", "downtrend_reversal_boundary",
        "2015년 고점(414,500) 이후 지속 하락 중 2018-10 저점(153,000)에서 소폭 반등, base 형성 전",
    ),
    OOSSnapshotSpec(
        "251270", "넷마블", "2020-08-31", "downtrend_reversal_boundary",
        "2017년 상장 이후 지속 하락 중 2020-02 저점(88,600) 이후 반등, base 형성 전",
    ),
    OOSSnapshotSpec(
        "069960", "현대백화점", "2019-04-30", "downtrend_reversal_boundary",
        "2016년부터 지속 하락 중 소폭 개선, base 형성 전",
    ),
    OOSSnapshotSpec(
        "097950", "CJ제일제당", "2019-12-31", "downtrend_reversal_boundary",
        "2018년부터 지속 하락 중 2019-08 저점(228,500) 이후 소폭 반등, base 형성 전",
    ),
    OOSSnapshotSpec(
        "006800", "미래에셋증권", "2022-10-31", "downtrend_reversal_boundary",
        "2015년 이후 장기 박스 하단권에서 추가 하락 중, 진짜 base 여부 불확실",
    ),
    # --- insufficient_data_check: range_36m 36개월 창을 못 채우는 시점 ---
    OOSSnapshotSpec(
        "247540", "에코프로비엠", "2021-06-30", "insufficient_data_check",
        "2019-03 상장, 이 시점 상장 후 약 27개월치 데이터만 존재(36개월 미만)",
    ),
)


@dataclass(frozen=True)
class StageAudit:
    audited_stage_label: str
    audit_note: str


# Stage Label Rubric v0.1(docs/patterns/pattern_a/spec/production_authority.md 참고)로 positive
# 15건을 감사한 결과. Score/Feature 값을 쓰지 않고 raw monthly close
# 구조만으로 판단했다(rubric 자체는 weekly close도 허용하지만 이번
# 감사에는 monthly만으로 충분했다). **원본 라벨(OOS_V01_DIAGNOSTIC_SNAPSHOTS의
# original_group)은 바꾸지 않는다** — 이건 별도 병렬 기록이다.
#
# **as-of 원칙(재리뷰 후속)**: 각 판정은 반드시 close.index <= snapshot_date
# 구간만 본다. 스냅샷 이후에 실제로 어떻게 됐는지(다음 달 돌파 확정, 이후
# 급락 등)는 audit_note에도 적지 않는다 — 이 audit은 "그 시점까지의 가격
# 구조만으로 지금 어느 Stage인가"를 판정하는 용도이지, 사후에 결과를 보고
# 맞춰 끼우는 용도가 아니다.
#
# key = (ticker, snapshot_date). positive_pre_breakout/early_trend/
# trend_progressed 15건만 감사 대상이다(hard_negative/boundary/
# insufficient_data_check는 Stage 개념 자체가 적용 대상이 아니다).
OOS_V01_STAGE_AUDIT: dict[tuple[str, str], StageAudit] = {
    ("010620", "2023-12-31"): StageAudit(
        "PRE_BREAKOUT",
        "박스 상단 근접이나 2022-08 스파이크 고점(107,000) 미돌파 — 원본 라벨과 일치",
    ),
    ("010620", "2024-06-30"): StageAudit(
        "PRE_BREAKOUT/EARLY_TREND 경계",
        "종가(93,000)가 2022-08 스파이크 고점(107,000) 아래이자 통상 박스 상단과 거의 겹침"
        " — 스냅샷 시점까지의 정보만으로는 '돌파 시도 초기 단계'에 더 가까움."
        " 원본 라벨(EARLY_TREND)보다 보수적으로 판단.",
    ),
    ("010620", "2024-12-31"): StageAudit(
        "TREND_PROGRESSED",
        "7월 신고가 돌파 이후 추가 상승 지속(93,000→134,200, +44%) — 원본 라벨과 일치",
    ),
    ("012450", "2021-12-31"): StageAudit(
        "PRE_BREAKOUT",
        "2016년 고점(약 65,000) 미회복, 다년 박스 상단 부근 — 원본 라벨과 일치",
    ),
    ("012450", "2022-12-31"): StageAudit(
        "TREND_PROGRESSED",
        "12개월간 +53%, 전 구간 신고가 돌파 완료 + 8월 급등 후 되돌림(spike-pullback) 패턴"
        " — '막 시작'이 아니라 이미 상당한 첫 leg가 진행된 구조. 원본 라벨(EARLY_TREND)과 불일치.",
    ),
    ("012450", "2024-06-30"): StageAudit(
        "TREND_PROGRESSED",
        "돌파 이후 추가로 3배 이상 상승 — 원본 라벨과 일치",
    ),
    ("079550", "2020-12-31"): StageAudit(
        "PRE_BREAKOUT",
        "2019~2020 상대적으로 좁은 박스(약 25,000~40,000) 내부 — 원본 라벨과 일치"
        "(다만 이 박스 자체가 2016~2018 대비 낮은 위치에서 형성됨, 참고)",
    ),
    ("079550", "2021-12-31"): StageAudit(
        "TREND_PROGRESSED",
        "12개월간 +125% — '막 시작'으로 보기 어려운 폭. 원본 라벨(EARLY_TREND)은 달력상"
        " 1년 경과를 기준으로 붙였을 뿐, 가격 구조 기준으로는 이미 상당히 진행됨. 불일치.",
    ),
    ("079550", "2023-12-31"): StageAudit(
        "TREND_PROGRESSED",
        "추가 상승 지속 — 원본 라벨과 일치",
    ),
    ("005490", "2022-12-31"): StageAudit(
        "PRE_BREAKOUT",
        "2018~2022 박스 상단 부근, 돌파 전 — 원본 라벨과 일치",
    ),
    ("005490", "2023-03-31"): StageAudit(
        "EARLY_TREND",
        "3개월 만에 박스 상단(293,000) 확실히 돌파(368,000), +33% — '막 시작' 유형에"
        " 부합. 원본 라벨과 일치(5건 중 가장 깨끗한 EARLY_TREND 사례)",
    ),
    ("005490", "2023-07-31"): StageAudit(
        "TREND_PROGRESSED",
        "돌파 이후 추가 +74%, 스냅샷 시점까지 구간 내 최고가 — 원본 라벨과 일치",
    ),
    ("042660", "2024-10-31"): StageAudit(
        "PRE_BREAKOUT",
        "다년 박스(2023년 여름 실패한 반등 포함) 내부, 아직 돌파 전 — 원본 라벨과 일치",
    ),
    ("042660", "2025-01-31"): StageAudit(
        "EARLY_TREND/TREND_PROGRESSED 경계",
        "3개월 +114%로 단기 변동은 이미 상당하지만, 절대 가격(57,200)이 2014~2015년"
        " 고점(80,000~110,000)에 크게 못 미쳐 장기 구조상 초기 회복 구간일 수 있음"
        " — 판단이 어려운 사례로 남긴다. 원본 라벨(EARLY_TREND) 유지 여부 불확실.",
    ),
    ("042660", "2025-07-31"): StageAudit(
        "TREND_PROGRESSED",
        "추가 상승, 2014~2015년 고점권 근접 — 원본 라벨과 일치",
    ),
}
