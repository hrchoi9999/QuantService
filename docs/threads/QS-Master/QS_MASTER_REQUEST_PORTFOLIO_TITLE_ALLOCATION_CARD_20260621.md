# QS Master 작업요청: 투자 포트폴리오 상단 비중 카드 웹 반영

## 요청 주체

- QuantAnalysis Master
- 작성일: 2026-06-21
- 대상: QuantService Master

## 요청 요약

투자 포트폴리오 페이지 상단 제목 섹션에 `주식 / ETF / 현금` 3개 비중 카드를 표시해 주세요.

QuantAnalysis는 이미 최신 JSON 생성과 GCS 게시를 완료했습니다. QS는 웹 렌더링만 반영하면 됩니다.

## 반영 대상

- 페이지: 투자 포트폴리오
- 위치: 페이지 상단 제목/요약 영역
- 데이터 원천: `admin/current/investment_portfolio_latest.json`
- 필드: `title_allocation_card`
- fallback 필드: `target_allocation`

## 현재 게시된 payload

- GCS current: `gs://quantservice-489808-market-analysis/admin/current/investment_portfolio_latest.json`
- 최신 생성시각: `2026-06-21T18:30:57.421+09:00`

## 표시해야 할 데이터

`title_allocation_card.cards[]`를 사용합니다.

| 카드 | 필드 |
|---|---|
| 카드명 | `label` |
| 권장 비중 | `target_pct` |
| 운용 범위 | `range_pct` |
| 설명 | `description` |

상단 보조 문구로 아래도 표시해 주세요.

- `title_allocation_card.summary`
- `title_allocation_card.stance`
- `title_allocation_card.action`

## 현재 기대 표시값

| 구분 | 권장 비중 | 운용 범위 |
|---|---:|---:|
| 주식 | 10% | 0~15% |
| ETF | 76.5% | 72.2~85% |
| 현금 | 13.5% | 12.8~15% |

## 구현 요청

1. payload parser/admin-public data mapping에서 `title_allocation_card`를 누락 없이 전달한다.
2. 투자 포트폴리오 페이지 상단에 3개 카드를 배치한다.
3. 카드 데이터가 없으면 기존 화면을 유지하고 카드 영역은 숨긴다.
4. `target_pct`는 `%` 단위로 표시한다.
5. `range_pct`는 문자열 그대로 사용하되 뒤에 `%`가 없으면 `%`를 붙인다.
6. null/undefined 값을 `0`으로 바꾸지 않는다.

## 검증 요청

- redbot 투자 포트폴리오 페이지 상단에서 세 카드가 보이는지 확인
- 주식 `10%`, ETF `76.5%`, 현금 `13.5%` 표시 확인
- payload 생성시각 `2026-06-21T18:30:57.421+09:00` 기준 데이터인지 확인
- 모바일/데스크톱에서 카드 텍스트가 겹치지 않는지 확인

## 관련 상세 요청서

- `D:\QuantAnalysis\docs\requests\QUANTSERVICE_PORTFOLIO_TITLE_ALLOCATION_CARD_20260621.md`
