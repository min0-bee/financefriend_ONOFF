
import streamlit as st
import hashlib
import json
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


def _get_articles_hash(articles):
    """뉴스 목록의 해시를 계산하여 변경 여부 확인 (최적화)"""
    if not articles:
        return ""
    
    # ✅ 성능 개선: 상위 5개 기사의 ID만으로 해시 생성 (더 빠름)
    # ID가 변경되면 뉴스가 변경된 것으로 간주
    tops = articles[:5]
    article_ids = []
    for item in tops:
        if isinstance(item, dict):
            article_id = item.get("id")
            if article_id:
                article_ids.append(str(article_id))
    
    # ID 리스트를 문자열로 변환 후 해시 계산 (JSON 직렬화보다 빠름)
    ids_string = ",".join(sorted(article_ids))
    return hashlib.md5(ids_string.encode('utf-8')).hexdigest()


@st.cache_data(ttl=3600)  # 1시간 캐시 (뉴스가 바뀌지 않는 한 재사용)
def _generate_news_summary(articles_hash: str, articles_context: str, prompt_template: str) -> str:
    """
    뉴스 요약 생성 (st.cache_data로 캐싱)
    - 뉴스 해시를 기반으로 캐시 키 생성
    - 같은 뉴스에 대해서는 세션 간 공유
    """
    from core.utils import llm_chat
    
    sys = {
        "role": "system",
        "content": "너는 초보자에게 금융 시장 이슈를 정확하고 쉽게 요약하는 금융 전문 기자야."
    }
    user_prompt = prompt_template.format(articles=articles_context)
    usr = {"role": "user", "content": user_prompt}
    
    try:
        summary = llm_chat([sys, usr], max_tokens=280, temperature=0.4)
        return summary
    except Exception as e:
        # 에러 발생 시 빈 문자열 반환 (호출하는 쪽에서 fallback 처리)
        raise e


def render(articles, use_openai: bool = False):
    if isinstance(articles, (str, bytes)):
        articles = [articles]
    elif articles is None:
        articles = []

    st.markdown('<div class="summary-box">', unsafe_allow_html=True)
    st.subheader("📊 오늘의 금융 뉴스 요약")

    if use_openai and articles:
        tops = articles[:5]
        
        # ✅ 성능 개선: 뉴스 목록 해시 계산하여 변경 여부 확인
        current_hash = _get_articles_hash(articles)
        articles_context = _format_articles_for_prompt(tops)
        prompt_template = st.session_state.get("news_summary_prompt", DEFAULT_NEWS_SUMMARY_PROMPT)
        
        # ✅ 최적화: st.cache_data로 세션 간 공유 캐싱
        # 뉴스 해시를 기반으로 캐시 키 생성 (같은 뉴스면 재사용)
        # 캐시 히트 여부 추적 (이전 해시와 비교)
        prev_hash = st.session_state.get("news_summary_hash")
        is_cache_hit = prev_hash == current_hash and prev_hash is not None
        
        try:
            # 캐시 미스일 때만 스피너 표시 (캐시 히트 시에는 즉시 반환)
            if not is_cache_hit:
                with st.spinner("🤖 AI가 뉴스를 요약하고 있습니다..."):
                    summary = _generate_news_summary(current_hash, articles_context, prompt_template)
                st.session_state["news_summary_hash"] = current_hash
                st.caption("✅ 새로운 요약 생성 완료")
            else:
                # 캐시 히트: 즉시 반환 (스피너 없음)
                summary = _generate_news_summary(current_hash, articles_context, prompt_template)
                st.caption("💾 캐시된 요약 (뉴스가 변경되지 않아 재요약하지 않음)")
        except Exception as e:
            # 캐시에서 가져오는 중이거나 생성 중 에러 발생 시 fallback
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