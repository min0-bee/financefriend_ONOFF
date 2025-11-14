# === 부트스트랩 인라인 ===
from core.user import init_session_and_user
from core.logger import log_event, _ensure_backend_user, _ensure_backend_session
from data.news import load_news_cached
from rag.glossary import ensure_financial_terms
from core.config import API_ENABLE
import streamlit as st


def init_app():
    """
    앱 초기화 함수 (뉴스 우선, 나머지 나중)
    ✅ 최적화: 실제 DB 뉴스를 먼저 로드하고 UI에 즉시 표시
    ✅ 최적화: 로그, 용어 사전 등은 나중에 실행 (UI 블로킹 방지)
    """
    # ✅ 1. 세션 및 사용자 초기화 (user_id, session_id 생성 등) - 필수 (빠름)
    if not st.session_state.get("user_initialized", False):
        init_session_and_user()
        st.session_state["user_initialized"] = True

    # ✅ 2. 세션 상태 기본값 설정 - 필수 (빠름)
    st.session_state.setdefault("selected_article", None)
    st.session_state.setdefault("chat_history", [])
    st.session_state.setdefault("term_click_count", 0)
    st.session_state.setdefault("news_click_count", 0)
    st.session_state.setdefault("chat_count", 0)
    st.session_state.setdefault("detail_enter_logged", False)
    st.session_state.setdefault("news_articles", [])

    # ✅ 3. 뉴스 데이터 먼저 수집 (실제 DB 뉴스 우선 표시)
    # ✅ 최적화: 뉴스는 블로킹되어도 됨 (사용자가 뉴스를 먼저 보고 싶어함)
    # ✅ 최적화: st.cache_data로 서버 기준 5분 동안 모든 세션이 공유
    if not st.session_state.news_articles:
        # 실제 DB에서 뉴스 로드 (Supabase 쿼리)
        st.session_state.news_articles = load_news_cached()

    # ✅ 4. 세션 시작 이벤트 로그는 나중에 실행 (뉴스 표시 후)
    # 로그는 비동기로 기록되지만, CSV 저장은 동기적이므로 나중에 실행


def init_app_background():
    """
    백그라운드에서 실행할 초기화 작업
    ✅ 최적화: UI를 블로킹하지 않는 작업들을 나중에 실행
    """
    # ✅ 1. 금융 용어 사전 초기화 (Lazy Loading + 백그라운드 로딩)
    # ✅ 최적화: 텍스트 사전만 빠르게 로드 (0.1초) → 즉시 UI 표시
    # ✅ 최적화: RAG 시스템은 백그라운드에서 로드 → 사용자는 기다리지 않음
    if not st.session_state.get("terms_initialized", False):
        # 텍스트 사전만 빠르게 로드 (스피너 없이 즉시 완료)
        ensure_financial_terms()
        st.session_state["terms_initialized"] = True

    # ✅ 2. 서버 연결 시 자동으로 UUID로 교체 및 세션 생성 (지연 실행)
    # ✅ 최적화: 이미 연결되었으면 스킵
    if API_ENABLE and not st.session_state.get("server_connected", False):
        user_id = st.session_state.get("user_id")
        if user_id:
            try:
                # 서버 연결은 백그라운드에서 조용히 수행 (에러 숨김)
                _ensure_backend_user(user_id, silent=True)
                _ensure_backend_session()
                st.session_state["server_connected"] = True
            except Exception:
                # 연결 실패해도 계속 진행
                pass

