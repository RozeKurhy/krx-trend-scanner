krx_historical_backfill_recommendation.md

FIX06 상태: BLOCKED_KRX_TRANSPORT

백필은 2299개 COMPLETE 날짜와 131개 확정 NO_DATA 날짜에서 중단됐고, 1개 FAILED partition이 남아 있다. 원인: 2019-04-26 KOSDAQ transport timeout.

PyKRX/KRX 신규 요청은 이 오프라인 검증에서 수행하지 않았다. transport 오류는 재시도하지 않고 blocker로 보존한다.
