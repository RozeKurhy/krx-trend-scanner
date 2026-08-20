# Pattern A FAST Core V02 Re-Entry Deep Loss Tail Analysis

================================================================================
1. Executive Overview
================================================================================
- Total Re-Entry Trades: **232건**
- Return <= -20% Trades: **14건 (6.03%)**
- Return <= -30% Trades: **4건 (1.72%)**

================================================================================
2. Re-Entry <= -30% Extreme Loss Cases (4건 전수 상세)
================================================================================

### [011170_02] 롯데케미칼 (011170) - Sequence 2
- **Previous Exit**: `LOSS_GUARD_CLOSE_LE_NEG_15` (Exec Date: `2018-05-31`)
- **Entry**: Signal `2020-11-13` -> Execution `2020-11-16` (Open: `256,700`원)
- **Entry Context**: Stage `TRANSITION`, Daily Risk `NORMAL`, Score State `READY`
- **Lifecycle**: `SKIPPED_EARLY_TREND_HANDOFF` (First PROGRESSED: `2021-05-31`, Effective: `2021-05-31`)
- **Loss Guard Triggered**: `False`
- **Exit Outcome**: Type `NO_EXIT_BEFORE_CUTOFF`, Exec Date `nan`, Status `OPEN_AT_CUTOFF`
- **Performance**: **Terminal `-77.72%`**, MFE `+25.42%`, MAE `-79.82%`, Giveback `103.14%`, Holding `281.8`주
- **원인 분류 (`Cause Classification`)**: **`F. OPEN_AT_CUTOFF structural tail & D. PROGRESSED coverage hole`**
- **상세 원인 분석**: SKIPPED_EARLY_TREND_HANDOFF에서 PROGRESSED 도달 후 Exit4 15pt 하락 조건이 미충족되어 cutoff까지 미청산 보유된 구조적 테일 케이스 (Gap Loss 아님)

### [000670_02] 영풍 (000670) - Sequence 2
- **Previous Exit**: `LOSS_GUARD_CLOSE_LE_NEG_15` (Exec Date: `2026-01-05`)
- **Entry**: Signal `2026-01-30` -> Execution `2026-02-02` (Open: `59,700`원)
- **Entry Context**: Stage `EARLY_TREND`, Daily Risk `NORMAL`, Score State `READY`
- **Lifecycle**: `NORMAL_EARLY_TREND_HANDOFF` (First PROGRESSED: `2026-02-28`, Effective: `2026-02-27`)
- **Loss Guard Triggered**: `False`
- **Exit Outcome**: Type `EXIT3_PROGRESSED_TO_WEAK`, Exec Date `2026-08-03`, Status `REALIZED`
- **Performance**: **Terminal `-45.64%`**, MFE `+18.93%`, MAE `-48.07%`, Giveback `64.57%`, Holding `24.4`주
- **원인 분류 (`Cause Classification`)**: **`C. Post-PROGRESSED monthly lag decline / Exit3 lag`**
- **상세 원인 분석**: 2026-02-27 PROGRESSED 도달로 Loss Guard 비활성화된 후 월봉 국면이 WEAK로 전환될 때까지 지연되어 -45.64% 손실 기록

### [200670_03] 휴메딕스 (200670) - Sequence 3
- **Previous Exit**: `LOSS_GUARD_CLOSE_LE_NEG_15` (Exec Date: `2025-01-24`)
- **Entry**: Signal `2025-05-23` -> Execution `2025-05-26` (Open: `54,100`원)
- **Entry Context**: Stage `EARLY_TREND`, Daily Risk `NORMAL`, Score State `PARTIAL`
- **Lifecycle**: `NORMAL_EARLY_TREND_HANDOFF` (First PROGRESSED: `2025-08-31`, Effective: `2025-08-29`)
- **Loss Guard Triggered**: `False`
- **Exit Outcome**: Type `EXIT3_PROGRESSED_TO_WEAK`, Exec Date `2026-04-01`, Status `REALIZED`
- **Performance**: **Terminal `-36.51%`**, MFE `+42.7%`, MAE `-38.45%`, Giveback `79.21%`, Holding `41.6`주
- **원인 분류 (`Cause Classification`)**: **`E. Exit3 lag after MFE surge`**
- **상세 원인 분석**: MFE +42.70% 급등 후 되돌림 과정에서 월봉 WEAK 전환 지연으로 -36.51% 손실 기록

### [298380_02] 에이비엘바이오 (298380) - Sequence 2
- **Previous Exit**: `LOSS_GUARD_CLOSE_LE_NEG_15` (Exec Date: `2024-09-06`)
- **Entry**: Signal `2024-10-11` -> Execution `2024-10-14` (Open: `40,050`원)
- **Entry Context**: Stage `EARLY_TREND`, Daily Risk `NORMAL`, Score State `PARTIAL`
- **Lifecycle**: `NORMAL_EARLY_TREND_HANDOFF` (First PROGRESSED: `2024-10-31`, Effective: `2024-10-31`)
- **Loss Guard Triggered**: `False`
- **Exit Outcome**: Type `EXIT4_SCORE_DRAWDOWN_GE_15`, Exec Date `2024-12-02`, Status `REALIZED`
- **Performance**: **Terminal `-31.34%`**, MFE `+8.11%`, MAE `-35.21%`, Giveback `39.45%`, Holding `7.2`주
- **원인 분류 (`Cause Classification`)**: **`A. Gap Execution Tail / Sharp Monthly Drawdown`**
- **상세 원인 분석**: 급격한 월간 가격 하락으로 Score HWM 15pt drawdown 청산 시 -31.34% 기록

================================================================================
3. Re-Entry <= -20% Summary Statistics (14건 종합)
================================================================================

| Ticker | 종목명 | Trade ID | Seq | Previous Exit | Lifecycle | Exit Type | Status | Return | MAE | MFE |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `011170` | 롯데케미칼 | `011170_02` | 2 | `LOSS_GUARD_CLOSE_LE_NEG_15` | `SKIPPED_EARLY_TREND_HANDOFF` | `NO_EXIT_BEFORE_CUTOFF` | `OPEN_AT_CUTOFF` | **-77.72%** | -79.82% | +25.42% |
| `000670` | 영풍 | `000670_02` | 2 | `LOSS_GUARD_CLOSE_LE_NEG_15` | `NORMAL_EARLY_TREND_HANDOFF` | `EXIT3_PROGRESSED_TO_WEAK` | `REALIZED` | **-45.64%** | -48.07% | +18.93% |
| `200670` | 휴메딕스 | `200670_03` | 3 | `LOSS_GUARD_CLOSE_LE_NEG_15` | `NORMAL_EARLY_TREND_HANDOFF` | `EXIT3_PROGRESSED_TO_WEAK` | `REALIZED` | **-36.51%** | -38.45% | +42.7% |
| `298380` | 에이비엘바이오 | `298380_02` | 2 | `LOSS_GUARD_CLOSE_LE_NEG_15` | `NORMAL_EARLY_TREND_HANDOFF` | `EXIT4_SCORE_DRAWDOWN_GE_15` | `REALIZED` | **-31.34%** | -35.21% | +8.11% |
| `264660` | 씨앤지하이테크 | `264660_02` | 2 | `LOSS_GUARD_CLOSE_LE_NEG_15` | `NORMAL_EARLY_TREND_HANDOFF` | `EXIT3_PROGRESSED_TO_TRANSITION` | `REALIZED` | **-29.8%** | -42.67% | +51.92% |
| `004020` | 현대제철 | `004020_02` | 2 | `LOSS_GUARD_CLOSE_LE_NEG_15` | `PROGRESSED_WITHOUT_DIRECT_HANDOFF` | `EXIT4_SCORE_DRAWDOWN_GE_15` | `REALIZED` | **-26.44%** | -34.61% | +28.74% |
| `034220` | LG디스플레이 | `034220_02` | 2 | `EXIT4_SCORE_DRAWDOWN_GE_15` | `NORMAL_EARLY_TREND_HANDOFF` | `EXIT3_PROGRESSED_TO_WEAK` | `REALIZED` | **-24.64%** | -31.71% | +50.97% |
| `011070` | LG이노텍 | `011070_02` | 2 | `EXIT4_SCORE_DRAWDOWN_GE_15` | `NORMAL_EARLY_TREND_HANDOFF` | `LOSS_GUARD_CLOSE_LE_NEG_15` | `REALIZED` | **-21.35%** | -21.35% | +22.47% |
| `000210` | DL | `000210_03` | 3 | `LOSS_GUARD_CLOSE_LE_NEG_15` | `PROGRESSED_WITHOUT_DIRECT_HANDOFF` | `LOSS_GUARD_CLOSE_LE_NEG_15` | `REALIZED` | **-21.2%** | -22.48% | +32.82% |
| `263750` | 펄어비스 | `263750_02` | 2 | `LOSS_GUARD_CLOSE_LE_NEG_15` | `NORMAL_EARLY_TREND_HANDOFF` | `EXIT3_PROGRESSED_TO_WEAK` | `REALIZED` | **-21.09%** | -27.61% | +68.26% |
| `003230` | 삼양식품 | `003230_02` | 2 | `LOSS_GUARD_CLOSE_LE_NEG_15` | `NORMAL_EARLY_TREND_HANDOFF` | `LOSS_GUARD_CLOSE_LE_NEG_15` | `REALIZED` | **-20.77%** | -25.05% | +18.13% |
| `074600` | 원익QnC | `074600_02` | 2 | `LOSS_GUARD_CLOSE_LE_NEG_15` | `NORMAL_EARLY_TREND_HANDOFF` | `EXIT3_PROGRESSED_TO_BASE` | `REALIZED` | **-20.59%** | -34.64% | +48.37% |
| `008930` | 한미사이언스 | `008930_02` | 2 | `LOSS_GUARD_CLOSE_LE_NEG_15` | `NEVER_PROGRESSED` | `LOSS_GUARD_CLOSE_LE_NEG_15` | `REALIZED` | **-20.57%** | -25.98% | +17.71% |
| `203650` | 드림시큐리티 | `203650_02` | 2 | `LOSS_GUARD_CLOSE_LE_NEG_15` | `NEVER_PROGRESSED` | `LOSS_GUARD_CLOSE_LE_NEG_15` | `REALIZED` | **-20.04%** | -20.04% | +9.01% |