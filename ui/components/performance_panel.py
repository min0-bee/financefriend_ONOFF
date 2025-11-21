"""
챗봇 응답시간 성능 분석 패널
각 단계별 시간을 측정하고 시각화
"""
import streamlit as st
import time
from typing import Dict, List, Optional
import pandas as pd


class PerformanceTracker:
    """성능 추적 클래스"""
    
    def __init__(self):
        self.steps: List[Dict] = []
        self.start_time: Optional[float] = None
        self.current_step: Optional[str] = None
        self.step_start_time: Optional[float] = None
    
    def start(self):
        """전체 측정 시작"""
        self.steps = []
        self.start_time = time.time()
        self.current_step = None
        self.step_start_time = None
    
    def step(self, name: str):
        """단계 시작"""
        # 이전 단계 종료
        if self.current_step and self.step_start_time:
            elapsed = (time.time() - self.step_start_time) * 1000
            self.steps.append({
                "step": self.current_step,
                "duration_ms": round(elapsed, 2),
                "status": "completed"
            })
        
        # 새 단계 시작
        self.current_step = name
        self.step_start_time = time.time()
    
    def finish(self):
        """전체 측정 종료"""
        # 마지막 단계 종료
        if self.current_step and self.step_start_time:
            elapsed = (time.time() - self.step_start_time) * 1000
            self.steps.append({
                "step": self.current_step,
                "duration_ms": round(elapsed, 2),
                "status": "completed"
            })
        
        # 전체 시간 계산
        if self.start_time:
            total_time = (time.time() - self.start_time) * 1000
            self.steps.append({
                "step": "총 응답 시간",
                "duration_ms": round(total_time, 2),
                "status": "total"
            })
    
    def get_summary(self) -> Dict:
        """성능 요약 반환"""
        if not self.steps:
            return {}
        
        total = self.steps[-1]["duration_ms"] if self.steps else 0
        steps_data = [s for s in self.steps if s.get("status") != "total"]
        
        return {
            "total_ms": total,
            "steps": steps_data,
            "step_count": len(steps_data)
        }
    
    def render_panel(self):
        """성능 분석 패널 렌더링"""
        if not self.steps:
            return
        
        with st.expander("📊 응답시간 성능 분석", expanded=True):
            summary = self.get_summary()
            
            # 전체 시간 표시
            total_ms = summary.get("total_ms", 0)
            st.metric("총 응답 시간", f"{total_ms:.0f}ms")
            
            # 단계별 시간 표시
            steps = summary.get("steps", [])
            if steps:
                st.subheader("단계별 소요 시간")
                
                # 데이터프레임 생성
                df_data = []
                for step in steps:
                    df_data.append({
                        "단계": step["step"],
                        "소요 시간 (ms)": step["duration_ms"],
                        "비율 (%)": round((step["duration_ms"] / total_ms * 100) if total_ms > 0 else 0, 1)
                    })
                
                df = pd.DataFrame(df_data)
                
                # 표시
                st.dataframe(df, use_container_width=True, hide_index=True)
                
                # 시각화 (막대 그래프)
                if len(steps) > 0:
                    try:
                        import plotly.express as px
                        fig = px.bar(
                            df,
                            x="단계",
                            y="소요 시간 (ms)",
                            title="단계별 응답 시간",
                            color="소요 시간 (ms)",
                            color_continuous_scale="Reds"
                        )
                        fig.update_layout(height=300, showlegend=False)
                        st.plotly_chart(fig, use_container_width=True)
                    except ImportError:
                        # plotly가 없으면 스킵
                        pass
                
                # 병목 지점 강조
                if steps:
                    max_step = max(steps, key=lambda x: x["duration_ms"])
                    if max_step["duration_ms"] > total_ms * 0.3:  # 전체의 30% 이상이면 병목
                        st.warning(
                            f"⚠️ 병목 지점: **{max_step['step']}** "
                            f"({max_step['duration_ms']:.0f}ms, 전체의 {max_step['duration_ms']/total_ms*100:.1f}%)"
                        )


def get_performance_tracker() -> PerformanceTracker:
    """성능 추적기 인스턴스 반환 (세션별)"""
    if "performance_tracker" not in st.session_state:
        st.session_state.performance_tracker = PerformanceTracker()
    return st.session_state.performance_tracker

