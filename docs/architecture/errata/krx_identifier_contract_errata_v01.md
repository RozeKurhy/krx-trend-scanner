krx_identifier_contract_errata_v01.md

================================================================================
KRX_IDENTIFIER_CONTRACT_ERRATA_V01
================================================================================

목적
----
2018-04-27 KRX Open API live whole-response census에서 Daily `ISU_CD`와 Basic
Info `ISU_SRT_CD`가 숫자만이 아닌 `03473K`, `08537M` 형태를 포함함을 확인했다.
기존 CLOSED architecture를 다시 쓰지 않고, 실제 source identifier 의미만
ERRATA overlay로 교정한다.

검증된 계약
----------
- namespace: `KRX_SHORT_CODE`
- shape: exactly six uppercase ASCII alphanumeric characters
- regex: `^[0-9A-Z]{6}$`
- Daily Trading `ISU_CD` -> `raw.ticker`
- Basic Info `ISU_SRT_CD` -> `master.ticker`
- InstrumentClassification ticker는 StockMaster의 동일 namespace를 상속한다.
- `ISU_CD` (Basic Info)는 계속 `KRX_STANDARD_CODE`다.

경계
----
- Raw KRX authority는 source code를 그대로 보존한다. suffix 제거, 숫자 변환,
  대문자 자동 변환, row drop을 하지 않는다.
- `AdjustedPriceProvider`와 숫자 전용 downstream consumer는 이번 ERRATA에서
  자동 확장하지 않는다. raw whole-market completeness와 strategy eligibility는
  별도 계층이다.
- 기존 `KRX_PRODUCTION_DATA_ARCHITECTURE_V01` CLOSED artifacts/history는
  변경하지 않는다. 이 문서와 `artifacts/.../errata/`가 correction overlay다.

증거
----
- 날짜: 2018-04-27
- Daily: KOSPI 892건(숫자 883, 영문 포함 9), KOSDAQ 1,272건(숫자 1,271,
  영문 포함 1), invalid length/charset 0.
- Basic Info: Daily와 동일한 892/1,272건 shape이며 `03473K`=`SK우`,
  `08537M`=`루트로닉3우C`가 `ISU_SRT_CD`에 존재한다.
- 전체 census와 corrected diagnostic은 raw full response를 artifact에 저장하지
  않고 bounded summary만 남긴다.

후속 단계
--------
이번 작업은 corrected 2018-04-27 diagnostic까지만 수행한다. 3-date pilot,
Samsung two-date evidence, full historical backfill은 Architect 승인 후
`KRX_HISTORICAL_BACKFILL_V01_FIX06`에서 진행한다.
