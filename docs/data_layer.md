# Data Layer v0.1

## 상태

종목별 일봉 OHLCV를 PyKRX에서 가져와 표준 스키마로 정규화하고, 로컬 Parquet 캐시에
저장·증분 업데이트하는 최소 구현입니다. Pattern A 점수 로직과는 무관합니다
(Pattern A는 [docs/patterns/pattern_a.md](patterns/pattern_a.md) 참고).

## 계층 구조

```text
MarketDataRepository        (repository.py)
  - cache 조회
  - 부족한 기간 판단
  - provider 호출 + validate
  - 기존 cache와 merge (증분 업데이트)
  - 요청 기간 slice 반환
        │
        ├── MarketDataProvider   (provider.py, Protocol)
        │       └── PyKrxDataProvider  (pykrx_provider.py) — PyKRX 의존성은 여기에만 존재
        │
        └── ParquetCache          (cache.py)

validator.py — validate_ohlcv(df): 구조/값 검증, 실패 시 MarketDataError
errors.py    — MarketDataError
```

Pattern/Feature/Resampler 계층은 `MarketDataProvider` Protocol과 표준 OHLCV
`DataFrame`만 알고, PyKRX를 직접 호출하지 않습니다.

## 데이터 원천

[PyKRX](https://github.com/sharebook-kr/pykrx) (`stock.get_market_ohlcv_by_date`).

**알려진 한계**: PyKRX 내부 두 백엔드(Naver 시세 / KRX 원천) 모두 응답 파싱 실패를
예외로 올리지 않고 빈 DataFrame으로 반환합니다. 즉 "거래일이 없어서 빈 응답"과
"API 응답이 깨져서 빈 응답"을 이 계층에서 구분할 수 없습니다. `validate_ohlcv`는
빈 DataFrame을 유효한 것으로 취급합니다.

**알려진 한계 2 (Feature Validation v0.1에서 발견, 관찰만 하고 아직 대응하지 않음)**:
두 백엔드 모두 휴장일(공휴일 등)을 응답에서 제외하지 않고, open/high/low/volume이
전부 0이고 close만 직전 거래일 값을 그대로 들고 있는 "phantom row"로 포함시키는
경우가 있습니다. 실측: 035420(NAVER) 2018-10-08/10/11, 005930(삼성전자)
2018-04-30~05-03. 이런 행은 `high < close` 등 OHLC 관계를 깨서 `validate_ohlcv`가
정상적으로 거부합니다(의도한 동작). 다만 10년 단위로 조회하면 이런 구간을 만날
확률이 높아, 실제로 4종목 중 2종목(NAVER, 삼성전자)이 이번 Feature Validation
실행에서 이 문제로 막혔습니다. 대응 방향(provider 단에서 phantom row 필터링 vs
validator에 허용오차 도입)은 아직 결정하지 않았습니다.

## 수정주가 정책

장기 기술적 분석(MA, Pivot Low, ATR, 장기 Range)이 액면분할/유상증자 같은 기업행동으로
왜곡되지 않도록 `adjusted=True`를 기본값으로 사용합니다.

문제는 PyKRX가 `adjusted=True`일 때 내부적으로 Naver 시세를 사용하는데, 이 경로는
`거래대금(trading_value)` 컬럼을 제공하지 않는다는 점입니다(`adjusted=False`인 KRX
원천 경로만 거래대금을 포함). 거래대금은 그날 실제 체결가 기준 값이라 과거로 소급
조정될 이유가 없으므로, 다음과 같이 처리합니다.

```text
OHLC (open/high/low/close)   <- adjusted=True 경로 (Naver)
volume                        <- adjusted=True 경로 (Naver)
trading_value                 <- adjusted=False 경로 (KRX)에서 날짜 기준으로 join
```

두 응답의 거래일이 완전히 일치하지 않으면 `trading_value`에 NaN이 생길 수 있습니다.
이 때문에 `validate_ohlcv`는 NaN 검증을 OHLC(open/high/low/close)로만 한정하고
`trading_value`는 대상에서 뺐습니다.

**미확인 사항**: `adjusted=True` 경로의 `volume`이 실제로 분할/액면 조정된 값인지는
PyKRX 소스 코드만으로는 확인되지 않습니다. 조정되지 않은 원본 거래량이라면 액면분할
시점에 거래량 기반 판단에 불연속이 생길 수 있습니다. 실제 종목(예: 2018년 삼성전자
액면분할) 데이터로 Validation 단계에서 확인이 필요합니다.

## 표준 일봉 schema

```text
DatetimeIndex (거래일 기준 오름차순)

columns:
open            float64
high            float64
low             float64
close           float64
volume          int64
trading_value   float64   # adjusted=True 경로에서는 NaN일 수 있음
```

## Parquet 캐시

`data/raw/stocks/{ticker}.parquet` (기본 경로, `ParquetCache(base_dir=...)`로 변경 가능).
`.gitignore`에 `/data/`가 포함돼 있어 캐시 파일은 커밋되지 않습니다. 주봉/월봉은
캐시하지 않고 `resampler.py`로 runtime에 일봉에서 생성합니다.

## 증분 업데이트

`MarketDataRepository.get_daily(ticker, start, end)` 호출 시:

1. 캐시가 없으면 `[start, end]` 전체를 조회한다.
2. 요청 시작일이 캐시 최소일보다 이르면(과거 구간 백필) `[start, end]` 전체를
   다시 조회한다.
3. 그 외에는 캐시 최근 `DEFAULT_OVERLAP_DAYS`(기본 5일) 구간부터 `end`까지만
   다시 조회해서, 정정될 수 있는 최근 데이터를 새 API 값으로 덮어쓴다.
4. 위 두 경우 모두 해당 없으면(요청 구간이 이미 안정된 과거 캐시 안에 완전히
   들어있으면) provider를 호출하지 않는다.

병합 시 동일 거래일이 캐시와 새 조회 결과 양쪽에 있으면 새 API 결과를 우선한다.
병합 후 정렬하고 중복 거래일을 제거해 캐시에 다시 저장한 뒤, 요청 구간만 slice해서
반환한다.

## 검증 시점

`validate_ohlcv`는 세 지점에서 실행된다.

1. provider가 새로 조회한 데이터(캐시 반영 전)
2. **캐시에서 읽은 기존 데이터**(non-empty일 때, provider 호출 여부와 무관하게)
3. **캐시와 병합한 결과**(캐시에 다시 저장하기 직전)

2번이 있어서, 요청 구간이 이미 안정된 과거 캐시로 완전히 커버돼 provider를 호출하지
않는 "stable cache hit" 경로에서도 깨진 Parquet·예전 schema·중복 index 같은 문제가
검증 없이 Pattern 계층까지 그대로 흘러가지 않는다.

**주의**: 이전에는 캐시가 깨져 있어도 다음 조회에서 provider가 다시 호출되면서 새
데이터로 자연히 덮어써질 여지가 있었지만, 이제는 깨진 캐시를 만나는 즉시
`MarketDataError`로 실패한다. 복구는 자동으로 되지 않으며, 해당 종목의
`data/raw/stocks/{ticker}.parquet` 파일을 수동으로 지워야 한다.

## 완료 봉 처리

Data Layer는 "이번 달/이번 주 봉이 완성됐는지"를 판단하지 않습니다. 오늘까지 존재하는
일봉을 그대로 반환하며, 완료된 봉만 쓸지는 Feature/Pattern 계층의 책임입니다.

## KRX 로그인 credential

`adjusted=False`(KRX 원천, 거래대금 조회용) 경로는 `KRX_ID`/`KRX_PW` 환경 변수가
있으면 PyKRX가 내부적으로 로그인 세션을 사용합니다. 없어도 익명 요청으로 폴백은
하지만, 최근 KRX 쪽에서 익명 스크래핑을 막는 경우가 있어 실전에서는 계정이
필요할 수 있습니다.

- 실제 ID/PW는 코드·README·테스트·로그·예외 메시지 어디에도 하드코딩하지 않고
  `KRX_ID`/`KRX_PW` 환경 변수로만 읽습니다.
- 로컬 개발은 저장소 루트의 `.env` 파일을 사용합니다(`.gitignore`에 포함, 커밋되지
  않습니다). `.env.example`을 복사해서 실제 값을 채우세요.

  ```bash
  cp .env.example .env
  # .env를 열어 KRX_ID / KRX_PW에 실제 값을 채운다
  ```

- `pykrx_provider.py`는 import 시점에 `python-dotenv`로 `.env`를 자동으로 읽어
  환경 변수로 등록합니다(이미 export된 환경 변수가 있으면 그걸 우선합니다).
- Integration test(`tests/test_pykrx_provider_integration.py`)는 `KRX_ID`/`KRX_PW`가
  없으면 자동으로 skip되고, 일반 unit test는 credential 유무와 무관하게 항상
  정상 실행됩니다.
- **알려진 한계**: PyKRX의 로그인 함수(`pykrx.website.comm.auth.build_krx_session`)가
  로그인 시도 시 `KRX_ID` 값(비밀번호는 아님)을 자체적으로 `print`합니다. 이건
  PyKRX 라이브러리 자체의 동작이라 이 프로젝트 코드로 막을 수 없습니다. CI 등에서
  표준출력이 로그로 남는 환경이라면 유의하세요.
