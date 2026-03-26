# QS-Platform-Auth Charter

목적:

- QuantService의 인증, 권한, 결제, 관리자 접근, 보안 기본값을 관리합니다.

담당 범위:

- 로그인/회원가입
- CSRF
- 관리자 접근 제어
- billing/checkout
- bootstrap 계정
- 공개 POST 보안 보강

비범위:

- 공개 UI 카피/레이아웃
- Quant / QM payload 의미 정의

대표 대상 파일:

- `service_platform/web/app.py`
- `service_platform/access`
- `service_platform/billing`
- `service_platform/feedback`
- auth/billing 관련 tests

관련 문서:

- `D:\QuantService\docs\REDBOT_REVIEW_TASK_01_P0_AUTH_STATE_2026-03-24.md`
- `D:\QuantService\docs\REDBOT_REVIEW_TASK_02_P0_CSRF_2026-03-24.md`
- `D:\QuantService\docs\REDBOT_REVIEW_TASK_03_P1_ADMIN_ACCESS_2026-03-24.md`
- `D:\QuantService\docs\REDBOT_REVIEW_TASK_04_P1_OPEN_REDIRECT_2026-03-24.md`
- `D:\QuantService\docs\REDBOT_FOLLOWUP_WORK_REQUEST_2026-03-24.md`
