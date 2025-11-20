"""
성능 분석 패널 독립 컴포넌트
챗봇 응답시간 분석을 위한 별도 뷰
"""
import streamlit as st
from ui.components.performance_panel import get_performance_tracker


def render():
    """
    성능 분석 패널 렌더링
    챗봇 응답시간 분석 결과를 표시
    """
    st.header("📊 응답시간 성능 분석")
    st.markdown("---")
    
    # 성능 추적기 가져오기
    tracker = get_performance_tracker()
    
    if not tracker.steps:
        st.info("💡 챗봇에 질문을 입력하면 성능 분석 결과가 여기에 표시됩니다.")
        st.markdown("""
        ### 측정 항목
        - 사용자 입력 처리
        - URL 감지 및 파싱
        - 기사 검색 (Supabase, 로컬)
        - RAG 초기화 및 데이터 로드
        - RAG 검색 (정확 매칭, 벡터 검색)
        - 용어 설명 생성
        - LLM 호출
        - 응답 처리 완료
        """)
        return
    
    # 성능 분석 패널 렌더링
    tracker.render_panel()
    
    # 추가 정보
    st.markdown("---")
    with st.expander("📈 성능 최적화 팁", expanded=False):
        st.markdown("""
        ### 병목 지점 개선 방법
        
        **1. LLM 호출이 느린 경우:**
        - 모델 변경 (gpt-4o-mini 권장)
        - temperature 낮추기 (0.2 권장)
        - max_tokens 조정
        
        **2. RAG 검색이 느린 경우:**
        - 임베딩 캐시 활용
        - 벡터 검색 top_k 조정
        - 정확 매칭 우선 사용
        
        **3. 데이터 로드가 느린 경우:**
        - 세션 상태 캐싱 활용
        - 백그라운드 로딩 활용
        - 불필요한 데이터 로드 최소화
        
        **4. 전체 응답 시간 개선:**
        - 불필요한 단계 제거
        - 병렬 처리 활용
        - 조기 종료 조건 추가
        """)

