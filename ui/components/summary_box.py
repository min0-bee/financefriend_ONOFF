
import streamlit as st
from core.utils import llm_chat
from core.config import DEFAULT_OPENAI_MODEL


# 📰 오늘의 금융 뉴스 요약 박스 렌더링 함수
def render(articles, use_openai : bool = False):
    st.markdown('<div class="summary-box">', unsafe_allow_html=True)
    st.subheader("📊 오늘의 금융 뉴스 요약")

    if use_openai and articles:
        # 기사 타이틀/ 요약 몇 개만 LLM에 전달 (토큰 보호)
        tops = articles[:5]
        news_bullets = "\n".join([f"- {a['title']} :: {a.get('summary','')}" for a in tops])
        sys = {"role": "system", "content": "너는 초보자에게 금융 뉴스를 3~4문장으로 쉽고 정확하게 요약하는 도우미야."}
        usr = {"role": "user", "content": f"다음 항목을 오늘의 포인트로 3~4문장 요약해줘.\n{news_bullets}\n\n일반 투자권유는 하지 말고, 중립적으로 핵심만."}
        try:
            summary = llm_chat([sys,usr], max_tokens= 280)
        except Exception as e:
            summary = f"요약 생성 중 오류가 발생했습니다: {e}\n(임시 Mock 요약을 표시합니다.)"
    else:
        # Mock 고정 텍스트
        summary = (
            "오늘 금융 시장은 한국은행의 기준금리 동결 결정과 삼성전자의 배당 증액 발표가 주목받았습니다. "
            "원달러 환율이 1,300원을 돌파하며 외환시장의 변동성도 커지고 있습니다. "
            "전문가들은 향후 통화정책 방향과 환율 추이를 주시할 필요가 있다고 조언합니다."
        )


    st.write(summary)
    st.caption(f"🔧 model: {DEFAULT_OPENAI_MODEL} | use_openai={use_openai}")
    st.markdown('</div>', unsafe_allow_html=True)