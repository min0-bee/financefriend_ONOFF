
import streamlit as st

def render(summary_text: str):
    st.markdown('<div class="summary-box">', unsafe_allow_html=True)
    st.subheader("📊 오늘의 금융 뉴스 요약")
    st.write(summary_text)
    st.markdown('</div>', unsafe_allow_html=True)
