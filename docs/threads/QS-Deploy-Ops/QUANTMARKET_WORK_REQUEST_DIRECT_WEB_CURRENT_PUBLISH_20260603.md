# QuantMarket 웹 current 직접 publish 운영정렬 요청서

- 작성일: 2026-06-03
- 요청 출처: QuantService
- 대상 쓰레드: QuantMarket
- 목적: 시장 브리핑/시장 현황판 current 데이터가 QS 동기화 없이 redbot.co.kr에 즉시 반영되도록 직접 GCS publish 운영 상태를 확인/정렬한다.

## 배경

QS는 2026-06-03 커밋 `4c30497`부터 `sync_web_data_to_quantservice.ps1`의 기본 동작을 GCS publish가 아닌 로컬 fallback 갱신으로 변경했다.

운영 원칙은 다음과 같다.

- QuantMarket은 시장분석 웹 current 생성과 GCS publish의 1차 책임을 가진다.
- QS는 GCS current를 조회한다.
- QS 동기화 스크립트의 GCS publish는 장애 복구용으로만 `-PublishToGcs`를 명시해 사용한다.

## 요청사항

1. QuantMarket 자동/애드혹 파이프라인에서 handoff current 생성 직후 GCS current publish가 실행되는지 확인한다.
2. `market_analysis/current` 전체 세트 업로드 후 manifest가 마지막에 갱신되도록 유지한다.
3. history 성격 파일은 `market_analysis/history` 경로로 업로드되는지 확인한다.
4. publish 성공 후 cache-buster URL로 manifest와 주요 API payload의 `asof/generated_at`을 검증한다.
5. publish 실패 시 작업이 성공으로 끝나지 않도록 non-zero exit 또는 명확한 실패 로그를 남긴다.

## 주요 대상

로컬 current 예시:

- `D:\QuantMarket\service_platform\web\public_data\handoff\quantservice\current\quantservice_market_manifest.json`
- `D:\QuantMarket\service_platform\web\public_data\handoff\quantservice\current\quantservice_market_page.json`
- `D:\QuantMarket\service_platform\web\public_data\handoff\quantservice\current\api_v1_market_analysis_page.json`
- `D:\QuantMarket\service_platform\web\public_data\handoff\quantservice\current\api_v1_market_environment_indicators.json`
- `D:\QuantMarket\service_platform\web\public_data\handoff\quantservice\current\quantservice_market_environment_indicators.json`

GCS current 예시:

- `gs://quantservice-489808-market-analysis/market_analysis/current/*.json`
- `gs://quantservice-489808-market-analysis/market_analysis/history/*.json`

## 완료 조건

- QuantMarket 파이프라인 완료 직후 redbot.co.kr 시장 브리핑/시장 현황판 API가 최신 current를 조회한다.
- QS `sync_web_data_to_quantservice.ps1`를 실행하지 않아도 웹 데이터가 최신화된다.
- manifest와 payload의 기준일/생성시각 검증 로그가 QuantMarket 작업 결과에 남는다.

