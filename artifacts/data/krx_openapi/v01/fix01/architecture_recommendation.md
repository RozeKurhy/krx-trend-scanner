architecture_recommendation.md
================================================================================
KRX Open API V01 FIX01 architecture recommendation
================================================================================

RECOMMEND_DUAL_PROVIDER

KRX Open API = raw market/index authority.
PyKRX adjusted=True = adjusted OHLC authority only.
Do not compare both providers for every ticker every day.
LIST_SHRS is a strong dirty trigger, not a complete corporate-action oracle.
Corporate-action dirty ticker only → PyKRX adjusted=True refresh → adjusted cache rebuild.
Production migration is not performed in FIX01.
