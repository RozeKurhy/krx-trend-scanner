# Pattern B 개발 표본 V02 차트 묶음

> 상태: 36개 차트 생성·봉인 완료. 사람 판정 대기.

## 차트 계약

[차트 묶음 V01](chart_pack_v01.md)과 [별도 검증 표본 V02](holdout_v02_protocol.md)의 계약을 그대로
쓴다.

- Repository V2 조정 가격을 종목 구간 시작일부터 기준일까지만 읽는다.
- 한 PNG(1600×1200)에 완료된 월봉 84개(위)와 주봉 156개(아래)를 흑백 캔들로 그린다. 진행
  중인 기간은 넣지 않는다.
- 가격은 패널별 첫 종가를 `100`으로 맞춘 표시용 값이며, y축은 선형 눈금이다.
- 거래량, 이동평균, 지표, 종목명, 종목코드, 날짜는 표시하지 않는다. 차트에는 표본 식별자만 있다.
- 거래정지 기간은 x축에 실제 시간 공백으로 남긴다. 기준일에 거래정지 중인 종목은 표본에서
  제외했다.

## 생성 결과

- 36장 모두 생성했다. 월봉 84개·주봉 156개, 기준일 이후 데이터 0건이다.
- 거래정지 공백이 있는 표본은 2개이며, 원시 데이터로 모두 실제 거래정지(거래량 0 자리표시
  행)임을 확인했다.
- 같은 대응표로 다시 생성하면 차트 묶음 ZIP이 같은 SHA-256으로 재현된다.

## 파일 위치와 Git 관리

산출물은 `artifacts/pattern_b_development_v02/`에 두고 Git에 올리지 않는다.

| 경로 | 내용 |
|---|---|
| `blind/` | PNG 36장, 빈 판정 양식 `annotation_template.csv` |
| `pattern_b_development_v02_blind_pack.zip` | 판정자 전달용 묶음 (`blind/`의 37개 파일) |
| `private/development_v02_private_manifest.csv` | 표본 식별자와 종목코드·기준일 대응표 (권한 600) |
| `private/selection_audit.json`, `private/verification_summary.json` | 선정·검증 기록 |

대응표는 Git 밖(`~/krx_private_backups/pattern_b_development_v02/`)에도 백업했다.
