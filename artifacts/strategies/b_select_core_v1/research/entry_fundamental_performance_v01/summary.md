# B Select Core V1 진입 시점 PIT 펀더멘탈 상태별 거래 성과

- 분석 기준: 최신 완료 production snapshot `artifacts/strategies/b_select_core_v1/production/20261003/status.json` (요청일 2026-10-03, 시장 기준일 2026-10-02)
- 기준 commit: `163f908fe26345eaf7caacbcd1e9900c5d3042c9`
- 전략 ID: `PATTERN_B_SELECT_CORE_V01` / 상태 평가기: `B_SELECT_OI_1Q_PIT_V03_FIX01`
- 각 거래의 분류는 `entry_signal_date`에 고정한 PIT resolver 결과야. 현재 재무상태를 과거에 적용하지 않았어.
- 수익률 단위는 퍼센트포인트야. 예를 들어 `10`은 `+10%`를 뜻해.
- 동시 보유 거래를 복리 연결하지 않았고, 아래 수치는 portfolio backtest나 CAGR이 아니야.

## 모집단 및 상태 표본

- 전체 trade history: **319** (CLOSED 293, OPEN 26)
- CLOSED 중복 identity: **0**; PIT 상태 배정 누락: **0**; 진입일 불일치: **0**; 미래 공시 증거: **0**.
- PIT resolver의 retryable 상태: **6개 key**가 재평가 후에도 retryable로 남았고 상태는 계약대로 `미상`으로 유지됐어.
- 범주별 표본 수와 전체 CLOSED 비중:

| 진입 PIT 상태 | CLOSED n | CLOSED 비중 | OPEN n | 해석 표본 구간 |
|---|---:|---:|---:|---|
| 우수 | 83 | 28.33% | 13 | BASIC_COMPARISON |
| 양호 | 27 | 9.22% | 4 | LIMITED |
| 보통 | 107 | 36.52% | 8 | BASIC_COMPARISON |
| 주의 | 64 | 21.84% | 1 | BASIC_COMPARISON |
| 미상 | 12 | 4.10% | 0 | VERY_SMALL |

## 핵심 비교

| 진입 PIT 상태 | n | 승률 | 평균 수익률 | 중앙 수익률 | 평균 보유일 | 평균 보유 세션 | +50% | +100% | -15% 이하 | -30% 이하 | PF |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 우수 | 83 | 86.75% | 15.49% | 12.66% | 132.39 | 89.02 | 6 (7.23%) | 1 (1.20%) | 7 (8.43%) | 2 (2.41%) | 7.59 |
| 양호 | 27 | 92.59% | 22.02% | 20.29% | 129.93 | 87.30 | 1 (3.70%) | 0 (0.00%) | 2 (7.41%) | 1 (3.70%) | 11.46 |
| 보통 | 107 | 76.64% | 11.50% | 10.59% | 209.93 | 140.81 | 8 (7.48%) | 1 (0.93%) | 11 (10.28%) | 6 (5.61%) | 3.58 |
| 주의 | 64 | 79.69% | 9.68% | 9.20% | 215.55 | 144.33 | 2 (3.12%) | 0 (0.00%) | 7 (10.94%) | 3 (4.69%) | 3.35 |
| 미상 | 12 | 75.00% | 26.66% | 10.29% | 140.00 | 93.67 | 1 (8.33%) | 1 (8.33%) | 0 (0.00%) | 0 (0.00%) | 23.01 |

## 가장 눈에 띄는 차이

- n≥20 그룹 중 평균 실현수익률 범위는 주의 (9.68%, n=64)부터 양호 (22.02%, n=27)까지야.
- n≥20 그룹의 승률 범위는 보통 (76.64%)부터 양호 (92.59%)까지야.
- n≥20 그룹의 중앙 수익률 범위는 주의 (9.20%)부터 양호 (20.29%)까지야.
- 미상 그룹은 closed n=12로 표본 기준상 VERY_SMALL에 해당해. 이 그룹의 수치는 참고용으로만 봐야 해.
- 청산 사유는 1종류이며, 모든 실현 거래에서 사유 누락은 0건이야.
- 이 비교는 분포와 효과 크기를 기술하는 용도야. 전략 채택·필터 승격을 뜻하지 않아.

## CLOSED 상세 분포와 보조 지표

상세 5분위수, 승·패/보합, 손익비, 기대값, profit factor, 수익 구간과 tail count/share는 `closed_trade_metrics_by_fundamental.csv`와 `closed_trade_detail.csv`에 있어.
연도별 표는 상태×연도 표본이 n≥20인 셀만 담았고, 작은 셀은 `INSUFFICIENT_SAMPLE` 원칙으로 뺐어.
Exit reason은 production trade history의 값을 그대로 집계했어.

## OPEN 보조 현황 (CLOSED와 분리)

- 평가 기준일: **2026-10-02**; production `latest_close`를 사용했어.
- 보유 거래: **26**; 현재가 누락 또는 기준일 불일치: **0**; source 기록 수익률과 mark 재계산 불일치: **0**.
- 상태별 미실현 평균/중앙 수익률, 보유기간과 +10/+20/+30/+50%, -10/-15/-20/-30% 건수·비중은 `open_trade_snapshot_by_fundamental.csv`에 있어.
- 종목별 OPEN snapshot은 `open_trade_detail.csv`에 따로 있어.

## 무결성 검증

- 결과: **PASS**
- 산출 CSV schema/count 및 상세 거래 identity 재대조: **PASS**.
- source history / Strategy Monitor: 원본 319건, monitor 319건; identity 누락 0, 추가 0, 상태 불일치 0.
- PIT entry date: 각 거래 `entry_signal_date`와 resolver status date 일치; 미래 source date 0, 미래 first filing date 0.
- KRX session authority: `data/market/rolling_authority/merged_trading_calendar.json` SHA-256이 production calendar authority와 일치; frontier 2026-10-02; 해당 달력으로 보유 거래 세션 계산.
- production history 파일 변경: False; PIT ledger 변경: False; production 코드·전략·웹 데이터 수정: 없음.
- `web/data/strategy-monitor.json`은 count/identity/status parity만 확인했고 거래 원본 authority로 사용하지 않았어.

## 산출물

- `artifacts/strategies/b_select_core_v1/research/entry_fundamental_performance_v01/summary.md`
- `artifacts/strategies/b_select_core_v1/research/entry_fundamental_performance_v01/summary.json`
- `artifacts/strategies/b_select_core_v1/research/entry_fundamental_performance_v01/closed_trade_metrics_by_fundamental.csv`
- `artifacts/strategies/b_select_core_v1/research/entry_fundamental_performance_v01/closed_trade_detail.csv`
- `artifacts/strategies/b_select_core_v1/research/entry_fundamental_performance_v01/open_trade_snapshot_by_fundamental.csv`
- `artifacts/strategies/b_select_core_v1/research/entry_fundamental_performance_v01/open_trade_detail.csv`
- `artifacts/strategies/b_select_core_v1/research/entry_fundamental_performance_v01/yearly_metrics.csv`
- `artifacts/strategies/b_select_core_v1/research/entry_fundamental_performance_v01/exit_reason_metrics.csv`

이번 작업은 descriptive research이며 전략 규칙이나 production history를 변경하지 않았어.
