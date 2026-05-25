# QuantAnalysis 웹 데이터 즉시 반영 작업요청서

- 작성일: 2026-05-23
- 요청 출처: QuantService / QS-Deploy-Ops
- 대상 쓰레드: QuantAnalysis, QuantOpsScheduler
- 목적: QuantAnalysis에서 투자 포트폴리오/주식 후보 점검 웹 데이터가 생성되면 redbot.co.kr에 자동 반영되도록 GCS publish 단계를 추가한다.

## 배경

현재 redbot.co.kr은 Cloud Run에서 GCS의 웹용 JSON을 조회한다.

현재 QuantAnalysis 투자 포트폴리오 웹 데이터 흐름은 다음과 같다.

1. QuantAnalysis가 `D:\QuantAnalysis\outputs\investment_portfolio_latest.json` 생성
2. QuantService 자동화 `quantservice-web-data-sync`가 매시간 실행
3. QS 스크립트 `D:\QuantService\scripts\sync_web_data_to_quantservice.ps1`가 해당 파일을 GCS에 업로드
4. redbot.co.kr이 GCS JSON 조회

이 방식은 매시간 pull 구조라서 QuantAnalysis 작업 직후 웹사이트에 즉시 반영되지 않는다.

## 문제

2026-05-23 16:33경 QuantAnalysis에서 주식 후보 점검 종목 관련 데이터가 갱신되었지만, GCS에는 이전 `generated_at=2026-05-23T14:35:53.879+09:00` 파일이 남아 있어 redbot.co.kr에 즉시 반영되지 않았다.

즉, 현재 구조는 “QuantAnalysis 완료 즉시 publish”가 아니라 “QS가 나중에 가져가는 방식”이다.

## 요청사항

QuantAnalysis 파이프라인 종료 시점에 웹용 최신 JSON을 직접 GCS로 업로드하도록 수정한다.

필수 업로드 대상:

- 원본 파일: `D:\QuantAnalysis\outputs\investment_portfolio_latest.json`
- GCS 대상: `gs://quantservice-489808-market-analysis/admin/current/investment_portfolio_latest.json`
- 공개 확인 URL: `https://storage.googleapis.com/quantservice-489808-market-analysis/admin/current/investment_portfolio_latest.json`

가능하면 timestamp archive 파일도 유지한다.

- 예: `D:\QuantAnalysis\outputs\investment_portfolio_YYYYMMDD_HHMMSSfff.json`
- GCS archive는 선택사항이나, 운영 추적을 위해 가능하면 `gs://quantservice-489808-market-analysis/admin/history/` 또는 별도 agreed path에 업로드한다.

## 구현 기준

QuantAnalysis 작업이 성공적으로 `investment_portfolio_latest.json`을 쓴 뒤 다음을 수행한다.

1. JSON 유효성 검사
2. 필수 메타 필드 확인
   - `as_of_date`
   - `generated_at`
   - `source_thread`
   - `stock_strategy.candidates`
3. GCS 업로드
4. cache-buster URL로 재조회하여 `generated_at`이 방금 생성한 값과 같은지 검증
5. 실패 시 명확한 에러 로그를 남기고 QuantOpsScheduler가 감지할 수 있게 non-zero exit 처리

## 권장 명령 예시

```powershell
$src = "D:\QuantAnalysis\outputs\investment_portfolio_latest.json"
$gcloud = Join-Path $env:LOCALAPPDATA "GoogleCloudSDK\google-cloud-sdk\bin\gcloud.cmd"
& $gcloud config configurations activate quantservice
& $gcloud storage cp $src "gs://quantservice-489808-market-analysis/admin/current/investment_portfolio_latest.json" --quiet
```

검증 예시:

```powershell
$url = "https://storage.googleapis.com/quantservice-489808-market-analysis/admin/current/investment_portfolio_latest.json?ts=$([DateTimeOffset]::Now.ToUnixTimeSeconds())"
(Invoke-WebRequest $url -UseBasicParsing -Headers @{"Cache-Control"="no-cache"}).Content | ConvertFrom-Json
```

## QuantOpsScheduler 반영 요청

QuantAnalysis 자동/애드혹 작업이 투자 포트폴리오 또는 주식 후보 점검 데이터를 갱신하는 경우, 작업 종료 후 위 GCS publish 검증까지 포함해서 실행되도록 스케줄/워크플로를 연결한다.

권장 운영 방식:

- QuantAnalysis가 데이터 생성과 GCS publish의 1차 책임을 가진다.
- QS의 `quantservice-web-data-sync`는 보조 안전망으로 유지한다.
- redbot.co.kr은 GCS 최신 JSON만 조회한다.

## 완료 조건

- QuantAnalysis에서 `investment_portfolio_latest.json` 갱신 직후 GCS current 객체가 즉시 갱신된다.
- GCS 재조회 결과의 `generated_at`이 QuantAnalysis 최신 파일과 일치한다.
- redbot.co.kr 투자 포트폴리오 페이지/API가 새 후보 데이터를 조회한다.
- QS 매시간 동기화 없이도 QuantAnalysis 완료 직후 웹 원본이 최신화된다.

## 참고

현재 QS 보조 동기화 스크립트:

- `D:\QuantService\scripts\sync_web_data_to_quantservice.ps1`

현재 QS 자동화:

- `quantservice-web-data-sync`
- 매시간 실행
- 역할: Quant, QuantMarket, QuantAnalysis 산출물을 QS fallback 및 GCS로 업로드

이 자동화는 장애 대비용으로 유지하되, QuantAnalysis 웹 데이터의 정식 최신화 경로는 QuantAnalysis 자체 publish로 전환한다.
