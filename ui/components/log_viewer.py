
from core.config import LOG_FILE
from core.utils import load_logs_as_df
import streamlit as st
import pandas as pd

def show_log_viewer():
    st.markdown("## 🧪 로그 뷰어 (MVP)")
    df = load_logs_as_df(LOG_FILE)
    if df.empty:
        st.info("아직 로그 파일이 없습니다. (logs/events.csv)")
        return
    st.dataframe(df, use_container_width=True, height=420)


def render():
    st.markdown("## 🧪 로그 뷰어 (MVP)")
    df = load_logs_as_df(LOG_FILE)
    if df.empty:
        return

    # ===== 상단 요약 (세션 기준 기본 뷰) =====
    colA, colB, colC, colD = st.columns(4)
    with colA:
        st.metric("총 이벤트", f"{len(df):,}")
    with colB:
        st.metric("세션 수", df["session_id"].nunique())
    with colC:
        st.metric("유저 수", df["user_id"].nunique())
    with colD:
        st.metric("이벤트 종류", df["event_name"].nunique())

    # ===== [추가] 유저 기준 요약 스위치 & 요약 카드 =====
    st.markdown("---")
    agg_by_user = st.toggle(
        "👤 유저(user_id) 기준으로 요약 보기",
        value=False,
        help="세션이 여러 개여도 같은 유저로 묶어서 봅니다."
    )

    if agg_by_user:
        # 유저 단위 집계
        g = (
            df.groupby("user_id", dropna=False)
              .agg(
                  events=("event_name", "count"),
                  sessions=("session_id", "nunique"),
                  first_seen=("event_time", "min"),
                  last_seen=("event_time", "max")
              )
              .reset_index()
              .sort_values(["events","sessions"], ascending=False)
        )

        # 유저 기준 메트릭
        colU1, colU2, colU3, colU4 = st.columns(4)
        with colU1:
            st.metric("고유 유저 수", f"{len(g):,}")
        with colU2:
            st.metric("유저당 평균 세션", f"{(g['sessions'].mean() if len(g) else 0):.2f}")
        with colU3:
            st.metric("유저당 평균 이벤트", f"{(g['events'].mean() if len(g) else 0):.1f}")
        with colU4:
            st.metric("총 이벤트(유저 합계)", f"{int(g['events'].sum()):,}")

        # 상위 유저 표
        st.caption("유저별 활동 요약 (이벤트/세션 많은 순)")
        st.dataframe(g.head(50), use_container_width=True, height=320)

        # 특정 유저 타임라인
        st.markdown("### 🔎 특정 유저 타임라인")
        target_user = st.selectbox("유저 선택", options=g["user_id"].tolist() if len(g) else [])
        if target_user:
            udf = df[df["user_id"] == target_user].copy().sort_values("event_time")

            st.write(f"세션 수: {udf['session_id'].nunique()}개")
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

            sel_sess = st.selectbox("세션 선택", options=sess_sum.index.tolist() if len(sess_sum) else [])
            if sel_sess:
                sdf = udf[udf["session_id"] == sel_sess].copy()
                sdf["next_time"] = sdf["event_time"].shift(-1)
                sdf["gap_sec"] = (sdf["next_time"] - sdf["event_time"]).dt.total_seconds()
                st.dataframe(
                    sdf[["event_time","event_name","surface","source","news_id","term","message","gap_sec"]],
                    use_container_width=True, height=320
                )

        # 유저 기준 보기에서는 기본 탭 숨김
        return

    # ===== 기본 탭: 전체표 / 이벤트요약 / 세션타임라인 / 용어통계 =====
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
            st.dataframe(
                sdf[["event_time","event_name","surface","source","news_id","term","message","gap_sec"]],
                use_container_width=True, height=420
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
            if "answer_len" in gans.columns:
                tmp = gans.copy()
                tmp["answer_len"] = pd.to_numeric(tmp["answer_len"], errors="coerce")
                agg = (
                    tmp.groupby("term", dropna=True)["answer_len"]
                       .agg(["count","mean","max"])
                       .sort_values("count", ascending=False)
                       .head(10)
                )
                st.write("응답 길이 요약(Top10)")
                st.dataframe(agg, use_container_width=True, height=300)
            else:
                st.info("`glossary_answer`에 answer_len이 아직 없어요.")