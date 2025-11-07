# === 부트스트랩 인라인 ===
from core.user import init_session_and_user
from core.logger import log_event, _ensure_backend_user, _ensure_backend_session
from data.news import collect_news
from rag.glossary import ensure_financial_terms
from core.config import API_ENABLE
import streamlit as st


def init_app():
    # 이미 초기화되었으면 스킵
    if st.session_state.get("app_initialized", False):
        return

    # ✅ 1. 세션 및 사용자 초기화 (user_id, session_id 생성 등) - 빠른 작업
    with st.spinner("👤 사용자 세션 초기화 중..."):
        init_session_and_user()

    # ✅ 2. 금융 용어 사전 초기화 (최우선 - RAG 시스템 시작)
    with st.spinner("📚 금융 용어 사전 초기화 중..."):
        ensure_financial_terms()

    # ✅ 2.5. 서버 연결 (선택적) - RAG 초기화가 끝난 뒤에 시도
    if API_ENABLE:
        user_id = st.session_state.get("user_id")

        if user_id:
            try:
                with st.spinner("🔗 서버 연결 중..."):
                    _ensure_backend_user(user_id, silent=True)
                    _ensure_backend_session()
            except Exception:
                pass  # 연결 실패해도 앱 진행에는 영향 없음

    # ✅ 3. 세션 상태 기본값 설정 (빠른 작업)
    st.session_state.setdefault("selected_article", None)
    st.session_state.setdefault("chat_history", [])
    st.session_state.setdefault("term_click_count", 0)
    st.session_state.setdefault("news_click_count", 0)
    st.session_state.setdefault("chat_count", 0)
    st.session_state.setdefault("detail_enter_logged", False)
    st.session_state.setdefault("news_articles", [])

    # ✅ 4. 뉴스 데이터 수집 (처음 실행 시만)
    if not st.session_state.news_articles:
        with st.spinner("📰 최신 뉴스를 수집하는 중..."):
            st.session_state.news_articles = collect_news()

    # ✅ 5. 세션 시작 이벤트 로그 (한 세션에 한 번만 기록)
    if not st.session_state.get("session_logged"):
        log_event(
            "session_start",
            surface="home",
            payload={
                "ua": st.session_state.get("_browser", {}),
                "note": "MVP session start"
            }
        )
        st.session_state.session_logged = True

    # ✅ 초기화 완료 플래그
    st.session_state.app_initialized = True

