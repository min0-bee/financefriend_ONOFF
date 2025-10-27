
import re
import time, streamlit as st
from core.logger import log_event
from rag.glossary import explain_term, search_terms_by_rag
from core.utils import llm_chat  

def render(terms: dict[str, dict], use_openai: bool=False):
    st.markdown("### 💬 금융 용어 도우미")
    st.markdown("---")

    # 대화 히스토리 렌더(기존 그대로)
    with st.container(height=400):
        for message in st.session_state.chat_history:
            role = message["role"]
            css = "user-message" if role == "user" else "bot-message"
            icon = "👤" if role == "user" else "🤖"
            st.markdown(
                f'<div class="chat-message {css}">{icon} {message["content"]}</div>',
                unsafe_allow_html=True
            )

    # 입력창
    user_input = st.chat_input("궁금한 금융 용어를 입력하세요...")
    if user_input:
        t0 = time.time()
        log_event("chat_question", message=user_input, source="chat", surface="sidebar")
        st.session_state.chat_history.append({"role": "user", "content": user_input})

        explanation = None
        matched_term = None
        is_financial_question = False  # 금융 용어 질문인지 판단

        # 1) RAG 정확 매칭 우선 (완전 일치 검색)
        if st.session_state.get("rag_initialized", False):
            try:
                collection = st.session_state.rag_collection
                all_data = collection.get()

                if all_data and all_data['metadatas']:
                    # 정확한 용어 매칭 시도 (단어 경계 고려)
                    for metadata in all_data['metadatas']:
                        rag_term = metadata.get('term', '').strip()
                        synonym = metadata.get('synonym', '').strip()

                        # 단어 경계를 고려한 정확한 매칭 (띄어쓰기, 문장부호 고려)
                        # \b는 단어 경계를 의미하지만 한글에는 적용 안됨
                        # 대신 공백이나 문장 시작/끝에서 매칭되는지 확인
                        pattern_term = r'(^|\s)' + re.escape(rag_term) + r'($|\s|[?!.,])'
                        if re.search(pattern_term, user_input, re.IGNORECASE):
                            matched_term = rag_term
                            is_financial_question = True
                            break

                        # 유의어도 동일하게 체크
                        if synonym:
                            pattern_syn = r'(^|\s)' + re.escape(synonym) + r'($|\s|[?!.,])'
                            if re.search(pattern_syn, user_input, re.IGNORECASE):
                                matched_term = rag_term
                                is_financial_question = True
                                break

                    # 정확 매칭 실패 시 벡터 검색으로 유사 용어 찾기 (단, 금융 관련 키워드가 있을 때만)
                    if not matched_term:
                        # 금융 관련 키워드 체크 (확장 가능)
                        financial_keywords = [
                            '금융', '투자', '주식', '금리', '환율', '배당', '채권', '은행', '예금', '적금',
                            '대출', '이자', '경제', '시장', '주가', '코스피', '원화', '달러', '부동산',
                            '세금', '보험', '펀드', '자산', '재무', '통화', '정책', '용어', '설명', '뭐야', '무엇'
                        ]

                        # 사용자 입력에 금융 키워드가 포함되어 있는지 확인
                        has_financial_keyword = any(kw in user_input for kw in financial_keywords)

                        if has_financial_keyword:
                            rag_results = search_terms_by_rag(user_input, top_k=1)
                            if rag_results and len(rag_results) > 0:
                                # 유사도가 충분히 높은 경우만 매칭 (거리 확인)
                                matched_term = rag_results[0].get('term', '')
                                is_financial_question = True

                    if matched_term:
                        # RAG에서 찾은 용어로 설명 생성
                        explanation = explain_term(matched_term, st.session_state.chat_history)
                        log_event(
                            "glossary_answer",
                            term=matched_term, source="chat_rag", surface="sidebar",
                            payload={"answer_len": len(explanation), "query": user_input}
                        )
            except Exception as e:
                st.warning(f"⚠️ RAG 검색 중 오류 발생: {e}")

        # 2) RAG 실패 시: 하드코딩된 사전에서 정확한 매칭 시도
        if explanation is None and not is_financial_question:
            # 단어 경계를 고려한 정확한 매칭
            for term_key in terms.keys():
                pattern = r'(^|\s)' + re.escape(term_key) + r'($|\s|[?!.,])'
                if re.search(pattern, user_input, re.IGNORECASE):
                    explanation = explain_term(term_key, st.session_state.chat_history)
                    is_financial_question = True
                    log_event(
                        "glossary_answer",
                        term=term_key, source="chat", surface="sidebar",
                        payload={"answer_len": len(explanation)}
                    )
                    break

        # 3) 금융 용어가 아닌 일반 질문: LLM 백업 (use_openai=True일 때만)
        if explanation is None and not is_financial_question:
            if use_openai:
                # 일반 질문에 대한 LLM 응답
                sys = {
                    "role": "system",
                    "content": (
                        "너는 친절하고 박식한 AI 어시스턴트야. "
                        "사용자의 질문에 정확하고 도움이 되는 답변을 제공해줘. "
                        "금융 관련 질문이 아니어도 최선을 다해 답변하되, "
                        "확실하지 않은 내용은 정직하게 모른다고 말해줘."
                    )
                }
                usr = {
                    "role": "user",
                    "content": user_input
                }
                try:
                    explanation = llm_chat([sys, usr], temperature=0.7, max_tokens=500)
                except Exception as e:
                    # LLM 장애 시 기존 MVP 메시지로 폴백
                    explanation = (
                        f"(LLM 연결 오류: {e})\n"
                        "죄송합니다. 현재 일반 질문에 대한 답변 기능에 문제가 있습니다. "
                        "금융 용어에 대해서는 답변해드릴 수 있습니다!"
                    )
            else:
                # 기존 MVP 안내문
                explanation = (
                    f"'{user_input}'에 대해 궁금하시군요! MVP 단계에서는 등록된 용어("
                    + ", ".join(list(terms.keys())[:5]) + " 등"
                    + ")만 설명합니다. 기사 하이라이트를 눌러도 설명이 떠요 😊"
                )

        # 로깅 + 응답 축적
        latency = int((time.time() - t0) * 1000)
        log_event(
            "chat_response",
            source="chat", surface="sidebar",
            payload={"answer_len": len(explanation), "latency_ms": latency}
        )
        st.session_state.chat_history.append({"role": "assistant", "content": explanation})
        st.rerun()

    # 대화 초기화(변경 없음)
    if st.button("🔄 대화 초기화"):
        log_event("chat_reset", surface="sidebar")
        st.session_state.chat_history = []
        st.rerun()
