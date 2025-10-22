
from core.config import LOG_FILE
from core.utils import load_logs_as_df
import streamlit as st
import pandas as pd

def render():
    st.markdown("## 🧪 로그 뷰어 (MVP)")
    df = load_logs_as_df(LOG_FILE)
    if df.empty:
        st.info("아직 로그 파일이 없습니다. (logs/events.csv)")
        return
    st.dataframe(df, use_container_width=True, height=420)
