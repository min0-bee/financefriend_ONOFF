
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
            # 뉴스를 클릭할 때마다 세션에 카운트 증가
            st.session_state.news_click_count += 1

            # ✅ 클릭 로그 기록
            log_event(
                "news_click",
                news_id=article.get("id"),
                source="list",
                surface="home",
                click_count=st.session_state.news_click_count,
                payload={"title": article.get("title")}
            )

            # ✅ 클릭된 기사 선택 후 리렌더링
            st.session_state.selected_article = article
            st.rerun()


