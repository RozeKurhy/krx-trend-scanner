# FastCore V3 Exit A/B + MCAP Bucket Diagnostic V00

## 핵심 질문에 대한 숫자 답

### Q1. 동일한 973개 진입에서 V0가 V2보다 좋아졌는가?

혼합 결과야. V0는 중앙수익률과 승률은 높였지만 평균 terminal return은 낮아졌어. 평균 delta는 **-0.194080%**, 개선/악화/동일은 **547/403/23건**이야.

### Q2. 평균수익률 / 중앙수익률 / 승률 변화

- 평균: V2 8.860421% → V0 8.666341% (delta -0.194080%)
- 중앙: V2 -15.140000% → V0 9.200000% (delta 10.230000%)
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

### Q6. Soft와 Hard 중 winner 훼손이 큰 쪽

V0 mean giveback은 Soft **20.515261%**, Hard **54.961398%**야. V0 mean terminal return은 Soft 17.599759%, Hard 35.424661%이므로, giveback 기준으로 더 큰 쪽은 **Hard**야.

### Q7. 현재 V3 내부 MCAP bucket 비교

- Bucket A (100B~<300B): 725건, 승률 66.206897%, 평균수익률 3.188993%, <=-40% 114건 (15.724138%)
- Bucket B (>=300B): 853건, 승률 72.684642%, 평균수익률 9.119555%, <=-40% 94건 (11.019930%)

이 bucket 결과만으로 V3와 기존 CONTROL의 차이를 small-cap 원인으로 단정하지 않아. 두 bucket 모두 V3의 유동성·가격 필터 제거와 V0 exit가 적용되어 있고, 이는 현재 V3 내부 비교용 diagnostic이야.

### Q8. 다음 V1 연구의 우선 문제 분류

데이터상 우선순위는 **1) MFE<20% loss control 문제, 2) Hard exit의 큰 giveback 문제, 3) small-cap universe 문제, 4) Soft exit 문제, 5) 복합 문제**로 분류해. 근거는 MFE<20% 구간의 deep-loss 증가, Hard exit의 mean giveback **54.961398%**, 그리고 bucket A/B의 평균수익률·tail 차이야. 이는 새 규칙 제안이 아니라 이번 matched-entry와 bucket 결과에서 관측된 진단 우선순위야.

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
