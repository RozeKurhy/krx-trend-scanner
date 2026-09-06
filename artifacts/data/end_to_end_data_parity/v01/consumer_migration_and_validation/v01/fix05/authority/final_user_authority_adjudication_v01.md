final_user_authority_adjudication_v01.md
========================================

USER_DECISION_REQUIRED=true
USER_DECISION_COUNT=3

TECHNICAL FIX FIRST
-------------------
COMMON technical-fix tickers=107640,176750,221800,303360,448900
canonical-vs-legacy options are not presented for these tickers until V2 coverage is repaired.

USER ADJUDICATION ITEMS
-----------------------
Pattern A: status=READY_FOR_USER_ADJUDICATION, behavior=279 tickers, technical_fix_first=4, policy_eligible=275
FastCore: status=READY_FOR_USER_ADJUDICATION, removed=2 trades (technical), matched_behavior=5 trades
Julia: status=READY_FOR_USER_ADJUDICATION, added=1 trade, matched_behavior=21 trades

VALID OPTIONS
--------------
ACCEPT_CANONICAL_V2_BEHAVIOR
RETAIN_FROZEN_LEGACY_BEHAVIOR

ETF ARCHITECTURE
----------------
17 ETF tickers remain ARCHITECTURE_DECISION_REQUIRED.
A. Repository V2 ETF support extension
B. ETF-specific canonical price path
C. explicit unsupported policy
