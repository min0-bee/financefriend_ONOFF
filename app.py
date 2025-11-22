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
    from ui.components.performance_view import render as PerformanceView
    
    # ① 전역 스타일 & 세션 초기화 (공통 환경 구성) - 즉시 실행 (블로킹 없음)
    inject_styles()
    
    # ② 최소한의 앱 초기화 (뉴스 로드는 백그라운드로)
    from core.user import init_session_and_user
    
    # 세션 및 사용자 초기화만 먼저 (빠름, 블로킹 없음)
    if not st.session_state.get("user_initialized", False):
        init_session_and_user()
        st.session_state["user_initialized"] = True
    
    # 세션 상태 기본값 설정 (빠름)
    st.session_state.setdefault("selected_article", None)
    st.session_state.setdefault("chat_history", [])
    st.session_state.setdefault("term_click_count", 0)
    st.session_state.setdefault("news_click_count", 0)
    st.session_state.setdefault("chat_count", 0)
    st.session_state.setdefault("detail_enter_logged", False)
    st.session_state.setdefault("news_articles", [])
    
    # ③ 뉴스 로드 및 백그라운드 초기화 (비동기로 실행)
    import threading
    from core.init_app import init_app_background
    from core.logger import log_event
    from data.news import load_news_cached, FALLBACK_NEWS
    
    # 뉴스 데이터가 없으면 먼저 동기적으로 빠르게 시도 (캐시 히트 시 즉시)
    # 실제 Supabase 뉴스를 우선적으로 로드 (Fallback 사용 안 함)
    if not st.session_state.news_articles and not st.session_state.get("news_loading", False):
        st.session_state["news_loading"] = True
        try:
            # 먼저 동기적으로 시도 (캐시 히트 시 즉시 로드, Fallback 사용 안 함)
            news = load_news_cached(use_fallback=False)
            if news and len(news) > 0:
                # 실제 Supabase 뉴스가 있으면 즉시 사용
                st.session_state.news_articles = news
                st.session_state["news_loading"] = False
            else:
                # 뉴스가 없으면 백그라운드에서 재시도 (Supabase 연결 재확인)
                def _load_news_async():
                    try:
                        # Supabase에서 실제 뉴스 로드 시도 (Fallback 사용 안 함)
                        news_retry = load_news_cached(use_fallback=False)
                        if news_retry and len(news_retry) > 0:
                            # 실제 뉴스가 있으면 사용
                            st.session_state.news_articles = news_retry
                        else:
                            # Supabase에서 뉴스를 가져올 수 없을 때만 Fallback 사용
                            # (연결 실패 또는 뉴스가 실제로 없을 때)
                            print("⚠️ Supabase에서 뉴스를 가져올 수 없어 Fallback 데이터를 사용합니다.")
                            st.session_state.news_articles = FALLBACK_NEWS
                    except Exception as e:
                        # 에러 발생 시 Supabase 연결 실패로 간주하고 Fallback 사용
                        print(f"⚠️ 뉴스 로드 실패: {e}, Fallback 데이터 사용")
                        st.session_state.news_articles = FALLBACK_NEWS
                    finally:
                        st.session_state["news_loading"] = False
                threading.Thread(target=_load_news_async, daemon=True).start()
        except Exception as e:
            # 첫 시도 실패 시 백그라운드에서 재시도
            print(f"⚠️ 뉴스 로드 첫 시도 실패: {e}, 백그라운드에서 재시도")
            def _load_news_async():
                try:
                    # Supabase에서 실제 뉴스 로드 시도 (Fallback 사용 안 함)
                    news = load_news_cached(use_fallback=False)
                    if news and len(news) > 0:
                        st.session_state.news_articles = news
                    else:
                        # Supabase에서 뉴스를 가져올 수 없을 때만 Fallback 사용
                        print("⚠️ Supabase에서 뉴스를 가져올 수 없어 Fallback 데이터를 사용합니다.")
                        st.session_state.news_articles = FALLBACK_NEWS
                except Exception as e2:
                    # 에러 발생 시 Fallback 데이터 사용
                    print(f"⚠️ 뉴스 로드 실패: {e2}, Fallback 데이터 사용")
                    st.session_state.news_articles = FALLBACK_NEWS
                finally:
                    st.session_state["news_loading"] = False
            threading.Thread(target=_load_news_async, daemon=True).start()
    
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

    with st.sidebar:
        # 화면 선택 라디오 버튼
        view_options = ["뉴스/챗봇", "대시보드", "로그 뷰어"]
        
        current_view = st.session_state.get("main_view", "뉴스/챗봇")
        
        selected_view = st.radio("화면 선택", view_options, index=view_options.index(current_view) if current_view in view_options else 0)
        st.session_state["main_view"] = selected_view

        # LLM 연결 진단 패널 숨김 (프로덕션 환경)
        # render_llm_diagnostics()

    # 대시보드 또는 로그 뷰어 선택 시
    if st.session_state["main_view"] == "대시보드":
        LogViewer(show_mode="dashboard")
        return
    elif st.session_state["main_view"] == "로그 뷰어":
        LogViewer(show_mode="log_viewer")
        return

    # ② 페이지 기본 레이아웃 분할 (5.5:4.5 비율)
    col_main, col_chat = st.columns([5.5, 4.5] , gap="large")

    # ③ 메인 영역 (뉴스 요약, 리스트, 상세)
    with col_main:
        st.title("📰 금융 뉴스 도우미")

        if st.session_state.selected_article is None:
            # ✅ 1단계: 뉴스 목록 먼저 렌더링 (즉시 표시, 블로킹 없음)
            # 뉴스 데이터가 있으면 표시, 없으면 빈 상태로 표시 (백그라운드에서 로딩 중)
            NewsList(st.session_state.news_articles if st.session_state.news_articles else [])
            
            # 뉴스가 로딩 중이면 표시
            if st.session_state.get("news_loading", False):
                st.caption("🔄 최신 뉴스를 불러오는 중...")
            
            # ✅ 2단계: 요약 박스 렌더링 (준비되면 표시, 블로킹 없음)
            # 텍스트 사전이 준비되었는지 확인
            if st.session_state.get("terms_initialized", False):
                SummaryBox(st.session_state.news_articles if st.session_state.news_articles else [], use_openai=USE_OPENAI)
            else:
                # 아직 초기화 중이면 표시하지 않음 (블로킹 없음)
                # 백그라운드에서 초기화 중이므로 나중에 자동으로 표시됨
                pass
        else:
            ArticleDetail()

    # ④ 오른쪽 챗봇 영역 (용어 사전이 준비되면 표시, 블로킹 없음)
    with col_chat:
        # 텍스트 사전이 준비되었는지 확인
        if st.session_state.get("terms_initialized", False):
            ChatPanel(st.session_state.financial_terms, use_openai=USE_OPENAI)
        else:
            # 아직 초기화 중이면 간단한 메시지만 표시 (블로킹 없음)
            st.info("💡 금융 용어 사전을 불러오는 중...")
            # 백그라운드에서 초기화 중이므로 다음 렌더링 시 자동으로 표시됨

    # ⑤ 왼쪽 사이드바: 용어 목록, 설정, 사용법 (용어 사전이 준비되면 표시, 블로킹 없음)
    if st.session_state.get("terms_initialized", False):
        Sidebar(st.session_state.financial_terms)
    # 용어 사전이 없으면 사이드바 표시 안 함 (블로킹 없음)



# 🔧 Streamlit 실행 진입점
# -----------------------------------------------------------------
# 이 모듈은 앱의 '컨트롤 타워'이며,
# 실제 컴포넌트 렌더링은 각 파일(components/*.py)에서 처리됩니다.
# 즉, 이곳은 '오케스트레이션 계층'이고,
# 각 컴포넌트는 render() 함수(혹은 클래스형) 인터페이스를 통해 호출됩니다.
# -----------------------------------------------------------------
if __name__ == "__main__":
    main()
