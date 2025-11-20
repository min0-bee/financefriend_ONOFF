
import streamlit as st
from core.config import API_ENABLE, API_BASE_URL, SUPABASE_ENABLE

def render(terms: dict[str, dict]):
    with st.sidebar:
        
        
        # API 전송 상태 표시
        if API_ENABLE:
            api_status = st.session_state.get("api_send_status", {"success": 0, "failed": 0})
            total = api_status["success"] + api_status["failed"]
            
            if total > 0:
                st.subheader("📊 서버 전송 상태")
                success_rate = (api_status["success"] / total * 100) if total > 0 else 0
                
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("✅ 성공", api_status["success"])
                with col2:
                    st.metric("❌ 실패", api_status["failed"])
                
                if success_rate >= 90:
                    st.success(f"✅ 전송률: {success_rate:.1f}%")
                elif success_rate >= 50:
                    st.warning(f"⚠️ 전송률: {success_rate:.1f}%")
                else:
                    st.error(f"❌ 전송률: {success_rate:.1f}%")
                
                if st.button("🔄 상태 초기화"):
                    st.session_state["api_send_status"] = {"success": 0, "failed": 0}
                    st.rerun()
                
                st.caption(f"서버: {API_BASE_URL}")
            else:
                st.info("📡 데이터 전송 대기 중...")
                st.caption(f"서버: {API_BASE_URL}")
        else:
            # event_log 중심 모드 확인 (프로덕션 환경에서는 숨김)
            # if SUPABASE_ENABLE:
            #     st.success("✅ event_log 중심 모드 (Supabase)")
            #     st.caption("📊 모든 이벤트가 Supabase에 기록됩니다")
            # else:
            #     st.warning("⚠️ API 비활성화 (로컬 CSV만 저장)")
            pass
        
        st.markdown("---")
        st.subheader("📚 금융 용어 사전")
        st.write(f"등록된 용어: {len(terms)}개")
        with st.expander("용어 목록 보기"):
            for t in terms.keys():
                st.write(f"• {t}")
