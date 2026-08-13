# krx-trend-scanner

코스피와 코스닥 전 종목을 대상으로 **대세 상승 초입에 진입하는 종목을 정량적으로 탐색하기 위한 스크리너 프로젝트**입니다.

단순히 이미 상승 중인 종목을 찾는 것이 아니라, 월봉과 주봉을 중심으로 장기 가격 구조와 추세 변화를 분석해 **상승 추세가 막 만들어지기 시작하는 후보**를 선별하는 것을 목표로 합니다.

## 주요 목표

* 장기 추세 전환 초기 구간 탐지
* 장기 박스권과 저점 상승 구조 정량화
* 이동평균선 수렴 및 기울기 변화 분석
* 변동성 축소와 돌파 준비 상태 측정
* 시장 지수 대비 상대강도 분석
* 패턴 점수와 점수 모멘텀을 이용한 후보 우선순위화

## 분석 기본 프레임

월봉과 주봉을 주요 분석 프레임으로 사용합니다.

일봉은 전체 시장을 스크리닝하는 핵심 기준보다는 단기 추세와 실제 진입 타이밍을 확인하는 용도로 사용합니다.

스크리너는 단순한 이동평균 정배열보다 다음과 같은 구조적 변화를 중요하게 평가합니다.

* 장기 하락 추세 둔화
* 이동평균선 평탄화
* 이동평균선 수렴
* 저점 상승
* 변동성 감소
* 장기 저항선 접근
* 상대강도 개선

## 패턴 기반 스크리닝

서로 다른 대세 상승 초기 구조를 여러 패턴으로 구분하여 평가할 예정입니다.

초기 구상은 다음과 같습니다.

### Pattern A: 장기 베이스 수렴형

장기간 박스권 또는 횡보 구간을 형성하면서 저점이 점차 상승하고, 장기 이동평균선이 평탄화 및 수렴하는 형태입니다.

주요 특징:

* 장기간의 가격 횡보
* 저점의 점진적 상승
* 장기 이동평균선의 하락 둔화
* 이동평균선 간격 축소
* 변동성 감소
* 장기 저항선 접근

자세한 스펙은 [docs/patterns/pattern_a.md](docs/patterns/pattern_a.md)를 참고하세요.

### 향후 패턴 후보

* Pattern B: 장기 하락 추세 종료 및 Stage 2 전환형
* Pattern C: 신고가 직전 고점 압축형
* Pattern D: 상대강도 선행형
* Pattern E: 장기 변동성 수축형
* Pattern F: 실적 턴어라운드 + 차트 선행형

## 점수 시스템

각 패턴은 독립적인 점수를 계산합니다.

예:

```text
Pattern A Score      86

Base Quality         22 / 25
Low Structure        18 / 20
MA Transition        23 / 25
Volatility           11 / 15
Breakout Position    12 / 15
```

최종적으로는 여러 패턴 점수와 상대강도, 수급, 실적 등을 조합해 종합적인 대세 상승 후보 점수를 만들 예정입니다.

또한 현재 점수뿐 아니라 시간에 따른 점수 변화도 중요하게 평가합니다.

예:

```text
5주 전    58
4주 전    63
3주 전    69
2주 전    74
1주 전    79
현재      84
```

현재 90점인 종목보다 이런 식으로 **점수가 지속적으로 상승하는 종목이 대세 상승 초입 탐지 목적에 더 적합할 수 있습니다.**

## 프로젝트 구조

```text
krx-trend-scanner/
├── README.md
├── pyproject.toml
├── .gitignore
│
├── src/
│   └── trend_scanner/
│       ├── data/
│       │   ├── loader.py
│       │   └── resampler.py
│       │
│       ├── features/
│       │   ├── moving_average.py
│       │   ├── pivot.py
│       │   ├── volatility.py
│       │   └── resistance.py
│       │
│       ├── patterns/
│       │   └── pattern_a.py
│       │
│       └── models/
│           └── score.py
│
├── tests/
│
└── docs/
    └── patterns/
        └── pattern_a.md
```

Pattern 로직은 데이터 공급자와 분리됩니다. `patterns/pattern_a.py`는 PyKRX 등 특정 데이터 소스를 직접 호출하지 않고, 표준 OHLCV `DataFrame`만 입력받습니다.

```text
데이터 수집
↓
표준 OHLCV DataFrame
↓
주봉 / 월봉 변환
↓
Feature 계산
↓
Pattern 평가
```

## 현재 개발 단계

현재는 프로젝트 골격과 재사용 가능한 Feature 함수(이동평균 기울기, Pivot Low, ATR%, Range Position 등) 위주로 구현돼 있습니다.

Pattern A의 점수 산식, Hard Filter 임계값은 아직 검증되지 않은 초기 후보값이며 [docs/patterns/pattern_a.md](docs/patterns/pattern_a.md)에 문서로만 정리돼 있고, `evaluate_pattern_a`는 아직 구현되지 않았습니다.

초기 단계에서는 정확도보다 좋은 후보를 놓치지 않는 것을 우선하며, 실제 종목 데이터를 이용해 False Positive를 분석하면서 규칙과 임계값을 반복적으로 개선할 예정입니다.

## 개발 환경

```bash
pip install -e ".[dev]"
pytest
```
