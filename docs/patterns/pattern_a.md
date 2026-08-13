# Pattern A: 장기 베이스 수렴형 (Long Term Base Convergence)

## 상태

스펙 정의 단계입니다. `evaluate_pattern_a`는 아직 구현되지 않았으며, 아래 점수 산식과 임계값은
모두 **초기 후보값**입니다. 실제 종목 데이터로 검증한 뒤 조정합니다.

## 목표

다음 구조를 가진 차트를 찾습니다.

```text
장기간 횡보
+
저점 상승
+
장기 이동평균 하락 종료
+
이동평균 수렴
+
변동성 감소
+
장기 저항 접근
```

## 분석 기간

월봉 중심입니다.

```text
전체 데이터 확보        최소 약 5년

월봉 분석               최근 48개월
장기 Base               최근 36개월
저점 구조               최근 24~36개월
이평 수렴               최근 12개월

주봉 보조 확인          최근 52주 이상
```

일봉 데이터를 원본으로 저장하고 이후 Pandas에서 주봉과 월봉을 생성하는 구조를 사용합니다
(`src/trend_scanner/data/resampler.py`).

## 점수 구성 (100점 만점)

| 영역                     |  점수 |
| ---------------------- | --: |
| Base Quality           |  25 |
| Low Structure          |  20 |
| MA Transition          |  25 |
| Volatility Compression |  15 |
| Breakout Position      |  15 |
| 합계                     | 100 |

가중치는 `src/trend_scanner/patterns/pattern_a.py`의 `PATTERN_A_WEIGHTS`에 상수로 고정돼 있습니다.

## Base Quality (25)

목적은 단순 하락 종목이 아니라 실제 장기 베이스가 만들어지고 있는지 판별하는 것입니다.

주요 Feature: 36개월 가격 Range, 24개월 가격 Range, 12개월/36개월 Range 압축비, 가격 중심값 변화, 장기 고점 기울기.

```python
high_36m = monthly["high"].tail(36).max()
low_36m = monthly["low"].tail(36).min()

range_36m = (high_36m - low_36m) / monthly["close"].tail(36).mean()

compression_ratio = range_12m / range_36m
```

초기 점수 후보:

```text
36개월 Range 과도하지 않음        +5
24개월 Range 축소                 +5
12M / 36M 압축비 < 0.6            +5
최근 중심가격 변화가 제한적        +5
장기 고점 급락 없음               +5
```

## Low Structure (20)

단순히 가격이 오르는 것이 아니라 주요 저점이 점차 높아지는 구조를 찾습니다.
월봉 Pivot Low를 탐색한 뒤(`features/pivot.py`의 `find_pivot_lows`) 최근 주요 저점의 기울기를
계산합니다(`pivot_low_regression_slope`).

초기 평가 요소:

```text
최근 주요 저점 상승
Pivot Low Regression Slope > 0
최근 저점이 장기 최저점보다 높음
최근 주요 저점 이탈 없음
```

**주의**: 저점 상승만으로 높은 점수를 주면 안 됩니다. 이미 강하게 상승하고 있는 종목 역시 당연히
저점이 상승하기 때문입니다. Proxy 테스트(아래 참고)에서 확인된 문제로, 최종적으로는 다음과 결합해야 합니다.

```text
저점 상승
+
고점 기울기는 상대적으로 평평
+
장기 가격 Range 제한
```

## MA Transition (25)

Pattern A에서 가장 중요한 영역입니다. 정배열 자체가 아니라 **기울기의 변화**가 핵심입니다.

```text
MA24

강한 하락
→ 완만한 하락
→ 평평
→ 상승
```

월봉 이동평균 MA6 / MA12 / MA24 사용을 우선 검토합니다 (`features/moving_average.py`).

초기 점수 후보:

```text
MA6 상승                     +5
MA12 평탄 또는 상승          +5
MA24 강한 하락 아님          +5
MA24 slope 개선              +5
MA6 / MA12 / MA24 수렴       +5
```

### MA Spread

세 이동평균의 간격을 정규화해서 계산합니다 (`ma_spread`, `ma_spread_ratio`).

```text
12개월 전 MA Spread     20%
현재 MA Spread           7%

Spread Ratio            0.35
```

초기 기준 후보:

```text
현재 MA Spread <= 약 10~12%
12개월 전 대비 Spread <= 60%
```

## Volatility Compression (15)

장기 베이스 후반부에서 변동성이 감소하는지 평가합니다 (`features/volatility.py`의 `atr_pct`).

정식 구현에서는 ATR %, Bollinger Band Width, 월봉 High-Low Range, 거래량 변화를 사용합니다.

초기 점수 후보:

```text
ATR 감소                       +5
BB Width 장기 평균 이하        +5
최근 월봉 Range 감소           +3
거래량 압축                    +2
```

거래량 감소는 단독으로 강한 신호로 취급하지 않습니다. 관심이 사라진 종목 역시 거래량이 감소할 수
있기 때문입니다.

## Breakout Position (15)

현재 가격이 장기 베이스의 어느 위치에 있는지 평가합니다 (`features/resistance.py`).

36개월 고점을 초기 장기 저항 프록시로 사용합니다.

```python
distance_to_resistance = (resistance - close) / resistance
range_position = (close - low_36m) / (high_36m - low_36m)
```

```text
0.0     장기 Range 최하단
0.5     중간
0.7     상단 진입
0.9     저항 직전
1.0     최고점
```

Pattern A는 대략 `range_position >= 0.65~0.70` 정도를 관심 영역으로 고려합니다.

## Hard Filter

총점과 별개로 명백하게 Pattern A가 아닌 종목을 제거합니다. 초기 후보:

```text
MA24가 아직 강하게 하락 중
최근 주요 저점 붕괴
장기 Range 하단 위치
장기 고점이 계속 크게 하락
유동성 부족
```

예:

```python
if range_position < 0.45:
    reject = True

if ma24_slope_6m < -0.08:
    reject = True
```

정확한 임계값은 검증 후 수정합니다.

## 저장해야 할 Feature

점수만 저장하지 않습니다. 디버깅과 규칙 개선을 위해 원본 Feature를 같이 저장합니다
(`patterns/pattern_a.py`의 `PatternAResult`).

```text
ticker
name

pattern_a_score

base_score
low_score
ma_score
volatility_score
breakout_score

ma6_slope
ma12_slope
ma24_slope

ma24_slope_acceleration

ma_spread
ma_spread_12m_ago
ma_spread_ratio

low_regression_slope

atr_pct
atr_ratio

distance_to_resistance
range_position
```

이렇게 해야 "왜 이 종목이 91점인가?"를 추적할 수 있습니다.

## Score Momentum

매주 또는 매일 Pattern Score를 저장합니다 (`models/score.py`).

```text
4주 전     62
3주 전     68
2주 전     73
1주 전     79
현재       85
```

단순 현재 점수뿐 아니라 다음을 중요하게 평가합니다.

```python
score_momentum_4w = current_score - score_4w_ago
```

목표는 이미 완성된 강한 상승주보다 점수가 빠르게 개선되고 있는 초기 후보를 찾는 것입니다.

## Proxy 테스트에서 확인한 문제

임시 월별 종가 데이터로 셀트리온, NAVER, 삼성전자, SK하이닉스 등을 테스트했습니다. 정확한 정식
점수는 아니었지만 중요한 문제 하나를 확인했습니다.

SK하이닉스처럼 이미 대세 상승이 상당히 진행된 종목도 "저점 상승 + MA 상승" 조건만 보면 높은
점수를 받을 수 있습니다. 따라서 Low Structure는 독립적으로 평가하면 안 되고, 다음 조합이
중요합니다.

```text
저점 상승
AND
고점은 상대적으로 평평
AND
장기 Range 제한
AND
MA가 이미 너무 확산되지 않음
```

즉 Pattern A는 단순 Higher Low 패턴이 아니라 **수렴하는 장기 Base 내부의 Higher Low**여야 합니다.
