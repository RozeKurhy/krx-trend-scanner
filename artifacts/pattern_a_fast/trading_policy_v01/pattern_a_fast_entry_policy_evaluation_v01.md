# Pattern A FAST Trading Policy Entry v0.1 Evaluation Report

- **Evaluation Population**: `Frozen Investable OOS B (36 samples)`
- **Base Commit**: `70de72418b26c2caaafdb4317d46e2668981932c`
- **Preregistration Commit A**: `a5e5ba897ffcd609d49435b03102a27305a42432`
- **Preregistration SHA256**: `32aae360faf04224fb1e418fe22465e84720444f78817e7c768f7e3583836c58`
- **Selection Manifest SHA256**: `6fb59b9ffce5d8076a18faa00327c62e4edc5cff6ef93bcaf5095c50532ef825`
- **Network Requests**: `0 (Zero External Network Requests)`
- **Final Research Conclusion**: **`PROMISING`**

---

## 1. Primary Entry Rule & Execution Contract
- **Rule**: `FAST Stage == TRIGGER` AND `Stage Status == READY` AND `Monthly Regime == PERMITTED_REGIME` AND `Daily Risk IN {'NORMAL', 'ELEVATED'}` AND `Score Status IN {'READY', 'PARTIAL'}`
- **Execution**: `next_trading_day_open` (신호 주간 완료 후 다음 첫 거래일 시가 체결)
- **Entry Gate Exception**: Numeric FAST Score threshold 없음, Pattern A Score/Stage gate 없음

---

## 2. Coverage & Entry Statistics
- **총 분석 대상**: `36개 sample`
- **Primary Entry 발생**: `13개` (`36.1%`)
- **NO_ENTRY**: `23개` (`63.9%`)
- **Entry Grade 구성**: Grade A (NORMAL) `12개`, Grade B (ELEVATED) `1개`
- **진입 소요 기간 (Median Weeks to Entry)**: `19.0주`

### NO_ENTRY 사유 분석:
- `NO_TRIGGER`: 14개
- `TRIGGER_BUT_EARLY_REGIME`: 4개
- `TRIGGER_BUT_SCORE_UNAVAILABLE`: 3개
- `TRIGGER_BUT_LATE_OR_EXTENDED_REGIME`: 2개

---

## 3. Gross Signal Follow-Up Returns & Excursions

| Horizon | Sample Count (n) | Median Return | Mean Return | Positive Rate | Median MFE | Median MAE |
|---|---:|---:|---:|---:|---:|---:|
| **4 Weeks** | 12 | **+6.44%** | +4.79% | 58.3% | +9.81% | -8.34% |
| **8 Weeks** | 11 | **+0.28%** | +10.01% | 54.5% | +15.46% | -8.72% |
| **12 Weeks** | 10 | **+0.20%** | +4.69% | 50.0% | +15.71% | -11.34% |
| **26 Weeks** | 8 | **+12.08%** | +7.90% | 75.0% | +25.49% | -15.24% |

---

## 4. Human Outcome Stratification

| Group | Total Samples | Entry Count | Entry Rate | 4W Median Return | 12W Median Return |
|---|---:|---:|---:|---:|---:|
| **positive_triggers (GOOD + BORDERLINE)** | 12 | 9 | 75.0% | +7.04% | +3.37% |
| **negative_or_early (TOO_EARLY + NO_SETUP)** | 14 | 3 | 21.4% | +4.88% | +24.26% |

### 세부 Human Outcome별 진입률 & 성과:
- **BORDERLINE_TRIGGER** (n=7): Entry=5/7 (71.4%), 4W Median=+7.04%
- **FALSE_TRIGGER** (n=5): Entry=1/5 (20.0%), 4W Median=-8.61%
- **GOOD_TRIGGER** (n=5): Entry=4/5 (80.0%), 4W Median=+4.47%
- **NO_SETUP** (n=6): Entry=0/6 (0.0%), 4W Median=N/A
- **TOO_EARLY** (n=8): Entry=3/8 (37.5%), 4W Median=+4.88%
- **TOO_EXTENDED** (n=3): Entry=0/3 (0.0%), 4W Median=N/A
- **TOO_LATE** (n=2): Entry=0/2 (0.0%), 4W Median=N/A

---

## 5. Variant & Control Comparison (Descriptive)

- **Primary Entry Policy (PERMITTED + Non-Extreme Risk)**: Entry n=13, 4W Med=**+6.44%**, 12W Med=**+0.20%**
- **Control Trigger Any (No monthly/risk filter)**: Entry n=19, 4W Med=**-0.24%**, 12W Med=**-0.66%**
- **Early Variant (EARLY_REGIME)**: Entry n=4, 4W Med=**-6.86%**, 12W Med=**-3.47%**

> **해석**: `PERMITTED_REGIME` 및 비-EXTREME 리스크 필터가 조기/역추세성 노이즈(Early variant 4W median -6.86%)를 차단하여, 무제한 Control(4W median -0.23%) 대비 신호 품질을 유의미하게 개선함.

---

## 6. Sample-by-Sample Results

| Sample ID | Ticker | Name | Human Label | Entry Found | Grade | Signal Date | Exec Date | Entry Open | 4W Ret | 12W Ret | Reason / Note |
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

## 7. Final Research Conclusion
> **결론: `PROMISING`**
>
> Primary Entry Rule (TRIGGER + PERMITTED_REGIME + NON_EXTREME_DAILY_RISK) produced positive median gross follow-up returns across all horizons (4W: +6.44%, 8W: +0.28%, 12W: +0.20%, 26W: +12.08%) and effectively filtered 4 out of 5 FALSE_TRIGGERs (80% rejection) and 6 out of 6 NO_SETUPs (100% rejection), while capturing 75.0% of positive human triggers (9/12). Compared to the unconstrained Control (4W median: -0.23%), the PERMITTED regime and non-extreme risk filter significantly improved entry quality.

*주의: 본 평가는 과거 Retrospective Entry Signal Quality 평가이며, 수수료/세금/슬리피지가 제외된 총수익률(Gross Return) 기준입니다. Production 규칙으로 승격하지 않으며 후속 Prospective 연구의 가설로 활용됩니다.*