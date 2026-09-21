# KRX 이중 데이터 제공자 계약 (KRX Dual Provider Contract v0.1)

목적
--------------------------------------------------
이 문서는 KRX Open API V01 검증 결과를 다음 운영 아키텍처 단계에
넘기기 위한 역할 분리 계약이다. FIX01에서는 운영 데이터 제공자 연결, cache
재생성, Pattern/RS/backtest 재실행을 하지 않는다.

원천 역할
--------------------------------------------------
| 원천 | 책임 |
|---|---|
| KRX Open API | raw OHLC, volume, trading_value, market_cap, listed_shares, market index |
| PyKRX `adjusted=True` | 수정주가 과거 OHLC |

두 원천을 매일 전 종목에 대해 서로 비교하지 않는다. KRX는 일자별 시장 전체
스냅샷이므로 ticker x date 요청 루프를 운영에 만들지 않는다.

수정주가 안전 계약
--------------------------------------------------
- KRX Open API stock OHLC는 FIX01 실측상 RAW_UNADJUSTED다.
- 장기 차트·기술적 분석의 수정주가 OHLC 기준 원천은 PyKRX adjusted=True다.
- 향후 별도 AdjustedPriceProvider는 수정주가 OHLC만 반환한다.
- AdjustedPriceProvider는 PyKRX adjusted=False, KRX Open API, trading_value,
  volume, market/index fetching을 호출하지 않는다.
- 수정주가 갱신으로 KRX Open API quota를 소비하지 않는다.

Corporate-action refresh 계약
--------------------------------------------------
KRX daily snapshot의 LIST_SHRS 변화는 ADJUSTMENT_DIRTY 후보를 만드는 강한
primary trigger다. 다만 상장주식수 반영시점과 가격조정시점이 다를 수 있으므로
완전한 corporate-action oracle로 취급하지 않는다. 향후 secondary signal로
PARVAL 변화, 큰 설명불가 가격 단절, corporate-action metadata, relisting/merger
정보를 결합할 수 있다.

향후 작업 흐름:

KRX daily snapshot
        ↓
LIST_SHRS / corporate-action detector
        ↓
dirty ticker only
        ↓
PyKRX adjusted=True 수정주가 이력 갱신
        ↓
수정주가 캐시 재구축
        ↓
ADJUSTMENT_CLEAN

평소 corporate action이 없는 날에는 수정주가 갱신이 0 requests일 수 있다.
기존 Pattern A의 수정주가 OHLC + 원천 volume + 원천 trading_value 정책은 FIX01에서
변경하지 않는다.

Quota 원칙
--------------------------------------------------
Local SQLite quota counter는 공식 KRX 사용량 API의 대체가 아니다. 실제 HTTP
attempt를 opener 호출 직전에 KST 날짜별로 예약하고, timeout/URLError/retry도
사용량으로 계산한다. endpoint별 visible limit과 local global safety limit은
서로 다른 개념이며, 두 limit의 공식 의미를 단정하지 않는다.

운영 전환 상태
--------------------------------------------------
NOT CONNECTED IN FIX01

현재 기준 경계
--------------------------------------------------
위 표와 `NOT CONNECTED IN FIX01`은 V01 이중 제공자 설계·검증 단계의
과거 상태다. 당시 수정주가 OHLC 경계는 PyKRX `adjusted=True`였지만,
현재 수정주가 기준 원천은 `NaverDirectAdjustedPriceDataProvider`의 Naver
direct date-range (`requestType=1`)와 `AdjustedPriceStore V02`다. KRX raw
기준과 이 문서가 정의한 원천/수정주가 의미 분리는 유지하며, 위의 dirty
refresh 흐름은 V01 역사 기록으로 읽는다.
