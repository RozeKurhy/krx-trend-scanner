# F7 Fundamentals V1 data-quality and Web presentation fix

- 기준일: `2026-09-04`
- 실행일: `2026-09-10`
- 결과: `PASS`

## Root cause

- 코웨이 `021240`의 Q1 filing은 FilingRegistry에서 확인됐지만 원본·기재정정 filing(`20240514001085`, `20240514001464`)의 XBRL ZIP이 로컬 cache에 없었어. 라이브 호출 없이 값을 만들지 않아 Q1은 `DATA_UNAVAILABLE`로 보존했어.
- Q2/Q3/FY CFS에는 `dart_OperatingIncomeLoss`와 `ifrs-full_ProfitLossFromOperatingActivities`가 같은 누적 경제 범위에서 서로 다른 값을 갖는 경우가 확인됐어. 이 충돌은 `PERIOD_AMBIGUOUS`로 보존했어.
- 반면 단독분기 영업이익이 하나만 존재하면, 서로 다른 누적 범위의 충돌이 단독분기 값을 가리지 않도록 일반 기간화 규칙을 수정했어.

## Result

- affected F7 대상: `29`
- published Stock Report 대상: `10`
- OpenDART live request: `0`
- F7: `4,415/4,415`, remaining `0`, invalid/outside/duplicate `0`
- Stock Report v0.5: `553`, schema errors `0`, F7 parity `553/553`
- Web compact: `553`, public Fundamentals parity `553/553`
- 코웨이: 2024Q2 영업이익 `211,194,775,407`, YoY `8.7671%`; 2024Q3 영업이익 `207,051,057,484`, YoY `6.0080%`

상세 machine-readable 근거는 `summary.json`에 기록했어.
