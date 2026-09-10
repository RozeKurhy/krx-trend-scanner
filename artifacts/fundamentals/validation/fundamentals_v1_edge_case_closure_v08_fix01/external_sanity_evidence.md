# FIX01 external sanity evidence

- Requested as-of: `2026-09-04`; validation run: `2026-09-10`; seed: `20260910_05`.
- Pool: `436` COMMON reports with `applicability=APPLICABLE` and no prior-sample exclusion; selected 10 without READY/PASS/non-null prefilter.
- Live Naver requests: `20` public FnGuide/Naver Securities JSON calls (annual and quarterly per ticker). Values are reported in 억원 and converted to KRW; Naver-missing periods are marked `SOURCE_MISSING`.
- Comparison tolerance: 100,000,000 KRW, matching the displayed Naver unit rounding. No Naver value is written into production payloads.
- A live value outside tolerance is classified as `NAVER_BASIS_OR_STALENESS` only when the PIT production value has explicit OpenDART periodization source evidence; the reason records the source filing, method, basis label, and any later cached comparative match.

## Selected tickers

| Ticker | Name | Status counts |
|---|---|---|
| 085660 | 차바이오텍 | {'MATCH_ROUNDED_NAVER_UNIT': 20, 'NAVER_BASIS_OR_STALENESS': 1, 'SOURCE_MISSING': 3} |
| 035720 | 카카오 | {'MATCH_ROUNDED_NAVER_UNIT': 17, 'NAVER_BASIS_OR_STALENESS': 4, 'SOURCE_MISSING': 3} |
| 402340 | SK스퀘어 | {'MATCH_ROUNDED_NAVER_UNIT': 13, 'NAVER_BASIS_OR_STALENESS': 8, 'SOURCE_MISSING': 3} |
| 006400 | 삼성SDI | {'MATCH_ROUNDED_NAVER_UNIT': 13, 'NAVER_BASIS_OR_STALENESS': 8, 'SOURCE_MISSING': 3} |
| 043260 | 성호전자 | {'MATCH_ROUNDED_NAVER_UNIT': 21, 'SOURCE_MISSING': 3} |
| 006120 | SK디스커버리 | {'MATCH_ROUNDED_NAVER_UNIT': 20, 'NAVER_BASIS_OR_STALENESS': 1, 'SOURCE_MISSING': 3} |
| 119850 | 지엔씨에너지 | {'MATCH_ROUNDED_NAVER_UNIT': 21, 'SOURCE_MISSING': 3} |
| 272210 | 한화시스템 | {'MATCH_ROUNDED_NAVER_UNIT': 17, 'NAVER_BASIS_OR_STALENESS': 4, 'SOURCE_MISSING': 3} |
| 003620 | KG모빌리티 | {'MATCH_ROUNDED_NAVER_UNIT': 21, 'SOURCE_MISSING': 3} |
| 032190 | 다우데이타 | {'MATCH_ROUNDED_NAVER_UNIT': 21, 'SOURCE_MISSING': 3} |

- Aggregate status counts: `{'MATCH_ROUNDED_NAVER_UNIT': 184, 'NAVER_BASIS_OR_STALENESS': 26, 'SOURCE_MISSING': 30}`.
- Acceptance: `PASS`; wrong sign `0`, unexplained mismatch `0`, unexpected OUR_MISSING `0`.

## Public references

- [Naver Securities 085660](https://finance.naver.com/item/main.naver?code=085660)
- [Naver Securities 035720](https://finance.naver.com/item/main.naver?code=035720)
- [Naver Securities 402340](https://finance.naver.com/item/main.naver?code=402340)
- [Naver Securities 006400](https://finance.naver.com/item/main.naver?code=006400)
- [Naver Securities 043260](https://finance.naver.com/item/main.naver?code=043260)
- [Naver Securities 006120](https://finance.naver.com/item/main.naver?code=006120)
- [Naver Securities 119850](https://finance.naver.com/item/main.naver?code=119850)
- [Naver Securities 272210](https://finance.naver.com/item/main.naver?code=272210)
- [Naver Securities 003620](https://finance.naver.com/item/main.naver?code=003620)
- [Naver Securities 032190](https://finance.naver.com/item/main.naver?code=032190)
