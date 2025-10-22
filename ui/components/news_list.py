
import streamlit as st
from core.logger import log_event

def render(articles: list[dict]):
    st.subheader("📋 최신 뉴스")
    for article in articles:
        if st.button(f"**{article['title']}**\n{article['summary']}", key=f"news_{article['id']}", use_container_width=True):
            log_event("news_click", news_id=article.get("id"), source="list", surface="home", payload={"title": article.get("title")})
            st.session_state.selected_article = article
            st.rerun()
