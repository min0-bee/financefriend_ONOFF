import streamlit as st
from datetime import datetime

# ─────────────────────────────────────────────────────────────
# 🔧 (1) 내부 모듈 가져오기
# 프로젝트 내부에 정의된 기능들을 import 합니다.
# core/ → 공통 설정, 세션 관리, 로깅
# data/ → 뉴스 데이터 수집
# rag/  → 금융 용어 RAG(지식베이스)
# ui/   → 화면 구성 및 디자인 요소
# ─────────────────────────────────────────────────────────────
from core.config import USE_OPENAI
from core.user import init_session_and_user
from core.logger import log_event
from core.utils import load_logs_as_df

from data.news import collect_news
from rag.glossary import ensure_financial_terms

from ui.styles import inject_styles
from ui.components import (
    render_summary,
    render_news_list,
    render_article_detail,
    render_chatbot,
    render_sidebar,
    show_log_viewer,
)

# ─────────────────────────────────────────────────────────────
# 🧱 (2) 페이지 기본 설정
# ─────────────────────────────────────────────────────────────
# Streamlit 앱의 제목, 레이아웃 등을 설정합니다.
st.set_page_config(
    layout="wide",              # 화면을 넓게 사용
    page_title="금융 뉴스 도우미"  # 브라우저 탭 제목
)

# ─────────────────────────────────────────────────────────────
# 🪄 (3) 세션 / 유저 정보 초기화
# ─────────────────────────────────────────────────────────────
# 세션 상태(st.session_state)는 Streamlit이 유저별로 유지하는 임시 저장소입니다.
# 여기서 유저를 식별하고 필요한 기본값을 설정합니다.
init_session_and_user()  # 세션 ID, 유저 ID 등 생성

# 금융 용어 사전(RAG용 데이터) 보장
# 없으면 기본값을 세팅합니다.
ensure_financial_terms()

# CSS 등 공통 스타일 적용
inject_styles()

# ─────────────────────────────────────────────────────────────
# 🪵 (4) 세션 시작 로그 (최초 1회 기록)
# ─────────────────────────────────────────────────────────────
# 유저가 페이지를 처음 열었을 때 'session_start' 이벤트를 CSV로 기록합니다.
if "session_logged" not in st.session_state:
    log_event(
        "session_start",          # 이벤트 종류
        surface="home",           # 어느 화면에서 발생했는지
        payload={
            "ua": st.session_state.get("_browser", {}),  # 브라우저 정보
            "note": "MVP session start"                  # 부가 설명
        },
    )
    st.session_state.session_logged = True  # 중복 기록 방지용 플래그

# ─────────────────────────────────────────────────────────────
# 🗞️ (5) 뉴스 데이터 준비
# ─────────────────────────────────────────────────────────────
# 뉴스 기사를 세션에 캐시합니다. (한 번 불러오면 다시 불러오지 않음)
if "news_articles" not in st.session_state:
    st.session_state.news_articles = []

# 뉴스가 비어 있으면 수집 실행
if not st.session_state.news_articles:
    with st.spinner("최신 뉴스를 수집하는 중..."):  # 로딩 스피너 표시
        st.session_state.news_articles = collect_news()

# ─────────────────────────────────────────────────────────────
# 💬 (6) 세션 상태: 선택 기사 및 챗봇 대화 기록
# ─────────────────────────────────────────────────────────────
st.session_state.setdefault("selected_article", None)  # 선택된 기사 (없으면 None)
st.session_state.setdefault("chat_history", [])        # 챗봇 대화 로그

# ─────────────────────────────────────────────────────────────
# 🧩 (7) 메인 레이아웃 구성
# ─────────────────────────────────────────────────────────────
# 화면을 두 컬럼으로 분할:
# 왼쪽(뉴스 영역): 2배 넓음 / 오른쪽(챗봇 영역): 1배 넓음
col1, col2 = st.columns([2, 1])

# 왼쪽 영역: 뉴스
with col1:
    st.title("📰 금융 뉴스 도우미")  # 페이지 상단 제목

    # (A) 아직 사용자가 기사를 선택하지 않은 경우
    #  → 뉴스 요약 + 기사 목록을 표시
    if st.session_state.selected_article is None:
        render_summary(st.session_state.news_articles, use_openai=USE_OPENAI)
        render_news_list(st.session_state.news_articles)

    # (B) 사용자가 특정 기사를 클릭한 경우
    #  → 기사 본문 + 하이라이트된 용어 + 설명 버튼 표시
    else:
        render_article_detail()

# 오른쪽 영역: 챗봇 UI
with col2:
    render_chatbot(use_openai=USE_OPENAI)

# ─────────────────────────────────────────────────────────────
# 🧭 (8) 사이드바 & 로그 뷰어
# ─────────────────────────────────────────────────────────────
# 사이드바에는 설정, 도움말, 버전 정보 등을 표시
render_sidebar()

# 하단 구분선
st.markdown("---")

# 수집된 로그 데이터를 테이블로 보여주는 영역
show_log_viewer()

