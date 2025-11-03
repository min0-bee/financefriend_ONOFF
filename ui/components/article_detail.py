import time
from datetime import datetime
import streamlit as st
from core.logger import log_event
from rag.glossary import highlight_terms, explain_term

def render():
    article = st.session_state.selected_article
    if not article:
        st.warning("선택된 기사가 없습니다.")
        return

    # ✅ 최초 진입 시에만 기사 렌더 latency 측정
    if not st.session_state.get("detail_enter_logged"):
        t0 = time.time()

        # # 렌더 시작 로그
        # log_event(
        #     "news_detail_open_start",
        #     news_id=article.get("id"),
        #     surface="detail",
        #     title=article.get("title"),
        #     note="기사 렌더링 시작"
        # )

        # 실제 렌더링
        st.markdown("---")
        st.header(article['title'])
        st.caption(f"📅 {article['date']}")
        st.markdown('<div class="article-content">', unsafe_allow_html=True)
        st.markdown(highlight_terms(article['content']), unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # 렌더 완료 → latency 기록
        latency_ms = int((time.time() - t0) * 1000)
        log_event(
            "news_detail_open",
            news_id=article.get("id"),
            surface="detail",
            title=article.get("title"),
            latency_ms=latency_ms,
            note="기사 렌더링 완료",
        )

        # 플래그 설정(중복 기록 방지)
        st.session_state.detail_enter_logged = True
        st.session_state.page_enter_time = datetime.now()

    else:
        # 재렌더 시에는 단순 표시만 (latency 미측정)
        st.markdown("---")
        st.header(article['title'])
        st.caption(f"📅 {article['date']}")
        st.markdown('<div class="article-content">', unsafe_allow_html=True)
        st.markdown(highlight_terms(article['content']), unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    # ← 목록으로
    if st.button("← 뉴스 목록으로 돌아가기"):
        log_event("news_detail_back", news_id=article.get("id"), surface="detail")
        st.session_state.selected_article = None
        st.session_state.detail_enter_logged = False
        st.rerun()

    # 용어 설명 UI
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

                        # 클릭 → 설명 생성까지 latency 측정
                        t0 = time.time()

                        user_question = f"'{term}' 용어를 설명해주세요"
                        # 대화 히스토리 (사용자 발화 1회만 기록)
                        st.session_state.chat_history.append({"role": "user", "content": user_question})

                        # 설명 생성
                        explanation = explain_term(term, st.session_state.chat_history)
                        latency_ms = int((time.time() - t0) * 1000)

                        # 클릭(자동 질문 포함) 이벤트 로그
                        log_event(
                            "glossary_click",
                            term=term,
                            news_id=article.get("id"),
                            source="news_highlight",
                            surface="detail",
                            message=user_question,              # 자동 생성된 질문
                            click_count=st.session_state.term_click_count,
                            latency_ms=latency_ms
                        )

                        # 답변 히스토리 + 답변 이벤트 로그
                        st.session_state.chat_history.append({"role": "assistant", "content": explanation})
                        log_event(
                            "glossary_answer",
                            term=term,
                            source="news_highlight",
                            surface="detail",
                            message=explanation,                # 설명 본문
                            answer_len=len(explanation),
                            latency_ms=latency_ms,
                            via="glossary"
                        )

                        st.rerun()

    st.caption("💡 Tip: 버튼을 누르면 오른쪽 챗봇에서 상세 설명을 볼 수 있어요!")
