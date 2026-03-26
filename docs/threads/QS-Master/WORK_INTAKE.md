# QS-Master Work Intake

새 요청 분류 기준:

## 1. `QS-Public-Web`

- 공개 페이지 UI/카피/레이아웃
- 홈, 시장 브리핑, 이번 주 모델 기준안, 성과 설명, 변경내역
- 공개 API 표현/공개 섹션 추가/삭제

## 2. `QS-Admin-Preview`

- `/admin` 하위 preview
- analytics p1~p5
- admin market briefing lab
- 공개 전 내부 검토용 페이지

## 3. `QS-Platform-Auth`

- 로그인, 회원가입, CSRF, 권한, 관리자 접근, billing, bootstrap 계정
- 공개/관리자 보안 정책

## 4. `QS-Quant-Handoff`

- Quant snapshot/model payload 연동
- 모델명, 성과, 변경내역, compliance 문구, 모델 설명 필드

## 5. `QS-QM-Handoff`

- QuantMarket market briefing public/admin payload 연동
- GCS current, manifest, optional payload, remote handoff 정책

## 6. `QS-Deploy-Ops`

- Cloud Run, GCS, env, 운영 반영, live 확인, 배포 스크립트

배정 규칙:

1. 공개 웹에 실제 보이는 변화가 있으면 `QS-Public-Web`
2. `/admin`에서만 보는 화면이면 `QS-Admin-Preview`
3. 인증/권한/결제/보안이면 `QS-Platform-Auth`
4. Quant source schema나 copy 변경이면 `QS-Quant-Handoff`
5. QM market payload/public/admin 변경이면 `QS-QM-Handoff`
6. 배포/환경변수/운영 장애는 `QS-Deploy-Ops`
7. 두 개 이상에 걸치면 `QS-Master`가 주관하고 대표 쓰레드를 하나 정합니다.
