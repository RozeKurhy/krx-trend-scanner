corporate_action_dirty_refresh_recommendation.md

======================================================================
Corporate Action Dirty Refresh V01 Recommendation
======================================================================

STATUS: READY_FOR_ARCHITECT_CORPORATE_ACTION_DIRTY_REFRESH_V01_REVIEW
RECOMMENDATION: RECOMMEND_PROCEED_TO_KRX_HISTORICAL_BACKFILL_V01

Detector는 refresh 필요성만 판단하고 event type이나 OHLC adjustment를 수행하지 않는다.
runtime SQLite와 validation parquet는 commit하지 않았다.
