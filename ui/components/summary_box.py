
import streamlit as st
from core.utils import llm_chat
from core.config import DEFAULT_OPENAI_MODEL, DEFAULT_NEWS_SUMMARY_PROMPT


# 📰 오늘의 금융 뉴스 요약 박스 렌더링 함수
def _format_articles_for_prompt(articles):
    if isinstance(articles, (str, bytes)):
        articles = [articles]
    elif not isinstance(articles, (list, tuple)):
        articles = list(articles) if articles else []

    lines = []
    for item in articles:
        title = item.get("title") or "제목 없음"
        summary = item.get("summary") or item.get("content", "")
        date = item.get("date")
        if date:
            lines.append(f"- [{date}] {title} :: {summary}")
        else:
            lines.append(f"- {title} :: {summary}")
    return "\n".join(lines)


def _build_fallback_summary(articles):
    if isinstance(articles, (str, bytes)):
        articles = [articles]
    elif not isinstance(articles, (list, tuple)):
        articles = list(articles) if articles else []

    if not articles:
        return (
            "오늘의 주요 금융 뉴스는 준비된 데이터가 없어 기본 안내를 표시합니다. "
            "뉴스 수집이 가능해지면 다시 시도해 주세요."
        )

    bullets = []
    for item in articles[:3]:
        if isinstance(item, dict):
            title = item.get("title") or "제목 없음"
            summary = item.get("summary") or item.get("content", "내용 없음")
            date = item.get("date")
            prefix = f"[{date}] " if date else ""
            bullets.append(f"• {prefix}{title}: {summary}")
        else:
            bullets.append(f"• {str(item)}")
    return "\n".join(bullets)


def render(articles, use_openai: bool = False):
    if isinstance(articles, (str, bytes)):
        articles = [articles]
    elif articles is None:
        articles = []

    st.markdown('<div class="summary-box">', unsafe_allow_html=True)
    st.subheader("📊 오늘의 금융 뉴스 요약")

    if use_openai and articles:
        tops = articles[:5]
        articles_context = _format_articles_for_prompt(tops)
        prompt_template = st.session_state.get("news_summary_prompt", DEFAULT_NEWS_SUMMARY_PROMPT)
        user_prompt = prompt_template.format(articles=articles_context)

        sys = {
            "role": "system",
            "content": "너는 초보자에게 금융 시장 이슈를 정확하고 쉽게 요약하는 금융 전문 기자야."
        }
        usr = {"role": "user", "content": user_prompt}
        try:
            summary = llm_chat([sys, usr], max_tokens=280, temperature=0.4)
        except Exception as e:
            summary = (
                f"요약 생성 중 오류가 발생했습니다: {e}\n"
                "아래는 최근 기사 목록을 간단히 나열한 정보입니다.\n"
                + _build_fallback_summary(tops)
            )
    else:
        summary = _build_fallback_summary(articles[:5])


    st.write(summary)
    if use_openai:
        st.caption(f"🔧 사용 모델: {DEFAULT_OPENAI_MODEL} (LLM 요약 활성)")
    else:
        st.caption("ℹ️ LLM 요약이 비활성화되어 기본 요약을 표시합니다.")
    st.markdown('</div>', unsafe_allow_html=True)