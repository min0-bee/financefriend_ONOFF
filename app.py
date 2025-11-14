import streamlit as st

# ⚡ 즉시 페이지 설정 (모든 import 전에 실행 - Streamlit 서버를 먼저 시작하여 로딩 화면 표시)
st.set_page_config(layout="wide", page_title="금융 뉴스 도우미")

# 최소한의 import만 (무거운 모듈은 함수 내부에서 지연 로딩)
from core.config import USE_OPENAI
from ui.styles import inject_styles

def main():
    """
    🧩 Main Orchestration Layer
    -----------------------------------------------------------
    이 함수는 전체 앱의 '오케스트레이터(Orchestrator)' 역할을 합니다.
    각 UI 컴포넌트는 독립적으로 구현되어 있지만,
    여기서 하나의 페이지로 '조립'되어 전체 UX가 완성됩니다.

    구성요소:
      - SummaryBox: 오늘의 금융 요약
      - NewsList: 최신 뉴스 목록
      - ArticleDetail: 기사 상세 (선택 시)
      - ChatPanel: 오른쪽 챗봇 영역
      - Sidebar: 용어 사전, 설정, 도움말
      - LogViewer: 내부 로그 대시보드
    -----------------------------------------------------------
    """
    # 무거운 모듈 지연 로딩 (import 시간 단축)
    from core.init_app import init_app
    from core.utils import load_logs_as_df, render_llm_diagnostics
    from ui.components.summary_box import render as SummaryBox
    from ui.components.news_list import render as NewsList
    from ui.components.article_detail import render as ArticleDetail
    from ui.components.chat_panel import render as ChatPanel
    from ui.components.sidebar import render as Sidebar
    from ui.components.log_viewer_server import render as LogViewer
    
    # ① 전역 스타일 & 세션 초기화 (공통 환경 구성)
    inject_styles()
    
    # ② 앱 초기화 (뉴스 먼저 로드)
    init_app()
    
    # ③ 로그 기록 및 백그라운드 초기화 (뉴스 표시 후 실행)
    import threading
    from core.init_app import init_app_background
    from core.logger import log_event
    
    # 세션 시작 로그는 뉴스 표시 후에 기록
    if not st.session_state.get("session_logged", False):
        def _log_session_async():
            try:
                log_event(
                    "session_start",
                    surface="home",
                    payload={
                        "ua": st.session_state.get("_browser", {}),
                        "note": "MVP session start"
                    }
                )
            except Exception:
                pass
        threading.Thread(target=_log_session_async, daemon=True).start()
        st.session_state.session_logged = True
    
    # 백그라운드 초기화 (용어 사전 등)
    if not st.session_state.get("background_init_done", False):
        # 백그라운드에서 실행 (UI 블로킹 없음)
        init_app_background()
        st.session_state["background_init_done"] = True

    st.session_state.setdefault("main_view", "뉴스/챗봇")
    
    # 관리자 권한 체크
    from core.user import is_admin_user
    is_admin = is_admin_user()

    with st.sidebar:
        # 관리자만 로그 뷰어 옵션 표시
        view_options = ["뉴스/챗봇"]
        if is_admin:
            view_options.append("로그 뷰어")
        
        current_view = st.session_state.get("main_view", "뉴스/챗봇")
        # 현재 선택된 뷰가 관리자 전용이고 권한이 없으면 뉴스/챗봇으로 변경
        if current_view == "로그 뷰어" and not is_admin:
            current_view = "뉴스/챗봇"
            st.session_state["main_view"] = current_view
        
        selected_view = st.radio("화면 선택", view_options, index=view_options.index(current_view))
        st.session_state["main_view"] = selected_view

        render_llm_diagnostics()

    if st.session_state["main_view"] == "로그 뷰어":
        # 이중 체크: URL 직접 접근 방지
        if not is_admin:
            st.error("⚠️ 접근 권한이 없습니다. 로그 뷰어는 관리자만 접근할 수 있습니다.")
            st.session_state["main_view"] = "뉴스/챗봇"
            st.rerun()
        
        st.title("📚 내부 로그 뷰어")
        LogViewer()
        return

    # ② 페이지 기본 레이아웃 분할 (7:3 비율)
    col_main, col_chat = st.columns([7, 3])

    # ③ 메인 영역 (뉴스 요약, 리스트, 상세)
    with col_main:
        st.title("📰 금융 뉴스 도우미")

        if st.session_state.selected_article is None:
            # ✅ 1단계: 뉴스 목록 먼저 렌더링 (즉시 표시, 매우 빠름)
            NewsList(st.session_state.news_articles)
            
            # ✅ 2단계: 요약 박스 렌더링 (OpenAI 요약은 준비되면 표시)
            # 텍스트 사전이 준비되었는지 확인
            if st.session_state.get("terms_initialized", False):
                SummaryBox(st.session_state.news_articles, use_openai=USE_OPENAI)
            else:
                # 아직 초기화 중이면 로딩 표시
                with st.spinner("🤖 금융 용어 사전을 불러오는 중..."):
                    # 백그라운드 초기화 강제 실행
                    init_app_background()
                    SummaryBox(st.session_state.news_articles, use_openai=USE_OPENAI)
        else:
            ArticleDetail()

    # ④ 오른쪽 챗봇 영역 (용어 사전이 준비되면 표시)
    with col_chat:
        # 텍스트 사전이 준비되었는지 확인
        if st.session_state.get("terms_initialized", False):
            ChatPanel(st.session_state.financial_terms, use_openai=USE_OPENAI)
        else:
            # 아직 초기화 중이면 로딩 표시
            st.info("💡 금융 용어 사전을 불러오는 중...")
            # 백그라운드 초기화 강제 실행
            init_app_background()
            if st.session_state.get("terms_initialized", False):
                ChatPanel(st.session_state.financial_terms, use_openai=USE_OPENAI)

    # ⑤ 왼쪽 사이드바: 용어 목록, 설정, 사용법 (용어 사전이 준비되면 표시)
    if st.session_state.get("terms_initialized", False):
        Sidebar(st.session_state.financial_terms)
    else:
        # 아직 초기화 중이면 사이드바는 나중에 표시
        init_app_background()
        if st.session_state.get("terms_initialized", False):
            Sidebar(st.session_state.financial_terms)



# 🔧 Streamlit 실행 진입점
# -----------------------------------------------------------------
# 이 모듈은 앱의 '컨트롤 타워'이며,
# 실제 컴포넌트 렌더링은 각 파일(components/*.py)에서 처리됩니다.
# 즉, 이곳은 '오케스트레이션 계층'이고,
# 각 컴포넌트는 render() 함수(혹은 클래스형) 인터페이스를 통해 호출됩니다.
# -----------------------------------------------------------------
if __name__ == "__main__":
    main()
