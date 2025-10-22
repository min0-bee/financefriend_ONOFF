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