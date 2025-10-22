
import streamlit as st
from datetime import datetime
from core.logger import log_event
from rag.glossary import highlight_terms, explain_term

def render():
    article = st.session_state.selected_article
    if not article:
        st.warning("선택된 기사가 없습니다.")
        return

    if not st.session_state.get("detail_enter_logged"):
        log_event("news_detail_open", news_id=article.get("id"), surface="detail", payload={"title": article.get("title")})
        st.session_state.detail_enter_logged = True
        st.session_state.page_enter_time = datetime.now()

    if st.button("← 뉴스 목록으로 돌아가기"):
        log_event("news_detail_back", news_id=article.get("id"), surface="detail")
        st.session_state.selected_article = None
        st.session_state.detail_enter_logged = False
        st.rerun()

    st.markdown("---")
    st.header(article['title'])
    st.caption(f"📅 {article['date']}")
    st.markdown('<div class="article-content">', unsafe_allow_html=True)
    st.markdown(highlight_terms(article['content']), unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    st.info("💡 아래 버튼에서 용어를 선택하면 챗봇이 쉽게 설명해드립니다!")
    st.subheader("🔍 용어 설명 요청")

    terms = [t for t in st.session_state.financial_terms.keys() if t in article['content']]
    for i in range(0, len(terms), 3):
        cols = st.columns(3)
        for j, col in enumerate(cols):
            if i + j < len(terms):
                term = terms[i + j]
                with col:
                    if st.button(f"📌 {term}", key=f"term_btn_{term}", use_container_width=True):
                        st.session_state.term_click_count += 1
                        log_event("glossary_click", term=term, news_id=article.get("id"), source="news_highlight", surface="detail", payload={"click_count": st.session_state.term_click_count})
                        st.session_state.chat_history.append({"role": "user", "content": f"'{term}' 용어를 설명해주세요"})
                        explanation = explain_term(term, st.session_state.chat_history)
                        st.session_state.chat_history.append({"role": "assistant", "content": explanation})
                        log_event("glossary_answer", term=term, source="news_highlight", surface="detail", payload={"answer_len": len(explanation)})
                        st.rerun()
    st.caption("💡 Tip: 버튼을 누르면 오른쪽 챗봇에서 상세 설명을 볼 수 있어요!")
