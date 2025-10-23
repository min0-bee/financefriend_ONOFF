import os

# 로그 경로
LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "events.csv")
USER_FILE = os.path.join(LOG_DIR, "user_info.json")


# OpenAI 연결 여부 (MVP: False)
USE_OPENAI = True

# Streamlit Secrets가 있으면 그것을 우선 사용
try:
    import streamlit as st
    if "OPENAI_API_KEY" in st.secrets:
        OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
    if "OPENAI_MODEL" in st.secrets:
        DEFAULT_OPENAI_MODEL = st.secrets["OPENAI_MODEL"]
except Exception:
    pass