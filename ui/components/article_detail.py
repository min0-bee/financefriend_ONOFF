
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

    # RAG 시스템이 초기화되어 있으면 RAG의 모든 용어 사용, 아니면 기본 사전 사용
    terms_to_show = []
    if st.session_state.get("rag_initialized", False):
        try:
            collection = st.session_state.rag_collection
            all_data = collection.get()
            if all_data and all_data['metadatas']:
                for metadata in all_data['metadatas']:
                    term = metadata.get('term', '').strip()
                    if term and term in article['content']:
                        terms_to_show.append(term)
                    # 유의어도 체크
                    synonym = metadata.get('synonym', '').strip()
                    if synonym and synonym in article['content']:
                        terms_to_show.append(synonym)
                # 중복 제거
                terms_to_show = list(set(terms_to_show))
        except Exception as e:
            st.warning(f"⚠️ RAG 용어 로드 중 오류: {e}")
            terms_to_show = [t for t in st.session_state.financial_terms.keys() if t in article['content']]
    else:
        terms_to_show = [t for t in st.session_state.financial_terms.keys() if t in article['content']]

    # 버튼 렌더링 (3열 그리드)
    for i in range(0, len(terms_to_show), 3):
        cols = st.columns(3)
        for j, col in enumerate(cols):
            if i + j < len(terms_to_show):
                term = terms_to_show[i + j]
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
