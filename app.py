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
    
    # ② 앱 초기화 (내부에서 단계별 스피너 표시)
    # init_app() 내부에서 각 단계별 스피너가 표시됨
    init_app()

    st.session_state.setdefault("main_view", "뉴스/챗봇")

    with st.sidebar:
        view_options = ["뉴스/챗봇", "로그 뷰어"]
        current_view = st.session_state.get("main_view", "뉴스/챗봇")
        selected_view = st.radio("화면 선택", view_options, index=view_options.index(current_view))
        st.session_state["main_view"] = selected_view

        render_llm_diagnostics()

    if st.session_state["main_view"] == "로그 뷰어":
        st.title("📚 내부 로그 뷰어")
        LogViewer()
        return

    # ② 페이지 기본 레이아웃 분할 (7:3 비율)
    col_main, col_chat = st.columns([7, 3])

    # ③ 메인 영역 (뉴스 요약, 리스트, 상세)
    with col_main:
        st.title("📰 금융 뉴스 도우미")

        if st.session_state.selected_article is None:
            # ✅ 성능 개선: 뉴스 목록을 먼저 렌더링 (즉시 표시)
            # OpenAI 요약은 나중에 표시하여 초기 로딩 속도 개선
            NewsList(st.session_state.news_articles)
            
            # ✅ 요약 박스는 뉴스 목록 다음에 렌더링 (사용자는 이미 뉴스를 볼 수 있음)
            SummaryBox(st.session_state.news_articles, use_openai=USE_OPENAI)
        else:
            ArticleDetail()

    # ④ 오른쪽 챗봇 영역
    with col_chat:
        ChatPanel(st.session_state.financial_terms, use_openai=USE_OPENAI)

    # ⑤ 왼쪽 사이드바: 용어 목록, 설정, 사용법
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
