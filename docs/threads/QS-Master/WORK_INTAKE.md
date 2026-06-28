# QS-Master Work Intake

새 요청은 먼저 active agent로 배정합니다.

## 1. `QS-Web-Platform Agent`

- 공개 페이지 UI/카피/레이아웃
- 홈, 시장 브리핑, 이번 주 모델 기준안, 성과 설명, 변경내역
- 공개 API 표현/공개 섹션 추가/삭제
- `/admin` 하위 preview
- analytics p1~p5
- admin market briefing lab
- 공개 전 내부 검토용 페이지
- 로그인, 회원가입, CSRF, 권한, 관리자 접근, billing, bootstrap 계정
- 공개/관리자 보안 정책

기존 기록 폴더:

- `QS-Public-Web`
- `QS-Admin-Preview`
- `QS-Platform-Auth`

## 2. `QS-Handoff Agent`

- Quant snapshot/model payload 연동
- 모델명, 성과, 변경내역, compliance 문구, 모델 설명 필드
- QuantMarket market briefing public/admin payload 연동
- GCS current, manifest, optional payload, remote handoff 정책

기존 기록 폴더:

- `QS-Quant-Handoff`
- `QS-QM-Handoff`

## 3. `QS-Deploy-Ops Agent`

- Cloud Run, GCS, env, 운영 반영, live 확인, 배포 스크립트

기존 기록 폴더:

- `QS-Deploy-Ops`

배정 규칙:

1. 공개/admin/auth 웹 변경은 `QS-Web-Platform Agent`
2. Quant/QM source schema, copy, current, fallback 변경은 `QS-Handoff Agent`
3. 배포/환경변수/운영 장애는 `QS-Deploy-Ops Agent`
4. 두 개 이상에 걸치면 `QS-Master`가 owner agent 1개와 reviewer agent 1개를 지정합니다.
5. `QS-Master`는 구현 담당이 아니라 배정, release gate, 충돌 조정을 담당합니다.
