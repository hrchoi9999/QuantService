# Review TASK 02

## 우선순위
- P0
- 범주: 보안 / CSRF / 결제 및 계정 플로우

## 핵심 이슈
공개 POST 엔드포인트에 CSRF 방어가 일관되게 적용되지 않았습니다.

- 근거 코드
  - CSRF 유틸 존재: `service_platform/web/app.py:629-640`
  - 결제 체크아웃 POST: `service_platform/web/app.py:1216-1239`
  - 로그인 POST: `service_platform/web/app.py:1080-1106`
  - 회원가입 POST: `service_platform/web/app.py:1108-1165`
  - 결제 폼: `service_platform/web/templates/pricing.html:31-43`
  - 로그인 폼: `service_platform/web/templates/login.html:15-29`
  - 회원가입 폼: `service_platform/web/templates/signup.html:16-24`, `service_platform/web/templates/signup.html:37-61`

## 왜 급한가
- 이미 CSRF 토큰 생성/검증 함수는 있는데, 관리자 POST에만 부분 적용되고 있습니다.
- 로그인 상태 사용자를 대상으로 외부 사이트에서 결제 주문 생성이나 세션 오염 요청을 유도할 수 있습니다.
- 특히 `billing_checkout`은 실제 주문 레코드를 만들기 때문에 우선 보강해야 합니다.

## 작업 목표
모든 상태 변경 POST에 동일한 CSRF 정책을 적용하고, 템플릿 폼에도 토큰을 주입합니다.

## 작업 지시
1. 아래 공개 POST 엔드포인트에 `require_csrf()`를 적용합니다.
   - `/billing/checkout`
   - `/signup` (`request_code`, `register` 모두)
   - `/login`
   - `/feedback`
2. 위 폼 템플릿에 공통 hidden field `csrf_token`을 추가합니다.
3. GET 렌더링 경로에서 토큰이 항상 템플릿 컨텍스트로 전달되는지 확인합니다.
4. CSRF 실패 시 사용자에게는 400 기본 에러 대신 안내 가능한 화면 또는 redirect 정책을 정합니다.
5. 테스트를 추가합니다.

## 필수 테스트
- CSRF 토큰 없이 `/billing/checkout` POST 시 실패
- 유효 토큰으로는 정상 체크아웃 페이지 렌더링
- 로그인/회원가입/피드백도 토큰 없으면 거부
- 기존 관리자 CSRF 플로우가 깨지지 않는지 확인

## 완료 기준
- 상태 변경 POST 전부가 같은 CSRF 정책을 따릅니다.
- 모든 사용자 폼에 토큰이 포함됩니다.
- 주문 생성 및 회원가입 관련 CSRF 회귀 테스트가 추가됩니다.

