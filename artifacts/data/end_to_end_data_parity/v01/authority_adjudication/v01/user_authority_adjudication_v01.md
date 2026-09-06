# user_authority_adjudication_v01.md

USER_AUTHORITY_ADJUDICATION_FROZEN=true
APPROVED_BY=user
STATUS=FROZEN

DECISION_1 Pattern A = ACCEPT_CANONICAL_V2_BEHAVIOR
DECISION_2 FastCore = ACCEPT_CANONICAL_V2_BEHAVIOR
DECISION_3 Julia = ACCEPT_CANONICAL_V2_BEHAVIOR
DECISION_4 ETF = REPOSITORY_V2_ETF_SUPPORT_EXTENSION

구현 의미: 모든 consumer는 MarketDataRepositoryV2 canonical input을 사용한다. ETF는 COMMON과 같은 Repository V2 interface에서 공식 adjusted/raw authority를 사용한다.
금지: legacy fallback, PyKRX, KRX HTML scraping, Naver raw fallback, 수동 주입, ticker-specific/consumer-specific override.
