# Pattern A Score v0.2 OOS2 Validation

## 개요

Score Design v0.2는 commit `fffce85`에서 freeze됐고, 재현성 tooling
후속(`_score_v01_baseline()` 완전 독립 고정)도 commit `4501c3b`까지
끝났다. 이 문서는 v0.2 freeze **이후** 처음 보는 완전히 새로운 종목/
snapshot(OOS2)에서 Frozen Pattern A Score v0.2가 어떻게 동작하는지
검증한 결과다.

**핵심 원칙**: OOS2 결과를 보기 전에는 Score v0.2를 절대 수정하지
않는다. 결과가 좋지 않아도 이번 Validation 중간에 threshold나 weight를
수정하지 않는다 — 발견된 문제는 v0.3 development evidence로 넘긴다.

이 문서는 두 단계로 채워진다.

1. **Selection Methodology**(이 절, OOS2 manifest freeze commit에 포함) —
   Score를 계산하기 전에 먼저 작성하고 commit한다.
2. **Frozen v0.2 결과**(별도 절, selection freeze 이후의 별도 commit에서
   추가) — 아래 "Frozen v0.2 결과" 절 참고. 이 절이 비어 있다면 아직
   validation 실행 전이라는 뜻이다.

Git history로 다음 순서를 증명한다.

```
4501c3b (재현성 최종 마무리, Score v0.2 그대로)
  ↓
OOS2 Manifest Freeze — 이 문서의 Selection Methodology + manifest만 포함,
                        Score 계산 없음
  ↓
Frozen v0.2 실행 — 위에서 freeze한 manifest로 score_pattern_a() 호출
  ↓
OOS2 결과 Commit — 이 문서의 "Frozen v0.2 결과" 절 + validation script
                    + 테스트, Score 코드 변경 없음
```

## Selection Methodology

### 데이터 소스

- 후보 43종목의 raw 일봉을 `scripts/_oos2_fetch_and_inspect.py`로
  fetch했다(5종목은 `validate_ohlcv`가 거부하는 OHLC 이상치가 있어
  제외 — 097230 HJ중공업, 267260 HD현대일렉트릭, 128940 한미약품,
  032350 롯데관광개발, 000100 유한양행. 002270은 2022-06-24 이후
  거래 데이터가 없어 확인해보니 실제로는 2022년에 상장폐지된 종목이라
  애초에 후보 이름이 틀렸다 — 006650/240810 등 이미 확보한 대체
  종목으로 충분해 재조사하지 않았다).
- 조회 구간은 `OOS2_SELECTION_START`/`OOS2_SELECTION_END`
  (2011-01-01~2025-12-31)로 절대 고정했다 — 재실행 시점마다 구간이
  밀리는 걸 막기 위해서다(OOS v0.1과 동일 원칙).
- 월봉/주봉 close만 CSV로 저장했다
  (`data/processed/oos2_selection_monthly_close.csv`,
  `data/processed/oos2_selection_raw_summary.csv` — 둘 다 로컬 전용,
  `data/`는 전체 gitignore). Feature나 Score는 **전혀** 계산하지 않았다.

### raw 구조 보조 지표 (scouting 전용)

`_oos2_fetch_and_inspect.py`는 선정을 돕기 위해 pandas rolling으로 4개
raw 보조 지표를 직접 계산한다 — `trend_scanner.features`의 어떤 함수도
호출하지 않는다.

| 이름 | 계산 | 용도 |
|---|---|---|
| `range_36m_raw` | (36개월 최고 - 36개월 최저) / 36개월 최저 | 박스권 폭 |
| `position_36m_raw` | (종가 - 36개월 최저) / (36개월 최고 - 36개월 최저) | 박스권 내 위치 |
| `ma24_raw_slope_6m` | 24개월 단순이동평균의 6개월 전 대비 변화율 | "core" 대리 지표 |
| `ma12w_raw_slope_8w` | 주봉 12주 이동평균의 8주 전 대비 변화율 | "support" 대리 지표 |

**주의**: 이 4개는 production Feature(`range_36m`/`ma24_slope`/
`weekly_ma12_slope` 등)와 계산 방식·스케일이 다르다. manifest의
selection_reason에 적힌 숫자가 나중에 production Feature 계산 결과와
다르더라도 오류가 아니다 — 이 숫자들은 순전히 "어떤 시점을 볼지"
고르기 위한 참고 자료였을 뿐, Score 판단 기준으로 쓰지 않았다.

v0.1/v0.2 Score의 curve breakpoint(예: `ma24_slope` 0.05, 0.15 등)를
선정 cutoff로 쓰지 않았다 — Score 자체의 판단 기준을 선정 단계로
끌어오면 순환 논리가 되기 때문이다. Weak Core/Strong Support 같은
그룹도 "core가 거의 0이거나 음수인데 주봉은 뚜렷하게 양수"라는 구조적
서술로만 판단했다.

### Development Data와의 분리

다음은 이미 v0.2 설계에 영향을 준 데이터라 OOS2 후보에서 제외했다.

- exploration 12 + holdout 15 + negative_control 8
  (`scripts/score_v02_candidate_compare.py`의 EXPLORATION_SNAPSHOTS/
  HOLDOUT_SNAPSHOTS/NEGATIVE_CONTROL_SNAPSHOTS/FAST_MOVER_CASES)
- OOS v0.1 diagnostic 29건(`oos_v01_manifest.py`)

이 종목들의 ticker 집합과 OOS2 manifest의 ticker 집합이 교집합이
없다는 것을 `tests/test_oos_v02_manifest.py::
test_manifest_tickers_are_disjoint_from_development_tickers`가 두 집합을
코드로 직접 import해서 검증한다 — 사람이 눈으로 대조한 목록이 아니다.

OOS v0.1 선정 당시 후보로 검토했지만 최종 미사용한 종목
(011070/010950/000720/010060, `scripts/_oos_fetch_and_inspect.py`
참고)도 OOS2 후보에서 제외했다 — 이미 한 번 "선정 후보"로 본 종목이라
포함하면 ∩=0 주장이 흐려진다.

### Positive Trajectory

일부 positive 종목은 동일 종목에서 여러 snapshot을 둬서(PRE_BREAKOUT→
EARLY_TREND→TREND_PROGRESSED) Pattern A Score가 대세 상승 진행에 따라
어떻게 이동하는지 볼 수 있게 했다: 042700 한미반도체, 105560 KB금융,
086790 하나금융지주, 001040 CJ, 000880 한화. 이 trajectory 선정에서도
v0.2 Score는 전혀 보지 않았다 — 순수하게 raw 종가 흐름(박스 상단
돌파 시점, 이후 확장 여부)만 봤다.

KB금융/하나금융지주는 서로 다른 종목이지만 같은 거시 테마(은행주
밸류업 재평가, 2023년 저점 대비 2024~2025년 재상승)를 공유한다 —
development set에는 은행/보험 섹터가 전혀 없어서, 이 테마 하나로
두 개의 독립적인 trajectory 증거를 확보했다.

### Case Group 구성 (총 38건, 19개 신규 종목)

| case_group | 건수 | 목적 |
|---|---|---|
| positive_pre_breakout | 5 | 박스권 유지, 아직 돌파 전 |
| positive_early_trend | 5 | 돌파 확인 직후 |
| positive_trend_progressed | 6 | 이미 많이 진행된 상승 |
| hard_negative_false_turn | 4 | 일시 개선 후 실패 확인 |
| downtrend_reversal_boundary | 4 | Pattern A/B 경계(장기 하락 중 반등 시도) |
| strong_core_failure | 5 | core는 강했지만 이후 실패(한국타이어형) |
| weak_core_strong_support | 4 | core는 약한데 support만 강함(SKC형) |
| fast_mover | 3 | 짧은 기간에 급격한 전환 |
| insufficient_history | 2 | 36개월/24개월 history 부족 |

전체 manifest는 `src/trend_scanner/validation/oos_v02_manifest.py`의
`OOS_V02_VALIDATION_SNAPSHOTS`에 있다 — 종목/날짜/그룹/선정 근거/
expected_behavior가 전부 그 파일에 기록돼 있고, 이 문서는 그 요약이다.

### selection_reason과 Stage Audit 분리

`selection_reason`은 snapshot 이후 실제 가격 흐름(outcome)을 근거로 들
수 있다 — 예: "2024-12까지 지속 하락 확인". 이건 이 사례를 왜 검증
대상으로 뽑았는지 설명하는 것이라 outcome-conditioned 정보 사용이
허용된다.

반면 **Stage Audit**(snapshot 시점의 Pattern A Stage를 사람이 다시
판정하는 것)은 반드시 `close.index <= snapshot_date` 범위만 보고
판정해야 한다 — "다음 달 돌파", "이후 100% 상승" 같은 미래 정보를 쓰면
안 된다. Manual Stage Audit은 이 문서의 "Frozen v0.2 결과" 절에서 Score
계산과 함께 별도로 기록한다.

### 이번 라운드에서 하지 않은 것

- Score/Feature 계산(다음 commit에서 한다)
- Threshold classification(예: "70점 이상이면 성공") 설계
- 이 selection을 근거로 한 v0.2 산식 수정

## Frozen v0.2 결과

*(selection freeze commit 이후, 별도 commit에서 채운다.)*
