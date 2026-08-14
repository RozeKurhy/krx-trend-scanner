# Pattern A Stage OOS Validation v0.1: Truth Set Freeze

## 1. 목적

이 문서는 `Stage Classifier v0.1`(commit `43ee01c`, 46건 calibration truth set 대상 EXACT 38/46, ADJACENT 5, SEVERE 3 baseline)을 **처음 보는 완전히 새로운 외부 사례(Out-of-Sample, OOS)**에서 엄격하게 검증하기 위해, classifier 예측을 실행하기 전에 **독립적인 OOS Ground Truth 35건을 사전에 봉인(freeze)**하는 selection methodology 및 audit 기록이다.

> **CRITICAL BLIND POLICY DECLARATION**
>
> - **Classifier prediction has not been run.**
> - **OOS labels were frozen before seeing classifier output.**
> - 본 문서 및 manifest에 기록된 모든 Stage truth는 classifier 실행 결과나 Score 파생값을 전혀 보지 않고, 오직 `snapshot_date` 시점까지의 raw monthly/weekly 가격 구조와 과거 historical path만을 근거로 독립 감사하여 확정했다.

---

## 2. Selection Methodology

### 2.1 Independence Policy & 기존 Calibration Set과의 중복 방지

1. **Ticker 완전 분리 (1순위 100% 달성)**:
   - 기존 Stage Calibration Dataset(46 snapshots, 27 unique tickers)에 포함된 종목(`000270`, `000810`, `000880`, `001040`, `003550`, `005380`, `005490`, `009150`, `010130`, `010620`, `011170`, `011200`, `011210`, `012450`, `015760`, `018260`, `023530`, `032830`, `034220`, `034730`, `042660`, `042700`, `051910`, `079550`, `086790`, `105560`, `214150`)을 **단 하나도 재사용하지 않았다.**
   - 본 OOS v0.1 manifest는 **100% 신규 24개 고유 ticker**로 구성되었다.
2. **Snapshot Key 중복 0건**:
   - 기존 Calibration 46건, OOS1 29건, OOS2 22건, Negative Control 8건, Holdout 3건과의 `(ticker, snapshot_date)` 중복이 0건이다.

### 2.2 Candidate Sourcing 및 Snapshot Selection 원칙

- **다양한 업종/시가총액/사이클 커버리지**: 반도체(`SK하이닉스`), 자동차 부품(`에스엘`, `한온시스템`), 금융/지주(`기업은행`, `신한지주`, `NH투자증권`, `메리츠금융지주`, `삼성물산`), 전력/인프라(`LS`, `한화시스템`), 플랜트(`삼성E&A`), 통신/유틸리티(`SK텔레콤`, `KT`), 바이오/제약(`셀트리온`), 엔터/콘텐츠(`JYP Ent.`), 소비재/음식료(`삼양식품`, `오리온`, `신세계`), 2차전지(`에코프로`), 건설(`GS건설`, `현대건설`), 화학/신재생(`한화솔루션`), 플랫폼(`NAVER`) 등.
- **Stage Lifecycle 균형**: 특정 Stage에 편중되지 않도록 5개 Stage 각각 7건씩 총 35건으로 고르게 구성했다.

### 2.3 사용 가능한 정보 vs 금지된 정보 (Classifier Threshold Leakage 방지)

| 구분 | 허용/사용 정보 | 절대 금지 정보 |
|---|---|---|
| **데이터 범위** | raw daily OHLCV, monthly/weekly resampling, 장기 고점/저점, 박스권 폭, 이평선 형태 및 가격 경로 | `classify_pattern_a_stage()` 실행 결과, `StageEvidence`, `StageLifecycleContext`, `reason_codes` |
| **Score 분리** | 순수 가격 구조의 장기 시계열 | `score_pattern_a()`, `PatternAStage` provisional score heuristic |
| **Cutoff 누출 방지** | 정성적 장기 추세 및 박스 구조 관찰 | classifier 내부 수치(`weekly_ma12_slope >= 0.03`, `range_position >= 0.60`, `avg_price_change_12m >= 0.30` 등)를 selection cutoff로 역이용하는 행위 |

### 2.4 Lookahead 및 Outcome Contamination 방지

- 모든 manual Stage 판정은 **`snapshot_date` 당일 및 그 이전 데이터만**을 보고 내렸다.
- 스냅샷 이후의 주가 급등, 신고가 갱신, 급락, 실적 발표 등 사후 결과(outcome)를 근거로 Stage를 소급 부여하거나 수정하는 일체의 행위를 금지했다.

### 2.5 Manual Stage Audit 절차

1. **Raw Monthly Structure 점검**: 36개월 레인지 내 위치, 장기 하락 지속 여부, 24개월선 평탄화/우상향 여부.
2. **Weekly Structure 점검**: 12주선 기울기 방향, 저점 상승(Higher Low) 형성 여부, 단기 반등 vs 구조적 반등 구분.
3. **Historical Path & Episode 점검**: 현재 시점이 과거 상승 사이클의 연장(Episode continuation)인지, 완전히 새로운 바닥(Cycle reset)인지, 신규 상승 돌파인지 판정.
4. **Manual Ground-Truth Stage 결정 및 근거 작성**: `WEAK`, `BASE`, `TRANSITION`, `EARLY_TREND`, `PROGRESSED` 중 하나로 확정하고 독립 사유 기록.

---

## 3. Known Failure Mode Coverage 계획

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

## 4. OOS Ground Truth Manifest (35 Snapshots)

### 4.1 Stage별 요약 통계

| Stage | 수량 | 대표 케이스 | 주요 특징 |
|---|---|---|---|
| **WEAK** | 7 | GS건설, 한화솔루션, 한온시스템, 현대건설, NAVER, 신세계 | 활성 장기 하락 지속, 52주 신저가 갱신, false turn |
| **BASE** | 7 | SK텔레콤, KT, 기업은행, 삼성물산, NH투자증권, 오리온, 셀트리온 | 3년 이상 저변동성 박스권, 바닥 안정화, Cycle reset BASE |
| **TRANSITION** | 7 | SK하이닉스, DB손해보험, LS, 삼성E&A, 삼양식품, JYP Ent., 신한지주 | Weekly leads, Core/Weekly 동반 턴, 급등성 회복 |
| **EARLY_TREND** | 7 | SK하이닉스, 에스엘, DB손해보험, LS, 삼성E&A, 삼양식품, 한화시스템 | 장기 저항선 돌파 안착, 이평선 정배열 초기, 실적 추세 개시 |
| **PROGRESSED** | 7 | SK하이닉스, 삼양식품, 에코프로(2건), JYP Ent., 메리츠금융지주, LS | 12개월 100%~1000% 극단적 확장, Episode continuation |
| **합계** | **35** | **24개 Unique Tickers (기존 Calibration과 0% 중복)** | **100% HIGH Confidence Ground Truth** |

---

### 4.2 전체 35건 상세 목록

```text
[WEAK (7건)]
1. 006360 GS건설       (2023-10-31) | active_decline_continuation : 검단 사고 후 장기 하락 지속, 1.3만원대 52주 신저가
2. 006360 GS건설       (2022-11-30) | false_turn                  : 장기 하락 중 주봉 단기 반등 있으나 월봉 구조 붕괴 지속
3. 009830 한화솔루션    (2024-04-30) | active_decline_continuation : 태양광 다운사이클 장기 하락 지속, 2.4만원 신저가
4. 018880 한온시스템    (2024-06-30) | active_decline_continuation : 부품 업황 둔화 장기 지속 하락, 바닥 미확인
5. 000720 현대건설     (2024-03-31) | active_decline_continuation : 건설업 침체 장기 하향 지속, 바닥 미형성
6. 035420 NAVER        (2022-10-31) | active_decline_continuation : 2021년 고점 이후 16만원대까지 가파른 낙폭 과대 지속
7. 004170 신세계       (2024-08-31) | active_decline_continuation : 내수 소비 침체 장기 계단식 하향 지속

[BASE (7건)]
8.  017670 SK텔레콤    (2023-12-31) | quiet_box_base             : 4만~5만원대 3년 이상 극도로 조용한 횡보 박스권
9.  030200 KT          (2023-10-31) | quiet_box_base             : 3만원 초반대 바닥 안정화 및 장기 수평 횡보
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
21. 055550 신한지주    (2024-01-31) | weekly_leading_transition  : 3.5만원 박스에서 밸류업 모멘텀으로 주봉 먼저 4만원 양전환

[EARLY_TREND (7건)]
22. 000660 SK하이닉스  (2023-11-30) | clean_early_trend          : 13만원 전고점 돌파 및 이평선 정배열 안착, HBM 초기 랠리
23. 005850 에스엘      (2023-04-30) | clean_early_trend          : 2.5만원 장기 박스 상단 돌파, 3.1만원 안착
24. 005830 DB손해보험  (2023-12-31) | clean_early_trend          : 8.3만원 도달, 역사적 신고가 영역 진입 및 정배열
25. 006260 LS          (2023-02-28) | clean_early_trend          : 7만원 저항 돌파, 전력 인프라 대세 상승 초입
26. 028050 삼성E&A     (2021-06-30) | clean_early_trend          : 2.3만원 돌파, 3년 박스 상단 제압 및 플랜트 사이클 진입
27. 003230 삼양식품    (2022-11-30) | clean_early_trend          : 11.1만원 안착, 불닭 수출 실적 동반 대세 상승 1차 도약
28. 272210 한화시스템  (2024-03-31) | clean_early_trend          : 1.7만원 저항 돌파, 방산 수주 사이클 초기 랠리

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

## 5. Current Status & Next Step

### 5.1 이번 단계 완료 상태

- **Pattern A Stage Classifier v0.1**: FROZEN (`43ee01c`)
- **Calibration Truth Set (46 snapshots)**: FROZEN
- **Stage OOS Selection (35 snapshots)**: FROZEN
- **Stage OOS Manual Truth (35 snapshots)**: FROZEN
- **Stage OOS Prediction**: **NOT RUN**

### 5.2 Next Step

본 OOS Ground Truth Freeze 커밋이 정상적으로 리뷰 및 승인된 후, 별도의 후속 작업(`Pattern A Stage Classifier v0.1 Frozen OOS Validation Run`)에서 얼려진 Stage Classifier v0.1을 실행하여 정확도와 혼동 행렬(Confusion Matrix) 및 failure mode를 검증한다.
