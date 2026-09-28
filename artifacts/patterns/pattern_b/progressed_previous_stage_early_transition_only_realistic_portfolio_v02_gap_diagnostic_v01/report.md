# Pattern B V02 valuation gap 진단 V01

- 기준 artifact commit: `b24779b41940ae83e170c7fae06aa230d286c434`
- 범위: 기존 V02 산출물과 exact KRX raw/PIT 자료의 사후 감사. 재백테스트·signal/evaluator·classifier 실행 없음.
- 판정 단위: 81 exact identity / 140 window×identity groups. 장기 gap은 artifact에서 `missing_days_max >= 100`으로 재계산.
- 비거래 placeholder 판정: 해당 일자 KRX raw exact row에서 `open=high=low=0`, `close>0`, `volume=trading_value=0`; 직전 adjusted close가 같은 PIT identity 내에 있을 때만 valuation-only carry candidate. 해당 후보는 승인 대기이며 체결/신호에 사용하지 않음.

## 분류 요약

- APPROVED_SUSPENSION_CARRY_CANDIDATE: 5 identity
- RAW_DATA_GAP: 49 identity
- CORPORATE_ACTION_OR_IDENTITY_BREAK: 8 identity
- SHORT_ISOLATED_GAP: 19 identity
- UNKNOWN: 0 identity

## 100일 이상 gap identity 13개

| ticker / ISU_CD | max missing days | gap date range | carry candidate distinct dates | raw-gap dates | PIT/delist boundary dates | class |
|---|---:|---|---:|---:|---:|---|
| 023430 / KR7023430002 | 2301 | 2017-03-30–2026-08-31 | 170 | 0 | 2131 | CORPORATE_ACTION_OR_IDENTITY_BREAK |
| 007630 / KR7007630007 | 1721 | 2019-03-22–2026-08-31 | 557 | 0 | 1164 | CORPORATE_ACTION_OR_IDENTITY_BREAK |
| 086250 / KR7086250008 | 1546 | 2020-05-04–2026-08-31 | 324 | 0 | 1222 | CORPORATE_ACTION_OR_IDENTITY_BREAK |
| 181340 / KR7181340001 | 1079 | 2022-03-24–2026-08-31 | 559 | 0 | 520 | CORPORATE_ACTION_OR_IDENTITY_BREAK |
| 174880 / KR7174880005 | 833 | 2021-04-12–2026-08-31 | 679 | 0 | 154 | CORPORATE_ACTION_OR_IDENTITY_BREAK |
| 121800 / KR7121800007 | 832 | 2016-09-20–2026-08-31 | 831 | 1 | 0 | RAW_DATA_GAP |
| 111870 / KR7111870002 | 821 | 2023-04-06–2026-08-31 | 667 | 0 | 154 | CORPORATE_ACTION_OR_IDENTITY_BREAK |
| 093230 / KR7093230001 | 813 | 2021-12-29–2026-08-31 | 577 | 1 | 235 | CORPORATE_ACTION_OR_IDENTITY_BREAK |
| 066790 / KR7066790007 | 679 | 2018-07-09–2021-04-09 | 679 | 0 | 0 | APPROVED_SUSPENSION_CARRY_CANDIDATE |
| 151910 / KR7151910007 | 592 | 2024-03-14–2026-08-31 | 406 | 0 | 186 | CORPORATE_ACTION_OR_IDENTITY_BREAK |
| 103230 / KR7103230009 | 523 | 2021-02-16–2023-03-27 | 523 | 0 | 0 | APPROVED_SUSPENSION_CARRY_CANDIDATE |
| 083660 / KR7083660001 | 422 | 2019-02-14–2022-12-15 | 422 | 0 | 0 | APPROVED_SUSPENSION_CARRY_CANDIDATE |
| 019490 / KR7019490002 | 396 | 2022-03-29–2024-09-24 | 396 | 0 | 0 | APPROVED_SUSPENSION_CARRY_CANDIDATE |

### 장기 대상별 해석

- `023430 / KR7023430002`: KRX official raw daily exact rows: zero OHLC except positive carried close, volume=0, trading_value=0 on 170 audited missing marks; valuation-only carry candidate requires policy/user approval and source audit. 2131 marks fall outside the exact PIT or official listing lifecycle boundary; no successor linking/carry.
- `007630 / KR7007630007`: KRX official raw daily exact rows: zero OHLC except positive carried close, volume=0, trading_value=0 on 615 audited missing marks; valuation-only carry candidate requires policy/user approval and source audit. 1164 marks fall outside the exact PIT or official listing lifecycle boundary; no successor linking/carry.
- `086250 / KR7086250008`: KRX official raw daily exact rows: zero OHLC except positive carried close, volume=0, trading_value=0 on 324 audited missing marks; valuation-only carry candidate requires policy/user approval and source audit. 1222 marks fall outside the exact PIT or official listing lifecycle boundary; no successor linking/carry.
- `181340 / KR7181340001`: KRX official raw daily exact rows: zero OHLC except positive carried close, volume=0, trading_value=0 on 2795 audited missing marks; valuation-only carry candidate requires policy/user approval and source audit. 1990 marks fall outside the exact PIT or official listing lifecycle boundary; no successor linking/carry.
- `174880 / KR7174880005`: KRX official raw daily exact rows: zero OHLC except positive carried close, volume=0, trading_value=0 on 679 audited missing marks; valuation-only carry candidate requires policy/user approval and source audit. 154 marks fall outside the exact PIT or official listing lifecycle boundary; no successor linking/carry.
- `121800 / KR7121800007`: KRX official raw daily exact rows: zero OHLC except positive carried close, volume=0, trading_value=0 on 3545 audited missing marks; valuation-only carry candidate requires policy/user approval and source audit. 1 marks are exact traded/missing-source or raw-row absent within PIT; no carry.
- `111870 / KR7111870002`: KRX official raw daily exact rows: zero OHLC except positive carried close, volume=0, trading_value=0 on 667 audited missing marks; valuation-only carry candidate requires policy/user approval and source audit. 154 marks fall outside the exact PIT or official listing lifecycle boundary; no successor linking/carry.
- `093230 / KR7093230001`: KRX official raw daily exact rows: zero OHLC except positive carried close, volume=0, trading_value=0 on 1668 audited missing marks; valuation-only carry candidate requires policy/user approval and source audit. 470 marks fall outside the exact PIT or official listing lifecycle boundary; no successor linking/carry. 3 marks are exact traded/missing-source or raw-row absent within PIT; no carry.
- `066790 / KR7066790007`: KRX official raw daily exact rows: zero OHLC except positive carried close, volume=0, trading_value=0 on 679 audited missing marks; valuation-only carry candidate requires policy/user approval and source audit.
- `151910 / KR7151910007`: KRX official raw daily exact rows: zero OHLC except positive carried close, volume=0, trading_value=0 on 1806 audited missing marks; valuation-only carry candidate requires policy/user approval and source audit. 558 marks fall outside the exact PIT or official listing lifecycle boundary; no successor linking/carry.
- `103230 / KR7103230009`: KRX official raw daily exact rows: zero OHLC except positive carried close, volume=0, trading_value=0 on 523 audited missing marks; valuation-only carry candidate requires policy/user approval and source audit.
- `083660 / KR7083660001`: KRX official raw daily exact rows: zero OHLC except positive carried close, volume=0, trading_value=0 on 422 audited missing marks; valuation-only carry candidate requires policy/user approval and source audit.
- `019490 / KR7019490002`: KRX official raw daily exact rows: zero OHLC except positive carried close, volume=0, trading_value=0 on 1980 audited missing marks; valuation-only carry candidate requires policy/user approval and source audit.

## Carry 후보

KRX raw exact placeholder와 PIT 내부의 직전 adjusted close가 함께 확인된 window×identity valuation mark는 16,512건이다. 중복 window 날짜를 제외하면 exact identity×date 후보는 7,114개다. 미해결 equity date는 해당 날짜의 모든 보유 포지션이 후보일 때만 복구 가능으로 계산했다. carry는 아직 적용하지 않았고 valuation-only 후보로만 본다.

## Coverage 시나리오

| window | baseline coverage | A: carry 후보만 | 개선 | A terminal equity | MDD |
|---|---:|---:|---:|---|---|
| p1 | 21.6930% | 26.6173% | 4.9244 pp | unresolved (2026-08-31) | unqualified (<90% coverage) |
| p2_1 | 27.6340% | 79.6673% | 52.0333 pp | unresolved (2025-05-30) | unqualified (<90% coverage) |
| p2_2 | 21.5573% | 62.1485% | 40.5912 pp | unresolved (2026-08-31) | unqualified (<90% coverage) |
| p3_1 | 6.3549% | 73.8609% | 67.5060 pp | unresolved (2025-05-30) | unqualified (<90% coverage) |
| p3_2 | 4.6532% | 54.0825% | 49.4293 pp | unresolved (2026-08-31) | unqualified (<90% coverage) |

- Scenario B(Scenario A + 이미 승인된 exclusions)는 A와 동일하다. 기존 exclusion은 이미 baseline에 포함되어 있고, 81개 unresolved identity와의 overlap은 0건이다. 새 exclusion은 적용하지 않았다.
- 모든 window의 커버리지가 90%에 못 미치면 portfolio-only MDD 재평가를 수행하지 않았으며, existing MDD 값은 observed-below-90 상태라 공식 exact MDD로 취급할 수 없다.
- terminal equity는 날짜별 마지막 일자에서 모든 unresolved marks가 carry candidate로 해결되는지 확인했다. 이번 실행 결과를 참조한다.

## RAW_DATA_GAP / identity-break 검토 후보

`permanent_exclusion_candidate=REVIEW_ONLY`인 identity는 identity_classification.csv에서 확인할 수 있다. 어떤 identity도 제외 정책에 자동 반영하지 않았다. 특히 identity 종료 뒤 날짜는 carry나 successor 연결 없이 그대로 구조적 unresolved로 남겼다.

## KRX 공시 근거 및 범위

- 007630 폴루스바이오팜: KRX 공시상 정리매매는 2021-11-08~11-16, 상장폐지일은 2021-11-17이다. merged PIT의 더 늦은 범위보다 공시를 우선해 11-16 이후 placeholder carry를 금지했다. 공시 [링크](https://kind.krx.co.kr/external/2021/11/02/000494/20211102001123/68051.htm).
- 086250 이노와이즈: KRX 상장폐지 공시에서 정리매매 일정 및 상장폐지일 확인. [링크](https://kind.krx.co.kr/external/2021/08/18/000466/20210818001107/70769.htm).
- 174880 장원테크: 2023-04-27부터 개선기간 중 거래정지 안내 확인. 그 공시가 2021년부터 시작하는 전 gap 전체를 증명하는 것은 아니며 raw placeholder가 일자별 근거다. [링크](https://kind.krx.co.kr/external/2023/04/27/000491/20230427000167/70780.htm).
- 093230 이아이디: 2025년 상장폐지 및 정리매매 공시가 PIT 이후 일부 구간과 맞물린다. [링크](https://kind.krx.co.kr/external/2025/02/14/001474/20250214003151/68051.htm).
- 121800 비덴트: 2024-10-04 거래정지 관련 KRX 공시가 후기 구간을 지지하지만, 2016년 raw 거래일과 2023년 이후 placeholder는 별도 구간으로 보았다. [링크](https://kind.krx.co.kr/external/2026/06/02/000871/20260602001954/70798.htm).
- 103230 에스앤더블류: KRX 거래정지기간 변경 공시에서 2021-02-15 시작 기록 확인. [링크](https://kind.krx.co.kr/external/2022/07/08/000567/20220708001288/70798.htm).
- 이 링크들은 장기 identity에 대한 일부 formal notice 확인용이다. 날짜별 carry 후보 판정은 exact KRX raw row, exact PIT interval, same-identity adjusted prior close를 함께 검사했다.

## Stop-rule 결론

다수 구조적 gap(identity 57개)이 남고 A 시나리오 최고 coverage도 79.67%다. HOLD 유지, full-run 금지.

## 검증 상태

- 140 groups / 81 exact identities and exact-key parity with frozen summary: PASS
- 100일 이상 identity 13개: PASS
- 각 identity classification 1행: PASS
- all inspected raw partition files SHA-256 vs manifest: PASS (3860 partitions)
- frozen summary exact day-count parity: PASS; identical duplicate valuation audit rows deduplicated: 23
- current exclusion overlap: 0
- scenario arithmetic: daily portfolio date is recovered only if every blocker mark on that date is carry-eligible; identity impact is not summed across overlaps.
- source file digests and scoped audit digests: source_hashes.json
