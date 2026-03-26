# QS Active Work Registry

| 영역 | 대표 쓰레드 | 현재 상태 | 최근 메모 |
|---|---|---|---|
| 공개 웹 | QS-Public-Web | 활성 | 시장 브리핑 고도화 1차 공개 반영 완료 |
| 관리자 preview | QS-Admin-Preview | 활성 | analytics p1~p5, market briefing lab 운영 검토 가능 |
| 인증/플랫폼 | QS-Platform-Auth | 유지보수 | 관리자 로그인, bootstrap, CSRF/권한 보강 반영 완료 |
| Quant 연동 | QS-Quant-Handoff | 활성 | 모델 copy/compliance/weekly model 관련 upstream 필드 반영 중 |
| QM 연동 | QS-QM-Handoff | 활성 | public market briefing optional payload, admin lab payload 연동 중 |
| 배포/운영 | QS-Deploy-Ops | 활성 | Cloud Run/GCS remote handoff 운영 유지 |

현재 대화 쓰레드:

- `QS-Public-Web`

운영 메모:

- 새 요청은 먼저 `QS-Master` 기준으로 대표 쓰레드를 정한 뒤 처리합니다.
- 공개와 admin preview가 동시에 걸리는 요청은 `QS-Master`가 릴리즈 게이트를 주관합니다.
