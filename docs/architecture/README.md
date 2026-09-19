# 아키텍처 (Architecture)

특정 Pattern에 종속되지 않는 공용 인프라 문서의 내비게이션이다. 현재 운영
기준을 먼저 확인한 뒤 세부 계약과 과거 기록으로 내려간다.

## A. 현재 핵심 아키텍처

현재 운영 구조를 파악할 때는 다음 다섯 문서를 먼저 읽는다.

| 문서 | 현재 역할 |
|---|---|
| [krx_production_data_architecture_v01.md](krx_production_data_architecture_v01.md) | 현재 운영 데이터 아키텍처 전체 기준 |
| [market_data_repository_v02.md](market_data_repository_v02.md) | 수정주가와 원천 일별 데이터를 결합해 실제 사용 코드에 제공하는 현재 시장데이터 계층 |
| [instrument_metadata_authority.md](instrument_metadata_authority.md) | 종목 메타데이터·자산 유형·PIT 분류의 현재 기준 |
| [survivorship_safe_denominator_freeze_v01.md](survivorship_safe_denominator_freeze_v01.md) | 과거 백테스트와 PIT 종목 집합의 생존편향 방지 기준 |
| [daily_update_contract_v01.md](daily_update_contract_v01.md) | 특정 기준일까지 운영 데이터를 일관되게 증분 갱신하는 데일리 업데이트 기준 |

데일리 업데이트의 단계별 상세 계약은 상위 기준 문서 아래에 둔다.

```text
데일리 업데이트 기준 V01
├─ 2단계: 주봉·월봉 파생 기준 V01
├─ 3단계: 분석 입력 갱신 기준 V01
└─ 4단계: 분석·리포트·웹 반영 기준 V01
```

| 단계 | 상세 계약 | 한 줄 역할 |
|---|---|---|
| 2단계 | [주봉·월봉 파생 기준 V01](daily_update_phase2_weekly_monthly_derivation_contract_v01.md) | 인증된 일봉에서 주봉·월봉을 파생하고 기간 완료 상태를 판정하는 기준 (`COMPLETE`) |
| 3단계 | [분석 입력 갱신 기준 V01](daily_update_phase3_analysis_inputs_contract_v01.md) | 수급·펀더멘털·시장·업종 RS 등 분석 입력을 기준일에 맞춰 갱신하는 기준 (`COMPLETE`) |
| 4단계 | [분석·리포트·웹 반영 기준 V01](daily_update_phase4_analysis_reporting_web_contract_v01.md) | 스캐너·공식 전략·Stock Report v0.5·필수 웹 투영을 같은 기준일에 연결하는 기준 (상세 계약 확정 / 구현 예정) |

## B. 현재 세부 데이터 계약

위 다섯 문서의 세부 저장소·원천·전환 계약은 다음 문서에서 확인한다.

| 문서 | 한 줄 역할 |
|---|---|
| [adjusted_price_store_v02.md](adjusted_price_store_v02.md) | 현재 수정주가 OHLC 저장소 V02 계약 |
| [corporate_action_dirty_refresh_v01.md](corporate_action_dirty_refresh_v01.md) | 기업행위 변경 감지와 수정주가 갱신 상태 |
| [krx_historical_backfill_v01.md](krx_historical_backfill_v01.md) | KRX 원천 과거 데이터 백필 계약 |
| [krx_index_migration_v01.md](krx_index_migration_v01.md) | KOSPI/KOSDAQ 시장 대표지수 원천 경계 |
| [sector_rs_krx_migration_v01.md](sector_rs_krx_migration_v01.md) | Sector RS 지수와 기준일별 구성 종목 기준 |
| [historical_snapshot.md](historical_snapshot.md) | 과거 시점 검증과 엄격한 PIT 스냅샷 |

세부 계약의 원문을 이 README에 반복하지 않는다. 각 문서의 현재 상태와
권위 표기를 따른다.

## C. 과거·보조·검증 문서

다음 문서는 현재 핵심 아키텍처와 같은 급의 운영 기준이 아니라 과거 기록,
보정 기록, 정보 구조 감사 또는 검증 자료다.

| 문서 | 역할 |
|---|---|
| [archive/adjusted_price_store_v01.md](archive/adjusted_price_store_v01.md) | 과거 V01 수정주가 저장소 구현·검증 계약 기록 |
| [data_layer.md](data_layer.md) | 과거 공용 데이터 레이어 v0.1 기록이며 현재 운영 데이터 레이어가 아님 |
| [krx_dual_provider_contract_v01.md](krx_dual_provider_contract_v01.md) | 과거 데이터 제공자 전환 계약 |
| [errata/krx_identifier_contract_errata_v01.md](errata/krx_identifier_contract_errata_v01.md) | KRX 식별자 계약 보정 기록 |
| [artifacts/artifacts_information_architecture_audit_v01.md](artifacts/artifacts_information_architecture_audit_v01.md) | 산출물 정보 구조와 계보 감사 |
| [validation/](validation/) | 아키텍처 검증과 테스트 기반 문서 |
| [archive/validation/](archive/validation/) | 과거·대체된 KRX 원천 검증과 조사 기록 |

`archive/`와 이 영역의 과거 문서는 현재 운영 권위를 대신하지 않는다. 현재
무엇을 먼저 읽어야 하는지는 A 영역의 다섯 문서와 해당 문서의 링크를 기준으로
판단한다.
