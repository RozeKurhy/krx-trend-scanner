krx_open_api_validation_v01.md
==================================================
KRX Open API Validation v0.1
==================================================

목적
--------------------------------------------------
이번 작업은 production provider migration이 아니라 KRX Open API가 기존
공식 market metadata와 수정주가 의미를 대체할 수 있는지 확인하기 위한
bounded validation이다. PyKRX, Pattern, FAST, Julia, Investability와 기존
Golden/Performance artifact는 변경하지 않았다.

실행 기준
--------------------------------------------------
- START HEAD: b73ae96a6a30f1211a045fedae7688973adb195f
- 기준일: 2026-08-14 (로컬 trading calendar의 max_observed_trading_date)
- 인증 로더: repo root `.env`, `load_dotenv(..., override=True)`
- AUTH_KEY 값은 출력·artifact·문서에 저장하지 않음
- 호출 수: 서비스별 기준일 1회, 총 4회(401은 재시도하지 않음)

공식 서비스 manifest
--------------------------------------------------
+----------------------+----------------+-----------------------------------------------+
| service              | API ID         | endpoint                                      |
+----------------------+----------------+-----------------------------------------------+
| KOSPI stock daily    | stk_bydd_trd   | /svc/apis/sto/stk_bydd_trd                    |
| KOSDAQ stock daily   | ksq_bydd_trd   | /svc/apis/sto/ksq_bydd_trd                    |
| KOSPI index daily    | kospi_dd_trd   | /svc/apis/idx/kospi_dd_trd                    |
| KOSDAQ index daily   | kosdaq_dd_trd  | /svc/apis/idx/kosdaq_dd_trd                   |
+----------------------+----------------+-----------------------------------------------+
호스트는 `https://data-dbg.krx.co.kr`이며 query parameter는 `basDd`이다.

실행 결과
--------------------------------------------------
모든 공식 endpoint가 HTTP 401, `respCode=401`, `respMsg=Unauthorized API Call`
을 반환했다. 로컬 dotenv 로더는 통과하여 `AUTH_KEY_PRESENT=true`였지만,
인증된 stock/index row가 하나도 반환되지 않았다. 따라서 실제 response schema,
market-cap/listed-shares/trading-value parity, corporate-action 조정 의미,
지수 parity와 휴장일 응답은 결론을 내리지 않았다.

판정
--------------------------------------------------
- AUTH_KEY_PRESENT: true
- AUTH_KEY_EXPOSED: false
- stock/index API callable: BLOCKED_API_ACCESS_OR_SERVICE_APPROVAL
- actual response schema frozen: no (401 error schema만 관찰)
- adjusted price classification: INCONCLUSIVE
- recommended architecture: DO_NOT_MIGRATE_YET
- final status: BLOCKED_API_ACCESS_OR_SERVICE_APPROVAL

생성 산출물
--------------------------------------------------
- `artifacts/data_providers/krx_open_api/validation_v01/request_manifest.json`
- `artifacts/data_providers/krx_open_api/validation_v01/connectivity_summary.json`
- `artifacts/data_providers/krx_open_api/validation_v01/response_schema.json`
- `artifacts/data_providers/krx_open_api/validation_v01/market_field_parity.csv`
- `artifacts/data_providers/krx_open_api/validation_v01/corporate_action_cases.csv`
- `artifacts/data_providers/krx_open_api/validation_v01/adjusted_price_equivalence.csv`
- `artifacts/data_providers/krx_open_api/validation_v01/index_validation.csv`
- `artifacts/data_providers/krx_open_api/validation_v01/validation_summary.json`

다음 조치
--------------------------------------------------
KRX Open API 포털에서 해당 key의 API 사용 신청/서비스별 승인 상태를 확인한
뒤, 승인된 key로 동일한 bounded validation을 재실행해야 한다. 승인 전에는
provider 설계·PyKRX 제거·대량 수집·README/Roadmap 변경을 진행하지 않는다.
