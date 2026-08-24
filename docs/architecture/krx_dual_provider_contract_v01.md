krx_dual_provider_contract_v01.md
==================================================
KRX Dual Provider Contract v0.1
==================================================

목적
--------------------------------------------------
이 문서는 KRX Open API V01 검증 결과를 다음 production architecture 단계에
넘기기 위한 역할 분리 계약이다. FIX01에서는 production provider 연결, cache
재생성, Pattern/RS/backtest 재실행을 하지 않는다.

원천 역할
--------------------------------------------------
+-------------------------+----------------------------------------------+
| 원천                    | 책임                                         |
+-------------------------+----------------------------------------------+
| KRX Open API            | raw OHLC, volume, trading_value, market_cap, |
|                         | listed_shares, market index                  |
| PyKRX adjusted=True     | adjusted historical OHLC                    |
+-------------------------+----------------------------------------------+

두 원천을 매일 전 종목에 대해 서로 비교하지 않는다. KRX는 일자별 시장 전체
snapshot이므로 ticker x date 요청 루프를 production에 만들지 않는다.

수정주가 안전 계약
--------------------------------------------------
- KRX Open API stock OHLC는 FIX01 실측상 RAW_UNADJUSTED다.
- 장기 차트·기술적 분석의 adjusted OHLC authority는 PyKRX adjusted=True다.
- 향후 별도 AdjustedPriceProvider는 adjusted OHLC만 반환한다.
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

향후 workflow:

KRX daily snapshot
        ↓
LIST_SHRS / corporate-action detector
        ↓
dirty ticker only
        ↓
PyKRX adjusted=True history refresh
        ↓
Adjusted Price Cache rebuild
        ↓
ADJUSTMENT_CLEAN

평소 corporate action이 없는 날에는 adjusted refresh가 0 requests일 수 있다.
기존 Pattern A의 adjusted OHLC + raw volume + raw trading_value 정책은 FIX01에서
변경하지 않는다.

Quota 원칙
--------------------------------------------------
Local SQLite quota counter는 공식 KRX 사용량 API의 대체가 아니다. 실제 HTTP
attempt를 opener 호출 직전에 KST 날짜별로 예약하고, timeout/URLError/retry도
사용량으로 계산한다. endpoint별 visible limit과 local global safety limit은
서로 다른 개념이며, 두 limit의 공식 의미를 단정하지 않는다.

Production migration 상태
--------------------------------------------------
NOT CONNECTED IN FIX01
