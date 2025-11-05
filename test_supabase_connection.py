"""
Supabase 연결 테스트 스크립트

사용법:
    streamlit run test_supabase_connection.py
"""

import streamlit as st
from core.logger import get_supabase_client, _log_to_event_log
from core.config import SUPABASE_ENABLE, SUPABASE_URL, SUPABASE_KEY
from datetime import datetime, timezone

st.set_page_config(page_title="Supabase 연결 테스트", layout="wide")

st.title("🗄️ Supabase 연결 테스트")
st.markdown("---")

# 설정 확인
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Supabase 활성화", "✅ 활성화" if SUPABASE_ENABLE else "❌ 비활성화")
with col2:
    url_display = SUPABASE_URL[:30] + "..." if SUPABASE_URL and len(SUPABASE_URL) > 30 else (SUPABASE_URL or "❌ 설정 안됨")
    st.metric("Supabase URL", url_display)
with col3:
    key_display = "✅ 설정됨" if SUPABASE_KEY else "❌ 설정 안됨"
    st.metric("Supabase KEY", key_display)

st.markdown("---")

# 클라이언트 생성 테스트
st.subheader("1️⃣ Supabase 클라이언트 생성 테스트")

if st.button("🔍 클라이언트 생성 테스트"):
    supabase = get_supabase_client()
    if supabase:
        st.success("✅ Supabase 클라이언트 생성 성공!")
        st.info(f"URL: {SUPABASE_URL}")
    else:
        st.error("❌ Supabase 클라이언트 생성 실패")
        if not SUPABASE_ENABLE:
            st.warning("⚠️ SUPABASE_ENABLE이 False입니다.")
        if not SUPABASE_URL:
            st.warning("⚠️ SUPABASE_URL이 설정되지 않았습니다.")
        if not SUPABASE_KEY:
            st.warning("⚠️ SUPABASE_KEY가 설정되지 않았습니다.")

st.markdown("---")

# event_logs 테이블 확인
st.subheader("2️⃣ event_logs 테이블 확인")

if st.button("📋 테이블 확인"):
    supabase = get_supabase_client()
    if not supabase:
        st.error("❌ Supabase 클라이언트를 먼저 생성하세요.")
    else:
        try:
            # 테이블에서 최근 5개 레코드 조회
            response = supabase.table("event_logs").select("*").limit(5).execute()
            
            if response.data:
                st.success(f"✅ event_logs 테이블 확인 완료! (최근 {len(response.data)}개 레코드)")
                st.json(response.data)
            else:
                st.info("ℹ️ event_logs 테이블은 존재하지만 데이터가 없습니다.")
        except Exception as e:
            error_msg = str(e)
            if "relation" in error_msg.lower() or "does not exist" in error_msg.lower():
                st.error("❌ event_logs 테이블이 존재하지 않습니다!")
                st.info("💡 Supabase SQL Editor에서 테이블 생성 SQL을 실행하세요:")
                st.code("""
CREATE TABLE event_logs (
    id           BIGSERIAL PRIMARY KEY,
    event_time   timestamptz NOT NULL,
    user_id      text,
    session_id   INTEGER,
    dialogue_id  BIGINT,
    event_name   text NOT NULL,
    surface      text,
    source       text,
    ref_id       text,
    payload      jsonb,
    created_at   timestamptz DEFAULT now()
);

CREATE INDEX idx_event_logs_event_time ON event_logs(event_time DESC);
CREATE INDEX idx_event_logs_user_id ON event_logs(user_id);
CREATE INDEX idx_event_logs_event_name ON event_logs(event_name);
CREATE INDEX idx_event_logs_session_id ON event_logs(session_id);
CREATE INDEX idx_event_logs_dialogue_id ON event_logs(dialogue_id);
""", language="sql")
            else:
                st.error(f"❌ 테이블 조회 실패: {error_msg}")
                st.info("💡 Supabase Dashboard에서 테이블 권한을 확인하세요.")

st.markdown("---")

# 테스트 이벤트 기록
st.subheader("3️⃣ 테스트 이벤트 기록")

col_test1, col_test2, col_test3 = st.columns(3)

with col_test1:
    if st.button("📰 뉴스 클릭 테스트"):
        success, error = _log_to_event_log(
            "news_click",
            news_id="999",
            surface="test",
            source="test_script",
            title="테스트 뉴스",
            payload={"test": True, "timestamp": datetime.now(timezone.utc).isoformat()}
        )
        if success:
            st.success("✅ 테스트 이벤트 기록 성공!")
        else:
            st.error(f"❌ 이벤트 기록 실패: {error}")

with col_test2:
    if st.button("💬 챗봇 질문 테스트"):
        success, error = _log_to_event_log(
            "chat_question",
            message="테스트 질문입니다",
            surface="test",
            source="test_script",
            payload={"test": True}
        )
        if success:
            st.success("✅ 테스트 이벤트 기록 성공!")
        else:
            st.error(f"❌ 이벤트 기록 실패: {error}")

with col_test3:
    if st.button("🔍 용어 클릭 테스트"):
        success, error = _log_to_event_log(
            "glossary_click",
            term="테스트용어",
            surface="test",
            source="test_script",
            payload={"test": True}
        )
        if success:
            st.success("✅ 테스트 이벤트 기록 성공!")
        else:
            st.error(f"❌ 이벤트 기록 실패: {error}")

st.markdown("---")

# 최근 이벤트 조회
st.subheader("4️⃣ 최근 이벤트 조회")

if st.button("📊 최근 이벤트 조회"):
    supabase = get_supabase_client()
    if not supabase:
        st.error("❌ Supabase 클라이언트를 먼저 생성하세요.")
    else:
        try:
            # 최근 10개 이벤트 조회 (시간순 정렬)
            response = supabase.table("event_logs")\
                .select("*")\
                .order("event_time", desc=True)\
                .limit(10)\
                .execute()
            
            if response.data:
                st.success(f"✅ 최근 {len(response.data)}개 이벤트 조회 완료!")
                
                # 데이터프레임으로 표시
                import pandas as pd
                df = pd.DataFrame(response.data)
                st.dataframe(df, use_container_width=True)
            else:
                st.info("ℹ️ 아직 기록된 이벤트가 없습니다.")
        except Exception as e:
            st.error(f"❌ 이벤트 조회 실패: {str(e)}")

st.markdown("---")

# 사용자별 집계 테스트
st.subheader("5️⃣ 사용자별 집계 테스트")

if st.button("👥 사용자별 이벤트 개수 집계"):
    supabase = get_supabase_client()
    if not supabase:
        st.error("❌ Supabase 클라이언트를 먼저 생성하세요.")
    else:
        try:
            # 모든 이벤트 조회
            response = supabase.table("event_logs")\
                .select("user_id, event_name")\
                .execute()
            
            if response.data:
                import pandas as pd
                df = pd.DataFrame(response.data)
                
                # user_id별 집계
                if 'user_id' in df.columns and not df.empty:
                    user_stats = df.groupby('user_id').agg({
                        'event_name': 'count'
                    }).rename(columns={'event_name': 'event_count'})
                    
                    st.success(f"✅ {len(user_stats)}명의 사용자 데이터 집계 완료!")
                    st.dataframe(user_stats, use_container_width=True)
                else:
                    st.info("ℹ️ user_id 데이터가 없습니다.")
            else:
                st.info("ℹ️ 아직 기록된 이벤트가 없습니다.")
        except Exception as e:
            st.error(f"❌ 집계 실패: {str(e)}")

st.markdown("---")

# 설정 정보
st.subheader("📋 설정 정보")

with st.expander("현재 설정 확인"):
    st.json({
        "SUPABASE_ENABLE": SUPABASE_ENABLE,
        "SUPABASE_URL": SUPABASE_URL,
        "SUPABASE_KEY": "***" + (SUPABASE_KEY[-10:] if SUPABASE_KEY else "설정 안됨") if SUPABASE_KEY else "설정 안됨",
    })

st.markdown("---")

# 테스트 체크리스트
st.subheader("✅ 테스트 체크리스트")

checklist = st.container()
with checklist:
    st.markdown("""
    - [ ] Supabase 클라이언트 생성 성공
    - [ ] event_logs 테이블 존재 확인
    - [ ] 테스트 이벤트 기록 성공
    - [ ] 최근 이벤트 조회 성공
    - [ ] 사용자별 집계 확인
    """)

st.markdown("---")
st.caption("💡 모든 테스트가 성공하면 event_log 중심 로깅 시스템이 정상 작동합니다!")

