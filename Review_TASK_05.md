# Review TASK 05

## 우선순위
- P2
- 범주: UI / 유지보수성 / 반응형 구조

## 핵심 이슈
UI 스타일이 단일 `site.css`에 과도하게 누적되어 있고, 후반부에 강제 override가 반복되어 화면 회귀 가능성이 큽니다.

- 근거 코드
  - 스타일 파일 길이: `service_platform/web/static/site.css` 약 2455 lines
  - `!important` 사용 다수: 약 70회
  - 중복 override 구간 예시: `service_platform/web/static/site.css:2029-2322`
  - 헤더/내비 텍스트 과대 설정: `service_platform/web/static/site.css:109-133`
  - 전역 네비 항목 수: `service_platform/web/templates/base.html:20-35`

## 리뷰 의견
- 현재 화면은 빠르게 시안을 맞춘 흔적이 많고, “Final override”, “Hard lock” 형태의 주석이 누적되어 있습니다.
- 이 상태에서는 작은 수정도 다른 페이지를 깨뜨릴 가능성이 큽니다.
- 모바일에서 헤더 메뉴 수가 많고 글자 크기가 커서 첫 화면 집중도가 떨어질 수 있습니다.

## 작업 목표
스타일 구조를 컴포넌트/페이지 기준으로 재정리하고, 정보 구조도 사용자 중심으로 단순화합니다.

## 작업 지시
1. `site.css`를 최소한 아래 단위로 분리합니다.
   - `base.css`
   - `layout.css`
   - `components.css`
   - `pages/home.css`, `pages/today.css`, `pages/market-analysis.css` 등
2. 후반부 `!important` override를 제거하고, 컴포넌트 클래스 우선순위로 재정렬합니다.
3. 공용 헤더를 재설계합니다.
   - 데스크톱: 핵심 메뉴 4~5개만 1차 노출
   - 모바일: 접히는 메뉴 또는 compact nav 적용
4. `홈`과 `오늘의 추천`의 상단 히어로에서 CTA를 1순위 행동 기준으로 정리합니다.
   - 추천 확인
   - 시장분석 보기
   - 성과 보기
5. 화면 QA 체크리스트를 만듭니다.
   - 1440px
   - 1024px
   - 820px
   - 390px

## 필수 산출물
- 리팩터링된 CSS 구조
- 헤더/내비 개선안 반영
- 주요 공개 페이지 반응형 캡처 또는 체크 결과

## 완료 기준
- 전역 `!important` 의존도가 크게 줄어듭니다.
- 모바일 헤더가 과밀하지 않습니다.
- 홈/오늘/시장분석 페이지의 시각적 위계가 더 명확해집니다.

