# Pattern A FAST Trading Policy Entry v0.1 평가 보고서

- **평가 대상 모집단**: `Frozen Investable OOS B (총 36개 표본)`
- **기준 커밋**: `70de72418b26c2caaafdb4317d46e2668981932c`
- **사전등록 커밋**: `a5e5ba897ffcd609d49435b03102a27305a42432`
- **사전등록 프로토콜 해시**: `32aae360faf04224fb1e418fe22465e84720444f78817e7c768f7e3583836c58`
- **선택 매니페스트 해시**: `6fb59b9ffce5d8076a18faa00327c62e4edc5cff6ef93bcaf5095c50532ef825`
- **외부 네트워크 요청**: `0회 (로컬 Parquet 캐시 전용, Zero Network Requests)`
- **최종 연구 결론**: **`PROMISING` (후속 검증 가치 있음)**

---

## 1. 기본 진입 규칙 및 체결 계약
- **진입 조건**: `FAST Stage == TRIGGER` AND `Stage Status == READY` AND `Monthly Regime == PERMITTED_REGIME` AND `Daily Risk IN {'NORMAL', 'ELEVATED'}` AND `Score Status IN {'READY', 'PARTIAL'}`
- **체결 가격**: `next_trading_day_open` (신호 완성 주간 직후 첫 거래일 시가 체결)
- **비게이트 정책**: FAST 점수 임계값(Score threshold) 및 Pattern A 점수/국면 조건 배제 (선행 신호 보존)

---

## 2. 진입 발생률 및 통계
- **총 분석 대상**: `36개 표본`
- **Primary Entry 발생**: `13개` (`36.1%`)
- **진입 미발생 (NO_ENTRY)**: `23개` (`63.9%`)
- **진입 등급 구성**: Grade A (NORMAL Risk) `12개`, Grade B (ELEVATED Risk) `1개`
- **진입 소요 기간 (Median Weeks to Entry)**: `19.0주`

### 진입 미발생 (NO_ENTRY) 사유 분류:
- `NO_TRIGGER`: 14개
- `TRIGGER_BUT_EARLY_REGIME`: 4개
- `TRIGGER_BUT_SCORE_UNAVAILABLE`: 3개
- `TRIGGER_BUT_LATE_OR_EXTENDED_REGIME`: 2개

---

## 3. 신호 이후 기간별 수익률 및 최대 순행 / 역행 폭

| 관측 기간 | 유효 표본수 (n) | 중위 수익률 (Median) | 평균 수익률 (Mean) | 승률 (Positive Rate) | 최대 순행 폭 중위수 (MFE) | 최대 역행 폭 중위수 (MAE) |
|---|---:|---:|---:|---:|---:|---:|
| **4주 (4W)** | 12 | **+6.44%** | +4.79% | 58.3% | +9.81% | -8.34% |
| **8주 (8W)** | 11 | **+0.28%** | +10.01% | 54.5% | +15.46% | -8.72% |
| **12주 (12W)** | 10 | **+0.20%** | +4.69% | 50.0% | +15.71% | -11.34% |
| **26주 (26W)** | 8 | **+12.08%** | +7.90% | 75.0% | +25.49% | -15.24% |

---

## 4. 인간 판정 결과별 성과 비교

| 그룹 구분 | 표본 수 | 진입 수 | 진입률 | 4주 중위 수익률 | 12주 중위 수익률 |
|---|---:|---:|---:|---:|---:|
| **positive_triggers (GOOD + BORDERLINE)** | 12 | 9 | 75.0% | +7.04% | +3.37% |
| **negative_or_early (TOO_EARLY + NO_SETUP)** | 14 | 3 | 21.4% | +4.88% | +24.26% |

### 세부 인간 판정 라벨별 성과:
- **BORDERLINE_TRIGGER** (총 7개): 진입=5/7 (71.4%), 4주 중위수=+7.04%
- **FALSE_TRIGGER** (총 5개): 진입=1/5 (20.0%), 4주 중위수=-8.61%
- **GOOD_TRIGGER** (총 5개): 진입=4/5 (80.0%), 4주 중위수=+4.47%
- **NO_SETUP** (총 6개): 진입=0/6 (0.0%), 4주 중위수=N/A
- **TOO_EARLY** (총 8개): 진입=3/8 (37.5%), 4주 중위수=+4.88%
- **TOO_EXTENDED** (총 3개): 진입=0/3 (0.0%), 4주 중위수=N/A
- **TOO_LATE** (총 2개): 진입=0/2 (0.0%), 4주 중위수=N/A

---

## 5. 실험 조건 및 비교군 결과

- **기본 진입 규칙 (PERMITTED + 비EXTREME 리스크)**: 진입 n=13, 4주 중위수=**+6.44%**, 12주 중위수=**+0.20%**
- **비교군 (Trigger Any Control, 필터 미적용)**: 진입 n=19, 4주 중위수=**-0.24%**, 12주 중위수=**-0.66%**
- **조기 진입 실험군 (Early Variant, EARLY_REGIME)**: 진입 n=4, 4주 중위수=**-6.86%**, 12주 중위수=**-3.47%**

> **기술적 비교 해석**: `PERMITTED_REGIME` 및 비-EXTREME 리스크 필터 적용 시, 조기 역추세성 노이즈(Early variant 4주 중위수 -6.86%)를 차단하여 무제한 Control(4주 중위수 -0.24%) 대비 더 나은 기술적 성과 특성이 관찰됨.

---

## 6. 표본별 세부 결과

| 표본 ID | 종목코드 | 종목명 | 인간 라벨 | 진입 여부 | 진입 등급 | 신호 발생일 | 체결일 | 체결 시가 | 4주 수익률 | 12주 수익률 | 미진입 사유 / 비고 |
|---|:---:|---|---|:---:|:---:|:---:|:---:|---:|---:|---:|---|
| INV_OOS_B_001 | `178920` | PI첨단소재 | `TOO_EARLY` | YES | Grade A | 2024-07-19 | 2024-07-22 | 31,000 | - | - | `ENTRY_SUCCESS` |
| INV_OOS_B_002 | `281740` | 레이크머티리얼즈 | `GOOD_TRIGGER` | YES | Grade A | 2024-02-23 | 2024-02-26 | 21,950 | +11.62% | - | `ENTRY_SUCCESS` |
| INV_OOS_B_003 | `060230` | 소니드 | `NO_SETUP` | NO | - | - | - | - | - | - | `NO_TRIGGER` |
| INV_OOS_B_004 | `064350` | 현대로템 | `BORDERLINE_TRIGGER` | NO | - | - | - | - | - | - | `TRIGGER_BUT_SCORE_UNAVAILABLE` |
| INV_OOS_B_005 | `000720` | 현대건설 | `TOO_LATE` | NO | - | - | - | - | - | - | `TRIGGER_BUT_LATE_OR_EXTENDED_REGIME` |
| INV_OOS_B_006 | `138040` | 메리츠금융지주 | `TOO_LATE` | NO | - | - | - | - | - | - | `TRIGGER_BUT_LATE_OR_EXTENDED_REGIME` |
| INV_OOS_B_007 | `036710` | 심텍홀딩스 | `FALSE_TRIGGER` | NO | - | - | - | - | - | - | `NO_TRIGGER` |
| INV_OOS_B_008 | `200130` | 콜마비앤에이치 | `NO_SETUP` | NO | - | - | - | - | - | - | `TRIGGER_BUT_EARLY_REGIME` |
| INV_OOS_B_009 | `402030` | 코난테크놀로지 | `FALSE_TRIGGER` | NO | - | - | - | - | - | - | `NO_TRIGGER` |
| INV_OOS_B_010 | `022100` | 포스코DX | `TOO_EARLY` | NO | - | - | - | - | - | - | `NO_TRIGGER` |
| INV_OOS_B_011 | `048410` | 현대바이오 | `NO_SETUP` | NO | - | - | - | - | - | - | `NO_TRIGGER` |
| INV_OOS_B_012 | `214320` | 이노션 | `FALSE_TRIGGER` | YES | Grade B | 2024-05-03 | 2024-05-07 | 23,800 | -8.61% | -17.02% | `ENTRY_SUCCESS` |
| INV_OOS_B_013 | `119830` | 아이텍 | `TOO_EARLY` | NO | - | - | - | - | - | - | `TRIGGER_BUT_EARLY_REGIME` |
| INV_OOS_B_014 | `053080` | 케이엔솔 | `TOO_EXTENDED` | NO | - | - | - | - | - | - | `NO_TRIGGER` |
| INV_OOS_B_015 | `079940` | 가비아 | `GOOD_TRIGGER` | YES | Grade A | 2025-04-18 | 2025-04-21 | 21,350 | -4.92% | +16.16% | `ENTRY_SUCCESS` |
| INV_OOS_B_016 | `256940` | 케이피에스 | `BORDERLINE_TRIGGER` | NO | - | - | - | - | - | - | `TRIGGER_BUT_SCORE_UNAVAILABLE` |
| INV_OOS_B_017 | `074600` | 원익QnC | `BORDERLINE_TRIGGER` | YES | Grade A | 2024-01-05 | 2024-01-08 | 31,950 | -11.58% | +3.76% | `ENTRY_SUCCESS` |
| INV_OOS_B_018 | `033780` | KT&G | `GOOD_TRIGGER` | YES | Grade A | 2024-03-08 | 2024-03-11 | 93,300 | -2.68% | -10.50% | `ENTRY_SUCCESS` |
| INV_OOS_B_019 | `051900` | LG생활건강 | `NO_SETUP` | NO | - | - | - | - | - | - | `NO_TRIGGER` |
| INV_OOS_B_020 | `271560` | 오리온 | `TOO_EARLY` | NO | - | - | - | - | - | - | `NO_TRIGGER` |
| INV_OOS_B_021 | `214150` | 클래시스 | `BORDERLINE_TRIGGER` | YES | Grade A | 2021-06-25 | 2021-06-28 | 17,800 | +25.56% | +17.70% | `ENTRY_SUCCESS` |
| INV_OOS_B_022 | `010140` | 삼성중공업 | `GOOD_TRIGGER` | YES | Grade A | 2024-03-29 | 2024-04-01 | 8,600 | +14.53% | +3.37% | `ENTRY_SUCCESS` |
| INV_OOS_B_023 | `125210` | 아모그린텍 | `FALSE_TRIGGER` | NO | - | - | - | - | - | - | `TRIGGER_BUT_SCORE_UNAVAILABLE` |
| INV_OOS_B_024 | `004020` | 현대제철 | `TOO_EARLY` | YES | Grade A | 2025-03-07 | 2025-03-10 | 31,350 | -22.97% | -10.05% | `ENTRY_SUCCESS` |
| INV_OOS_B_025 | `028050` | 삼성엔지니어링 | `BORDERLINE_TRIGGER` | YES | Grade A | 2023-02-17 | 2023-02-20 | 28,250 | +5.84% | - | `ENTRY_SUCCESS` |
| INV_OOS_B_026 | `101530` | 해태제과식품 | `BORDERLINE_TRIGGER` | YES | Grade A | 2025-06-13 | 2025-06-16 | 7,080 | +10.88% | -2.97% | `ENTRY_SUCCESS` |
| INV_OOS_B_027 | `084370` | 유진테크 | `TOO_EARLY` | YES | Grade A | 2025-08-22 | 2025-08-25 | 48,750 | +32.72% | +58.56% | `ENTRY_SUCCESS` |
| INV_OOS_B_028 | `217330` | 싸이토젠 | `FALSE_TRIGGER` | NO | - | - | - | - | - | - | `NO_TRIGGER` |
| INV_OOS_B_029 | `002350` | 넥센타이어 | `TOO_EARLY` | NO | - | - | - | - | - | - | `TRIGGER_BUT_EARLY_REGIME` |
| INV_OOS_B_030 | `010620` | 현대미포조선 | `BORDERLINE_TRIGGER` | YES | Grade A | 2023-07-07 | 2023-07-10 | 86,600 | +7.04% | -12.12% | `ENTRY_SUCCESS` |
| INV_OOS_B_031 | `270520` | 지오릿에너지 | `NO_SETUP` | NO | - | - | - | - | - | - | `NO_TRIGGER` |
| INV_OOS_B_032 | `005180` | 빙그레 | `TOO_EXTENDED` | NO | - | - | - | - | - | - | `NO_TRIGGER` |
| INV_OOS_B_033 | `018880` | 한온시스템 | `NO_SETUP` | NO | - | - | - | - | - | - | `NO_TRIGGER` |
| INV_OOS_B_034 | `005850` | 에스엘 | `TOO_EXTENDED` | NO | - | - | - | - | - | - | `NO_TRIGGER` |
| INV_OOS_B_035 | `222080` | 씨아이에스 | `TOO_EARLY` | NO | - | - | - | - | - | - | `TRIGGER_BUT_EARLY_REGIME` |
| INV_OOS_B_036 | `086520` | 에코프로 | `GOOD_TRIGGER` | NO | - | - | - | - | - | - | `NO_TRIGGER` |

---

## 7. 최종 연구 결론
> **결론: `PROMISING` (후속 검증 가치 있음)**
>
> - **진입 필터 선별력**: `PROMISING`
> - **수익률 프로파일**: `MIXED`
> - **전체 연구 상태**: `PROMISING FOR FURTHER VALIDATION`
>
> Primary Entry Rule(TRIGGER + PERMITTED_REGIME + 비EXTREME 리스크)은 기술적 비교상 4W(+6.44%), 8W(+0.28%), 12W(+0.20%), 26W(+12.08%) 전 호라이즌에서 플러스 중위수 총수익률을 기록하였으며, FALSE_TRIGGER(80% 차단) 및 NO_SETUP(100% 차단) 등 부적합 샘플을 차단하고 긍정적 인간 라벨(GOOD+BORDERLINE)의 75.0%(9/12)를 포착함. 무제한 Control(4W 중위수: -0.24%) 대비 더 나은 기술적 성과 특성이 관찰되어 후속 prospective / walk-forward 연구 가설로 검증할 가치가 있음. 다만 본 평가는 과거 표본 사후 분석이며 통계적 유의성 검정이나 전략 검증 완료를 의미하지 않음.

*주의: 본 평가는 과거 Frozen OOS B 표본을 활용한 사후 평가(Retrospective Evaluation)이며, 수수료/세금/슬리피지가 제외된 총수익률(Gross Return) 기준입니다. Production 규칙으로 승격하지 않으며 후속 Prospective / Walk-Forward 연구 가설로 활용됩니다.*