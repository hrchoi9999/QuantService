# QS 작업요청 제출 가이드

이 문서는 Quant / QuantMarket에서 QuantService 관련 작업요청을 보낼 때의 기본 제출 원칙을 정의합니다.

기본 원칙:

- QS 관련 작업요청의 **기본 제출처는 항상 `QS-Master`** 입니다.
- Quant / QM에서 개별 쓰레드를 직접 선택해도 되지만, **최종 배정 권한은 `QS-Master`** 가 가집니다.
- 공개 반영, 관리자 전용 반영, 인증/권한, 배포 이슈가 섞일 수 있으므로 일원 접수가 가장 안전합니다.

## 왜 `QS-Master`로 먼저 보내야 하나

Quant / QM 작업요청은 아래처럼 경계가 자주 섞입니다.

- 공개 웹 UI 변경 + handoff 연결
- admin preview 추가 + 권한 제어
- payload 변경 + public route/API 변경
- 공개 반영 + 운영 배포 확인

이 경우 요청자가 처음부터 정확한 QS 담당 쓰레드를 고르기 어렵습니다.
따라서 `QS-Master`가 먼저 받아서 범위를 나누고, 필요하면 여러 쓰레드로 분배하는 방식이 기본입니다.

## QS 쓰레드 역할 요약

### 1. `QS-Public-Web`

- 공개 웹페이지 UI/카피/레이아웃
- 홈, 시장 브리핑, 이번 주 모델 기준안, 성과 설명, 변경내역
- 공개 페이지에서 실제 보이는 변화

### 2. `QS-Admin-Preview`

- `/admin` 하위 내부 preview
- analytics preview p1~p5
- admin market briefing lab
- 공개 전 검토용 페이지

### 3. `QS-Platform-Auth`

- 로그인 / 회원가입
- 권한 / 관리자 접근
- CSRF / billing / 보안 기본값

### 4. `QS-Quant-Handoff`

- Quant가 생산하는 모델/성과/변경내역/snapshot payload 연결
- 모델명, 성과, compliance 문구, canonical API 경로

### 5. `QS-QM-Handoff`

- QuantMarket이 생산하는 시장 브리핑 public/admin payload 연결
- GCS current, manifest, optional payload, public/admin 분리

### 6. `QS-Deploy-Ops`

- Cloud Run 배포
- 환경변수 / GCS 연결
- live 확인 및 운영 반영

## 권장 제출 방식

### 기본 방식

- `QS-Master`로 작업요청 전달
- 필요하면 아래 항목을 함께 적어 주세요:
  - `권장 담당 쓰레드`
  - `공개 반영 포함 여부`
  - `admin only 여부`

### 권장 이유

- 요청자는 “대충 어느 영역인지”만 표시하면 됩니다.
- `QS-Master`가 실제 범위를 보고 최종 쓰레드를 정합니다.
- 필요하면 하나의 요청을 여러 쓰레드로 분리할 수 있습니다.

## 작업요청서 권장 헤더

작업요청서 상단에는 아래 형식을 권장합니다.

```text
QS 요청 제출처: QS-Master
권장 담당 쓰레드: QS-QM-Handoff
공개 반영 포함 여부: Yes
Admin only 여부: No
관련 시스템: QuantMarket
```

`권장 담당 쓰레드`는 비워도 됩니다.
비워도 `QS-Master`가 보고 배정합니다.

## 요청서에 꼭 포함할 내용

1. 작업 목적
2. 필수 참조 문서
3. 사용 payload / 파일 / API 경로
4. 이번 작업에서 QS가 반영해야 할 내용
5. 공개 반영인지, admin only 인지
6. 이번 작업에서 반영하면 안 되는 범위
7. fallback / optional payload 규칙
8. QA 체크리스트

## 공개 반영 요청일 때 추가로 적을 것

- 실제 공개 반영 대상 페이지
- 공개 사이트에 보여도 되는 표현인지
- 공개 반영하면 안 되는 admin/intraday 데이터가 무엇인지
- 기존 공개 UI를 유지해야 하는 영역

## admin only 요청일 때 추가로 적을 것

- `/admin` 하위 경로 권장안
- 로그인/권한 제어 조건
- 공개 페이지와 분리해야 하는 이유
- 운영 배포 여부

## QS-Master의 처리 방식

`QS-Master`는 요청을 받은 뒤 아래 순서로 처리합니다.

1. 요청 범위를 확인
2. 대표 담당 쓰레드 결정
3. 필요하면 보조 쓰레드 분리
4. 공개/비공개 경계 확인
5. 구현 후 릴리즈 게이트 체크
6. 배포 필요 여부 판단

## 결론

- Quant / QM은 **기본적으로 `QS-Master`로 작업요청을 전달**합니다.
- `권장 담당 쓰레드`는 선택적으로 적되, **최종 배정은 `QS-Master`가 담당**합니다.
- 공개 반영이 걸린 요청은 특히 `QS-Master` 일원 접수가 원칙입니다.
