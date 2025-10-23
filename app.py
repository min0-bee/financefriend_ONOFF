

import streamlit as st
from core.config import USE_OPENAI
from core.init_app import init_app
from core.utils import load_logs_as_df, render_llm_diagnostics
from ui.styles import inject_styles
from ui.components.summary_box import render as SummaryBox

# 컴포넌트 임포트
from ui.components.summary_box import render as SummaryBox
from ui.components.news_list import render as NewsList
from ui.components.article_detail import render as ArticleDetail
from ui.components.chat_panel import render as ChatPanel
from ui.components.sidebar import render as Sidebar
from ui.components.log_viewer import render as LogViewer



# 📄 페이지 설정: 전체 레이아웃 및 기본 제목
st.set_page_config(layout="wide", page_title="금융 뉴스 도우미")

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
     # ① 전역 스타일 & 세션 초기화 (공통 환경 구성)
    inject_styles()
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
