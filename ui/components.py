import time
import streamlit as st
from datetime import datetime

from core.logger import log_event
from core.config import LOG_FILE
from core.utils import load_logs_as_df
from rag.glossary import highlight_terms, explain_term

# ─────────────────────────────────────────────────────────────
# A) 상단 요약 + 뉴스 리스트
# ─────────────────────────────────────────────────────────────

def render_summary(articles, use_openai: bool = False):
    st.markdown('<div class="summary-box">', unsafe_allow_html=True)
    st.subheader("📊 오늘의 금융 뉴스 요약")

    # Mock 요약
    summary = (
        "오늘 금융 시장은 한국은행의 기준금리 동결 결정과 삼성전자의 배당 증액 발표가 주목받았습니다. "
        "원달러 환율이 1,300원을 돌파하며 외환시장의 변동성도 커지고 있습니다. "
        "전문가들은 향후 통화정책 방향과 환율 추이를 주시할 필요가 있다고 조언합니다."
    )
    st.write(summary)
    st.markdown('</div>', unsafe_allow_html=True)

def render_news_list(articles):
    st.subheader("📋 최신 뉴스")
    for article in articles:
        if st.button(f"**{article['title']}**\n{article['summary']}", key=f"news_{article['id']}", use_container_width=True):
            log_event("news_click", news_id=article.get("id"), source="list", surface="home", payload={"title": article.get("title")})
            st.session_state.selected_article = article
            st.rerun()

# ─────────────────────────────────────────────────────────────
# B) 기사 상세 + 하이라이트 + 용어 버튼 + 뒤로가기
# ─────────────────────────────────────────────────────────────

def render_article_detail():
    article = st.session_state.selected_article
    if not article:
        st.warning("선택된 기사가 없습니다.")
        return

    # 상세 화면 진입 로그 (중복 방지)
    if not st.session_state.get("detail_enter_logged"):
        log_event("news_detail_open", news_id=article.get("id"), surface="detail", payload={"title": article.get("title")})
        st.session_state.detail_enter_logged = True
        st.session_state.page_enter_time = datetime.now()

    # 뒤로가기 버튼
    if st.button("← 뉴스 목록으로 돌아가기", use_container_width=False):
        log_event("news_detail_back", news_id=article.get("id"), surface="detail")
        st.session_state.selected_article = None
        st.session_state.detail_enter_logged = False
        st.rerun()

    st.markdown("---")
    st.header(article['title'])
    st.caption(f"📅 {article['date']}")

    st.markdown('<div class="article-content">', unsafe_allow_html=True)
    highlighted = highlight_terms(article['content'])
    st.markdown(highlighted, unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    st.info("💡 아래 버튼에서 용어를 선택하면 챗봇이 쉽게 설명해드립니다!")

    st.subheader("🔍 용어 설명 요청")
    terms = [t for t in st.session_state.financial_terms.keys() if t in article['content']]

    for i in range(0, len(terms), 3):
        cols = st.columns(3)
        for j, col in enumerate(cols):
            if i + j < len(terms):
                term = terms[i + j]
                with col:
                    if st.button(f"📌 {term}", key=f"term_btn_{term}", use_container_width=True, type="secondary"):
                        st.session_state.term_click_count += 1
                        log_event(
                            "glossary_click",
                            term=term,
                            news_id=article.get("id"),
                            source="news_highlight",
                            surface="detail",
                            payload={"click_count": st.session_state.term_click_count},
                        )
                        user_msg = {"role": "user", "content": f"'{term}' 용어를 설명해주세요"}
                        st.session_state.chat_history.append(user_msg)
                        explanation = explain_term(term, st.session_state.chat_history)
                        bot_msg = {"role": "assistant", "content": explanation}
                        st.session_state.chat_history.append(bot_msg)
                        log_event(
                            "glossary_answer",
                            term=term,
                            source="news_highlight",
                            surface="detail",
                            payload={"answer_len": len(explanation)},
                        )
                        st.rerun()

    st.caption("💡 Tip: 위 버튼을 클릭하면 오른쪽 챗봇에서 상세한 설명을 확인할 수 있습니다!")

# ─────────────────────────────────────────────────────────────
# C) 챗봇 영역
# ─────────────────────────────────────────────────────────────

def render_chatbot(use_openai: bool = False):
    st.markdown("### 💬 금융 용어 도우미")
    st.markdown("---")

    chat_container = st.container(height=400)
    with chat_container:
        for message in st.session_state.chat_history:
            if message["role"] == "user":
                st.markdown(f'<div class="chat-message user-message">👤 {message["content"]}</div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="chat-message bot-message">🤖 {message["content"]}</div>', unsafe_allow_html=True)

    user_input = st.chat_input("궁금한 금융 용어를 입력하세요...")
    if user_input:
        t0 = time.time()
        log_event("chat_question", message=user_input, source="chat", surface="sidebar")
        st.session_state.chat_history.append({"role": "user", "content": user_input})

        found_term = None
        for term in st.session_state.financial_terms.keys():
            if term in user_input:
                found_term = term
                break

        if found_term:
            explanation = explain_term(found_term, st.session_state.chat_history)
            log_event("glossary_answer", term=found_term, source="chat", surface="sidebar", payload={"answer_len": len(explanation)})
        else:
            explanation = (
                f"'{user_input}'에 대해 궁금하시군요! MVP 개발 단계에서는 금융 사전에 등록된 용어("
                + ", ".join(st.session_state.financial_terms.keys())
                + ")만 설명이 가능합니다. 해당 용어를 입력하시거나 기사에서 하이라이트된 용어를 선택해주세요! 😊"
            )
            latency = int((time.time() - t0) * 1000)
            log_event("chat_response", source="chat", surface="sidebar", payload={"answer_len": len(explanation), "latency_ms": latency})

        st.session_state.chat_history.append({"role": "assistant", "content": explanation})
        log_event("chat_response", source="chat", surface="sidebar", payload={"answer_len": len(explanation)})
        st.rerun()

    if st.button("🔄 대화 초기화"):
        log_event("chat_reset", surface="sidebar")
        st.session_state.chat_history = []
        st.rerun()

# ─────────────────────────────────────────────────────────────
# D) 사이드바
# ─────────────────────────────────────────────────────────────

def render_sidebar():
    with st.sidebar:
        st.header("⚙️ 설정")
        st.markdown("---")
        st.subheader("📚 금융 용어 사전")
        st.write(f"등록된 용어: {len(st.session_state.financial_terms)}개")
        with st.expander("용어 목록 보기"):
            for term in st.session_state.financial_terms.keys():
                st.write(f"• {term}")
        st.markdown("---")
        st.info(
            """
            **사용 방법:**
            1. 최신 뉴스 목록에서 관심있는 기사를 선택하세요
            2. 기사 내 노란색 용어를 클릭하거나 챗봇에 질문하세요
            3. RAG 기반으로 쉬운 설명을 받아보세요
            """
        )
        st.markdown("---")
        st.caption("💡 OpenAI GPT-4o-mini 사용(추후 활성화)")

# ─────────────────────────────────────────────────────────────
# E) 로그 뷰어
# ─────────────────────────────────────────────────────────────

def show_log_viewer():
    import pandas as pd
    st.markdown("## 🧪 로그 뷰어 (MVP)")
    df = load_logs_as_df(LOG_FILE)
    if df.empty:
        st.info("아직 로그 파일이 없습니다. (logs/events.csv)")
        return

    colA, colB, colC, colD = st.columns(4)
    with colA:
        st.metric("총 이벤트", f"{len(df):,}")
    with colB:
        st.metric("세션 수", df["session_id"].nunique())
    with colC:
        st.metric("유저 수", df["user_id"].nunique())
    with colD:
        st.metric("이벤트 종류", df["event_name"].nunique())

    st.markdown("---")
    agg_by_user = st.toggle("👤 유저(user_id) 기준으로 요약 보기", value=False)

    if agg_by_user:
        g = (
            df.groupby("user_id", dropna=False)
              .agg(events=("event_name", "count"), sessions=("session_id", "nunique"), first_seen=("event_time", "min"), last_seen=("event_time", "max"))
              .reset_index()
              .sort_values(["events", "sessions"], ascending=False)
        )
        colU1, colU2, colU3, colU4 = st.columns(4)
        with colU1:
            st.metric("고유 유저 수", f"{len(g):,}")
        with colU2:
            st.metric("유저당 평균 세션", f"{(g['sessions'].mean() if len(g) else 0):.2f}")
        with colU3:
            st.metric("유저당 평균 이벤트", f"{(g['events'].mean() if len(g) else 0):.1f}")
        with colU4:
            st.metric("총 이벤트(유저 합계)", f"{int(g['events'].sum()):,}")
        st.caption("유저별 활동 요약 (이벤트/세션 많은 순)")
        st.dataframe(g.head(50), use_container_width=True, height=320)

        st.markdown("### 🔎 특정 유저 타임라인")
        target_user = st.selectbox("유저 선택", options=g["user_id"].tolist() if len(g) else [])
        if target_user:
            udf = df[df["user_id"] == target_user].copy().sort_values("event_time")
            st.write(f"세션 수: {udf['session_id'].nunique()}개")
            sess_sum = (
                udf.groupby("session_id", dropna=False)
                   .agg(events=("event_name","count"), start=("event_time","min"), end=("event_time","max"))
                   .assign(dwell_sec=lambda x: (x["end"] - x["start"]).dt.total_seconds())
                   .sort_values("start", ascending=False)
            )
            st.dataframe(sess_sum, use_container_width=True, height=260)

            sel_sess = st.selectbox("세션 선택", options=sess_sum.index.tolist() if len(sess_sum) else [])
            if sel_sess:
                sdf = udf[udf["session_id"] == sel_sess].copy()
                sdf["next_time"] = sdf["event_time"].shift(-1)
                sdf["gap_sec"] = (sdf["next_time"] - sdf["event_time"]).dt.total_seconds()
                st.dataframe(sdf[["event_time","event_name","surface","source","news_id","term","message","gap_sec"]], use_container_width=True, height=320)
        return

    # 기본 탭들
    tab1, tab2, tab3, tab4 = st.tabs(["📄 전체 로그", "📊 이벤트 요약", "🧵 세션 타임라인", "🏷️ 용어 통계"])

    with tab1:
        st.caption("CSV를 테이블로 보기")
        st.dataframe(df, use_container_width=True, height=420)

    with tab2:
        st.caption("이벤트별 건수/최근 10건")
        counts = df["event_name"].value_counts().rename_axis("event_name").reset_index(name="count")
        st.dataframe(counts, use_container_width=True, height=250)
        try:
            st.bar_chart(data=counts.set_index("event_name"))
        except Exception:
            pass
        nc = (df["event_name"] == "news_click").sum()
        ndo = (df["event_name"] == "news_detail_open").sum()
        conv = (ndo / nc * 100) if nc else 0
        st.write(f"**클릭→진입 전환율(rough)**: {conv:.1f}%  (clicks={nc}, opens={ndo})")

    with tab3:
        st.caption("세션을 선택해 타임라인 확인")
        session_ids = df["session_id"].dropna().unique().tolist()
        sess = st.selectbox("세션 선택", options=session_ids, index=0 if session_ids else None)
        if sess:
            sdf = df[df["session_id"] == sess].copy().sort_values("event_time")
            sdf["next_time"] = sdf["event_time"].shift(-1)
            sdf["gap_sec"] = (sdf["next_time"] - sdf["event_time"]).dt.total_seconds()
            st.dataframe(sdf[["event_time","event_name","surface","source","news_id","term","message","gap_sec"]], use_container_width=True, height=420)

    with tab4:
        st.caption("용어 클릭/응답 길이 통계")
        gclick = df[df["event_name"] == "glossary_click"]
        gans = df[df["event_name"] == "glossary_answer"]
        col1, col2 = st.columns(2)
        with col1:
            st.write("용어 클릭 Top N")
            top_terms = gclick["term"].value_counts().head(10).rename_axis("term").reset_index(name="clicks")
            st.dataframe(top_terms, use_container_width=True, height=300)
        with col2:
            if "answer_len" in gans.columns:
                tmp = gans.copy()
                tmp["answer_len"] = pd.to_numeric(tmp["answer_len"], errors="coerce")
                agg = (
                    tmp.groupby("term", dropna=True)["answer_len"]
                        .agg(["count", "mean", "max"])
                        .sort_values("count", ascending=False).head(10)
                )
                st.write("응답 길이 요약(Top10)")
                st.dataframe(agg, use_container_width=True, height=300)
            else:
                st.info("`glossary_answer`에 answer_len이 아직 없어요.")
