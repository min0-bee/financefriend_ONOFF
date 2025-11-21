import streamlit as st
from data.news import parse_news_from_url
from core.logger import log_event


def render():
    """
    URL 입력 컴포넌트를 렌더링합니다.
    사용자가 뉴스 URL을 입력하면 파싱하여 뉴스 리스트에 추가합니다.
    """
    st.markdown("---")
    st.subheader("🔗 뉴스 URL 추가")
    
    with st.form("url_input_form", clear_on_submit=True):
        url = st.text_input(
            "뉴스 기사 URL을 입력하세요",
            placeholder="https://example.com/news/article",
            help="원하는 뉴스 기사의 URL을 입력하면 서비스 화면에서 확인할 수 있습니다."
        )
        
        submitted = st.form_submit_button("📥 기사 가져오기", use_container_width=True)
        
        if submitted:
            if not url or not url.strip():
                st.error("⚠️ URL을 입력해주세요.")
            else:
                with st.spinner("🔄 기사를 가져오는 중..."):
                    try:
                        article = parse_news_from_url(url)
                        
                        if article:
                            # 세션 상태에 뉴스 추가
                            if "news_articles" not in st.session_state:
                                st.session_state.news_articles = []
                            
                            # 중복 체크 (같은 URL이 이미 있는지)
                            existing_urls = [a.get("url") for a in st.session_state.news_articles]
                            if article["url"] in existing_urls:
                                st.warning("⚠️ 이미 추가된 기사입니다.")
                            else:
                                # 새 기사를 맨 앞에 추가 (최신순)
                                st.session_state.news_articles.insert(0, article)
                                st.success(f"✅ '{article['title']}' 기사가 추가되었습니다!")
                                
                                # 로그 기록
                                log_event(
                                    "news_url_added",
                                    news_id=article.get("id"),
                                    surface="home",
                                    payload={
                                        "url": url,
                                        "title": article.get("title"),
                                        "source": "url_input"
                                    }
                                )
                                
                                # 성공 후 리렌더링
                                st.rerun()
                        else:
                            st.error("❌ 기사를 가져올 수 없습니다. URL을 확인해주세요.")
                            
                    except Exception as e:
                        st.error(f"❌ 오류가 발생했습니다: {str(e)}")
                        log_event(
                            "news_url_add_error",
                            surface="home",
                            payload={
                                "url": url,
                                "error": str(e)
                            }
                        )




