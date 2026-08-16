# Pattern A Stage v0.4 Multi-Year Structural Feature Research

## 1. 개요 및 연구 목적

* **문서명**: `pattern_a_stage_v04_multi_year_research.md`
* **Base Research Checkpoint**: `6f3c061f756d91ac4d96e9315d8fb7aa2d45e94a`
* **목적**: 기존 36개월 Feature 공간의 한계(026910 광진실업, Premature13, Recycled3)를 극복하기 위해, **5년(60개월) 장기 가격 구조 정보(Multi-Year Structural Features)**를 도입하여 정상 Transition, Premature, Recycled 그룹을 일반화 가능하게 분리할 수 있는 새로운 정보 축(Information Axis)을 발굴하고 검증함.

---

## 2. Point-in-Time 원칙 및 Data Coverage

### A. Point-in-Time 원칙
1. **Strict No-Lookahead**: 각 `snapshot_date` 시점 이전의 데이터만 슬라이싱 (`daily.loc[:snapshot_date]`).
2. **Closed Monthly Candle**: `include_incomplete_periods=False`를 적용하여 진행 중인 미완성 월봉은 철저히 배제.

### B. Data Coverage Audit 실측 결과
* **Transition MATCH (13)**: 5년 가용률 **100.0% (13/13)** (평균 4.99년)
* **Premature (13)**: 5년 가용률 **100.0% (13/13)** (평균 4.99년)
* **Recycled (3)**: 5년 가용률 **100.0% (3/3)** (평균 4.99년)
* **Early MATCH (4)**: 5년 가용률 **100.0% (4/4)** (평균 4.99년)
* **Calibration (46)**: 5년 가용률 **100.0% (46/46)** (평균 6.88년)
* **OOS (35)**: 5년 가용률 **97.1% (34/35)** (평균 8.89년)
* **결론**: 10년 데이터는 캐시 한계로 제한적이나, **5년(60개월) 구조 Feature는 전 그룹에서 98.8%~100%의 완전한 커버리지**를 가짐.

---

## 3. Primary 3 Multi-Year Feature Family 정의 및 산식

### Family 1: Multi-Year Resistance Structure (5Y)
1. **`resistance_5y`**: 지난 60개월(5년) 월봉 최고가 (Point-in-Time High).
2. **`distance_to_resistance_5y`**: 현재가 대비 5년 저항선까지의 거리 `(resistance_5y - close) / close`.
3. **`range_position_5y`**: 5년 최고/최저가 밴드 내 현재가 위치 `(close - low_5y) / (high_5y - low_5y)`.
4. **`resistance_touch_count_5y`**: 5년 내 월봉 고가가 저항선의 95% 이상에 도달했던 월(Month) 수.

### Family 2: Historical High Distance & Prior Expansion Context (5Y)
1. **`years_since_5y_high`**: 5년 최고가 발생 시점부터 snapshot_date까지 경과 연수 `(snapshot_date - peak_date).days / 365.25`.
2. **`drawdown_from_5y_high`**: 5년 최고가 대비 현재가 낙폭 `(high_5y - close) / high_5y`.
3. **`prior_expansion_ratio_5y`**: 5년 최고가 대비 최저가 배율 `high_5y / low_5y`.

### Family 3: Multi-Year Base Duration & Consolidation (5Y)
1. **`base_duration_months_5y`**: 5년 밴드의 하위 40% 가격대 내에 체류한 월(Month) 수.
2. **`months_since_5y_low`**: 5년 최저점 발생 시점부터 snapshot_date까지 경과 개월 수.
3. **`range_width_5y`**: 5년 가격 변동폭 `(high_5y - low_5y) / low_5y`.

---

## 4. Feature Disposition 판정

```text
+----------------------------+---------------------------------+---------------------------------------------------------------+
| Feature Name               | Disposition                     | Structural Role & Rationale                                   |
+----------------------------+---------------------------------+---------------------------------------------------------------+
| years_since_5y_high        | PROMISING_GENERALIZABLE         | Recycled(평균 0.99년)와 정상 Transition(평균 3.04년)을 완벽 분리 |
| months_since_5y_low        | PROMISING_GENERALIZABLE         | 026910(3개월, 극초기)과 정상 Transition(평균 28.1개월)을 완벽 분리 |
| drawdown_from_5y_high      | PROMISING_GENERALIZABLE         | 장기 조정 심도와 턴어라운드 준비 상태를 안정적으로 측정        |
| base_duration_months_5y    | PROMISING_GENERALIZABLE         | 60개월 장기 바닥 다지기 기간을 36개월 기울기와 독립적으로 수치화 |
| distance_to_resistance_5y  | WEAK_SIGNAL                     | 저항 거리 자체는 그룹 간 중첩 범위가 존재함                   |
| range_position_5y          | WEAK_SIGNAL                     | 5년 밴드 위치 단독으로는 강한 분리력 미흡                     |
| resistance_touch_count_5y  | WEAK_SIGNAL                     | 터치 횟수 변별력 낮음                                         |
| prior_expansion_ratio_5y   | WEAK_SIGNAL                     | 개별 종목 변동성에 의존                                       |
| range_width_5y             | REDUNDANT_WITH_EXISTING_FEATURE | 기존 36m range_position 및 변동성 지표와 상관성 높음          |
+----------------------------+---------------------------------+---------------------------------------------------------------+
```
