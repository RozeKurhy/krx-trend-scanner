KRX_OPEN_API_V02_VALIDATION.md
================================================================================
KRX Open API V02 validation boundary
================================================================================

목적
--------------------------------------------------------------------------------
V02는 신규 승인 KRX Open API 3개를 live evidence로 검증하는 단계다.
검증 대상은 endpoint/request contract, schema, endpoint별 identifier semantic,
종목기본정보의 PIT snapshot, PARVAL/LIST_SHRS 후보 신호, KRX index inventory와
Sector RS source readiness다.

검증 대상 API
--------------------------------------------------------------------------------
| API ID              | Endpoint                 | 역할                  |
|---------------------|--------------------------|-----------------------|
| krx_dd_trd          | /idx/krx_dd_trd          | KRX 지수 시리즈 일별  |
| stk_isu_base_info   | /sto/stk_isu_base_info  | KOSPI 종목기본정보    |
| ksq_isu_base_info   | /sto/ksq_isu_base_info  | KOSDAQ 종목기본정보   |

공통 transport 계약은 GET, AUTH_KEY header, basDd(YYYYMMDD), OutBlock_1로
검증하되 실제 live response를 authority로 삼는다.

동결 범위
--------------------------------------------------------------------------------
다음은 변경하지 않는다.

- PyKrxDataProvider, MarketDataRepository, ParquetCache
- IndexPriceDataProvider production semantics
- Pattern A, FastCore, Julia, Foreign Flow
- Relative Strength 계산식 및 기존 sector mapping
- production provider 연결, historical full backfill, corporate-action detector

실행 경계
--------------------------------------------------------------------------------
scripts/validate_krx_open_api_v02.py는 production import path와 분리된 bounded
validator다. LocalKrxOpenApiQuota를 재사용하고 전체 HTTP attempt는 40회 이내로
제한한다. 401/403/429는 재시도하지 않고 차단 상태를 남긴다. raw sample에는
응답 payload만 저장하며 AUTH_KEY는 절대 저장하지 않는다.

해석 원칙
--------------------------------------------------------------------------------
일별매매정보의 ISU_CD는 V01 evidence 기준 6자리 단축코드다. 종목기본정보의
ISU_CD는 표준코드, ISU_SRT_CD는 단축코드로 endpoint-specific semantic을
유지한다. SECT_TP_NM은 소속부로 취급하며 업종 RS mapping에 사용하지 않는다.
PARVAL/LIST_SHRS는 corporate-action dirty candidate signal이지 완전한 oracle이
아니다. Sector RS 계산은 변경하지 않고, KRX series full mapping은 다음 단계로
분리한다.
