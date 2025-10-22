### 구조

financefriend_onoff/
├─ app.py # 진입점: 레이아웃/라우팅만 담당
├─ core/
│ ├─ __init__.py
│ ├─ config.py # 상수/플래그/경로
│ ├─ utils.py # 공통 유틸(now_utc_iso, ensure_log_file, load_logs_as_df)
│ ├─ user.py # user_id/session_id 획득 및 세션 스테이트 초기화
│ └─ logger.py # CSV 로깅(log_event)
├─ data/
│ ├─ __init__.py
│ └─ news.py # mock 뉴스 수집(collect_news)
├─ rag/
│ ├─ __init__.py
│ └─ glossary.py # 금융용어 사전 dict, highlight_terms, explain_term
└─ ui/
├─ __init__.py
├─ styles.py # CSS 인젝션
└─ components.py # 요약/뉴스리스트/기사상세/챗봇/사이드바/로그뷰어