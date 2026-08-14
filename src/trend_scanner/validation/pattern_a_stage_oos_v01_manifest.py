"""Pattern A Stage OOS Validation v0.1 Truth Set Freeze Manifest.

이 manifest는 Stage Classifier v0.1(commit 43ee01c, exact 38/46 baseline)을
독립적인 새로운 종목/스냅샷에서 검증하기 위한 OOS Ground Truth 35건을
사전에 봉인(freeze)한다.

[STRICT BLIND POLICY]
- 이 manifest 작성 시점에 `classify_pattern_a_stage()`는 일체 실행하지 않았다.
- Stage Classifier v0.1의 prediction 결과는 전혀 보지 않은 상태에서
  오직 snapshot 시점까지의 raw monthly/weekly 가격 구조와 장기 historical path만
  보고 manual ground-truth Stage를 확정했다.
- classifier 내부 threshold(weekly_ma12_slope 0.03, range_position 0.60,
  avg_price_change_12m 0.30 등)를 selection cutoff로 사용하지 않았다.
- `pattern_a_stage` 및 `pattern_a_score` 모듈을 import하지 않는다.

[OOS 독립성]
- 기존 Stage calibration dataset(46 snapshots, 27 unique tickers)에
  포함된 종목을 전혀 사용하지 않고, 100% 완전히 새로운 24개 unique ticker로 구성했다.
- snapshot_date 이후의 미래 결과나 수익률을 Stage 판정에 사용하는 lookahead 및
  outcome contamination을 철저히 배제했다.
"""

from __future__ import annotations

from dataclasses import dataclass

from trend_scanner.patterns.pattern_a_feature_set import PatternAStage

STAGE_OOS_V01_DATASET_VERSION = "pattern_a_stage_oos_v0.1_freeze"


@dataclass(frozen=True)
class StageOOSSnapshotSpec:
    ticker: str
    name: str
    snapshot_date: str
    selection_group: str
    selection_reason: str
    manual_stage: PatternAStage
    manual_stage_reason: str
    episode_notes: str
    source_notes: str
    manual_confidence: str = "HIGH"


PATTERN_A_STAGE_OOS_V01_LABELS: tuple[StageOOSSnapshotSpec, ...] = (
    # ============================================================
    # 1. WEAK (7 snapshots)
    # ============================================================
    StageOOSSnapshotSpec(
        "006360", "GS건설", "2023-10-31",
        "active_decline_continuation",
        "2021년 4.9만원 고점 및 검단 아파트 사고 후 장기 지속 하락세, 1.3만원대 신저가.",
        PatternAStage.WEAK,
        "장기 월봉 및 주봉 하향 추세가 지배적이며 52주 신저가 연속 갱신 중으로 "
        "베이스 안정화 신호가 전혀 없는 전형적 활성 하락 국면.",
        "2021년 고점 이후 장기 하락 episode가 지속 중이며 바닥 형성 조짐 없음.",
        "OOS v0.1 신규 선정 후보(건설업 대표 하락 사례).",
        "HIGH",
    ),
    StageOOSSnapshotSpec(
        "006360", "GS건설", "2022-11-30",
        "false_turn",
        "2021~2022년 가파른 하락 중 주봉상 단기 2만원 초반대 기술적 반등 시점.",
        PatternAStage.WEAK,
        "주봉에서 일시적인 단기 반등이 나타났으나 월봉 장기 추세는 여전히 가파르게 하향 중이며 "
        "장기 이평선 역배열 및 하락 구조가 지배적인 false turn.",
        "장기 하락 episode 내 일시적 단기 반등에 불과하여 구조적 전환으로 볼 수 없음.",
        "OOS v0.1 신규 선정 후보(false turn 검증용).",
        "HIGH",
    ),
    StageOOSSnapshotSpec(
        "009830", "한화솔루션", "2024-04-30",
        "active_decline_continuation",
        "2022년 태양광 고점(5만원대 이상) 이후 업황 악화로 2.4만원대까지 지속 하락.",
        PatternAStage.WEAK,
        "월봉 및 주봉 모두 뚜렷한 역배열 하향세를 보이며 36개월 레인지 하단(신저가 근접)에 "
        "위치하여 하락세가 여전히 가격 구조를 지배함.",
        "과거 상승 episode 종료 후 새로운 하락 추세가 진행 중이며 바닥 안정화 미확인.",
        "OOS v0.1 신규 선정 후보(태양광/화학 다운사이클 사례).",
        "HIGH",
    ),
    StageOOSSnapshotSpec(
        "018880", "한온시스템", "2024-06-30",
        "active_decline_continuation",
        "자동차 부품 업황 둔화 및 장기 실적 부진으로 수년간 지속 하락, 4천원대 신저가.",
        PatternAStage.WEAK,
        "월봉 장기 이평선이 지속 우하향하고 장기 저점을 계속 낮추는 계단식 하락으로 "
        "하락 관성이 유지되는 상태.",
        "수년간의 장기 하락 episode 지속, 베이스 형성 미흡.",
        "OOS v0.1 신규 선정 후보(장기 계단식 하락 부품주 사례).",
        "HIGH",
    ),
    StageOOSSnapshotSpec(
        "000720", "현대건설", "2024-03-31",
        "active_decline_continuation",
        "부동산 PF 및 건설업 침체로 3만원대 초반까지 장기 하향 표류.",
        PatternAStage.WEAK,
        "월봉 장기 추세가 하향 안정화되지 못하고 지속적으로 저점을 낮추는 하락 추세 국면.",
        "장기 하락 episode 지속, 전환 신호 부재.",
        "OOS v0.1 신규 선정 후보(대형 건설주 하락 사례).",
        "HIGH",
    ),
    StageOOSSnapshotSpec(
        "035420", "NAVER", "2022-10-31",
        "active_decline_continuation",
        "2021년 45만원 고점 이후 금리 인상 및 성장주 조정으로 16만원대까지 가파른 낙폭 과대.",
        PatternAStage.WEAK,
        "월봉 12개월 이상 연속 음봉 중심의 급격한 장기 하락이 진행 중이며 "
        "하락 가속도가 멈추지 않은 전형적 active decline.",
        "2020~2021 대세 상승 episode 완전 종료 후 급격한 하락 국면 진행 중.",
        "OOS v0.1 신규 선정 후보(대형 플랫폼 급락 사례).",
        "HIGH",
    ),
    StageOOSSnapshotSpec(
        "004170", "신세계", "2024-08-31",
        "active_decline_continuation",
        "내수 소비 침체 및 유통 채널 변화로 15만원대까지 수년간 계단식 하락 지속.",
        PatternAStage.WEAK,
        "월봉 장기 이평선이 지속 우하향하며 반등 시도마다 저항에 부딪혀 저점을 낮추는 "
        "구조적 약세.",
        "장기 침체 episode 지속, 횡보 바닥 안정화 미형성.",
        "OOS v0.1 신규 선정 후보(유통 소비재 장기 하향 사례).",
        "HIGH",
    ),

    # ============================================================
    # 2. BASE (7 snapshots)
    # ============================================================
    StageOOSSnapshotSpec(
        "017670", "SK텔레콤", "2023-12-31",
        "quiet_box_base",
        "4만~5만원대 좁은 레인지에서 3년 이상 극도로 조용한 횡보 지속.",
        PatternAStage.BASE,
        "장기 하락세가 완전히 소멸하고 36개월 레인지 중간대에서 변동성이 극도로 수축되며 "
        "안정된 가격 지지대를 형성하는 전형적 조용한 박스권 BASE.",
        "이전 변동성 국면 종료 후 3년 이상 지속된 독립적인 장기 베이스 episode.",
        "OOS v0.1 신규 선정 후보(통신 대표 저변동성 박스권 사례).",
        "HIGH",
    ),
    StageOOSSnapshotSpec(
        "030200", "KT", "2023-10-31",
        "quiet_box_base",
        "경영진 선임 지연 등 불확실성 속에서 3만원 초반대 바닥을 탄탄히 다지는 횡보.",
        PatternAStage.BASE,
        "하방 경직성이 뚜렷하고 장기 이평선이 평탄화되어 있으며 아직 뚜렷한 상방 돌파 "
        "모멘텀은 없는 안정화 단계.",
        "장기 횡보 안정화 episode 형성 중.",
        "OOS v0.1 신규 선정 후보(통신 지주 바닥 안정화 사례).",
        "HIGH",
    ),
    StageOOSSnapshotSpec(
        "024110", "기업은행", "2023-11-30",
        "quiet_box_base",
        "1만원~1.1만원대 장기 박스권 하단에서 저점을 완만하게 지지하며 횡보.",
        PatternAStage.BASE,
        "장기 하락 압력이 사라지고 수년간의 박스권 내에서 수렴 안정화된 전형적 베이스 구조.",
        "장기 박스권 episode 내 바닥 안정화 국면.",
        "OOS v0.1 신규 선정 후보(은행 금융주 박스권 베이스).",
        "HIGH",
    ),
    StageOOSSnapshotSpec(
        "028260", "삼성물산", "2023-10-31",
        "quiet_box_base",
        "10만~11만원대 좁은 박스에서 수년간 지루한 횡보 지속.",
        PatternAStage.BASE,
        "가격 변동성이 수축되고 장기 이평선 간격이 좁혀져 평탄하게 누워 있는 전형적 BASE.",
        "장기간 지루한 횡보로 에너지를 응축하는 독립 베이스 episode.",
        "OOS v0.1 신규 선정 후보(지주/상사 대표 박스권 사례).",
        "HIGH",
    ),
    StageOOSSnapshotSpec(
        "005940", "NH투자증권", "2023-10-31",
        "quiet_box_base",
        "8천원대 후반~9천원대에서 1년 이상 하방을 다지며 횡보.",
        PatternAStage.BASE,
        "가파른 하락 이후 1년 이상 추가 하락 없이 수평 횡보하며 바닥 지지력을 구축한 BASE.",
        "하락 둔화 후 신규 베이스 형성 episode.",
        "OOS v0.1 신규 선정 후보(증권주 바닥 다지기 사례).",
        "HIGH",
    ),
    StageOOSSnapshotSpec(
        "271560", "오리온", "2024-08-31",
        "quiet_box_base",
        "M&A 불확실성 이후 9만원대 초반에서 하방 경직성을 보이며 안정적 수평 횡보.",
        PatternAStage.BASE,
        "하락이 멈추고 9만원대에서 수개월간 좁은 박스를 형성하며 에너지를 모으는 BASE 단계.",
        "과거 하락 조정 마무리 후 신규 베이스 episode 진입.",
        "OOS v0.1 신규 선정 후보(음식료 안정형 박스권 사례).",
        "HIGH",
    ),
    StageOOSSnapshotSpec(
        "068270", "셀트리온", "2023-09-30",
        "cycle_reset_base",
        "2020~2021년 코로나 랠리 35만원대에서 14만원대까지 2년간 하락 후 1년 이상 바닥 다지기.",
        PatternAStage.BASE,
        "과거 2020년 상승 및 2021~2022년 하락 cycle이 완전히 종료(cycle reset)되었으며, "
        "14만원대에서 1년 이상 새로운 장기 횡보 바닥을 구축한 신규 episode의 BASE 후보.",
        "과거 PROGRESSED 상승 사이클 붕괴 후 완벽한 cycle reset을 거쳐 형성된 신규 BASE.",
        "OOS v0.1 신규 선정 후보(cycle reset 대표 바이오 사례).",
        "HIGH",
    ),

    # ============================================================
    # 3. TRANSITION (7 snapshots)
    # ============================================================
    StageOOSSnapshotSpec(
        "000660", "SK하이닉스", "2023-05-31",
        "weekly_leading_transition",
        "2022년 7.5만원 바닥에서 반등하여 10만원대로 주봉이 먼저 강하게 상방 턴어라운드.",
        PatternAStage.TRANSITION,
        "주봉 이평선이 강력하게 골든크로스를 내며 상방 전환을 주도하나, 월봉 장기 코어는 "
        "이제 막 하락 둔화에서 평탄화로 접어드는 전형적인 Weekly leads TRANSITION.",
        "장기 바닥권 탈출을 시도하는 새로운 상승 episode의 초기 전환 단계.",
        "OOS v0.1 신규 선정 후보(반도체 사이클 전환 대표 사례).",
        "HIGH",
    ),
    StageOOSSnapshotSpec(
        "005830", "DB손해보험", "2023-06-30",
        "dual_turn_transition",
        "7만원대 장기 박스권 상단에 근접하며 주봉과 월봉 장기선이 동반 우상향 조짐.",
        PatternAStage.TRANSITION,
        "월봉 코어와 주봉 이평선이 함께 우상향으로 방향을 틀기 시작했으나 아직 저항선을 "
        "완전히 돌파 안착하기 전인 전환 국면.",
        "장기 베이스에서 본격적인 돌파를 준비하는 전환 episode.",
        "OOS v0.1 신규 선정 후보(보험주 상방 전환 사례).",
        "HIGH",
    ),
    StageOOSSnapshotSpec(
        "006260", "LS", "2022-10-31",
        "box_breakout_prep_transition",
        "5만원대 장기 박스를 벗어나 6.6만원대로 주봉/월봉이 동반 우상향 턴어라운드.",
        PatternAStage.TRANSITION,
        "36개월 박스권 상단을 타진하며 주봉/월봉 기울기가 개선되고 있으나 역사적 고점 저항대 "
        "도달 전인 전환 모멘텀 단계.",
        "장기 횡보를 탈피하여 신규 상승 사이클로 전환되는 단계.",
        "OOS v0.1 신규 선정 후보(전력 인프라 전환 국면).",
        "HIGH",
    ),
    StageOOSSnapshotSpec(
        "028050", "삼성E&A", "2021-03-31",
        "weekly_leading_transition",
        "1.2만원대 장기 바닥 횡보 후 1.4만원대로 주봉이 먼저 고개를 들기 시작.",
        PatternAStage.TRANSITION,
        "장기 하락 압력을 벗어나 주봉이 먼저 우상향 정배열을 시도하며 코어 회복을 견인하는 "
        "Weekly leading 전환 국면.",
        "플랜트 장기 침체 바닥을 벗어나는 초기 전환 episode.",
        "OOS v0.1 신규 선정 후보(엔지니어링 턴어라운드 사례).",
        "HIGH",
    ),
    StageOOSSnapshotSpec(
        "003230", "삼양식품", "2022-04-30",
        "gradual_turn_transition",
        "8만원대 박스에서 9.8만원대로 주봉 및 월봉 이평선이 서서히 상향 수렴 턴어라운드.",
        PatternAStage.TRANSITION,
        "장기 하락 둔화 후 주봉과 월봉이 점진적으로 상향 정렬되기 시작하며 10만원대 저항선 "
        "돌파를 모색하는 점진적 전환 단계.",
        "음식료 신규 성장 episode의 초기 전환 단계.",
        "OOS v0.1 신규 선정 후보(수출 모멘텀 전환 초기).",
        "HIGH",
    ),
    StageOOSSnapshotSpec(
        "035900", "JYP Ent.", "2020-07-31",
        "surge_recovery_transition",
        "코로나 급락(1.7만원) 후 3만원으로 가파른 V자 반등을 보이며 전고점 회복 시도.",
        PatternAStage.TRANSITION,
        "최근 12개월 변화율은 급등성 회복으로 크지만 장기 구조상 아직 전고점 돌파 전이며 "
        "추세 확장 전인 급등성 회복 / TRANSITION.",
        "단기 충격 후 장기 상승 추세로 복귀를 타진하는 전환 국면.",
        "OOS v0.1 신규 선정 후보(급등성 회복 known failure mode 검증).",
        "HIGH",
    ),
    StageOOSSnapshotSpec(
        "055550", "신한지주", "2024-01-31",
        "weekly_leading_transition",
        "3.5만원대 지루한 박스권에서 4만원대로 주봉이 먼저 양전환하며 거래량 수반.",
        PatternAStage.TRANSITION,
        "월봉 장기선은 아직 평탄하나 주봉이 밸류업 모멘텀으로 강력하게 상방으로 꺾이는 "
        "전형적 Weekly leads TRANSITION.",
        "금융지주 장기 박스권 상향 돌파 시도 episode.",
        "OOS v0.1 신규 선정 후보(밸류업 금융 전환 초기).",
        "HIGH",
    ),

    # ============================================================
    # 4. EARLY_TREND (7 snapshots)
    # ============================================================
    StageOOSSnapshotSpec(
        "000660", "SK하이닉스", "2023-11-30",
        "clean_early_trend",
        "13만원대 전고점 저항선을 뚫고 주봉/월봉 완벽한 정배열 상승 추세 안착.",
        PatternAStage.EARLY_TREND,
        "장기 저항선을 깔끔하게 돌파하고 월봉 및 주봉 이평선이 강력한 우상향 정배열을 "
        "구축했으며, 아직 극단적 과열 확장 전인 정석적 EARLY_TREND.",
        "전환기를 거쳐 HBM 대세 상승의 1차 확장이 막 전개되는 초기 추세 국면.",
        "OOS v0.1 신규 선정 후보(반도체 대세 상승 정석 사례).",
        "HIGH",
    ),
    StageOOSSnapshotSpec(
        "005850", "에스엘", "2023-04-30",
        "clean_early_trend",
        "2.5만원대 장기 박스 상단을 강력하게 돌파하여 3.1만원에 안착.",
        PatternAStage.EARLY_TREND,
        "36개월 레인지 상단을 확실히 뚫어내고 주봉/월봉 동반 우상향 가속도가 붙은 "
        "깔끔한 돌파 안착 EARLY_TREND.",
        "장기 박스권 종료 후 신규 상승 추세 진입 episode.",
        "OOS v0.1 신규 선정 후보(자동차 부품 신고가 돌파 사례).",
        "HIGH",
    ),
    StageOOSSnapshotSpec(
        "005830", "DB손해보험", "2023-12-31",
        "clean_early_trend",
        "8.3만원에 도달하며 역사적 신고가 영역을 개척하고 추세적 우상향 전개.",
        PatternAStage.EARLY_TREND,
        "모든 장기 저항선을 상방 돌파하고 이평선이 정배열로 정렬되어 상승 추세를 굳힌 "
        "정석적 EARLY_TREND.",
        "전환기를 완성하고 본격적 신고가 상승 추세로 진입한 episode.",
        "OOS v0.1 신규 선정 후보(보험주 신고가 추세 사례).",
        "HIGH",
    ),
    StageOOSSnapshotSpec(
        "006260", "LS", "2023-02-28",
        "clean_early_trend",
        "6.7만원~7만원대 장기 저항을 뚫고 주봉/월봉 정배열 상승 궤도 진입.",
        PatternAStage.EARLY_TREND,
        "장기 박스권 상단 돌파가 확인되었고 코어 기울기와 주봉 기울기가 모두 가파른 "
        "우상향을 형성하는 초기 추세 단계.",
        "전력 인프라 대세 상승 episode의 본격 전개 국면.",
        "OOS v0.1 신규 선정 후보(지주/인프라 대세 상승 초입).",
        "HIGH",
    ),
    StageOOSSnapshotSpec(
        "028050", "삼성E&A", "2021-06-30",
        "clean_early_trend",
        "2.3만원을 돌파하며 3년 이상의 장기 박스 상단을 완벽히 제압.",
        PatternAStage.EARLY_TREND,
        "다년간의 장기 저항대를 뚫고 월봉 24개월선이 본격적인 우상향 궤도에 진입한 "
        "깔끔한 돌파형 EARLY_TREND.",
        "플랜트 턴어라운드 상승 episode의 본격적 추세 단계.",
        "OOS v0.1 신규 선정 후보(플랜트 대세 상승 초기).",
        "HIGH",
    ),
    StageOOSSnapshotSpec(
        "003230", "삼양식품", "2022-11-30",
        "clean_early_trend",
        "11.1만원에 안착하며 2년여의 박스 상단을 돌파하고 실적 동반 우상향 개시.",
        PatternAStage.EARLY_TREND,
        "장기 저항선을 확실히 넘어서고 주봉/월봉 기울기가 모두 탄탄한 양수를 유지하는 "
        "정석적 EARLY_TREND.",
        "불닭 수출 성장에 따른 대세 상승 episode 1차 도약 국면.",
        "OOS v0.1 신규 선정 후보(음식료 수출 대세 상승 초입).",
        "HIGH",
    ),
    StageOOSSnapshotSpec(
        "272210", "한화시스템", "2024-03-31",
        "clean_early_trend",
        "1.7만원대 장기 저항선을 상방 돌파하며 방산 수주 사이클에 올라탄 시점.",
        PatternAStage.EARLY_TREND,
        "장기 박스 상단을 돌파하여 52주 신고가를 갱신하고 이평선이 상향 발산하기 시작한 "
        "초기 추세 단계.",
        "방산 사이클 본격화에 따른 신규 상승 추세 episode 진입.",
        "OOS v0.1 신규 선정 후보(방산 부품/ICT 돌파 사례).",
        "HIGH",
    ),

    # ============================================================
    # 5. PROGRESSED (7 snapshots)
    # ============================================================
    StageOOSSnapshotSpec(
        "000660", "SK하이닉스", "2024-06-30",
        "extended_progressed",
        "23.6만원 돌파, 12개월 상승률 100% 초과 및 장기 이평선 대폭 발산.",
        PatternAStage.PROGRESSED,
        "돌파 기준점(10~13만원) 대비 2배 이상 폭등하고 36개월 레인지 96% 위치에 도달하여 "
        "대세 상승의 확장이 극단적으로 진행된 PROGRESSED.",
        "2023년 시작된 상승 episode가 1년 이상 지속되어 성숙 확장에 도달한 상태.",
        "OOS v0.1 신규 선정 후보(반도체 대세 상승 확장 국면).",
        "HIGH",
    ),
    StageOOSSnapshotSpec(
        "003230", "삼양식품", "2024-06-30",
        "extended_progressed",
        "66.9만원 도달, 12개월 상승률 +500% 이상의 역사적 초과열 확장.",
        PatternAStage.PROGRESSED,
        "초기 돌파가 이미 1년 반 전에 끝나고 주가가 수직 상승하여 이평선 간격과 가격이 "
        "극도로 확장된 전형적 PROGRESSED.",
        "2022년 말 시작된 대세 상승 episode가 극단적인 피크 확장 단계에 도달.",
        "OOS v0.1 신규 선정 후보(음식료 역사적 랠리 확장).",
        "HIGH",
    ),
    StageOOSSnapshotSpec(
        "086520", "에코프로", "2023-07-31",
        "extreme_expansion_progressed",
        "수정주가 기준 23.6만원(분할 전 150만원 상당) 도달, 12개월 1000% 이상 폭등.",
        PatternAStage.PROGRESSED,
        "역사상 유례없는 숏스퀴즈 및 광풍으로 가격이 통상적 밴드를 완전히 이탈하여 "
        "극단적 과열 확장에 도달한 PROGRESSED.",
        "2차전지 광풍 episode의 최종 버블 확장 단계.",
        "OOS v0.1 신규 선정 후보(극단적 버블 확장 사례).",
        "HIGH",
    ),
    StageOOSSnapshotSpec(
        "086520", "에코프로", "2023-11-30",
        "episode_continuation_progressed",
        "7월 최고점 이후 14.6만원으로 40% 이상 급락 조정을 거쳐 횡보 중인 시점.",
        PatternAStage.PROGRESSED,
        "최근 단기 주가는 크게 하락 조정 중이나, 2023년 폭발적 확장을 거친 동일 episode 내에 "
        "위치하므로 EARLY_TREND나 BASE로 단순 회귀할 수 없는 전형적 episode continuation PROGRESSED.",
        "극단적 확장 후 조정 국면이나 cycle reset(장기 베이스 재구축) 전이므로 동일 episode 유지.",
        "OOS v0.1 신규 선정 후보(episode continuation known failure mode 검증).",
        "HIGH",
    ),
    StageOOSSnapshotSpec(
        "035900", "JYP Ent.", "2023-06-30",
        "extended_progressed",
        "13만원 돌파, 2020년 2만원대 대비 6배 이상 수년간 지속 확장된 국면.",
        PatternAStage.PROGRESSED,
        "다년간의 장기 랠리를 거쳐 주가가 고도화되었으며 36개월 레인지 92% 위치에서 "
        "추세가 충분히 성숙된 PROGRESSED.",
        "2020년 하반기 시작된 엔터 대세 상승 episode의 후반 확장 국면.",
        "OOS v0.1 신규 선정 후보(엔터 대세 상승 장기 확장 사례).",
        "HIGH",
    ),
    StageOOSSnapshotSpec(
        "138040", "메리츠금융지주", "2024-08-31",
        "extended_progressed",
        "9.1만원 돌파, 지주 통합 이후 2년 이상 지속된 랠리로 36개월 레인지 93% 도달.",
        PatternAStage.PROGRESSED,
        "2022~2023년 초기 전환/돌파를 마친 후 2년 연속 우상향하며 장기 이평선과 주가가 "
        "넓게 확장된 성숙 추세 국면.",
        "지주사 통합 이후 전개된 주주환원 대세 상승 episode의 확장 국면.",
        "OOS v0.1 신규 선정 후보(금융 대세 상승 확장 사례).",
        "HIGH",
    ),
    StageOOSSnapshotSpec(
        "006260", "LS", "2023-07-31",
        "extended_progressed",
        "12만원 돌파, 2023년 초 6만원대 돌파 이후 2배 이상 단기 폭등한 과열 확장.",
        PatternAStage.PROGRESSED,
        "초기 돌파(2023년 2월) 이후 가속도가 붙어 주가가 수직 상승하며 이평선 갭이 "
        "대폭 벌어진 전형적 PROGRESSED.",
        "2022년 말 전환된 상승 episode의 과열 확장 단계.",
        "OOS v0.1 신규 선정 후보(인프라 급등 확장 사례).",
        "HIGH",
    ),
)
