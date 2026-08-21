# Pattern A FAST Trading Policy Entry v0.1 Preregistration

================================================================================
1. Protocol & Research Meta
================================================================================
- **Document Version**: `v0.1`
- **Status**: `PREREGISTERED_BEFORE_EVALUATION`
- **Research Classification**: `RESEARCH / EXPERIMENTAL / RETROSPECTIVE TRADING POLICY EVALUATION`
- **Base Commit**: `70de72418b26c2caaafdb4317d46e2668981932c`
- **Target Population**: `FROZEN_INVESTABLE_OOS_B_36`
- **Selection Manifest**: `artifacts/pattern_a_fast/investable_oos/pattern_a_fast_investable_oos_selection_manifest_v01.csv`
- **Selection Manifest SHA256**: `6fb59b9ffce5d8076a18faa00327c62e4edc5cff6ef93bcaf5095c50532ef825`
- **Sample Count**: `36`

--------------------------------------------------------------------------------
2. Research Core Question & Scope
--------------------------------------------------------------------------------
- **Core Question**:
  "Does the primary FAST common entry rule (TRIGGER + PERMITTED_REGIME + NON_EXTREME_DAILY_RISK) capture entry points with high forward upward potential across frozen Investable OOS B?"
- **Scope Limitations**:
  - This is an **ENTRY SIGNAL QUALITY EVALUATION ONLY**.
  - Exit policy, trailing stop, position sizing, and scaling-in rules are strictly **OUT OF SCOPE**.
  - Returns are reported as **Gross Signal Follow-up Returns** (no slippage, no commission, no tax).
  - No post-hoc rule changes, threshold tuning, or sample dropping permitted.

--------------------------------------------------------------------------------
3. Primary Entry Rule Specification
--------------------------------------------------------------------------------
A Primary Entry Event occurs on a completed weekly bar when all of the following conditions are simultaneously satisfied:

1. `fast_machine_stage == "TRIGGER"`
2. `fast_machine_stage_status == "READY"`
3. `fast_monthly_permission_state == "PERMITTED_REGIME"`
4. `fast_daily_risk_state IN {"NORMAL", "ELEVATED"}`
5. `fast_score_status IN {"READY", "PARTIAL"}`

### Entry Grade Classification:
- **Grade A**: `TRIGGER` + `PERMITTED_REGIME` + `NORMAL` Daily Risk
- **Grade B**: `TRIGGER` + `PERMITTED_REGIME` + `ELEVATED` Daily Risk

### Non-Qualifying Events (Disqualified from Primary Entry):
- Any other FAST stage (`WATCH`, `SETUP`, `TREND`, `EXTENDED`)
- Monthly regime in `EARLY_REGIME`, `LATE_OR_EXTENDED_REGIME`, or `UNAVAILABLE`
- Daily risk in `EXTREME` or `UNAVAILABLE`
- Stage or Score `UNAVAILABLE`

### Non-Gate Policy:
- **Numeric FAST Score**: Recorded for descriptive analysis only. **No score threshold** (e.g. >= 60, >= 70) is used as an entry filter.
- **Pattern A Score/Stage**: Recorded as diagnostic columns only. **No Pattern A gate** is applied.

--------------------------------------------------------------------------------
4. Execution & PIT Forward Evaluation Rules
--------------------------------------------------------------------------------
1. **Evaluation Start**: `completed_weekly_reference_date` (Prospective forward scan only; no retrospective backfill before reference date).
2. **Evaluation End**: Strictly capped at `outcome_review_end` (No evaluation beyond frozen review end).
3. **First Entry Principle**: Maximum 1 primary entry per sample (first qualifying event).
4. **Execution Price Contract**:
   - `signal_date`: Date of the qualifying completed weekly bar.
   - `execution_date`: The very next local trading day in daily OHLCV (`date > signal_date`).
   - `entry_price`: Exact **OPEN** price on `execution_date`.
   - Signal close or execution close fallbacks are strictly prohibited.
5. **Forward Horizons**:
   - **4 Weeks**: 4th completed weekly bar close after signal week.
   - **8 Weeks**: 8th completed weekly bar close after signal week.
   - **12 Weeks**: 12th completed weekly bar close after signal week.
   - **26 Weeks**: 26th completed weekly bar close after signal week.
   - If horizon completion date exceeds `outcome_review_end`, the return is set to `null` and status is marked `CENSORED`.
6. **MFE / MAE (Maximum Favorable / Adverse Excursion)**:
   - Evaluated using daily High / Low from `execution_date` to horizon end date relative to `entry_price` (Open).

--------------------------------------------------------------------------------
5. Integrity & Offline Execution Contract
--------------------------------------------------------------------------------
- **Network Requests**: `0` (Zero external network requests; local daily Parquet cache only).
- **Existing Contracts**: Phase 13 OOS seals, HIERARCHICAL_V01 Score/Stage contracts, and Pattern A evaluator remain completely untouched and immutable.
- **Retuning Allowed**: `False`.
