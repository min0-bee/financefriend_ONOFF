
from core.config import LOG_FILE, LOG_DIR
from core.utils import load_logs_as_df
import streamlit as st
import pandas as pd
import os
from datetime import datetime

def show_log_viewer():
    st.markdown("## 🧪 로그 뷰어 (MVP)")
    df = load_logs_as_df(LOG_FILE)
    if df.empty:
        st.info("아직 로그 파일이 없습니다. (logs/events.csv)")
        return
    st.dataframe(df, use_container_width=True, height=420)


def render():
    st.markdown("## 📊 로컬 로그 뷰어")
    
    # CSV 파일 정보 표시
    if os.path.exists(LOG_FILE):
        file_size = os.path.getsize(LOG_FILE)
        file_mtime = datetime.fromtimestamp(os.path.getmtime(LOG_FILE))
        
        col_info1, col_info2, col_info3 = st.columns(3)
        with col_info1:
            st.caption(f"📁 파일 위치: `{LOG_FILE}`")
        with col_info2:
            st.caption(f"📏 파일 크기: {file_size:,} bytes ({file_size/1024:.2f} KB)")
        with col_info3:
            st.caption(f"🕐 최종 수정: {file_mtime.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # CSV 파일 다운로드 버튼
        with open(LOG_FILE, "rb") as f:
            st.download_button(
                label="📥 CSV 파일 다운로드",
                data=f.read(),
                file_name="events.csv",
                mime="text/csv",
                help="현재 로그 파일을 다운로드합니다"
            )
    else:
        st.info(f"📁 로그 파일이 아직 생성되지 않았습니다. (`{LOG_FILE}`)")
        st.caption("이벤트가 발생하면 자동으로 생성됩니다.")
        return
    
    st.markdown("---")
    
    df = load_logs_as_df(LOG_FILE)
    if df.empty:
        st.info("로그 파일이 비어있습니다.")
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
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📄 전체 로그", 
        "📊 이벤트 요약", 
        "🧵 세션 타임라인", 
        "🏷️ 용어 통계",
        "📁 파일 정보"
    ])

    with tab1:
        st.caption(f"총 {len(df):,}개의 로그가 있습니다. (CSV 파일: {LOG_FILE})")
        
        # 최근 로그만 보기 옵션
        show_recent_only = st.checkbox("최근 100개만 보기", value=False)
        display_df = df.tail(100) if show_recent_only else df
        
        st.dataframe(display_df, use_container_width=True, height=420)
        
        if show_recent_only:
            st.caption(f"전체 {len(df):,}개 중 최근 100개만 표시 중입니다.")

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
    
    with tab5:
        st.markdown("### 📁 로그 파일 정보")
        
        if os.path.exists(LOG_FILE):
            file_stats = os.stat(LOG_FILE)
            
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**파일 경로**")
                st.code(LOG_FILE, language="text")
                
                st.markdown("**파일 크기**")
                file_size = file_stats.st_size
                st.write(f"- {file_size:,} bytes")
                st.write(f"- {file_size/1024:.2f} KB")
                if file_size > 1024*1024:
                    st.write(f"- {file_size/(1024*1024):.2f} MB")
            
            with col2:
                st.markdown("**파일 정보**")
                st.write(f"생성 시간: {datetime.fromtimestamp(file_stats.st_ctime).strftime('%Y-%m-%d %H:%M:%S')}")
                st.write(f"수정 시간: {datetime.fromtimestamp(file_stats.st_mtime).strftime('%Y-%m-%d %H:%M:%S')}")
                st.write(f"접근 시간: {datetime.fromtimestamp(file_stats.st_atime).strftime('%Y-%m-%d %H:%M:%S')}")
            
            st.markdown("---")
            st.markdown("### 📊 데이터 통계")
            
            col_stat1, col_stat2 = st.columns(2)
            with col_stat1:
                st.write("**기본 통계**")
                st.write(f"- 총 로그 수: {len(df):,}개")
                st.write(f"- 고유 세션: {df['session_id'].nunique()}개")
                st.write(f"- 고유 사용자: {df['user_id'].nunique()}개")
                st.write(f"- 이벤트 종류: {df['event_name'].nunique()}개")
            
            with col_stat2:
                st.write("**시간 범위**")
                if not df.empty and 'event_time' in df.columns:
                    st.write(f"- 시작: {df['event_time'].min()}")
                    st.write(f"- 종료: {df['event_time'].max()}")
                    time_span = (df['event_time'].max() - df['event_time'].min())
                    if pd.notna(time_span):
                        st.write(f"- 기간: {time_span}")
            
            st.markdown("---")
            st.markdown("### 💾 CSV 파일 미리보기")
            st.caption("CSV 파일의 원본 내용을 확인할 수 있습니다.")
            
            preview_lines = st.slider("미리보기 줄 수", 1, 50, 10)
            try:
                with open(LOG_FILE, "r", encoding="utf-8-sig") as f:
                    lines = f.readlines()[:preview_lines+1]
                    st.code("".join(lines), language="csv")
            except Exception as e:
                st.error(f"파일 읽기 실패: {e}")
        else:
            st.warning(f"로그 파일이 없습니다: {LOG_FILE}")