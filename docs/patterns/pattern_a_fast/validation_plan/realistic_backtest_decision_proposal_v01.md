# FastCore 현실적 백테스트 미확정 조건 결정안 V01

- **상태**: `사용자 검토 대기`
- **작성일**: 2026-09-15 KST
- **대상 브랜치**: `codex/fastcore-fundamentals-simple-backtest-v01`
- **기준 HEAD**: `cbb0cb2b49c350988c0fc2917be433a64ba2a527`
- **문서 성격**: 최종 실행계약이 아닌 사용자 검토용 결정안

## 1. 목적과 범위

이 문서는 FastCore 현실적 백테스트에서 아직 공통 실행계약으로 확정되지 않은 조건을 정리하고, 각 항목에 대해 최대 두 가지 선택안과 하나의 추천안을 제시한다. 추천안도 사용자의 승인 전에는 확정 규칙으로 취급하지 않는다.

이번 문서에서는 백테스트, 코드, runner, artifact, 데이터 수집, pytest를 실행하지 않는다. Fundamentals 조건, cutoff, threshold, score, revenue/profit 조건도 다루지 않는다. V2 전략 규칙과 PIT 유니버스 및 adjusted 가격 원천은 변경하지 않는다.

## 2. 확인된 기존 기준

다음 기준은 새로 결정하지 않고 현재 레포의 공식 기준으로 사용한다.

| 영역 | 현재 공식 기준 |
|---|---|
| 전략 | `PATTERN_A_FAST_FINAL_STRATEGY_V02`, `docs/patterns/pattern_a_fast/strategy/version_02/README.md` |
| 신호·체결 | 완료된 관측값만 사용하며 `NEXT_LOCAL_TRADING_DAY_OPEN`에서 체결 |
| Pre-PROGRESSED Loss Guard | 완료 일봉 종가 기준 판단 후 다음 로컬 거래일 시가에서 청산 |
| PROGRESSED 이후 청산 | V2 Exit 3/4와 기존 lifecycle 의미론을 유지 |
| 중복 보유 | 동일 종목 동시 보유·pyramiding·같은 시가 exit/re-entry 금지 |
| 가격 | `AdjustedPriceStore` / Naver direct adjusted V02 |
| raw 거래 자료 | `KrxRawStockStore` / KRX Open API stock daily |
| PIT 유니버스 | `survivorship_safe_denominator_freeze`의 frozen effective authority와 loader |
| 시장 범위 | KOSPI COMMON 및 KOSDAQ COMMON 보통주. ETF·ETN 등은 자동 포함하지 않음 |
| 결측 | current-list broadcast, nearest-date fallback, 임의 0 대체 금지. 필요한 결측은 fail-closed |

기존 200M/5M 포트폴리오 구현은 참고 구현일 뿐이며, 이번 공통계약에 자동 승계하지 않는다.

## 3. A. 비용과 거래세

### A-1. 현재 상태와 기존 근거

매수·매도 수수료, 매수·매도 슬리피지, 매도 거래세의 시장별·거래일별 적용은 아직 `검토 필요`다. 기존 `GROSS` 또는 `NO_COST_MODEL`은 현실적 공통계약의 권위가 아니다.

수수료는 특정 증권사 계좌 재현이 아니라 공통 현실성 가정이어야 한다. 레포에는 모든 계좌에 공통으로 적용할 공식 수수료율이 없다. 따라서 전 증권사 조사는 하지 않는다.

### A-2. 거래세의 공식 역사 확인

증권거래세법 시행령 연혁에서 2021~2022년 유가증권시장 본세율은 0.08%, 코스닥시장 세율은 0.23%로 확인된다. 2023년은 코스피 0.05%, 코스닥 0.20%, 2024년은 코스피 0.03%, 코스닥 0.18%로 정해졌다. 2025년은 2024년 기간 한정 세율이 끝난 뒤 2026년 개정 전 기본 탄력세율인 코스피 0%, 코스닥 0.15%가 적용되는 기간으로 해석한다. 2026년 1월 1일부터는 코스피 0.05%, 코스닥 0.20%로 개정되었다.

코스피에는 농어촌특별세 0.15%가 별도로 붙고, 코스닥에는 해당 농어촌특별세가 붙지 않는 구조를 반영한다. 아래 표의 `총 매도세율`은 백테스트에서 실제 매도 notional에 적용할 제안 표기이며, 코스피 본세와 농어촌특별세를 합산한 값이다.

| 양도일 | 코스피 증권거래세 본세 | 코스피 농특세 | 코스피 총 매도세율 | 코스닥 총 매도세율 |
|---|---:|---:|---:|---:|
| 2021-01-01 ~ 2022-12-31 | 0.08% | 0.15% | 0.23% | 0.23% |
| 2023-01-01 ~ 2023-12-31 | 0.05% | 0.15% | 0.20% | 0.20% |
| 2024-01-01 ~ 2024-12-31 | 0.03% | 0.15% | 0.18% | 0.18% |
| 2025-01-01 ~ 2025-12-31 | 0.00% | 0.15% | 0.15% | 0.15% |
| 2026-01-01 이후 | 0.05% | 0.15% | 0.20% | 0.20% |

2025년 행은 2022년 개정문이 2024년까지의 기간 한정 세율을 정하고, 2025년에는 2026년 개정 전 세율이 유지되며, 2026년 개정문이 2026년 1월 1일부터 0.05%/0.20%로 변경한 법령 연혁을 연결한 해석이다. 최종 실행계약 확정 시 해당 연혁을 다시 대조한다.

공식 근거:

- [국가법령정보센터 증권거래세법 시행령 제·개정문](https://www.law.go.kr/LSW/lsRvsDocListP.do?chrClsCd=010102&lsId=005028)
- [국가법령정보센터 증권거래세법 시행령 제5조](https://www.law.go.kr/lsLinkCommonInfo.do?chrClsCd=010202&lspttninfSeq=64014)
- [국가법령정보센터 농어촌특별세법](https://www.law.go.kr/LSW/lsInfoP.do?ancYnChk=0&lsId=001569)
- [기획재정부 2021년 증권거래세율 인하 안내](https://whatsnew.moef.go.kr/mec/ots/dif/view.do?comBaseCd=DIFGODEPRT&difGovDepart1=DIFGODR001&difSer=5df48aab-ae37-437c-8e86-d6f1a9ee7823&temp=2021&temp2=HALF001)

거래세는 매수에 부과하지 않고 매도 notional에만 적용한다. 거래일은 체결일이 속한 적용기간으로 매핑하며, 하나의 고정 매도세율을 전체 기간에 적용하지 않는다.

### A-3. 선택안과 추천안

| 항목 | 선택안 1 | 선택안 2 |
|---|---|---|
| 수수료 | 0% 통제값. 총수익과 비용효과를 분리해 보는 분석용 기준 | 매수·매도에 동일한 공통 비율 `c`를 적용. 특정 증권사 계좌를 재현하지 않음 |
| 거래세 | 기간·시장별 공식 역사 세율을 매도 notional에만 적용 | 전체 기간에 하나의 고정 세율 적용 |
| 슬리피지 | 0% 통제값 | 체결 open에 고정 비율을 매수·매도 방향별로 적용. 거래량 충격 모델은 사용하지 않음 |

**추천**: 수수료는 선택안 2의 공통 비율 방식, 거래세는 선택안 1의 거래일·시장별 역사 세율, 슬리피지는 선택안 2의 단순 고정 비율 방식을 추천한다. 수수료와 슬리피지의 정확한 수치 및 매수·매도 대칭 여부는 사용자가 결정해야 하며, 이 문서에서 임의 확정하지 않는다.

**사용자 결정 필요**: 예. 수수료율, 슬리피지율, 수수료·슬리피지의 매수·매도 대칭 여부를 승인해야 한다.

## 4. B. 포트폴리오·자본·현금·동일 시가 이벤트

### B-1. 현재 상태와 기존 근거

초기자본, 진입별 sizing, 종목별 최대 투자금액 또는 비중, 동시 보유 한도, 현금 부족, 매도대금 재사용 시점, 서로 다른 종목의 동일 시가 이벤트 순서는 미확정이다. 200M/5M는 이전 실험의 구현 기준일 뿐 공통 계약이 아니다.

### B-2. 선택안과 추천안

| 항목 | 선택안 1 | 선택안 2 |
|---|---|---|
| 초기자본 | 사용자 승인 절대금액 `C0`를 두고 실제 현금 잔고를 추적 | 초기자본을 1.0으로 정규화하고 현금 부족을 측정하지 않음 |
| 종목별 sizing | 진입마다 동일한 고정 notional `q`를 배정하고 종목별 최대치 `q_max`를 둠 | 진입 시점의 가용 현금과 빈 슬롯에 따라 동일 비중으로 배분 |
| 동시 보유 | 승인된 최대 슬롯 `N`개를 두고 초과 신호는 진입하지 않음 | 슬롯 제한 없이 현금이 허용하는 만큼 보유 |
| 현금 부족 | 주문 전체를 체결하지 않고 `SKIPPED_CASH_UNAVAILABLE`로 기록 | 잔여 현금만큼 부분 체결 |
| 매도대금 재사용 | 매도 체결 이벤트가 끝난 다음 평가 가능한 다음 시가부터 재사용 | 같은 시가의 후속 진입에도 재사용 |
| 동일 시가 순서 | 청산 이벤트를 먼저 처리하고, 신규 진입은 이후 처리하되 매도대금은 같은 시가에 재사용하지 않음. 남은 신규 진입은 종목코드 오름차순을 tie-break로 사용 | 모든 이벤트를 종목코드 오름차순으로 순차 처리 |

**추천**: 선택안 1 계열을 추천한다. 즉 사용자 승인 절대 초기자본을 사용하고, 고정 notional과 유한 슬롯을 적용하며, 현금 부족은 부분 체결 없이 명시적으로 건너뛰고, 매도대금은 다음 평가 가능한 시가부터 재사용한다. 동일 시가에서는 청산을 먼저 반영하되 같은 시가 재사용은 금지하고, 남은 진입 순서만 결정적 tie-break로 처리한다. `C0`, `q`, `q_max`, `N`의 수치는 사용자 결정 전까지 미확정이다.

이 추천은 기존 200M/5M를 자동 승계하는 의미가 아니다. 해당 값은 사용자가 별도로 승인하는 경우에만 입력값이 된다.

**사용자 결정 필요**: 예. `C0`, sizing 방식과 수치, 종목 한도, 동시 보유 `N`, 현금 부족 처리 및 재사용 시점을 승인해야 한다.

## 5. C. 평가 예외와 최종 valuation

### C-1. 현재 상태와 기존 근거

상장폐지, 장기 거래정지, 최종 valuation 가격 결측, 실행 가능한 다음 open 결측의 처리 방식이 미확정이다. 현재 권위로 확인 가능한 identity/lifecycle 및 가격 지원범위가 있으면 그것을 우선 사용해야 한다. nearest-date close, 임의의 마지막 관측값, 0 가격 대체, 복잡한 corporate-action 재구성은 사용하지 않는다.

### C-2. 선택안과 추천안

| 항목 | 선택안 1 | 선택안 2 |
|---|---|---|
| 상장폐지·거래정지 | repository identity/lifecycle authority가 제공하는 공식 terminal 상태와 유효 가격만 사용. 가격이 없으면 포지션을 `UNRESOLVED`로 표시하고 별도 예외 집계 | 마지막 관측 close 또는 nearest-date close로 조용히 mark |
| 최종 valuation 결측 | 유효한 최종 지원일과 lifecycle 근거가 모두 없으면 fail-closed. 포트폴리오 결과에서 제외하지 않고 예외 상태·영향 금액을 보고 | 결측 가격을 0 또는 임의 close로 대체 |
| 실행 open 결측 | 다음 로컬 거래일 open이 지원되지 않으면 `OPEN_AT_CUTOFF` 또는 `UNRESOLVED`로 남김 | 지원되는 가장 가까운 날짜의 close/open으로 실행 처리 |

**추천**: 선택안 1을 추천한다. 결측을 조용히 보간하지 않고, repository authority가 증명할 수 있는 경우에만 terminal valuation을 적용하며, 그 밖에는 `UNRESOLVED`/fail-closed와 영향 보고를 사용한다. `UNRESOLVED` 포지션을 전체 실행 중단으로 볼지, 포지션 수준 예외로 보고 전체 실행은 계속할지는 사용자 승인이 필요하다.

**사용자 결정 필요**: 예. `UNRESOLVED`를 포지션 수준 예외로 계속 보고할지, 하나라도 있으면 전체 백테스트를 실패시킬지 결정해야 한다.

## 6. D. Turnover 정의

### D-1. 현재 상태와 기존 근거

turnover는 numerator, 매수·매도 notional 범위, normalization 분모, 비용 포함 여부, 보고 단위가 모두 미확정이다. 거래 횟수와 turnover는 서로 대체하지 않는다.

### D-2. 선택안과 추천안

| 항목 | 선택안 1: 총 거래 notional / 초기자본 | 선택안 2: 평균 equity 기준 turnover |
|---|---|---|
| Numerator | 모든 매수 notional + 모든 매도 notional | 모든 매수 notional + 모든 매도 notional |
| Denominator | 승인된 초기자본 `C0` | 평가기간의 일별 평균 gross equity |
| 비용 포함 | 거래세·수수료·슬리피지는 numerator에 포함하지 않고 비용 항목으로 별도 보고 | 동일하게 별도 보고 |
| 보고 단위 | 전체기간 `x` 및 `%`, 필요 시 연환산 보조값 | 전체기간 `x` 및 `%`, 평균 equity 기준임을 명시 |
| 장점 | 재현성이 높고 초기자본·현금 제약과 직접 연결됨 | 자본 규모 변화가 큰 경우 기간 중 자본 활용도를 반영함 |
| 주의점 | 장기간 자본 규모 변화나 cutoff open position을 별도 해석해야 함 | 평균 equity 정의가 추가로 필요하고 비용·valuation 결측에 민감함 |

**추천**: 선택안 1을 추천한다. `Σ(buy notional + sell notional) / initial capital`을 기본 turnover로 보고하고, 거래세·수수료·슬리피지는 비용 합계로 별도 보고한다. 전체기간 배수와 퍼센트 표기를 함께 사용하고, 연환산 값은 보조값으로만 표시한다.

**사용자 결정 필요**: 예. 분모와 연환산 보조값의 표시 여부를 승인해야 한다.

## 7. E. 전략 중립 benchmark

### E-1. 현재 상태와 기존 근거

레포에는 KRX 공식 지수 원천과 시장·섹터 benchmark metadata가 있다. ROADMAP에는 KOSPI COMMON은 KOSPI, KOSDAQ COMMON은 KOSDAQ을 benchmark로 사용하는 방향이 기록되어 있다. 다만 FastCore 현실적 portfolio에 대한 동일기간·동일 valuation 의미론의 공통 benchmark 계약은 아직 확정하지 않았다.

### E-2. 선택안과 추천안

| 항목 | 선택안 1 | 선택안 2 |
|---|---|---|
| Benchmark | 시장별 matched KRX broad index: KOSPI COMMON은 KOSPI 지수 1001, KOSDAQ COMMON은 KOSDAQ 지수 2001. 혼합 portfolio는 시작자본 기준 시장별 benchmark를 합성 | 단일 KRX 300 지수를 혼합 portfolio 전체의 benchmark로 사용 |
| 기간·가격 | 전략과 동일한 evaluation 기간, 지원 범위, 최종 valuation 의미론 적용 | 동일 기간이지만 단일 지수로 비교 |
| 장점 | 실제 투자 유니버스 시장과 직접 대응하며 ROADMAP 방향과 일치 | 혼합 portfolio를 한 숫자로 간단히 표현 |
| 주의점 | 혼합 시 sleeve 가중 방식이 필요함 | KOSPI/KOSDAQ 시장 구성 차이를 희석할 수 있음 |

**추천**: 선택안 1을 추천한다. 기존 KRX 공식 지수 authority와 ROADMAP 방향을 재사용하고, 시장별 결과와 혼합 결과를 분리한다. benchmark용 신규 데이터 구축은 하지 않는다.

**사용자 결정 필요**: 예. 혼합 portfolio의 시장별 benchmark 가중을 시작자본 기준으로 할지, 시장별 결과만 보고 혼합 benchmark를 생략할지 결정해야 한다.

## 8. F. Market regime

### F-1. 현재 상태와 기존 근거

V2의 `PERMITTED_REGIME`은 전략 내부의 월간 permission state이지, 모든 전략에 공통으로 적용하는 독립 시장 regime authority가 아니다. 기존 연구의 Fear Index나 별도 regime 모델은 공통 공식 기준으로 승인되지 않았다.

### F-2. 선택안과 추천안

| 항목 | 선택안 1 | 선택안 2 |
|---|---|---|
| 공통 gate | 기존 공식 authority가 있는 regime만 mandatory gate로 사용하고, 없으면 `UNAVAILABLE`로 처리 | 공통 market regime을 mandatory gate로 두지 않고, 전략 내부 `PERMITTED_REGIME`만 V2 규칙대로 사용 |
| 결과 보고 | regime별 성과를 별도 분할 | regime gate 없이 전체 성과와 시장별 분할만 보고 |

**추천**: 선택안 2를 추천한다. 새로운 공통 regime 모델을 만들지 않고, V2의 `PERMITTED_REGIME`은 전략 규칙으로만 유지한다. 공식 공통 regime authority가 나중에 승인되면 mandatory gate가 아니라 우선 stratified reporting으로 추가 검토한다.

**사용자 결정 필요**: 예. Stage 4 공통 mandatory gate에서 regime을 제외하는지 승인해야 한다.

## 9. G. Robustness 범위와 보고 형식

### G-1. 현재 상태와 기존 근거

V2 threshold는 frozen 상태이며, 이번 공통조건 결정에서 V2 threshold sweep이나 grid search를 수행하지 않는다. generic robustness의 최소 범위와 보고 형식만 정하면 된다.

### G-2. 선택안과 추천안

| 항목 | 선택안 1 | 선택안 2 |
|---|---|---|
| 범위 | threshold 변경 없이 연도, 시장, ticker, winner concentration, loss-tail concentration을 기술통계로 분할 | V2 threshold 및 진입 조건을 여러 조합으로 sweep |
| 보고 | 전체 결과와 각 slice의 n, return, MDD, trade count, exposure, turnover, `OPEN_AT_CUTOFF`를 표로 보고 | 조합별 성과 순위와 최적 조합을 보고 |
| 해석 | 견고성·집중위험을 설명하는 descriptive audit | 최적화 또는 재튜닝으로 해석될 위험 |

**추천**: 선택안 1을 추천한다. 최소 robustness는 threshold를 건드리지 않는 연도·시장·ticker·winner concentration·loss-tail concentration slice로 한정하고, 각 slice의 표본 수와 핵심 위험지표를 함께 보고한다. parameter sweep과 V2 규칙 변경은 이번 범위에서 제외한다.

**사용자 결정 필요**: 예. 최소 slice 범위와 최종 보고 표를 승인해야 한다.

## 10. 최종 결정 요약

| 항목 | 추천안 | 근거 요약 | 사용자 결정 |
|---|---|---|---|
| 수수료 | 공통 고정 비율, 특정 broker 재현 아님 | 계좌별 조사 없이 재현 가능한 현실성 가정 | 필요 |
| 거래세 | 거래일·시장별 공식 역사 세율, 매도에만 적용 | 법령 연혁상 단일 전기간 세율이 부적절함 | 필요 |
| 슬리피지 | 체결 open에 단순 고정 비율 | 복잡한 volume impact 없이 방향성 왜곡을 통제 | 필요 |
| 초기자본·sizing | 사용자 승인 `C0`, 고정 notional·유한 슬롯 | 현금 제약과 재현성 확보. 200M/5M 자동 승계 안 함 | 필요 |
| 현금·이벤트 | 현금 부족 시 전체 진입 skip, 매도대금 다음 시가 재사용, 청산 우선 | order-dependent 결과와 부분체결 가정 방지 | 필요 |
| valuation 예외 | lifecycle authority 우선, 결측은 `UNRESOLVED`/fail-closed | nearest-date·0·임의 close 대체 방지 | 필요 |
| turnover | 매수+매도 notional / 초기자본, 비용 별도 | 정의가 단순하고 자본 제약과 직접 연결 | 필요 |
| benchmark | 시장 matched KRX 1001/2001, 동일기간 | ROADMAP 및 공식 시장 authority와 일치 | 필요 |
| market regime | 공통 mandatory gate로 새 모델을 만들지 않음 | 현재 공통 공식 authority가 없음 | 필요 |
| robustness | threshold sweep 없이 최소 descriptive slices | frozen V2 보호 및 과최적화 방지 | 필요 |

현재 사용자 결정 필요 묶음은 다음과 같다.

1. 공통 수수료율과 슬리피지율, 방향별 대칭 여부
2. 초기자본 `C0`, sizing·종목 한도·동시 보유 `N`
3. 현금 부족·매도대금 재사용·`UNRESOLVED` 처리의 세부 운영
4. turnover 분모와 benchmark 혼합 가중
5. market regime mandatory gate 여부와 robustness slice 범위

## 11. 다음 단계 제한

사용자 결정 전에는 이 문서의 추천안을 실행계약으로 승격하지 않는다. 승인 이후에만 필요한 범위에서 별도 실행계약 문서와 구현 계획을 만든다. 그 전까지 FastCore 백테스트, Julia 실행, parameter sweep, production 코드 변경, artifact 생성, 외부 API 호출, pytest는 수행하지 않는다.
