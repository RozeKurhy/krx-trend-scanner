# battle_c_kospi_only — Pattern B E/T PROGRESSED Candidate V1

동결된 Pattern B 신호·청산 원장을 사용하고 chronological cash-aware portfolio replay를 새로 수행했어.
- 공통 진입 순서: `ticker, exact ISU_CD, entry_signal_date, entry_execution_date`.
- worker: 10.
- valuation carry는 exact same-date KRX NON_TRADING_PLACEHOLDER_V01, exact PIT identity 안의 이전 정상 조정 종가에만 valuation-only로 적용했어.
- Battle C는 entry identity의 exact entry-date PIT market이 KOSPI인 후보만 포함했고 시총 필터는 적용하지 않았어.

| Window | Return | CAGR | MDD / type | Coverage | Eligible | Executed / closed | Cash skip % | Median | +50 / +100 | Turnover |
|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|
| P1 | 43.02165836459084 | 2.866792199307633 | -10.58812334188326 / EXACT | 100.0 | 164 | 164 / 156 | 0.0 | 9.878373455442194 | 10 / 2 | 1691312185.4570003 |
| P2-1 | 13.984291682941574 | 3.0196626058259124 | -10.65509953760817 / EXACT | 100.0 | 70 | 70 / 62 | 0.0 | 12.45258428085819 | 5 / 0 | 704807160.78 |
| P2-2 | 23.21829358366916 | 3.7619945847024994 | -10.65509953760817 / EXACT | 100.0 | 101 | 101 / 93 | 0.0 | 10.921058468132298 | 6 / 0 | 1023324304.4129999 |
| P3-1 | 14.410367436894944 | 4.035076528081172 | -8.637226640578156 / EXACT | 100.0 | 58 | 58 / 52 | 0.0 | 14.440875541558613 | 5 / 0 | 588500308.0680001 |
| P3-2 | 23.93843332506802 | 4.716184794116196 | -8.637226640578156 / EXACT | 100.0 | 89 | 89 / 82 | 0.0 | 11.88647181721102 | 6 / 0 | 905724685.7609999 |

이 문서는 양 전략 정면 비교용 포트폴리오 결과이며, 단독 채택 판정 문서가 아니야.
