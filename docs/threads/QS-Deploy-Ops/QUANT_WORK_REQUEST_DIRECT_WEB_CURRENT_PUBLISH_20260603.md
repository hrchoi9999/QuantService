# Quant 웹 current 직접 publish 운영정렬 요청서

- 작성일: 2026-06-03
- 요청 출처: QuantService
- 대상 쓰레드: Quant
- 목적: Quant current 웹 데이터가 QS 동기화 없이 redbot.co.kr에 즉시 반영되도록 직접 GCS publish 운영 상태를 확인/정렬한다.

## 배경

QS는 2026-06-03 커밋 `4c30497`부터 `sync_web_data_to_quantservice.ps1`의 기본 동작을 GCS publish가 아닌 로컬 fallback 갱신으로 변경했다.

운영 원칙은 다음과 같다.

- Quant는 Quant 모델/성과/변경내역/t-series 웹 current 생성과 GCS publish의 1차 책임을 가진다.
- QS는 GCS current를 조회한다.
- QS 동기화 스크립트의 GCS publish는 장애 복구용으로만 `-PublishToGcs`를 명시해 사용한다.

## 요청사항

1. Quant 자동/애드혹 파이프라인에서 current 파일 생성 직후 GCS current publish가 실행되는지 확인한다.
2. 정상 운영 작업에서 `--skip-remote-current-publish` 또는 유사 skip 옵션이 사용되지 않도록 정리한다.
3. publish 성공 후 cache-buster URL로 재조회하여 `generated_at` 또는 manifest 기준 시간이 최신 산출물과 일치하는지 검증한다.
4. publish 실패 시 작업이 성공으로 끝나지 않도록 non-zero exit 또는 명확한 실패 로그를 남긴다.

## 주요 대상

로컬 current 예시:

- `D:\Quant\service_platform\web\public_data\current\publish_manifest_user.json`
- `D:\Quant\service_platform\web\public_data\current\user_model_catalog.json`
- `D:\Quant\service_platform\web\public_data\current\user_model_snapshot_report.json`
- `D:\Quant\service_platform\web\public_data\current\user_performance_summary.json`
- `D:\Quant\service_platform\web\public_data\current\user_recent_changes.json`
- `D:\Quant\service_platform\web\public_data\current\quantservice_tseries_discovery.json`

GCS current 예시:

- `gs://quantservice-489808-market-analysis/<user current json>`
- `gs://quantservice-489808-market-analysis/tseries_discovery/current/quantservice_tseries_discovery.json`
- 필요 시 `gs://quantservice-489808-market-analysis/history/`

## 완료 조건

- Quant 파이프라인 완료 직후 redbot.co.kr의 퀀트모델/성과/t-series 관련 API가 최신 current를 조회한다.
- QS `sync_web_data_to_quantservice.ps1`를 실행하지 않아도 웹 데이터가 최신화된다.
- 직접 publish 검증 로그가 Quant 작업 결과에 남는다.

