# === 부트스트랩 인라인 ===
from core.user import init_session_and_user
from core.logger import log_event
from data.news import collect_news
from rag.glossary import ensure_financial_terms
import streamlit as st


def init_app():   # ← 함수 이름 꼭 일치
    init_session_and_user()
    ensure_financial_terms()
    st.session_state.setdefault("selected_article", None)
    st.session_state.setdefault("chat_history", [])
    st.session_state.setdefault("term_click_count", 0)
    st.session_state.setdefault("detail_enter_logged", False)
    st.session_state.setdefault("news_articles", [])
    if not st.session_state.news_articles:
        with st.spinner("최신 뉴스를 수집하는 중..."):
            st.session_state.news_articles = collect_news()
    if not st.session_state.get("session_logged"):
        log_event("session_start", surface="home",
                  payload={"ua": st.session_state.get("_browser", {}), "note": "MVP session start"})
        st.session_state.session_logged = True
