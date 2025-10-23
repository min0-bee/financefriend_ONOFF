### 구조
```
financefriend_onoff/
├─ app.py # 🎯 진입점: 전체 레이아웃 및 라우팅 담당
│
├─ core/ # ⚙️ 핵심 로직 (설정, 유저, 로깅, 공통 유틸)
│ ├─ init.py
│ ├─ config.py # 상수, 플래그, 경로 등 환경 설정
│ ├─ utils.py # 공통 유틸리티 (now_utc_iso, ensure_log_file, load_logs_as_df 등)
│ ├─ user.py # user_id / session_id 생성 및 세션 스테이트 초기화
│ └─ logger.py # CSV 로깅 (log_event 함수)
│
├─ data/ # 🗞️ 데이터 계층 (뉴스 수집 등)
│ ├─ init.py
│ └─ news.py # mock 뉴스 수집 함수 (collect_news)
│
├─ rag/ # 🧠 RAG/지식 계층 (금융용어 사전 등)
│ ├─ init.py
│ └─ glossary.py # 금융용어 사전 dict, highlight_terms, explain_term
│
└─ ui/ # 💬 UI 컴포넌트 및 스타일
├─ init.py
├─ styles.py # CSS 인젝션 및 테마 스타일 정의
└─ components.py # 요약, 뉴스리스트, 기사상세, 챗봇, 사이드바, 로그뷰어 등 구성요소
```

```
## 🧩 Orchestration Layer (app.py)

이 프로젝트는 **조합 중심 설계(Orchestration-first)** 를 따릅니다.  
`app.py`는 전체 화면을 조립하는 **컨트롤 타워**이며, 실제 UI 그리기는 `components/*` 모듈이 맡습니다.

### 역할 분담
- **app.py = Orchestrator**
  - 레이아웃 분할(메인/챗/사이드바)
  - 라우팅/상태 전환(목록 ↔ 상세)
  - 공통 초기화(스타일, 세션)
  - 각 컴포넌트의 `render()` 또는 컴포넌트 함수 호출
- **components/* = Renderer**
  - 화면 조각(요약, 뉴스리스트, 상세, 챗봇, 사이드바, 로그뷰어)
  - **공통 인터페이스: `render(...)`**
- **core/* = Service**
  - 설정/유저/로깅/유틸(예: `log_event`, `now_utc_iso`, `llm_chat`)
- **rag/*, data/* = Domain**
  - 용어 사전, 하이라이트, 모의 뉴스 수집 등

### app.py 구조(요약)
```python
# ① 공통 준비: 스타일/세션
inject_styles(); init_app()

# ② 레이아웃 분할
col_main, col_chat = st.columns([2, 1])

# ③ 메인: (목록) SummaryBox + NewsList  / (상세) ArticleDetail
with col_main:
    if st.session_state.selected_article is None:
        SummaryBox(...); NewsList(st.session_state.news_articles)
    else:
        ArticleDetail()

# ④ 우측: ChatPanel
with col_chat:
    ChatPanel(st.session_state.financial_terms, use_openai=USE_OPENAI)

# ⑤ 사이드바 + ⑥ 하단 로그뷰어
Sidebar(st.session_state.financial_terms)
st.markdown("---"); LogViewer()
```

###🎛️ Component Contract (컴포넌트 규약)

- 모든 컴포넌트는 동일한 진입점을 갖습니다.

- 함수형: def render(...): ...

- 혹은 래퍼 함수: SummaryBox(...), NewsList(...) 등 (내부에서 render(호출)

### 규칙
- 파일 1개 = 컴포넌트 1개
- 외부에서 모듈 단위로 import 하고 module.render() 형태로 호출(⚠️ from ... import render 금지: 이름 충돌)

### ✅ 권장
- from components import news_list
- news_list.render(articles)

### ❌ 비권장 (여러 파일의 render가 충돌)
- from components.news_list import render
- render(articles)