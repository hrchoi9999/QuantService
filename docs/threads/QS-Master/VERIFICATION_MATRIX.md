# QS Verification Matrix

| 쓰레드 | 필수 검증 | 추가 확인 |
|---|---|---|
| QS-Public-Web | `pytest tests\test_web -q`, `ruff check`, `black --check` | live URL 확인, 공개/비공개 경계 확인 |
| QS-Admin-Preview | `pytest tests\test_web -q`, `ruff check`, `black --check` | 관리자 권한 체크, 공개 메뉴 미노출 확인 |
| QS-Platform-Auth | `pytest tests -q` 중 auth/billing/web 범위, `ruff check`, `black --check` | CSRF, 권한, bootstrap 계정, 공개 POST 보호 확인 |
| QS-Quant-Handoff | `pytest tests\test_web -q`, `ruff check`, `black --check` | payload 필드 연결, 금지 표현 여부 확인 |
| QS-QM-Handoff | `pytest tests\test_web -q`, `ruff check`, `black --check` | remote handoff, optional payload fallback, public/admin 분리 확인 |
| QS-Deploy-Ops | dry run 또는 배포 스크립트 점검 | live API/HTML 확인, env 반영 확인 |
| QS-Master | 각 대표 쓰레드 결과 취합 | 릴리즈 게이트 완료 기록 |
