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

    # ② 페이지 기본 레이아웃 분할 (7:3 비율)
    col_main, col_chat = st.columns([7, 3])

    # ③ 메인 영역 (뉴스 요약, 리스트, 상세)
    with col_main:
        st.title("📰 금융 뉴스 도우미")

        if st.session_state.selected_article is None:
            # 요약 + 목록
            SummaryBox(  # 기존 mock summary는 여기에서 생성
                "오늘 금융 시장은 한국은행의 기준금리 동결과 삼성전자의 배당 증액이 이슈입니다. "
                "원/달러 1300원 돌파로 변동성 확대. 통화정책/환율 추이 주시 필요."
            )
            NewsList(st.session_state.news_articles)
        else:
            # 상세
            ArticleDetail()

    # ④ 오른쪽 챗봇 영역
    with col_chat:
        ChatPanel(st.session_state.financial_terms, use_openai=USE_OPENAI)

    # ⑤ 왼쪽 사이드바: 용어 목록, 설정, 사용법
    Sidebar(st.session_state.financial_terms)
    
    with st.sidebar:
        render_llm_diagnostics()

        st.markdown("### 🔍 RAG 성능 모니터")
        last_init = st.session_state.get("rag_last_initialize_perf")
        last_query = st.session_state.get("rag_last_query_perf")
        perf_logs = st.session_state.get("rag_perf_logs")

        if last_init:
            st.write("마지막 초기화(ms)", last_init)
        else:
            st.caption("초기화 로그가 아직 없습니다.")

        if last_query:
            st.write("마지막 검색(ms)", last_query)
        else:
            st.caption("검색 로그가 아직 없습니다.")

        if perf_logs:
            with st.expander("최근 측정 이력 (최대 10건)"):
                st.json(perf_logs)
        else:
            st.caption("누적 성능 로그가 없습니다.")

        cache_source = st.session_state.get("rag_cache_source")
        if cache_source:
            st.caption(f"RAG 캐시 소스: {cache_source}")

        st.markdown("### 📰 뉴스 로딩 모니터")
        news_perf = st.session_state.get("news_last_fetch_perf")
        if news_perf:
            st.write("마지막 로드", news_perf)
        else:
            st.caption("뉴스 로드 로그가 아직 없습니다.")

        news_logs = st.session_state.get("news_perf_logs")
        if news_logs:
            with st.expander("최근 뉴스 로드 기록"):
                st.json(news_logs)

        news_source = st.session_state.get("news_cache_source")
        if news_source:
            st.caption(f"뉴스 데이터 소스: {news_source}")

    # ⑥ 하단: 내부 분석용 로그 뷰어
    st.markdown("---")
    LogViewer()



# 🔧 Streamlit 실행 진입점
# -----------------------------------------------------------------
# 이 모듈은 앱의 '컨트롤 타워'이며,
# 실제 컴포넌트 렌더링은 각 파일(components/*.py)에서 처리됩니다.
# 즉, 이곳은 '오케스트레이션 계층'이고,
# 각 컴포넌트는 render() 함수(혹은 클래스형) 인터페이스를 통해 호출됩니다.
# -----------------------------------------------------------------
if __name__ == "__main__":
    main()
