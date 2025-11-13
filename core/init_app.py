# === 부트스트랩 인라인 ===
from core.user import init_session_and_user
from core.logger import log_event, _ensure_backend_user, _ensure_backend_session
from data.news import collect_news
from rag.glossary import ensure_financial_terms
from core.config import API_ENABLE
import streamlit as st


def init_app():
    """
    앱 초기화 함수
    ✅ 최적화: 각 단계별로 완료 여부를 체크하여 불필요한 재실행 방지
    """
    # 이미 초기화되었으면 스킵
    if st.session_state.get("app_initialized", False):
        return

    # ✅ 1. 세션 및 사용자 초기화 (user_id, session_id 생성 등)
    if not st.session_state.get("user_initialized", False):
        with st.spinner("👤 사용자 세션 초기화 중..."):
            init_session_and_user()
            st.session_state["user_initialized"] = True

    # ✅ 2. 금융 용어 사전 초기화 (없으면 기본 사전 로드)
    # ✅ 최적화: 이미 초기화되었으면 스킵
    if not st.session_state.get("terms_initialized", False):
        with st.spinner("📚 금융 용어 사전 초기화 중..."):
            ensure_financial_terms()
            st.session_state["terms_initialized"] = True

    # ✅ 2.5. 서버 연결 시 자동으로 UUID로 교체 및 세션 생성 (지연 실행)
    # ✅ 최적화: 이미 연결되었으면 스킵
    if API_ENABLE and not st.session_state.get("server_connected", False):
        user_id = st.session_state.get("user_id")
        if user_id:
            try:
                with st.spinner("🔗 서버 연결 중..."):
                    # 서버에 연결하여 UUID로 교체 (silent=True로 에러 숨김 - event_log만 사용 시)
                    _ensure_backend_user(user_id, silent=True)
                    # 서버 세션 생성 (로그 뷰어에서 사용하기 위해 미리 생성)
                    _ensure_backend_session()
                    st.session_state["server_connected"] = True
            except Exception:
                # 연결 실패해도 계속 진행
                pass

    # ✅ 3. 세션 상태 기본값 설정
    st.session_state.setdefault("selected_article", None)
    st.session_state.setdefault("chat_history", [])
    st.session_state.setdefault("term_click_count", 0)
    st.session_state.setdefault("news_click_count", 0)
    st.session_state.setdefault("chat_count", 0)
    st.session_state.setdefault("detail_enter_logged", False)
    st.session_state.setdefault("news_articles", [])

    # ✅ 4. 뉴스 데이터 수집 (처음 실행 시만, st.cache_data로 캐싱됨)
    if not st.session_state.news_articles:
        with st.spinner("📰 최신 뉴스를 수집하는 중..."):
            st.session_state.news_articles = collect_news() or []

    # ✅ 5. 세션 시작 이벤트 로그 (한 세션에 한 번만 기록)
    if not st.session_state.get("session_logged", False):
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

