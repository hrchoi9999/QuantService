# Stitch 작업의뢰서: redbot.co.kr 디자인 개편용 QS 구현 산출물 요청

작성일: 2026-06-18

## 목적

redbot.co.kr의 현행 QuantService 웹서비스를 `stitch_redbot_modern_redesign.zip` 시안의 방향성으로 개편하려고 합니다. QS는 Flask/Jinja 기반 서버 렌더링 웹서비스이며, 실제 투자/시장/포트폴리오 데이터가 동적으로 렌더링됩니다. 따라서 Stitch에는 단일 정적 HTML이 아니라 QS가 실제 서비스에 안전하게 이식할 수 있는 디자인 산출물을 요청합니다.

기존 기능, 라우팅, 데이터 구조는 유지하지만 기존 UI 스타일은 유지 대상이 아닙니다. 이번 개편은 Stitch 신규 디자인 시스템을 redbot.co.kr 전체에 적용하는 전면 디자인 개편을 목표로 합니다.

## 현재 Stitch 시안 참고

제공 파일:

- `code.html`
- `DESIGN.md`
- `screen.png`

시안 방향:

- Modern Corporate / Clean Data / FinTech SaaS 스타일
- RedBot 브랜드 레드, 차콜/슬레이트, 화이트 카드 기반
- Hanken Grotesk, JetBrains Mono 기반 데이터 가독성
- 시장 브리핑 중심의 3컬럼 대시보드 구조

## QS 구현 환경

- Backend: Python Flask
- Template: Jinja HTML templates
- Styling: repo 내 CSS 파일 중심
- Frontend behavior: vanilla JavaScript 중심
- 운영 배포: Cloud Run
- 실제 데이터: Quant, QuantMarket, QuantAnalysis에서 생성한 current JSON을 QS가 렌더링

주의:

- 최종 QS 구현에는 CDN Tailwind를 그대로 쓰기 어렵습니다.
- 더미 데이터가 아니라 실제 QS 데이터 구조에 맞는 컴포넌트 스펙이 필요합니다.
- 로그인/구독/관리자/시장/포트폴리오 등 기존 기능은 유지되어야 합니다.

## 요청 산출물

### 1. 디자인 시스템

다음 항목을 QS에 이식 가능한 형태로 제공해 주세요.

- 색상 토큰: primary, secondary, background, surface, border, text, muted, positive, negative, warning, neutral
- typography 토큰: heading, body, label, numeric/mono
- spacing scale
- radius scale
- border/shadow/elevation 규칙
- data 상태별 색상 규칙: 좋음, 나쁨, 중립, 위험, 상승, 하락, 결측, 테스트/preview
- CSS custom properties 형태 예시

희망 형식:

- `design-tokens.css`
- `design-tokens.json`
- 간단한 사용 가이드 Markdown

### 2. 페이지별 디자인 스펙

아래 페이지별 desktop/mobile 시안을 요청합니다.

- 홈
- 오늘의 퀀트
- 시장 브리핑 / 시장 현황판
- 퀀트 모델
- 모델 상세
- 투자 포트폴리오
- 로그인 / 회원가입
- 구독 / 결제 안내
- 관리자/내부용 페이지는 1차 범위에서는 제외 가능하나, 기본 카드/테이블 스타일은 호환 필요

각 페이지는 다음 상태를 포함해 주세요.

- 데이터 정상
- 데이터 로딩
- 데이터 없음
- 데이터 오래됨/경고
- 모바일 360px 기준
- 태블릿 768px 기준
- 데스크톱 1200px 이상 기준

### 3. 컴포넌트 라이브러리

QS에 필요한 핵심 컴포넌트별 디자인 스펙을 요청합니다.

- Top navigation
- Mobile navigation
- Login/register buttons
- Market verdict card
- KPI card
- Status badge/chip
- Data table
- Model card
- Portfolio allocation card
- Chart container
- Chart tooltip
- Chart legend
- Alert/risk notice
- Empty state
- Loading skeleton
- Error/fallback message
- Footer

각 컴포넌트는 다음 정보를 포함해 주세요.

- 목적
- desktop/mobile layout
- spacing
- color states
- hover/focus/active 상태
- 긴 텍스트 처리
- 숫자/퍼센트 표시 규칙
- 접근성 고려사항

### 4. 실제 QS 데이터 구조에 맞춘 디자인 매핑

정적 더미 텍스트 대신 QS의 실제 정보 구조에 맞게 매핑 가이드를 주세요.

시장 브리핑:

- 현재 시장 판단
- 3축 그래프: 금융시장 환경, 퀀트모델 전망, 단기 시장상황
- KOSPI 기준선
- 익일 preview/test point
- 핵심 판단 숫자
- 리스크/긍정 요인
- 시장 뉴스/브리핑

퀀트 모델:

- 모델 목록
- 모델별 수익률/위험/샤프/MDD
- holdings/candidates
- change history
- 모델 설명과 고지 문구

투자 포트폴리오:

- 시장위험 판단
- ETF 전략
- 주식 후보 점검
- 최종 포트폴리오 전략
- 검증/시나리오 정보

### 5. 차트/데이터 시각화 가이드

다음 항목을 구체적으로 요청합니다.

- 3축 그래프의 선/점/tooltip/legend/x축/y축 디자인
- hover crosshair 디자인
- 익일 preview point는 실제 포인트처럼 보이되 날짜축에는 포함하지 않는 표시 방식
- 기준지수 보조선 스타일
- 날짜 라벨 밀집 시 처리 방식
- 모바일에서 차트 스크롤/축 표시 방식
- 결측/휴장/이월(carry-forward) 표시 원칙

### 6. 구현 친화적 코드 산출물

QS 적용을 위해 아래 중 하나 이상을 제공해 주세요.

- Tailwind CDN 의존 없는 HTML/CSS 예시
- CSS custom properties 기반 스타일시트
- Jinja로 분리하기 쉬운 컴포넌트 단위 HTML
- 주요 레이아웃별 responsive CSS
- JS가 필요한 interaction은 vanilla JS 기준

금지/주의:

- CDN Tailwind 런타임 의존 전제 금지
- 임의 투자 조언 문구 고정 금지
- 실제 서비스 라우팅을 대체하는 mock 링크만 제공 금지
- 더미 수치가 실제 값처럼 보이는 산출물만 제공 금지

## 검수 기준

Stitch 산출물은 QS에서 아래 기준으로 검수합니다.

- 현재 redbot.co.kr 기능을 잃지 않고 적용 가능해야 함
- 실제 데이터 길이와 결측 상태에서도 레이아웃이 깨지지 않아야 함
- 모바일에서 주요 투자/시장 정보가 겹치지 않아야 함
- 숫자 데이터는 빠르게 비교 가능해야 함
- 브랜드 레드는 강조용으로 사용하고 화면 전체를 과도하게 지배하지 않아야 함
- 투자자문 오해를 줄이는 고지/참고자료 톤을 유지해야 함

## 최종 전달 형식

권장 전달물:

- `DESIGN_SYSTEM.md`
- `design-tokens.css`
- `design-tokens.json`
- `components.html`
- `home.html`
- `market-analysis.html`
- `quant-models.html`
- `portfolio.html`
- desktop/mobile PNG 또는 Figma 링크
- 구현 메모: QS 적용 시 우선순위와 주의사항

## 우선순위

1. 디자인 시스템과 공통 컴포넌트
2. 시장 브리핑 / 시장 현황판
3. 홈
4. 퀀트 모델
5. 투자 포트폴리오
6. 로그인/구독/기타 페이지

## Stitch에 전달할 핵심 요청 문장

redbot.co.kr은 실제 퀀트 투자 웹서비스이므로, 단순 정적 랜딩페이지가 아니라 동적 데이터 기반 Flask/Jinja 서비스에 적용 가능한 디자인 시스템과 페이지/컴포넌트 산출물이 필요합니다. 기존 시안의 Modern Corporate FinTech 방향은 유지하되, QS가 CSS/Jinja/vanilla JS로 이식할 수 있도록 토큰, 컴포넌트 상태, 반응형 레이아웃, 차트/테이블/결측 상태까지 구체화해 주세요.
