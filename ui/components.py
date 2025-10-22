import time
import streamlit as st
from datetime import datetime

from core.logger import log_event
from core.config import LOG_FILE
from core.utils import load_logs_as_df
from rag.glossary import highlight_terms, explain_term

# ---------------------------------------------------------------------
# ⚠️ 사전 준비(중요)
# - 이 파일은 UI 컴포넌트 모음입니다. app.py에서 아래 함수들을 호출해 레이아웃을 그립니다.
# - app.py(혹은 초기화 코드)에서 다음과 같은 세션 상태가 준비되어 있어야 합니다.
#     - st.session_state.financial_terms : {용어: 설명} dict
#     - st.session_state.chat_history    : [{"role": "user"/"assistant", "content": "..."} ...]
#     - st.session_state.selected_article: None 또는 dict(선택 기사)
#     - st.session_state.term_click_count: int (0부터 시작)
# - log_event(...)은 CSV로 이벤트를 쌓는 로거입니다. (MVP 단계에서 사용자 행동 데이터 분석용)
# ---------------------------------------------------------------------


# ─────────────────────────────────────────────────────────────
# A) 상단 요약 + 뉴스 리스트
# ─────────────────────────────────────────────────────────────

def render_summary(articles, use_openai: bool = False):
    """
    상단 '오늘의 금융 뉴스 요약' 영역 렌더링.
    - Streamlit은 HTML도 렌더링할 수 있어(unsafe_allow_html=True)로 CSS 박스처럼 묶음.
    - 실제 서비스에서는 use_openai=True로 전환하여 LLM 요약을 붙일 수 있음.
    """
    st.markdown('<div class="summary-box">', unsafe_allow_html=True)
    st.subheader("📊 오늘의 금융 뉴스 요약")

    # ✅ 현재는 Mock 텍스트(고정값). 이후 OpenAI/Agent 연결로 교체 가능.
    summary = (
        "오늘 금융 시장은 한국은행의 기준금리 동결 결정과 삼성전자의 배당 증액 발표가 주목받았습니다. "
        "원달러 환율이 1,300원을 돌파하며 외환시장의 변동성도 커지고 있습니다. "
        "전문가들은 향후 통화정책 방향과 환율 추이를 주시할 필요가 있다고 조언합니다."
    )
    st.write(summary)
    st.markdown('</div>', unsafe_allow_html=True)


def render_news_list(articles):
    """
    뉴스 목록 영역.
    - 각 뉴스는 '버튼'으로 표시 → 클릭 시 세션 상태에 선택 기사 저장 → st.rerun()으로 페이지 즉시 갱신.
    - log_event(...)로 뉴스 클릭을 이벤트로 기록.
    """
    st.subheader("📋 최신 뉴스")

    # 🔎 Streamlit은 루프 안에서 여러 개의 버튼을 만드는 패턴이 흔함.
    #    key를 고유하게 설정해야 버튼 상태가 섞이지 않음.
    for article in articles:
        # 버튼 한 개 = 기사 카드 한 개라고 생각하면 됨.
        # use_container_width=True → 버튼이 상위 컨테이너의 가로폭에 맞게 늘어남.
        if st.button(
            f"**{article['title']}**\n{article['summary']}",
            key=f"news_{article['id']}",
            use_container_width=True
        ):
            # 🔔 이벤트 로깅 (어떤 뉴스가, 어떤 화면에서, 어떤 경로로 클릭되었는지)
            log_event(
                "news_click",
                news_id=article.get("id"),
                source="list",           # 클릭이 발생한 컴포넌트/맥락
                surface="home",          # 화면(페이지) 위치
                payload={"title": article.get("title")}
            )
            # ✅ 선택한 기사를 세션 상태에 저장 → 라우팅 없이 뷰 전환 효과
            st.session_state.selected_article = article

            # ❗️즉시 rerun: Streamlit은 "상태"가 바뀌면 전체 스크립트를 다시 실행해 최신 UI를 반영
            st.rerun()


# ─────────────────────────────────────────────────────────────
# B) 기사 상세 + 하이라이트 + 용어 버튼 + 뒤로가기
# ─────────────────────────────────────────────────────────────

def render_article_detail():
    """
    기사 상세 페이지.
    - 세션에 저장된 selected_article을 읽어 상세 뷰를 그림.
    - '하이라이트'는 glossary.highlight_terms로 처리(용어는 <mark> 등으로 강조).
    - 하단의 용어 버튼을 누르면 오른쪽 챗봇에 설명이 추가되도록 chat_history에 메시지를 push.
    - back 버튼 → 목록 화면으로 복귀(세션 상태를 None으로 되돌리고 rerun).
    """
    article = st.session_state.selected_article
    if not article:
        st.warning("선택된 기사가 없습니다.")
        return

    # ✅ 상세 화면에 처음 들어올 때 한 번만 열람 이벤트를 로깅하기 위한 플래그
    if not st.session_state.get("detail_enter_logged"):
        log_event(
            "news_detail_open",
            news_id=article.get("id"),
            surface="detail",
            payload={"title": article.get("title")}
        )
        st.session_state.detail_enter_logged = True
        st.session_state.page_enter_time = datetime.now()  # 체류시간(dwell time) 측정 등에 활용 가능

    # ⬅️ 뒤로가기: 목록 화면으로
    if st.button("← 뉴스 목록으로 돌아가기", use_container_width=False):
        log_event("news_detail_back", news_id=article.get("id"), surface="detail")
        # 목록으로 돌아갈 때 상세 플래그 초기화
        st.session_state.selected_article = None
        st.session_state.detail_enter_logged = False
        st.rerun()

    st.markdown("---")
    st.header(article['title'])
    st.caption(f"📅 {article['date']}")

    # 🖍️ 기사 본문 + 용어 하이라이트 표시
    st.markdown('<div class="article-content">', unsafe_allow_html=True)
    highlighted = highlight_terms(article['content'])
    st.markdown(highlighted, unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    st.info("💡 아래 버튼에서 용어를 선택하면 챗봇이 쉽게 설명해드립니다!")

    # ✅ 기사 본문에 등장한 용어만 추출 → 버튼으로 노출
    #    (성능을 위해선 highlight_terms가 돌려준 매칭 결과를 재사용하는 편이 좋음)
    terms = [t for t in st.session_state.financial_terms.keys() if t in article['content']]

    st.subheader("🔍 용어 설명 요청")
    # 3개씩 열 배치(그리드)
    for i in range(0, len(terms), 3):
        cols = st.columns(3)
        for j, col in enumerate(cols):
            if i + j < len(terms):
                term = terms[i + j]
                with col:
                    # type="secondary"는 최신 Streamlit에서 Button 스타일 옵션(테마에 따라 다르게 보일 수 있음)
                    if st.button(f"📌 {term}", key=f"term_btn_{term}", use_container_width=True, type="secondary"):
                        # 용어 클릭 카운터(간단한 인터랙션 지표)
                        st.session_state.term_click_count += 1
                        log_event(
                            "glossary_click",
                            term=term,
                            news_id=article.get("id"),
                            source="news_highlight",
                            surface="detail",
                            payload={"click_count": st.session_state.term_click_count},
                        )
                        # 오른쪽 챗봇에 '유저가 물었다'는 히스토리를 추가
                        user_msg = {"role": "user", "content": f"'{term}' 용어를 설명해주세요"}
                        st.session_state.chat_history.append(user_msg)

                        # RAG/사전 기반으로 용어 설명 생성 → 챗봇 메시지에 추가
                        explanation = explain_term(term, st.session_state.chat_history)
                        bot_msg = {"role": "assistant", "content": explanation}
                        st.session_state.chat_history.append(bot_msg)

                        # 응답 길이도 로깅해두면 품질/길이 상관 분석 가능
                        log_event(
                            "glossary_answer",
                            term=term,
                            source="news_highlight",
                            surface="detail",
                            payload={"answer_len": len(explanation)},
                        )
                        st.rerun()  # 버튼 클릭 후 UI 업데이트

    st.caption("💡 Tip: 위 버튼을 클릭하면 오른쪽 챗봇에서 상세한 설명을 확인할 수 있습니다!")


# ─────────────────────────────────────────────────────────────
# C) 챗봇 영역
# ─────────────────────────────────────────────────────────────

def render_chatbot(use_openai: bool = False):
    """
    오른쪽 사이드(또는 메인)의 챗봇 영역.
    - chat_input은 하단 고정 입력창 제공.
    - chat_history를 순회하며 대화 버블 표시.
    - 입력된 텍스트에서 사전 용어를 찾아 설명(없으면 안내 메시지).
    """
    st.markdown("### 💬 금융 용어 도우미")
    st.markdown("---")

    # ✅ 스크롤 가능한 메시지 컨테이너
    #   (height로 고정 높이, 내부가 넘치면 스크롤)
    chat_container = st.container(height=400)
    with chat_container:
        for message in st.session_state.chat_history:
            # 간단한 역할별 스타일(HTML)
            if message["role"] == "user":
                st.markdown(
                    f'<div class="chat-message user-message">👤 {message["content"]}</div>',
                    unsafe_allow_html=True
                )
            else:
                st.markdown(
                    f'<div class="chat-message bot-message">🤖 {message["content"]}</div>',
                    unsafe_allow_html=True
                )

    # ✅ Streamlit 전용 채팅 입력창 (Enter로 전송)
    user_input = st.chat_input("궁금한 금융 용어를 입력하세요...")
    if user_input:
        t0 = time.time()

        # 1) 질문 로깅
        log_event("chat_question", message=user_input, source="chat", surface="sidebar")

        # 2) 히스토리 추가(유저 발화)
        st.session_state.chat_history.append({"role": "user", "content": user_input})

        # 3) 간단한 키워드 매칭: 입력문에 사전에 있는 용어가 포함되었는지 검사
        found_term = None
        for term in st.session_state.financial_terms.keys():
            if term in user_input:
                found_term = term
                break

        # 4) 용어가 발견되면 설명, 아니면 안내문 반환
        if found_term:
            explanation = explain_term(found_term, st.session_state.chat_history)
            log_event(
                "glossary_answer",
                term=found_term,
                source="chat",
                surface="sidebar",
                payload={"answer_len": len(explanation)}
            )
        else:
            # MVP 한정: 사전에 등록된 용어만 지원
            explanation = (
                f"'{user_input}'에 대해 궁금하시군요! MVP 개발 단계에서는 금융 사전에 등록된 용어("
                + ", ".join(st.session_state.financial_terms.keys())
                + ")만 설명이 가능합니다. 해당 용어를 입력하시거나 기사에서 하이라이트된 용어를 선택해주세요! 😊"
            )
            latency = int((time.time() - t0) * 1000)
            # chat_response는 일반 답변(용어 미인식)에 대한 이벤트
            log_event(
                "chat_response",
                source="chat",
                surface="sidebar",
                payload={"answer_len": len(explanation), "latency_ms": latency}
            )

        # 5) 히스토리 추가(봇 응답)
        st.session_state.chat_history.append({"role": "assistant", "content": explanation})

        # 6) 응답 로깅(중복일 수 있으나, 이후 분석에서 분리해서 쓸 수 있음)
        log_event("chat_response", source="chat", surface="sidebar", payload={"answer_len": len(explanation)})

        # 7) UI 업데이트
        st.rerun()

    # 🔄 대화 초기화(세션의 chat_history만 비워 간단 리셋)
    if st.button("🔄 대화 초기화"):
        log_event("chat_reset", surface="sidebar")
        st.session_state.chat_history = []
        st.rerun()


# ─────────────────────────────────────────────────────────────
# D) 사이드바
# ─────────────────────────────────────────────────────────────

def render_sidebar():
    """
    좌측 사이드바.
    - 기본 설정, 간단 사용법, 사전 내 등록 용어 개수/목록 제공.
    - 간단한 온보딩 가이드 제공으로 유입 사용자 학습 비용 낮춤.
    """
    with st.sidebar:
        st.header("⚙️ 설정")
        st.markdown("---")

        st.subheader("📚 금융 용어 사전")
        st.write(f"등록된 용어: {len(st.session_state.financial_terms)}개")

        # 접었다 펴는 영역(expander)
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
        st.caption("💡 OpenAI GPT-4o-mini 사용(추후 활성화)")  # 실제 활성화 시 토글/설정 UI로 변경 가능


# ─────────────────────────────────────────────────────────────
# E) 로그 뷰어
# ─────────────────────────────────────────────────────────────

def show_log_viewer():
    """
    내부 QA/운영용 간단 로그 뷰어(MVP).
    - CSV로 쌓인 이벤트를 DataFrame으로 읽어 간단한 메트릭/탭/테이블로 확인.
    - Streamlit의 '탭', '토글', '셀렉트박스', '데이터프레임', '차트' 등을 학습하기 좋은 예시.
    """
    import pandas as pd

    st.markdown("## 🧪 로그 뷰어 (MVP)")
    df = load_logs_as_df(LOG_FILE)

    if df.empty:
        st.info("아직 로그 파일이 없습니다. (logs/events.csv)")
        return

    # 상단 4개 지표 카드: 전체 이벤트 수/세션 수/유저 수/이벤트 종류 수
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

    # 👤 유저 단위 요약 보기 토글
    agg_by_user = st.toggle("👤 유저(user_id) 기준으로 요약 보기", value=False)

    if agg_by_user:
        # groupby로 유저별 이벤트/세션/최초/최종 활동 정리
        g = (
            df.groupby("user_id", dropna=False)
              .agg(
                  events=("event_name", "count"),
                  sessions=("session_id", "nunique"),
                  first_seen=("event_time", "min"),
                  last_seen=("event_time", "max")
              )
              .reset_index()
              .sort_values(["events", "sessions"], ascending=False)
        )

        # 요약 메트릭
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

        # 특정 유저 타임라인 드릴다운
        st.markdown("### 🔎 특정 유저 타임라인")
        target_user = st.selectbox("유저 선택", options=g["user_id"].tolist() if len(g) else [])
        if target_user:
            udf = df[df["user_id"] == target_user].copy().sort_values("event_time")
            st.write(f"세션 수: {udf['session_id'].nunique()}개")

            # 세션별 요약: 시작/끝/체류시간
            sess_sum = (
                udf.groupby("session_id", dropna=False)
                   .agg(
                       events=("event_name","count"),
                       start=("event_time","min"),
                       end=("event_time","max")
                   )
                   .assign(dwell_sec=lambda x: (x["end"] - x["start"]).dt.total_seconds())
                   .sort_values("start", ascending=False)
            )
            st.dataframe(sess_sum, use_container_width=True, height=260)

            # 특정 세션 선택 → 이벤트 타임라인 표
            sel_sess = st.selectbox("세션 선택", options=sess_sum.index.tolist() if len(sess_sum) else [])
            if sel_sess:
                sdf = udf[udf["session_id"] == sel_sess].copy()
                sdf["next_time"] = sdf["event_time"].shift(-1)  # 다음 이벤트 시간(간격 계산용)
                sdf["gap_sec"] = (sdf["next_time"] - sdf["event_time"]).dt.total_seconds()
                st.dataframe(
                    sdf[["event_time","event_name","surface","source","news_id","term","message","gap_sec"]],
                    use_container_width=True,
                    height=320
                )
        return  # 유저 요약 뷰 종료

    # 기본 탭 구성: 전체/요약/세션/용어
    tab1, tab2, tab3, tab4 = st.tabs(["📄 전체 로그", "📊 이벤트 요약", "🧵 세션 타임라인", "🏷️ 용어 통계"])

    with tab1:
        st.caption("CSV를 테이블로 보기")
        st.dataframe(df, use_container_width=True, height=420)

    with tab2:
        st.caption("이벤트별 건수/최근 10건")
        counts = df["event_name"].value_counts().rename_axis("event_name").reset_index(name="count")
        st.dataframe(counts, use_container_width=True, height=250)

        # 간단 바차트(에러는 무시: Streamlit 버전에 따라 index 세팅 방식이 다를 수 있음)
        try:
            st.bar_chart(data=counts.set_index("event_name"))
        except Exception:
            pass

        # 예시 지표: 뉴스 클릭 → 상세 진입 전환율
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
            st.dataframe(
                sdf[["event_time","event_name","surface","source","news_id","term","message","gap_sec"]],
                use_container_width=True,
                height=420
            )

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
            # answer_len이 로깅된 경우에만 통계
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


# ---------------------------------------------------------------------
# 🧩 Streamlit 초보자를 위한 핵심 개념 요약
# ---------------------------------------------------------------------
# 1) rerun: Streamlit은 '선언형' 방식. 버튼 클릭 등으로 상태가 바뀌면 전체 스크립트가 다시 실행됨.
#    → 그래서 버튼 클릭 직후 st.rerun()을 호출해 즉시 화면을 갱신하는 패턴을 자주 씀.
#
# 2) session_state: 사용자 개별 브라우저 세션에 유지되는 상태 딕셔너리.
#    - 페이지 사이 이동 없이도 값(선택 기사, 대화 기록 등)을 유지할 수 있음.
#    - 딕셔너리처럼 사용: st.session_state["key"] 또는 st.session_state.key
#
# 3) 레이아웃: st.columns, st.sidebar, st.container, st.expander, st.tabs 등으로 구조를 잡음.
#
# 4) 데이터 표시: st.dataframe / st.metric / st.bar_chart 등 고수준 컴포넌트로 빠르게 대시보드화 가능.
#
# 5) 이벤트 로깅: 사용자의 행동(클릭, 전환, 체류시간)을 log_event(...)로 CSV 등으로 쌓아
#    MVP 단계에서도 간단한 퍼널/전환율/상호작용 분석이 가능.
#
# 6) 안전한 HTML 사용: st.markdown(..., unsafe_allow_html=True) 사용 시
#    - 외부 입력을 그대로 넣지 않기(보안)
#    - CSS/HTML은 가능한 최소 범위로(스타일 충돌 방지)
#
# 7) 성능 팁: 큰 데이터프레임/차트는 @st.cache_data, @st.cache_resource로 캐시 고려.
# ---------------------------------------------------------------------
