# QS-Master Release Gate

공개 반영 전 필수 체크:

## 1. 공개/비공개 경계

- public 변경이 `/admin` 전용 기능을 노출하지 않는가
- admin preview가 공개 메뉴/공개 링크/sitemap에 노출되지 않는가
- internal preview payload가 public current에 섞이지 않았는가

## 2. 컴플라이언스

- 금지 표현 여부 확인
  - 추천
  - 권유
  - 개인 맞춤
  - 매수/매도 추천
  - 적합/유리
- 공개 모델 정보/시장 브리핑 톤 유지 여부 확인

## 3. 권한/보안

- 관리자 전용 경로 보호 확인
- 공개 POST CSRF 상태 확인
- 오픈 리다이렉트/관리자 access key 노출 재발 여부 확인

## 4. 검증 실행

- `pytest`
- `ruff check`
- `black --check`
- live 확인이 필요한 경우 실제 URL 점검

## 5. 배포/기록

- 배포 필요 여부 판단
- Cloud Run 반영 여부 기록
- GitHub push 여부 기록
- Quant/QM 후속 요청 필요 시 링크 첨부

릴리즈 게이트 기록 형식:

- 작업명
- 대표 쓰레드
- 검증 명령 결과
- 공개 반영 여부
- 운영 확인 URL
- 후속 요청서 유무
