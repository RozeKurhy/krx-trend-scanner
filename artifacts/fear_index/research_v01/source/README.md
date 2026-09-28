# V-KOSPI 200 official acquisition source

These original nine CSV files are preserved from the KRX Data Marketplace screen:

`통계 > 기본 통계 > 지수 > 파생 및 기타지수 > 개별지수 시세 추이`

The selected KRX index was `코스피 200 변동성지수` (V-KOSPI 200). The KRX
download was chunked because the screen limits a query to two years. The
browser-downloaded files were CP949 CSVs; the repository copies are UTF-8
decoded text copies with the same rows and values. The original download
filenames and SHA-256 hashes are recorded in `krx_acquisition_validation.json`.

`v_kospi200_daily_normalized.csv` is the ascending, numeric normalized copy
used by the exact-date research join.

For the 2026-09-25 target, the official KRX screen was queried for
2026-09-22 through 2026-09-23. Its two returned rows were saved separately in
`v_kospi200_2026-09-22_2026-09-23_official.csv`; the pre-existing annual file
and all rows through 2026-09-21 were left unchanged.
