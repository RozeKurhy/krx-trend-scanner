# B Select Daily Exit MDD Coverage Remediation V01

- 판정: **B_SELECT_DAILY_EXIT_MDD_COVERAGE_CHECK_REQUIRED**
- 후보 판정: **B_SELECT_DAILY_NORMAL_EXIT_CANDIDATE_CHECK_REQUIRED**
- 기준 HEAD / origin/main: 782dd934f93d49aef35131f049ea85fd68500c0c / 782dd934f93d49aef35131f049ea85fd68500c0c
- 전략 신호·거래 이벤트 재실행: 아니오. 봉인 이벤트를 고정하고 일별 평가만 재구성했어.
- Production 변경: 없음. 승격·운영 반영은 별도 결정이야.

## 레벨

| 레벨 | 개수 |
|---|---:|
| CRITICAL | 0 |
| MAJOR | 7 |
| MINOR | 0 |

## 1. 24개 exact identity 기업행위·주식수 점검

KRX raw 파티션은 ticker만 제공해 PIT COMMON 구간으로 exact ISU identity를 함께 확인했어. A는 공백 전후 상장주식수와 adjusted/raw 단위계수가 안정적, B는 주식수 비율과 Repository V2 adjusted/raw 계수 비율이 1% 이내 일치, C는 가격 단위 연속성이 입증되지 않아 carry 제외야. 법적 기업행위 종류는 근거 없이 단정하지 않았어.

| 종목 | ISU_CD | 판정 | 결측 mark 날짜 | 상장주식수 변경일 | 근거/제한 |
|---|---|---|---:|---|---|
| 001000 신라섬유 | KR7001000009 | B | 13 | 2016-04-01:4855508->24277540 | ALL_GAPS_HAVE_VALID_ADJUSTED_UNIT_CONTINUITY |
| 001380 SG글로벌 | KR7001380005 | B | 19 | 2026-05-11:44964143->22482071 | ALL_GAPS_HAVE_VALID_ADJUSTED_UNIT_CONTINUITY |
| 007720 소노스퀘어 | KR7007720006 | C | 19 | 2026-07-14:100800450->20160090 | LISTED_SHARE_CHANGE_WITH_UNRESOLVED_ADJUSTED_UNIT |
| 011080 형지I&C | KR7011080009 | C | 17 | 2026-05-07:42962622->4296262 | LISTED_SHARE_CHANGE_WITH_UNRESOLVED_ADJUSTED_UNIT |
| 015020 이스타코 | KR7015020001 | A | 1 | 없음 | NO_SHARE_OR_ADJUSTED_UNIT_CHANGE |
| 019490 엑시큐어하이트론 | KR7019490002 | C | 396 | 2023-07-31:9611224->27611224 | LISTED_SHARE_CHANGE_WITH_UNRESOLVED_ADJUSTED_UNIT |
| 019570 GMI벤처 | KR7019570001 | C | 37 | 없음 | UNEXPLAINED_ADJUSTED_PRICE_UNIT_CHANGE |
| 023760 한국캐피탈 | KR7023760002 | B | 19 | 2026-08-27:315609576->157804788 | ALL_GAPS_HAVE_VALID_ADJUSTED_UNIT_CONTINUITY |
| 023790 동일스틸럭스 | KR7023790009 | A | 2 | 없음 | NO_SHARE_OR_ADJUSTED_UNIT_CHANGE |
| 032680 소프트센 | KR7032680001 | B | 12 | 2023-05-03:38247703->95619257 | ALL_GAPS_HAVE_VALID_ADJUSTED_UNIT_CONTINUITY |
| 066790 씨씨에스 | KR7066790007 | C | 679 | 2019-12-16:85564335->91952335|2020-06-29:91952335->45976167|2021-01-11:45976167->55976167 | LISTED_SHARE_CHANGE_WITH_UNRESOLVED_ADJUSTED_UNIT |
| 069640 한세엠케이 | KR7069640001 | B | 11 | 2026-05-13:44806502->22403251 | ALL_GAPS_HAVE_VALID_ADJUSTED_UNIT_CONTINUITY |
| 073570 리튬포어스 | KR7073570004 | C | 14 | 2017-11-15:25363747->5072749 | LISTED_SHARE_CHANGE_WITH_UNRESOLVED_ADJUSTED_UNIT |
| 083660 CSA 코스믹 | KR7083660001 | C | 422 | 2020-04-16:19747641->37072045 | LISTED_SHARE_CHANGE_WITH_UNRESOLVED_ADJUSTED_UNIT |
| 093240 형지엘리트 | KR7093240000 | A | 2 | 없음 | NO_SHARE_OR_ADJUSTED_UNIT_CHANGE |
| 096630 에스코넥 | KR7096630009 | B | 15 | 2026-05-06:79381616->15876323 | ALL_GAPS_HAVE_VALID_ADJUSTED_UNIT_CONTINUITY |
| 103230 에스앤더블류 | KR7103230009 | A | 523 | 없음 | NO_SHARE_OR_ADJUSTED_UNIT_CHANGE |
| 105550 엣지파운드리 | KR7105550008 | B | 16 | 2026-08-12:78307051->15661410 | ALL_GAPS_HAVE_VALID_ADJUSTED_UNIT_CONTINUITY |
| 121850 코이즈 | KR7121850002 | A | 1 | 없음 | NO_SHARE_OR_ADJUSTED_UNIT_CHANGE |
| 123010 MSDI | KR7123010001 | B | 11 | 2020-04-17:6899157->34495785 | ALL_GAPS_HAVE_VALID_ADJUSTED_UNIT_CONTINUITY |
| 227610 아우딘퓨쳐스 | KR7227610003 | B | 16 | 2026-05-28:38047246->19023623 | ALL_GAPS_HAVE_VALID_ADJUSTED_UNIT_CONTINUITY |
| 234100 폴라리스세원 | KR7234100006 | B | 16 | 2026-05-26:73008183->14601636 | ALL_GAPS_HAVE_VALID_ADJUSTED_UNIT_CONTINUITY |
| 900100 파이온엑스 | USU652221081 | A | 3 | 없음 | NO_SHARE_OR_ADJUSTED_UNIT_CHANGE |
| 900250 크리스탈신소재 | KYG2115T1076 | B | 16 | 2026-06-23:143260004->35815001 | ALL_GAPS_HAVE_VALID_ADJUSTED_UNIT_CONTINUITY |

## 2. valuation-only carry 조건

- 봉인 audit의 누락 mark 8,304건을 raw placeholder·PIT identity·직전 Repository V2 adjusted close와 다시 대조했어.
- 안전 확인된 A/B identity carry: 1,875 marks.
- basis가 불명확하거나 anchor 재검증이 안 된 미평가 mark: 6,429 marks. 이 mark에는 자동 보정하지 않았어.
- KRX raw market/date partition 무결성 검증: 2,440 / 2,440 PASS.

## 3–5. 10개 case coverage·unresolved·MDD

| Window | Scenario | 거래일 | 유효 equity 전→후 | Coverage 전→후 | unresolved marks 전→후 | carry marks / 고유 종목 | 최대 누락 연속 | MDD / 유형 | peak / trough / recovery |
|---|---|---:|---:|---:|---:|---:|---:|---|---|
| P1 | CONTROL_MONTH_END | 3107 | 1635→2711 | 52.62%→87.25% | 2280→1584 | 696 / 17 | 394 | -19.2961% / NO OFFICIAL MDD: coverage below 90% | 2026-04-24 / 2026-07-30 / 2026-08-10 |
| P1 | TEST_DAILY | 3107 | 1653→2711 | 53.20%→87.25% | 2214→1567 | 647 / 11 | 394 | -14.8415% / NO OFFICIAL MDD: coverage below 90% | 2026-04-27 / 2026-07-30 / 2026-08-05 |
| P2-1 | CONTROL_MONTH_END | 1082 | 684→686 | 63.22%→63.40% | 410→396 | 14 / 3 | 394 | -15.3640% / NO OFFICIAL MDD: coverage below 90% | 2024-01-11 / 2024-12-09 / 2025-01-20 |
| P2-1 | TEST_DAILY | 1082 | 685→686 | 63.31%→63.40% | 409→396 | 13 / 2 | 394 | -14.6456% / NO OFFICIAL MDD: coverage below 90% | 2024-01-09 / 2024-12-09 / 2025-02-17 |
| P2-2 | CONTROL_MONTH_END | 1387 | 901→991 | 64.96%→71.45% | 574→432 | 142 / 11 | 394 | -26.5260% / NO OFFICIAL MDD: coverage below 90% | 2026-04-24 / 2026-07-30 / 미회복 |
| P2-2 | TEST_DAILY | 1387 | 902→991 | 65.03%→71.45% | 525→415 | 110 / 8 | 394 | -19.6677% / NO OFFICIAL MDD: coverage below 90% | 2026-04-27 / 2026-07-30 / 2026-08-10 |
| P3-1 | CONTROL_MONTH_END | 834 | 437→438 | 52.40%→52.52% | 409→396 | 13 / 2 | 394 | -15.3547% / NO OFFICIAL MDD: coverage below 90% | 2024-01-11 / 2024-12-09 / 2025-01-06 |
| P3-1 | TEST_DAILY | 834 | 438→438 | 52.52%→52.52% | 408→396 | 12 / 1 | 394 | -14.7068% / NO OFFICIAL MDD: coverage below 90% | 2024-01-09 / 2024-12-09 / 2025-01-20 |
| P3-2 | CONTROL_MONTH_END | 1139 | 654→743 | 57.42%→65.23% | 562→432 | 130 / 9 | 394 | -26.5990% / NO OFFICIAL MDD: coverage below 90% | 2026-04-24 / 2026-07-30 / 미회복 |
| P3-2 | TEST_DAILY | 1139 | 655→743 | 57.51%→65.23% | 513→415 | 98 / 6 | 394 | -21.4509% / NO OFFICIAL MDD: coverage below 90% | 2026-04-27 / 2026-07-30 / 2026-08-12 |

Coverage 90% 미만 case의 MDD 수치는 진단용 관측값이며 공식 MDD로 채택하지 않았어. 보간·추정은 하지 않았어.

## 6. CONTROL vs TEST 상대 MDD

| Window | CONTROL 관측 MDD | TEST 관측 MDD | CONTROL−TEST | 상대 Gate |
|---|---:|---:|---:|---|
| P1 | -19.2961% | -14.8415% | -4.4545 pp | 관측 기준 미악화 |
| P2-1 | -15.3640% | -14.6456% | -0.7184 pp | 관측 기준 미악화 |
| P2-2 | -26.5260% | -19.6677% | -6.8583 pp | 관측 기준 미악화 |
| P3-1 | -15.3547% | -14.7068% | -0.6479 pp | 관측 기준 미악화 |
| P3-2 | -26.5990% | -21.4509% | -5.1481 pp | 관측 기준 미악화 |

## 7. event·현금·종료 자산 parity

- 봉인 event·trade ledger를 입력으로만 사용했고 수정·재생성하지 않았어. 10개 case의 event count/hash와 trade ledger hash는 원본 그대로야.
- 원래 유효 valuation day의 invested market value 불일치: 0건.
- 현금 보존 산식 실패: 0건.
- cutoff/support terminal equity exact parity: 10/10 case.
- ENTRY/EXIT 날짜·체결가·수량·수수료·슬리피지·현금흐름은 봉인 event 입력을 바꾸지 않아 carry로 거래 결과가 바뀌지 않았어.

## 8–9. D/E Gate와 Daily NORMAL Exit 후보 판정

| Window | A/B/C 재사용 | D | E | coverage 최소 | CONTROL−TEST MDD |
|---|---|---|---|---:|---:|
| P1 | PASS/PASS/PASS | CHECK_REQUIRED | CHECK_REQUIRED | 87.25% | -4.4545 pp |
| P2-1 | PASS/PASS/PASS | CHECK_REQUIRED | CHECK_REQUIRED | 63.40% | -0.7184 pp |
| P2-2 | PASS/PASS/PASS | CHECK_REQUIRED | CHECK_REQUIRED | 71.45% | -6.8583 pp |
| P3-1 | PASS/PASS/PASS | CHECK_REQUIRED | CHECK_REQUIRED | 52.52% | -0.6479 pp |
| P3-2 | PASS/PASS/PASS | CHECK_REQUIRED | CHECK_REQUIRED | 65.23% | -5.1481 pp |

Daily NORMAL Exit 후보 최종 검증 토큰: B_SELECT_DAILY_NORMAL_EXIT_CANDIDATE_CHECK_REQUIRED.
이번 remediation 판정 토큰: B_SELECT_DAILY_EXIT_MDD_COVERAGE_CHECK_REQUIRED.

## 10. Production decision

이 보고서는 연구 검증 결과야. 전략 승격, 공식 history/lifecycle 반영, Production 적용, 기존 OPEN 포지션 EXIT 규칙 적용은 별도 결정이야.
