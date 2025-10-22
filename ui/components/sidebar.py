
import streamlit as st

def render(terms: dict[str, dict]):
    with st.sidebar:
        st.header("⚙️ 설정")
        st.markdown("---")
        st.subheader("📚 금융 용어 사전")
        st.write(f"등록된 용어: {len(terms)}개")
        with st.expander("용어 목록 보기"):
            for t in terms.keys():
                st.write(f"• {t}")
        st.markdown("---")
        st.info("1) 뉴스 선택 → 2) 하이라이트된 용어 클릭 → 3) 오른쪽 챗봇 확인")
        st.markdown("---")
        st.caption("💡 OpenAI 연동은 추후 활성화 예정")
