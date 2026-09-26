# P2-1 Raw Daily MKTCAP Source Correction Preflight

작성일: 2026-09-26 KST  
판정: `P2_1_RAW_DAILY_MCAP_PREFLIGHT_PASS`

## 범위와 원천

P2-1 시총 preflight만 수행했고 전체 포트폴리오 리플레이 및 네트워크 호출은 하지 않았다. PIT 시총은 로컬 `data/market/raw/krx_stocks/v01`의 production `KrxRawStockStore.load_snapshot`으로 exact `entry_signal_date` partition에서 직접 읽었다. 원천은 KRX Open API Stock Daily의 `MKTCAP`, 저장 필드는 `market_cap`이다. Julia legacy market-cap 값, proxy, 현재·미래·인접일 대체는 사용하지 않았다.

## 대상 및 조회 결과

- 원본 P2-1 matched pair: 1,801; 기존 lifecycle 생존 overlay 적용 후 1,743 pair / 1,129 identity. 제외 58 pair.
- exact raw market-cap 조회: 1,743/1,743; 1조원 이상 330, 미만 1,413, unresolved 0.
- unresolved reason: `{}`.
- 고유 signal date 211개; exact raw partition hash 검증일 211개; 모든 ticker의 mcap까지 완전 해소된 날짜 211개.

## Closure 증적과 live manifest

FIX09 closure 증적은 `PASS` (`2010-01-04..2026-08-21`, missing 0, failed 0, partial 0)다. 해당 기간의 현재 SQLite manifest partition 수·상태·연도별 행수는 증적과 정확히 일치했고, manifest SHA-256도 조회 전후 동일했다. Live manifest는 증적 대상보다 더 최신인 `2026-09-21`까지 KOSPI/KOSDAQ 각각 21개 COMPLETE partition을 추가 보유하며, 이 추가분은 closure 대상 밖의 정상적인 coverage 확장이다.

## 이전 117/94 결과의 출처

레거시 시총 값은 조회하지 않고 기준일 metadata만 출처 대조에 사용했다. available manifest 117일 중 생존 신호일과 겹치는 날은 111일이고, 분기 grid 22일 중 manifest에 없는 10일 가운데 6일이 추가로 생존 신호일과 겹친다. 따라서 manifest·분기 grid 합집합 127일 중 신호일 117일이 커버되고 94일이 빠져 기존 `211 - 94 = 117`이 재현된다. 즉 이전 94건은 raw daily store의 결측이 아니라 **legacy manifest와 분기 grid 조합의 날짜 한계**였다. 이 비교는 날짜 출처 설명만을 위한 것이며 이번 PIT 시총 값 판정에는 두 legacy source 모두 사용하지 않았다.

## 다음 단계

raw daily PIT coverage preflight는 통과했다. 별도 지시된 P2-1 realistic full portfolio run을 10 workers로 진행할 수 있지만, 이번 작업에서는 시작하지 않았다.
