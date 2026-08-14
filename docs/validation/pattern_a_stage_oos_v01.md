# Pattern A Stage OOS Validation v0.1: Truth Set Freeze

## 1. 목적

이 문서는 `Stage Classifier v0.1`(commit `43ee01c`, 46건 calibration truth set 대상 EXACT 38/46, ADJACENT 5, SEVERE 3 baseline)을 **처음 보는 완전히 새로운 외부 사례(Out-of-Sample, OOS)**에서 엄격하게 검증하기 위해, classifier 예측을 실행하기 전에 **독립적인 OOS Ground Truth 35건을 사전에 봉인(freeze)**하는 selection methodology 및 audit 기록이다.

> **CRITICAL BLIND POLICY DECLARATION**
>
> - **Classifier prediction has not been run.**
> - **OOS labels were frozen before seeing classifier output.**
> - **Non-price narratives are descriptive context only. They were not used to determine manual_stage.**
> - 본 문서 및 manifest에 기록된 모든 Stage truth는 classifier 실행 결과나 Score 파생값을 전혀 보지 않고, 오직 `snapshot_date` 시점까지의 raw monthly/weekly 가격 구조와 과거 historical path만을 근거로 독립 감사하여 확정했다.

---

## 2. Dataset 성격 및 해석 Caveat

### 2.1 Dataset 성격
본 OOS v0.1 validation dataset(35 snapshots)은 시장의 무작위 표본이 아니며, 다음 성격을 갖는다.
* **Stage-balanced**: 5개 Stage(WEAK, BASE, TRANSITION, EARLY_TREND, PROGRESSED)를 각각 정확히 7건씩 균등하게 구성.
* **Failure-mode-enriched**: Stage Classifier v0.1의 4대 known failure mode(Episode continuation override 부재, 급등성 회복과 진짜 확장 구분, 약한 양전환에 대한 BASE 민감도, Active decline/false turn 과다반응)와 Cycle Reset 구조를 의도적으로 집중 배치.
* **External Challenge OOS**: 기존 Stage calibration에 쓰인 종목과 0% 겹치는 100% 신규 티커로 구성된 외부 도전 과제 세트.

### 2.2 향후 검증 결과 해석 Caveat
향후 진행될 OOS Validation Run의 exact match rate는:
* **`stage-balanced OOS exact match rate`** 또는 **`external challenge OOS reproduction rate`**로 해석해야 한다.
* 시장 전체 종목의 자연 분포(prevalence)가 반영된 **`real-world market accuracy`**나 **`production hit rate`**로 직접 환산하여 해석해서는 안 된다.

---

## 3. Selection Methodology & Code-Enforced 검증

### 3.1 기존 Dataset과의 Overlap 0 검증 (Test-Enforced)

[`tests/test_pattern_a_stage_oos_v01_manifest.py`](file:///Users/june/Documents/projects/krx-trend-scanner/tests/test_pattern_a_stage_oos_v01_manifest.py)를 통해 다음 무중복성이 코드로 강제 검증되었다.

1. **Stage Calibration 46건**:
   - `exact key overlap = 0` (Test Enforced)
   - `ticker overlap = 0` (Test Enforced: 기존 27개 티커와 0% 중복, 100% 신규 24개 고유 티커)
2. **OOS v0.1 Diagnostic (29 snapshots)**:
   - `exact key overlap = 0` (Test Enforced)
3. **OOS v0.2 Validation (22 snapshots)**:
   - `exact key overlap = 0` (Test Enforced)
4. **Negative Control (8 snapshots)**:
   - `exact key overlap = 0` (Test Enforced)
5. **Holdout datasets**:
   - `exact key overlap = 0` (Test Enforced)

### 3.2 HistoricalSnapshot Reconstruction & Provenance 검증 (Test-Enforced)

35건 전체에 대해 `build_historical_snapshot(..., include_incomplete_periods=False)`를 실행하여 다음을 검증했다.
* 35건 전체 `HistoricalSnapshot` 생성 성공 및 `FeatureRow` 계산 완료.
* `effective_as_of <= snapshot_date`
* `monthly_as_of <= snapshot_date` 및 `snapshot.monthly.index.max() <= monthly_as_of`
* `weekly_as_of <= snapshot_date`
* **Future bar / Lookahead leakage 없음**이 전수 확인됨.

### 3.3 사용 가능한 정보 vs 금지된 정보 (Classifier Threshold Leakage 방지)

| 구분 | 허용/사용 정보 | 절대 금지 정보 |
|---|---|---|
| **데이터 범위** | raw daily OHLCV, monthly/weekly resampling, 장기 고점/저점, 박스권 폭, 이평선 형태 및 가격 경로 | `classify_pattern_a_stage()` 실행 결과, `StageEvidence`, `StageLifecycleContext`, `reason_codes` |
| **Score 분리** | 순수 가격 구조의 장기 시계열 | `score_pattern_a()`, `PatternAStage` provisional score heuristic |
| **Cutoff 누출 방지** | 정성적 장기 추세 및 박스 구조 관찰 | classifier 내부 수치(`weekly_ma12_slope >= 0.03`, `range_position >= 0.60`, `avg_price_change_12m >= 0.30` 등)를 selection cutoff로 역이용하는 행위 |

### 3.4 Non-Price Narrative의 철저한 분리 원칙

* **`manual_stage_reason`**: 오직 가격 구조(이평선 배열, 박스권 위치, 저항선 도달, 저점 상승/하락 등)만 기술.
* **`episode_notes`**: 오직 과거 가격 경로(과거 상승 사이클 붕괴, 수년간 횡보, 새로운 상승 파동, 피크 후 조정 등)만 기술.
* **`source_notes`**: 업황, 정책(밸류업 등), 제품(불닭 등), 테마, M&A 등 비가격 시장 맥락은 참고용 설명으로만 분리 기재.
* **원칙**: 비가격 narrative는 Stage 판정에 일체 영향을 주지 않았다.

---

## 4. Known Failure Mode Coverage 계획

현재 Stage Classifier v0.1의 4가지 주요 Failure Mode를 신규 종목에서도 철저히 시험할 수 있도록 다음 사례들을 전략적으로 포함했다.

1. **Episode Continuation Override 부재 검증**:
   - `086520` 에코프로 (2023-11-30, PROGRESSED): 7월 피크(23.6만원) 이후 14.6만원으로 -40% 급락 조정 중이나, 2023년 폭발적 확장을 거친 동일 episode 내 consolidation 국면.
2. **급등성 회복(Bounce Recovery) vs 진짜 Progression 구분**:
   - `035900` JYP Ent. (2020-07-31, TRANSITION): 코로나 급락 후 가파른 V자 반등으로 12개월 변화율은 높지만 장기 구조상 전고점 돌파 전인 전환 단계.
3. **약한 양전환 신호에 대한 BASE 민감도**:
   - `017670` SK텔레콤 (2023-12-31, BASE), `024110` 기업은행 (2023-11-30, BASE): 장기 조용한 박스권에서 단기 잔파동에 흔들리지 않는 순수 베이스 특성 검증.
4. **Active Decline 과다 반응 및 False Turn 검증**:
   - `006360` GS건설 (2022-11-30, WEAK): 장기 하락세 속 주봉만 일시 반등하는 false turn.
5. **Cycle Reset 구조 검증**:
   - `068270` 셀트리온 (2023-09-30, BASE): 2020~2021년 과거 대세 상승 episode가 붕괴 후 2년간 바닥을 다져 완전한 Cycle Reset을 거친 신규 BASE.

---

## 5. OOS Ground Truth Manifest (35 Snapshots)

### 5.1 Stage별 요약 통계

| Stage | 수량 | 대표 케이스 | 주요 특징 |
|---|---|---|---|
| **WEAK** | 7 | GS건설, 한화솔루션, 한온시스템, 현대건설, NAVER, 신세계 | 활성 장기 하락 지속, 52주 신저가 갱신, false turn |
| **BASE** | 7 | SK텔레콤, KT, 기업은행, 삼성물산, NH투자증권, 오리온, 셀트리온 | 3년 이상 저변동성 박스권, 바닥 안정화, Cycle reset BASE |
| **TRANSITION** | 7 | SK하이닉스, DB손해보험, LS, 삼성E&A, 삼양식품, JYP Ent., 신한지주 | Weekly leads, Core/Weekly 동반 턴, 급등성 회복 |
| **EARLY_TREND** | 7 | SK하이닉스, 에스엘, DB손해보험, LS, 삼성E&A, 삼양식품, 한화시스템 | 장기 저항선 돌파 안착, 이평선 정배열 초기, 실적 추세 개시 |
| **PROGRESSED** | 7 | SK하이닉스, 삼양식품, 에코프로(2건), JYP Ent., 메리츠금융지주, LS | 12개월 100%~1000% 극단적 확장, Episode continuation |
| **합계** | **35** | **24개 Unique Tickers (기존 Calibration과 0% 중복)** | **100% HIGH Confidence Ground Truth** |

---

### 5.2 전체 35건 상세 목록

```text
[WEAK (7건)]
1. 006360 GS건설       (2023-10-31) | active_decline_continuation : 2021년 고점 이후 장기 지속 하락세, 1.3만원대 52주 신저가
2. 006360 GS건설       (2022-11-30) | false_turn                  : 장기 하락 중 주봉 단기 반등 있으나 월봉 구조 붕괴 지속
3. 009830 한화솔루션    (2024-04-30) | active_decline_continuation : 2022년 고점 이후 장기 하락 지속, 2.4만원 신저가
4. 018880 한온시스템    (2024-06-30) | active_decline_continuation : 수년간 지속 하락하여 4천원대 신저가 지속 갱신
5. 000720 현대건설     (2024-03-31) | active_decline_continuation : 3만원대 초반까지 장기 하향 표류 및 바닥 미확인
6. 035420 NAVER        (2022-10-31) | active_decline_continuation : 2021년 고점 이후 16만원대까지 가파른 낙폭 과대 지속
7. 004170 신세계       (2024-08-31) | active_decline_continuation : 15만원대까지 수년간 계단식 하락 지속

[BASE (7건)]
8.  017670 SK텔레콤    (2023-12-31) | quiet_box_base             : 4만~5만원대 3년 이상 극도로 조용한 횡보 박스권
9.  030200 KT          (2023-10-31) | quiet_box_base             : 3만원 초반대 바닥을 탄탄히 다지는 수평 횡보
10. 024110 기업은행    (2023-11-30) | quiet_box_base             : 9천~1.1만원대 장기 박스 하단 안정화
11. 028260 삼성물산    (2023-10-31) | quiet_box_base             : 10만~11만원대 3년간 지루한 박스권 안정화
12. 005940 NH투자증권  (2023-10-31) | quiet_box_base             : 8천~9천원대 장기 바닥 지지력 구축
13. 271560 오리온      (2024-08-31) | quiet_box_base             : 9만원대 초반 안정적 수평 횡보 박스권
14. 068270 셀트리온    (2023-09-30) | cycle_reset_base           : 2020년 랠리 완전 소멸 후 14만원대 바닥 재정비 (Cycle reset)

[TRANSITION (7건)]
15. 000660 SK하이닉스  (2023-05-31) | weekly_leading_transition  : 7.5만원 바닥에서 10만원대로 주봉이 먼저 강하게 상방 전환
16. 005830 DB손해보험  (2023-06-30) | dual_turn_transition       : 7만원대 박스 상단 도달, 주봉/월봉 동반 턴어라운드 시작
17. 006260 LS          (2022-10-31) | box_breakout_prep_transition : 5만원대 박스 탈피, 6.6만원대로 주봉/월봉 우상향 전환
18. 028050 삼성E&A     (2021-03-31) | weekly_leading_transition  : 1.2만원 바닥 탈출, 1.4만원대로 주봉이 먼저 전환
19. 003230 삼양식품    (2022-04-30) | gradual_turn_transition    : 8만원대 횡보 후 9.8만원대로 주봉/월봉 서서히 상향 수렴
20. 035900 JYP Ent.    (2020-07-31) | surge_recovery_transition  : 코로나 급락 후 3만원으로 가파른 V자 반등 회복 (급등성 회복)
21. 055550 신한지주    (2024-01-31) | weekly_leading_transition  : 3.5만원 박스에서 주봉 먼저 4만원 양전환

[EARLY_TREND (7건)]
22. 000660 SK하이닉스  (2023-11-30) | clean_early_trend          : 13만원 전고점 돌파 및 이평선 정배열 안착
23. 005850 에스엘      (2023-04-30) | clean_early_trend          : 2.5만원 장기 박스 상단 돌파, 3.1만원 안착
24. 005830 DB손해보험  (2023-12-31) | clean_early_trend          : 8.3만원 도달, 역사적 신고가 영역 진입 및 정배열
25. 006260 LS          (2023-02-28) | clean_early_trend          : 7만원 저항 돌파, 대세 상승 초입
26. 028050 삼성E&A     (2021-06-30) | clean_early_trend          : 2.3만원 돌파, 3년 박스 상단 제압
27. 003230 삼양식품    (2022-11-30) | clean_early_trend          : 11.1만원 안착, 장기 박스 상단 돌파 및 우상향 개시
28. 272210 한화시스템  (2024-03-31) | clean_early_trend          : 1.7만원 저항 돌파, 52주 신고가 갱신

[PROGRESSED (7건)]
29. 000660 SK하이닉스  (2024-06-30) | extended_progressed        : 23.6만원 돌파, 12개월 상승률 100% 초과 극단적 확장
30. 003230 삼양식품    (2024-06-30) | extended_progressed        : 66.9만원 도달, 12개월 상승률 +500% 초과 역사적 초과열 확장
31. 086520 에코프로    (2023-07-31) | extreme_expansion_progressed : 수정주가 23.6만원 도달, 12개월 1000% 이상 버블 확장
32. 086520 에코프로    (2023-11-30) | episode_continuation_progressed : 피크 후 14.6만원 조정 중이나 동일 episode 내 유지
33. 035900 JYP Ent.    (2023-06-30) | extended_progressed        : 13만원 돌파, 2020년 대비 6배 이상 진행된 성숙 확장
34. 138040 메리츠금융지주 (2024-08-31) | extended_progressed     : 9.1만원 돌파, 2년 연속 우상향 장기 성숙 추세
35. 006260 LS          (2023-07-31) | extended_progressed        : 12만원 돌파 급등, 단기 및 장기 과열 확장 국면
```

---

## 6. Current Status & Next Step

### 6.1 이번 단계 완료 상태

- **Pattern A Stage Classifier v0.1**: FROZEN (`43ee01c`)
- **Calibration Truth Set (46 snapshots)**: FROZEN
- **Stage OOS Selection (35 snapshots)**: FROZEN
- **Stage OOS Manual Truth (35 snapshots)**: FROZEN
- **Stage OOS Prediction**: **NOT RUN**

### 6.2 Next Step

본 OOS Ground Truth Freeze 후속 커밋이 정상적으로 리뷰 및 승인된 후, 별도의 후속 작업(`Pattern A Stage Classifier v0.1 Frozen OOS Validation Run`)에서 얼려진 Stage Classifier v0.1을 실행하여 정확도와 혼동 행렬(Confusion Matrix) 및 failure mode를 검증한다.
