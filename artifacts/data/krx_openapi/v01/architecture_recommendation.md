architecture_recommendation.md
================================================================================
KRX Open API V01 architecture recommendation
================================================================================

RECOMMENDATION: RECOMMEND_DUAL_PROVIDER

KRX endpoints are date-scoped market-wide snapshots; production ticker×date loops are prohibited.
Samsung split price classification: RAW_UNADJUSTED.
Existing PyKRX adjusted=True remains frozen for long-term chart semantics.
Raw parity uses PyKRX adjusted=False; adjusted parity is secondary and separate.
Production provider/cache replacement: NOT PERFORMED.
