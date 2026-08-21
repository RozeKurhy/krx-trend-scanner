# Pattern A FAST Core V02 Re-Entry Deep Loss Tail Analysis

================================================================================
1. Executive Overview
================================================================================
- Total Re-Entry Trades: **232건**
- Return <= -20% Trades: **14건 (6.03%)**
- Return <= -30% Trades: **4건 (1.72%)**

================================================================================
2. Re-Entry <= -30% Extreme Loss Cases (4건 전수 구조적 사실 및 해석)
================================================================================

### [011170_02] 롯데케미칼 (011170) - Sequence 2

**[Structural Facts]**
- Previous Exit: `LOSS_GUARD_CLOSE_LE_NEG_15` (Execution Date: `2018-05-31`)
- Entry: Signal `2020-11-13` -> Execution `2020-11-16` (Open Price: `256,700`원)
- Entry Context: Stage `TRANSITION`, Daily Risk `NORMAL`, Score State `READY`
- Lifecycle: `SKIPPED_EARLY_TREND_HANDOFF` (First PROGRESSED: `2021-05-31`, Effective Trading Date: `2021-05-31`)
- Loss Guard Triggered: `False`
- Exit Outcome: Type `NO_EXIT_BEFORE_CUTOFF`, Signal Date `nan`, Exec Date `nan`, Exec Price `nan`, Status `OPEN_AT_CUTOFF`
- Performance: Terminal Return **`-77.72%`**, MFE `+25.42%`, MAE `-79.82%`, Giveback `103.14%`, Holding `281.8`주

**[RESEARCH_INTERPRETATION]**
- **Primary Cause**: `OPEN_AT_CUTOFF_STRUCTURAL_TAIL`
- **Secondary Flags**: `COVERAGE_STRUCTURAL_TAIL`
- **Analysis**: 포지션이 Cutoff 시점까지 청산 조건을 충족하지 못하고 장기 보유되어 평가손실이 누적된 구조적 테일 (Coverage 경로 상 Exit 3 미적용 및 점수 하락 급락 미발생으로 인한 미청산)

### [000670_02] 영풍 (000670) - Sequence 2

**[Structural Facts]**
- Previous Exit: `LOSS_GUARD_CLOSE_LE_NEG_15` (Execution Date: `2026-01-05`)
- Entry: Signal `2026-01-30` -> Execution `2026-02-02` (Open Price: `59,700`원)
- Entry Context: Stage `EARLY_TREND`, Daily Risk `NORMAL`, Score State `READY`
- Lifecycle: `NORMAL_EARLY_TREND_HANDOFF` (First PROGRESSED: `2026-02-28`, Effective Trading Date: `2026-02-27`)
- Loss Guard Triggered: `False`
- Exit Outcome: Type `EXIT3_PROGRESSED_TO_WEAK`, Signal Date `2026-07-31`, Exec Date `2026-08-03`, Exec Price `32450.0`, Status `REALIZED`
- Performance: Terminal Return **`-45.64%`**, MFE `+18.93%`, MAE `-48.07%`, Giveback `64.57%`, Holding `24.4`주

**[RESEARCH_INTERPRETATION]**
- **Primary Cause**: `POST_PROGRESSED_EXIT3_LAG`
- **Secondary Flags**: `NONE`
- **Analysis**: PROGRESSED 도달 후 주가가 하락하였으나 월봉 국면이 WEAK/BASE/TRANSITION 등으로 전환될 때까지 지연 청산되어 발생한 손실

### [200670_03] 휴메딕스 (200670) - Sequence 3

**[Structural Facts]**
- Previous Exit: `LOSS_GUARD_CLOSE_LE_NEG_15` (Execution Date: `2025-01-24`)
- Entry: Signal `2025-05-23` -> Execution `2025-05-26` (Open Price: `54,100`원)
- Entry Context: Stage `EARLY_TREND`, Daily Risk `NORMAL`, Score State `PARTIAL`
- Lifecycle: `NORMAL_EARLY_TREND_HANDOFF` (First PROGRESSED: `2025-08-31`, Effective Trading Date: `2025-08-29`)
- Loss Guard Triggered: `False`
- Exit Outcome: Type `EXIT3_PROGRESSED_TO_WEAK`, Signal Date `2026-03-31`, Exec Date `2026-04-01`, Exec Price `34350.0`, Status `REALIZED`
- Performance: Terminal Return **`-36.51%`**, MFE `+42.7%`, MAE `-38.45%`, Giveback `79.21%`, Holding `41.6`주

**[RESEARCH_INTERPRETATION]**
- **Primary Cause**: `POST_PROGRESSED_EXIT3_LAG`
- **Secondary Flags**: `NONE`
- **Analysis**: PROGRESSED 도달 후 주가가 하락하였으나 월봉 국면이 WEAK/BASE/TRANSITION 등으로 전환될 때까지 지연 청산되어 발생한 손실

### [298380_02] 에이비엘바이오 (298380) - Sequence 2

**[Structural Facts]**
- Previous Exit: `LOSS_GUARD_CLOSE_LE_NEG_15` (Execution Date: `2024-09-06`)
- Entry: Signal `2024-10-11` -> Execution `2024-10-14` (Open Price: `40,050`원)
- Entry Context: Stage `EARLY_TREND`, Daily Risk `NORMAL`, Score State `PARTIAL`
- Lifecycle: `NORMAL_EARLY_TREND_HANDOFF` (First PROGRESSED: `2024-10-31`, Effective Trading Date: `2024-10-31`)
- Loss Guard Triggered: `False`
- Exit Outcome: Type `EXIT4_SCORE_DRAWDOWN_GE_15`, Signal Date `2024-11-30`, Exec Date `2024-12-02`, Exec Price `27500.0`, Status `REALIZED`
- Performance: Terminal Return **`-31.34%`**, MFE `+8.11%`, MAE `-35.21%`, Giveback `39.45%`, Holding `7.2`주

**[RESEARCH_INTERPRETATION]**
- **Primary Cause**: `POST_PROGRESSED_EXIT4_TAIL`
- **Secondary Flags**: `NONE`
- **Analysis**: PROGRESSED 점수 HWM 대비 15pt 하락 청산 시 월간 급락으로 인해 큰 실현손실이 발생한 테일

================================================================================
3. Re-Entry <= -20% Summary Statistics (14건 종합)
================================================================================

| Ticker | 종목명 | Trade ID | Seq | Previous Exit | Lifecycle | Exit Type | Status | Return | Primary Cause |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---|
| `011170` | 롯데케미칼 | `011170_02` | 2 | `LOSS_GUARD_CLOSE_LE_NEG_15` | `SKIPPED_EARLY_TREND_HANDOFF` | `NO_EXIT_BEFORE_CUTOFF` | `OPEN_AT_CUTOFF` | **-77.72%** | `OPEN_AT_CUTOFF_STRUCTURAL_TAIL` |
| `000670` | 영풍 | `000670_02` | 2 | `LOSS_GUARD_CLOSE_LE_NEG_15` | `NORMAL_EARLY_TREND_HANDOFF` | `EXIT3_PROGRESSED_TO_WEAK` | `REALIZED` | **-45.64%** | `POST_PROGRESSED_EXIT3_LAG` |
| `200670` | 휴메딕스 | `200670_03` | 3 | `LOSS_GUARD_CLOSE_LE_NEG_15` | `NORMAL_EARLY_TREND_HANDOFF` | `EXIT3_PROGRESSED_TO_WEAK` | `REALIZED` | **-36.51%** | `POST_PROGRESSED_EXIT3_LAG` |
| `298380` | 에이비엘바이오 | `298380_02` | 2 | `LOSS_GUARD_CLOSE_LE_NEG_15` | `NORMAL_EARLY_TREND_HANDOFF` | `EXIT4_SCORE_DRAWDOWN_GE_15` | `REALIZED` | **-31.34%** | `POST_PROGRESSED_EXIT4_TAIL` |
| `264660` | 씨앤지하이테크 | `264660_02` | 2 | `LOSS_GUARD_CLOSE_LE_NEG_15` | `NORMAL_EARLY_TREND_HANDOFF` | `EXIT3_PROGRESSED_TO_TRANSITION` | `REALIZED` | **-29.8%** | `POST_PROGRESSED_EXIT3_LAG` |
| `004020` | 현대제철 | `004020_02` | 2 | `LOSS_GUARD_CLOSE_LE_NEG_15` | `PROGRESSED_WITHOUT_DIRECT_HANDOFF` | `EXIT4_SCORE_DRAWDOWN_GE_15` | `REALIZED` | **-26.44%** | `POST_PROGRESSED_EXIT4_TAIL` |
| `034220` | LG디스플레이 | `034220_02` | 2 | `EXIT4_SCORE_DRAWDOWN_GE_15` | `NORMAL_EARLY_TREND_HANDOFF` | `EXIT3_PROGRESSED_TO_WEAK` | `REALIZED` | **-24.64%** | `POST_PROGRESSED_EXIT3_LAG` |
| `011070` | LG이노텍 | `011070_02` | 2 | `EXIT4_SCORE_DRAWDOWN_GE_15` | `NORMAL_EARLY_TREND_HANDOFF` | `LOSS_GUARD_CLOSE_LE_NEG_15` | `REALIZED` | **-21.35%** | `LOSS_GUARD_REALIZED_DEEP_LOSS` |
| `000210` | DL | `000210_03` | 3 | `LOSS_GUARD_CLOSE_LE_NEG_15` | `PROGRESSED_WITHOUT_DIRECT_HANDOFF` | `LOSS_GUARD_CLOSE_LE_NEG_15` | `REALIZED` | **-21.2%** | `LOSS_GUARD_REALIZED_DEEP_LOSS` |
| `263750` | 펄어비스 | `263750_02` | 2 | `LOSS_GUARD_CLOSE_LE_NEG_15` | `NORMAL_EARLY_TREND_HANDOFF` | `EXIT3_PROGRESSED_TO_WEAK` | `REALIZED` | **-21.09%** | `POST_PROGRESSED_EXIT3_LAG` |
| `003230` | 삼양식품 | `003230_02` | 2 | `LOSS_GUARD_CLOSE_LE_NEG_15` | `NORMAL_EARLY_TREND_HANDOFF` | `LOSS_GUARD_CLOSE_LE_NEG_15` | `REALIZED` | **-20.77%** | `LOSS_GUARD_REALIZED_DEEP_LOSS` |
| `074600` | 원익QnC | `074600_02` | 2 | `LOSS_GUARD_CLOSE_LE_NEG_15` | `NORMAL_EARLY_TREND_HANDOFF` | `EXIT3_PROGRESSED_TO_BASE` | `REALIZED` | **-20.59%** | `POST_PROGRESSED_EXIT3_LAG` |
| `008930` | 한미사이언스 | `008930_02` | 2 | `LOSS_GUARD_CLOSE_LE_NEG_15` | `NEVER_PROGRESSED` | `LOSS_GUARD_CLOSE_LE_NEG_15` | `REALIZED` | **-20.57%** | `LOSS_GUARD_REALIZED_DEEP_LOSS` |
| `203650` | 드림시큐리티 | `203650_02` | 2 | `LOSS_GUARD_CLOSE_LE_NEG_15` | `NEVER_PROGRESSED` | `LOSS_GUARD_CLOSE_LE_NEG_15` | `REALIZED` | **-20.04%** | `LOSS_GUARD_REALIZED_DEEP_LOSS` |