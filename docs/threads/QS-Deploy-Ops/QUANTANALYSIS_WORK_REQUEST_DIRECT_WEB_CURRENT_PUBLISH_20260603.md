# QuantAnalysis 투자 포트폴리오 직접 publish 운영정렬 요청서

- 작성일: 2026-06-03
- 요청 출처: QuantService
- 대상 쓰레드: QuantAnalysis
- 목적: 투자 포트폴리오/주식 후보 점검 current 데이터가 QS 동기화 없이 redbot.co.kr에 즉시 반영되도록 직접 GCS publish 운영 상태를 확인/정렬한다.

## 배경

QS는 2026-06-03 커밋 `4c30497`부터 `sync_web_data_to_quantservice.ps1`의 기본 동작을 GCS publish가 아닌 로컬 fallback 갱신으로 변경했다.

또한 QS 투자 포트폴리오 API는 production에서 아래 GCS URL을 authoritative source로 사용하고, 로컬 fallback을 기본 차단한다.

- `https://storage.googleapis.com/quantservice-489808-market-analysis/admin/current/investment_portfolio_latest.json`

운영 원칙은 다음과 같다.

- QuantAnalysis는 투자 포트폴리오 웹 current 생성과 GCS publish의 1차 책임을 가진다.
- QS는 GCS current를 조회한다.
- QS 동기화 스크립트의 GCS publish는 장애 복구용으로만 `-PublishToGcs`를 명시해 사용한다.

## 요청사항

1. QuantAnalysis 자동/애드혹 파이프라인에서 `investment_portfolio_latest.json` 생성 직후 GCS current publish가 실행되는지 확인한다.
2. 정상 운영 작업에서 `--skip-gcs-publish`, `QUANTANALYSIS_SKIP_GCS_PUBLISH=1` 또는 유사 skip 설정이 사용되지 않도록 정리한다.
3. publish 성공 후 cache-buster URL로 재조회하여 `as_of_date`와 `generated_at`이 최신 산출물과 일치하는지 검증한다.
4. publish 실패 시 작업이 성공으로 끝나지 않도록 non-zero exit 또는 명확한 실패 로그를 남긴다.
5. 가능하면 timestamp history 파일도 GCS `admin/history`에 보존한다.

## 주요 대상

로컬 current:

- `D:\QuantAnalysis\outputs\investment_portfolio_latest.json`

GCS current:

- `gs://quantservice-489808-market-analysis/admin/current/investment_portfolio_latest.json`

공개 확인 URL:

- `https://storage.googleapis.com/quantservice-489808-market-analysis/admin/current/investment_portfolio_latest.json`

## 완료 조건

- QuantAnalysis 파이프라인 완료 직후 redbot.co.kr 투자 포트폴리오 페이지/API가 최신 후보 데이터를 조회한다.
- QS `sync_web_data_to_quantservice.ps1`를 실행하지 않아도 웹 데이터가 최신화된다.
- GCS 재조회 결과의 `as_of_date/generated_at` 검증 로그가 QuantAnalysis 작업 결과에 남는다.

