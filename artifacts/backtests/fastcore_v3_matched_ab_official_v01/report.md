# FastCore V3 공식 동일 진입 matched A/B 결과

## 실행 상태

- 상태: `COMPLETE`
- 기간: `2021-04-01` ~ `2026-08-21` 지원, signal cutoff `2026-08-14`, 최종 평가 `2026-08-21 CLOSE`
- matched 거래: `973` / 고유 종목: `542`
- entry execution date 일치: `973/973`
- entry open 일치: `973/973`
- 네트워크 요청: `0`

## V2 / V3 핵심 지표

| 지표 | V2 | V3 |
|---|---:|---:|
| mean terminal return | 8.860421 | 8.666341 |
| median terminal return | -15.14 | 9.2 |
| win rate | 30.524152% | 70.914697% |
| mean MAE | -16.049856 | -24.416341 |
| median MAE | -16.48 | -17.99 |
| mean holding days | 148.448099 | 292.540596 |
| median holding days | 85.0 | 128.0 |
| OPEN_AT_CUTOFF | 89 (9.146968%) | 239 (24.563207%) |
| <= -30% | 16 (1.644399%) | 139 (14.285714%) |
| <= -40% | 7 (0.719424%) | 111 (11.408016%) |
| >= +50% | 160 | 50 |
| >= +100% | 57 | 24 |
| mean giveback | 36.471418 | 35.019137 |
| median giveback | 25.05 | 24.87 |

## Cohort diagnostics

| cohort | side | trades | mean return | median return | mean MAE | median MAE | median holding | OPEN_AT_CUTOFF | <= -20% | <= -30% | <= -40% |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| PRE_WINNER_LT_20 | V2 | 236 | -15.295678 | -15.805 | -17.545466 | -16.995 | 39.5 | 19 (8.050847%) | 13 | 3 | 1 |
| PRE_WINNER_LT_20 | V3 | 236 | -37.333559 | -34.4 | -47.906441 | -48.485 | 468.5 | 236 (100.0%) | 172 | 138 | 110 |
| WINNER_CAPABLE_GE_20 | V2 | 737 | 16.595617 | -14.29 | -15.570936 | -16.16 | 104.0 | 70 (9.497965%) | 39 | 13 | 6 |
| WINNER_CAPABLE_GE_20 | V3 | 737 | 23.396296 | 13.95 | -16.89441 | -12.23 | 101.0 | 3 (0.407056%) | 1 | 1 | 1 |

## Paired 결과

- mean delta: `-0.19408`
- median delta: `10.23`
- improved / worsened / same: `547 / 403 / 23`

## 사전등록 판정

- Path A: `False`
- Path B: `False`
- Path C: `True`
- performance improvement: `True`
- large loss area worsened: `True`
- capital lock area worsened: `True`
- official risk block: `True`
- official adoption eligible: `False`
- default promotion eligible: `False`

## MDD

- 상태: `NOT_EVALUATED`
- 사유: fixed-entry trade-level A/B has no pre-confirmed common portfolio equity curve; new portfolio model is prohibited

이 결과는 고정 CONTROL 진입에 대한 청산 규칙 matched A/B 결과이며, 자동 전략 채택·승격 또는 V3 규칙 수정으로 이어지지 않는다.
