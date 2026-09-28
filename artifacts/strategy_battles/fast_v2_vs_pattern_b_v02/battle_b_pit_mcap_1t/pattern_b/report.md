# battle_b_pit_mcap_1t — Pattern B E/T PROGRESSED Candidate V1

동결된 Pattern B 신호·청산 원장을 사용하고 chronological cash-aware portfolio replay를 새로 수행했어.
- 공통 진입 순서: `ticker, exact ISU_CD, entry_signal_date, entry_execution_date`.
- worker: 10.
- valuation carry는 exact same-date KRX NON_TRADING_PLACEHOLDER_V01, exact PIT identity 안의 이전 정상 조정 종가에만 valuation-only로 적용했어.
- Battle B만 entry_signal_date exact PIT 시총 1조원 이상을 포함했어.

| Window | Return | CAGR | MDD / type | Coverage | Eligible | Executed / closed | Cash skip % | Median | +50 / +100 | Turnover |
|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|
| P1 | 8.18350526685161 | 0.6232598858672667 | -3.612873365227043 / EXACT | 100.0 | 33 | 33 / 30 | 0.0 | 12.234214424350693 | 2 / 1 | 332271815.31200004 |
| P2-1 | 2.4964890864881184 | 0.5620255988835865 | -3.2665242434083863 / EXACT | 100.0 | 12 | 12 / 10 | 0.0 | 5.842019013453177 | 2 / 1 | 120729153.492 |
| P2-2 | 7.344953706690882 | 1.2615446662099572 | -3.6418961950266393 / EXACT | 100.0 | 26 | 26 / 23 | 0.0 | 13.310514376175975 | 2 / 1 | 261223884.122 |
| P3-1 | 4.5843884661197265 | 1.3258487511665917 | -1.746728287596666 / EXACT | 100.0 | 9 | 9 / 8 | 0.0 | 8.022407585136584 | 2 / 1 | 96069191.737 |
| P3-2 | 9.311222073768 | 1.930076802157199 | -3.5745639480716074 / EXACT | 100.0 | 23 | 23 / 20 | 0.0 | 16.232403011022544 | 2 / 1 | 235271156.42700002 |

이 문서는 양 전략 정면 비교용 포트폴리오 결과이며, 단독 채택 판정 문서가 아니야.
