
import time, streamlit as st
from core.logger import log_event
from rag.glossary import explain_term
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

    # 입력창(기존 그대로)
    user_input = st.chat_input("궁금한 금융 용어를 입력하세요...")
    if user_input:
        t0 = time.time()
        log_event("chat_question", message=user_input, source="chat", surface="sidebar")
        st.session_state.chat_history.append({"role": "user", "content": user_input})

        # 1) 사전 매칭 우선 (변경 없음)
        found = next((t for t in terms.keys() if t in user_input), None)
        if found:
            explanation = explain_term(found, st.session_state.chat_history)
            log_event(
                "glossary_answer",
                term=found, source="chat", surface="sidebar",
                payload={"answer_len": len(explanation)}
            )
        else:
            # 2) LLM 백업(🔌 use_openai=True일 때만)
            if use_openai:
                sys = {
                    "role": "system",
                    "content": (
                        "너는 초보자를 위해 금융 용어/질문을 쉬운 한국어로 설명하는 도우미야. "
                        "정확하고 중립적으로, 과장 없이. 출력 형식: "
                        "1) 정의  2) 핵심 포인트 2~3개  3) 아주 짧은 예시"
                    )
                }
                usr = {
                    "role": "user",
                    "content": f"이 용어/질문을 쉽게 설명해줘: {user_input}"
                }
                try:
                    # max_tokens/temperature는 필요시 config로 뺄 수 있음
                    explanation = llm_chat([sys, usr], temperature=0.2, max_tokens=420)
                except Exception as e:
                    # LLM 장애 시 기존 MVP 메시지로 폴백
                    explanation = (
                        f"(LLM 연결 오류: {e})\n"
                        "MVP 단계에서는 등록된 용어만 안정적으로 지원합니다. 다음 중에서 선택해 주세요: "
                        + ", ".join(terms.keys())
                    )
            else:
                # 기존 MVP 안내문 (변경 없음)
                explanation = (
                    f"'{user_input}'에 대해 궁금하시군요! MVP 단계에서는 등록된 용어("
                    + ", ".join(terms.keys())
                    + ")만 설명합니다. 기사 하이라이트를 눌러도 설명이 떠요 😊"
                )

        # 로깅 + 응답 축적 (변경 없음)
        latency = int((time.time() - t0) * 1000)
        log_event(
            "chat_response",
            source="chat",
            surface="sidebar",
            message=explanation,          # ✅ 챗봇 답변 본문
            answer_len=len(explanation),  # ✅ 응답 길이
            latency_ms=latency            # ✅ 응답 지연(ms)
        )
        st.session_state.chat_history.append({"role": "assistant", "content": explanation})
        st.rerun()

    # 대화 초기화(변경 없음)
    if st.button("🔄 대화 초기화"):
        log_event("chat_reset", surface="sidebar")
        st.session_state.chat_history = []
        st.rerun()
