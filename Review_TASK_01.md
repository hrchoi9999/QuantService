# Review TASK 01

## 우선순위
- P0
- 범주: 로직 / 회원 데이터 무결성 / 인증 상태

## 핵심 이슈
`get_user_profile()` 호출만으로 휴대폰 인증 상태가 자동으로 `verified` 처리됩니다.

- 근거 코드
  - `service_platform/access/store.py:413-415`
  - `service_platform/access/store.py:1187-1245` (`_upsert_user_profile`)
- 현재 구현
  - `get_user_profile()` 진입 시 `self._upsert_user_profile(user_id, verified=True)`를 먼저 호출합니다.
  - 이 호출은 조회(read) 동작인데도 `phone_verification_status`와 `phone_verified_at`를 갱신할 수 있습니다.
- 영향
  - 실제 휴대폰 인증을 거치지 않은 계정도 프로필 조회 시점에 검증 완료 상태로 바뀔 수 있습니다.
  - `/me` 같은 조회 API가 인증 상태를 오염시키는 구조라 운영 중 데이터 신뢰도가 깨집니다.
  - 이후 유료 전환, 본인확인, 고객응대 기준 데이터가 모두 흔들릴 수 있습니다.

## 작업 목표
조회 로직과 상태 변경 로직을 분리하고, 휴대폰 인증 성공 시점에만 검증 상태가 갱신되도록 수정합니다.

## 작업 지시
1. `get_user_profile()`에서 `_upsert_user_profile(..., verified=True)` 호출을 제거합니다.
2. 프로필이 없을 때만 생성하는 전용 보정 함수가 필요하면 `verified=False` 기본값으로 별도 분리합니다.
3. 휴대폰 인증 완료 후 회원가입 성공 경로에서만 `phone_verified_at`과 `phone_verification_status='verified'`가 기록되게 만듭니다.
4. 기존 로컬 로그인 사용자 중 프로필 누락 계정은 조회 시 자동 생성하되, 인증 상태는 절대 승격되지 않게 합니다.
5. 회귀 테스트를 추가합니다.

## 필수 테스트
- 미인증 프로필 조회 후에도 `phone_verification_status`가 `unverified`로 유지되는지 확인
- 회원가입 시 정상 인증코드 입력 후에만 `verified`로 저장되는지 확인
- 기존 verified 사용자는 조회 후 상태가 변하지 않는지 확인

## 완료 기준
- 조회 API나 페이지 접근만으로 인증 상태가 바뀌지 않습니다.
- 인증 상태 변경은 회원가입/인증 성공 플로우에서만 발생합니다.
- 관련 테스트가 추가되고 모두 통과합니다.
