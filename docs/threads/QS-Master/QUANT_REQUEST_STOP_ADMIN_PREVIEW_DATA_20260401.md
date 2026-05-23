# Quant 작업요청서

## 작업명
QS admin preview 데이터 수집/생산 중단 요청

## 요청 출처
QS-Master

## 배경
- QuantService의 `/admin` 하위 analytics preview 계열 페이지는 당분간 운영상 필요하지 않아 웹 동선과 직접 접근을 모두 비활성화했습니다.
- 따라서 여기에 사용되던 Quant internal preview 데이터도 당분간 계속 수집/생산할 필요가 없습니다.
- 이번 요청은 public 웹 데이터 중단이 아니라, **admin preview 전용 데이터 생산 중단** 요청입니다.

## 중단 대상
아래 internal preview bundle의 수집/생산/동기화를 당분간 중단해 주세요.

1. `D:\Quant\reports\service_analytics_review\20260325\p1_bundle`
2. `D:\Quant\reports\service_analytics_review\20260325\p2_bundle`
3. `D:\Quant\reports\service_analytics_review\20260325\p3_bundle`
4. `D:\Quant\reports\service_analytics_review\20260325\p4_bundle`
5. `D:\Quant\reports\service_analytics_review\20260325\p5_bundle`

## 중단 범위
- 신규 산출 중단
- 정기 갱신 중단
- current 동기화 중단
- validator/publish 파이프라인에서 admin preview bundle 후속 갱신 중단

## 유지 대상
아래는 이번 요청 범위에서 제외합니다.

- public user snapshot/current
- public market briefing/current
- T-series Discovery current
- 기존 S-series public API 및 공개 화면용 데이터

## QS 측 처리 상태
- QS는 admin preview/lab 동선을 웹에서 제거했습니다.
- direct URL 접근도 기본 비활성 상태입니다.
- 따라서 Quant 쪽에서는 당분간 admin preview 데이터를 계속 생산하지 않아도 QS 동작에는 영향이 없습니다.

## 참고
- 이번 요청은 Quant analytics preview bundle에 대한 중단 요청입니다.
- QM admin market payload는 별도 시스템이므로 이번 문서 범위에 포함하지 않습니다.

## 완료 기준
1. P1~P5 preview bundle의 정기 생산이 중단됨
2. 관련 current 동기화/후속 갱신도 중단됨
3. public 데이터 파이프라인에는 영향이 없음
