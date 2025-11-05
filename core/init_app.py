# === 부트스트랩 인라인 ===
from core.user import init_session_and_user
from core.logger import log_event, _ensure_backend_user, _ensure_backend_session
from data.news import collect_news
from rag.glossary import ensure_financial_terms
from core.config import API_ENABLE
import streamlit as st


def init_app():   
    # ✅ 1. 세션 및 사용자 초기화 (user_id, session_id 생성 등)
    init_session_and_user()
    
    # ✅ 1.5. 서버 연결 시 자동으로 UUID로 교체 및 세션 생성
    # event_log 중심 모드에서는 선택적으로 실행 (실패해도 계속 진행)
    if API_ENABLE:
        user_id = st.session_state.get("user_id")
        if user_id:
            # 서버에 연결하여 UUID로 교체 (silent=True로 에러 숨김 - event_log만 사용 시)
            _ensure_backend_user(user_id, silent=True)
            # 서버 세션 생성 (로그 뷰어에서 사용하기 위해 미리 생성)
            _ensure_backend_session()

    # ✅ 2. 금융 용어 사전 초기화 (없으면 기본 사전 로드)
    ensure_financial_terms()

    # ✅ 3. 세션 상태 기본값 설정
    # 선택된 뉴스 기사 (없을 경우 None)
    st.session_state.setdefault("selected_article", None)
    # 챗봇 대화 기록 저장용 리스트
    st.session_state.setdefault("chat_history", [])
    # 금융 용어 클릭 횟수
    st.session_state.setdefault("term_click_count", 0)         # 용어 클릭 수
    st.session_state.setdefault("news_click_count", 0)         # 📰 뉴스 클릭 수  - 추가중
    st.session_state.setdefault("chat_count", 0)               # 💬 챗봇 대화 수  - 추가중
    # 상세 뉴스 진입 로그 기록 여부 (중복 방지)
    st.session_state.setdefault("detail_enter_logged", False)
    # 뉴스 기사 리스트 (빈 상태로 초기화)
    st.session_state.setdefault("news_articles", [])

    # ✅ 4. 뉴스 데이터 수집 (처음 실행 시만)
    if not st.session_state.news_articles:
        with st.spinner("최신 뉴스를 수집하는 중..."):
            # collect_news(): 외부 API 또는 크롤러로부터 최신 뉴스 불러오기
            st.session_state.news_articles = collect_news()

    # ✅ 5. 세션 시작 이벤트 로그 (한 세션에 한 번만 기록)
    if not st.session_state.get("session_logged"):
        log_event(
            "session_start",
            surface="home",  # 발생 위치 (홈 화면)
            payload={
                "ua": st.session_state.get("_browser", {}),  # 브라우저 정보
                "note": "MVP session start"                  # 설명용 메모
            }
        )
        # 중복 로그 방지를 위해 플래그 설정
        st.session_state.session_logged = True

