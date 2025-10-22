
import time, streamlit as st
from core.logger import log_event
from rag.glossary import explain_term

def render(terms: dict[str, dict], use_openai: bool=False):
    st.markdown("### 💬 금융 용어 도우미")
    st.markdown("---")

    with st.container(height=400):
        for message in st.session_state.chat_history:
            role = message["role"]
            css = "user-message" if role == "user" else "bot-message"
            icon = "👤" if role == "user" else "🤖"
            st.markdown(f'<div class="chat-message {css}">{icon} {message["content"]}</div>', unsafe_allow_html=True)

    user_input = st.chat_input("궁금한 금융 용어를 입력하세요...")
    if user_input:
        t0 = time.time()
        log_event("chat_question", message=user_input, source="chat", surface="sidebar")
        st.session_state.chat_history.append({"role": "user", "content": user_input})

        found = next((t for t in terms.keys() if t in user_input), None)
        if found:
            explanation = explain_term(found, st.session_state.chat_history)
            log_event("glossary_answer", term=found, source="chat", surface="sidebar", payload={"answer_len": len(explanation)})
        else:
            explanation = (f"'{user_input}'에 대해 궁금하시군요! MVP 단계에서는 등록된 용어(" + ", ".join(terms.keys()) + ")만 설명합니다. 기사 하이라이트를 눌러도 설명이 떠요 😊")

        latency = int((time.time() - t0) * 1000)
        log_event("chat_response", source="chat", surface="sidebar", payload={"answer_len": len(explanation), "latency_ms": latency})
        st.session_state.chat_history.append({"role": "assistant", "content": explanation})
        st.rerun()

    if st.button("🔄 대화 초기화"):
        log_event("chat_reset", surface="sidebar")
        st.session_state.chat_history = []
        st.rerun()
