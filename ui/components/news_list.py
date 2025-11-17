
import streamlit as st
from core.logger import log_event

def render(articles: list[dict]):
    st.subheader("📋 최신 뉴스")

    for article in articles:
        if st.button(
            f"**{article['title']}**\n{article['summary']}",
            key=f"news_{article['id']}",
            use_container_width=True
        ):
            # ✅ 성능 측정: 뉴스 클릭 직후 처리 시간 측정
            import time
            click_start = time.time()
            
            # 뉴스를 클릭할 때마다 세션에 카운트 증가
            st.session_state.news_click_count += 1

            # ✅ 클릭된 기사 선택
            article_id = article.get("id")
            st.session_state.selected_article = article
            
            # ✅ 성능 측정: 클릭 처리 시간
            click_process_time = int((time.time() - click_start) * 1000)
            
            # ✅ 클릭 로그 기록 (성능 정보 포함)
            log_event(
                "news_click",
                news_id=article_id,
                source="list",
                surface="home",
                click_count=st.session_state.news_click_count,
                payload={
                    "title": article.get("title"),
                    "article_id": article_id,
                    "click_process_ms": click_process_time,  # 클릭 처리 시간
                    "content_length": len(article.get("content", "")),  # 기사 길이
                }
            )

            # ✅ 클릭된 기사 선택 후 리렌더링
            st.rerun()


