# FastCore V3 Exit A/B Diagnostic FIX01

## 핵심 질문에 대한 숫자 답

### Q1. 동일한 973개 진입에서 V0가 V2보다 좋아졌는가?

혼합 결과야. V0는 중앙수익률과 승률은 높였지만 평균 terminal return은 낮아졌어. 평균 paired trade delta는 **-0.194080%**, 개선/악화/동일은 **547/403/23건**이야.

### Q2. 평균수익률 / 중앙수익률 / 승률 변화

- 평균 terminal return: V2 8.860421% → V0 8.666341% (terminal return difference -0.194080%; paired mean delta -0.194080%)
- 중앙 terminal return: V2 -15.140000% → V0 9.200000% (terminal return difference 24.340000%)
- 중앙 paired trade delta: 10.230000%
- 승률: V2 30.524152% → V0 70.914697%

### Q3. Winner 보존

"보존 능력"은 threshold 도달 건수 기준으로 판단했어.

- +50%: V2 160 (16.443988%), V0 50 (5.138746%)
- +100%: V2 57 (5.858171%), V0 24 (2.466598%)
- +200%: V2 9 (0.924974%), V0 12 (1.233299%)

### Q4. MFE <20%에서 Loss Guard 제거가 deep loss를 얼마나 증가시켰는가?

Loss Guard subset의 MFE<20% 구간은 **203건**이야. V2의 `<=-20/-30/-40/-50/-60%`는 **9/0/0/0/0건**, V0는 **158/125/100/64/35건**이야. 즉 V0 증가폭은 **149/125/100/64/35건**이야. 전체 Loss Guard subset V0는 **159/126/101/64/35건**이야.

### Q5. 기존 Loss Guard 거래 중 V0에서 최종 수익 전환된 비율

전체 Loss Guard subset **590건 중 353건 (59.830508%)**이 V2 비수익에서 V0 양의 수익으로 전환됐어. MFE<20% / MFE>=20%의 전환은 **4건 (1.970443%) / 349건 (90.180879%)**이야.

### Q6. Soft와 Hard winner clipping 진단

Soft와 Hard는 MFE 분포가 다른 cohort라 absolute giveback만으로 winner 훼손 우선순위를 결론내리지 않아.

- Soft: V2 mean/median return 15.746526% / -13.945000% → V0 17.599759% / 13.390000%; paired mean/median delta 1.853233% / 20.315000%; V2→V0 >=+50 **110/14건**, >=+100 **35/5건**.
- Hard: V2 mean/median return 18.203263% / -14.930000% → V0 35.424661% / 15.125000%; paired mean/median delta 17.221398% / 19.740000%; V2→V0 >=+50 **49/35건**, >=+100 **22/19건**.
- V0 mean/median MFE는 Soft 38.115020% / 30.110000%, Hard 90.386059% / 48.860000%; mean/median giveback은 Soft 20.515261% / 17.885000%, Hard 54.961398% / 35.540000%야.
- Hard는 absolute giveback이 크지만 MFE 자체가 훨씬 높은 cohort이고 matched outcome 기준 V2 대비 평균 terminal return이 크게 개선됐어. Soft는 평균 terminal return이 소폭 개선됐지만 V2에서 >=+50/+100으로 끝난 거래가 V0에서는 각각 **14/5건**으로 줄어 winner clipping의 우선 추가 연구 대상이야. 이것은 Soft rule 수정 지시가 아니야.

### Q7. 현재 V3 내부 MCAP bucket 비교

- Bucket A (100B~<300B): 725건, 승률 66.206897%, 평균수익률 3.188993%, <=-40% 114건 (15.724138%)
- Bucket B (>=300B): 853건, 승률 72.684642%, 평균수익률 9.119555%, <=-40% 94건 (11.019930%)

이 bucket 결과만으로 V3와 기존 CONTROL의 차이를 small-cap 원인으로 단정하지 않아. 두 bucket 모두 V3의 유동성·가격 필터 제거와 V0 exit가 적용되어 있고, 이는 현재 V3 내부 비교용 diagnostic이야.

### Q8. 다음 V1 연구의 우선 문제 분류

데이터상 다음 연구/진단 우선순위는 **1) MFE<20% loss control 문제, 2) Soft Exit winner clipping 문제, 3) small-cap universe 문제, 4) Hard Exit 추가 검토, 5) 복합 interaction 문제**로 분류해. 이는 전략 수정 우선순위가 아니야. Hard를 문제가 없다고 확정하지 않지만 현재 matched 결과에서 Soft보다 우선적인 문제라는 근거는 없어.

## 실험 계약

- 기간: `2021-04-01` evaluation start, `2026-08-14` signal cutoff, `2026-08-21` execution support end, final valuation `2026-08-21 CLOSE`.
- CONTROL 973개 진입을 각각 독립 replay했어. V0에서 앞선 거래가 이후 CONTROL entry와 겹쳐도 entry를 삭제·이동하지 않았어. 따라서 실제 실행 sequence가 아닌 matched-entry exit experiment이야.
- V0는 기존 V3 V0 함수/계약을 그대로 재사용했어: daily HIGH HWM/MFE, daily LOW MAE, daily CLOSE breach, latest completed weekly FAST, next local trading day OPEN, no look-ahead, cutoff 강제매도 없음.
- 이번 작업에서 새 entry scan, threshold tuning, Loss Guard 재도입, V1 구현, portfolio/Julia 실행은 하지 않았어.

## 파일

- `matched_control_entries_v2_vs_v0.csv`: 973개 matched row
- `matched_control_entries_v2_vs_v0_summary.json`: A/B 전체 summary와 계약
- `v0_mfe_tier_diagnostics.csv`
- `v2_loss_guard_subset_diagnostics.csv`
- `v0_exit_reason_diagnostics.csv`
- `v3_market_cap_bucket_diagnostics.csv`

기존 V3 거래 artifact는 읽기만 했고 재생성하지 않았어.
