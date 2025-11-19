"""
성능 측정 및 분석 유틸리티
- 각 단계별 시간 측정
- 성능 분석 리포트 생성
- 개선 전/후 비교
"""

import time
import streamlit as st
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from contextlib import contextmanager


@dataclass
class PerformanceStep:
    """성능 측정 단계"""
    name: str
    start_time: float
    end_time: Optional[float] = None
    duration_ms: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def finish(self, metadata: Optional[Dict[str, Any]] = None):
        """단계 종료 및 시간 계산"""
        self.end_time = time.perf_counter()
        self.duration_ms = (self.end_time - self.start_time) * 1000
        if metadata:
            self.metadata.update(metadata)


@dataclass
class PerformanceProfile:
    """전체 성능 프로파일"""
    session_id: str
    user_input: str
    steps: List[PerformanceStep] = field(default_factory=list)
    total_duration_ms: Optional[float] = None
    optimization_enabled: bool = False
    
    def add_step(self, name: str, metadata: Optional[Dict[str, Any]] = None) -> PerformanceStep:
        """새 단계 추가"""
        step = PerformanceStep(name=name, start_time=time.perf_counter(), metadata=metadata or {})
        self.steps.append(step)
        return step
    
    def finish(self):
        """프로파일 완료"""
        if self.steps:
            first_step = self.steps[0]
            last_step = self.steps[-1]
            if last_step.end_time:
                self.total_duration_ms = (last_step.end_time - first_step.start_time) * 1000
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "session_id": self.session_id,
            "user_input": self.user_input,
            "optimization_enabled": self.optimization_enabled,
            "total_duration_ms": self.total_duration_ms,
            "steps": [
                {
                    "name": step.name,
                    "duration_ms": step.duration_ms,
                    "metadata": step.metadata
                }
                for step in self.steps
                if step.duration_ms is not None
            ]
        }
    
    def get_summary(self) -> Dict[str, Any]:
        """성능 요약 정보"""
        finished_steps = [s for s in self.steps if s.duration_ms is not None]
        if not finished_steps:
            return {}
        
        return {
            "total_ms": self.total_duration_ms,
            "step_count": len(finished_steps),
            "steps": {
                step.name: {
                    "duration_ms": round(step.duration_ms, 2),
                    "percentage": round((step.duration_ms / self.total_duration_ms * 100) if self.total_duration_ms else 0, 2)
                }
                for step in finished_steps
            },
            "bottleneck": max(finished_steps, key=lambda s: s.duration_ms).name if finished_steps else None
        }


class PerformanceTracker:
    """성능 추적기 (싱글톤 패턴)"""
    
    def __init__(self):
        self.profiles: List[PerformanceProfile] = []
        self.current_profile: Optional[PerformanceProfile] = None
    
    def start_profile(self, user_input: str, optimization_enabled: bool = False) -> PerformanceProfile:
        """새 성능 프로파일 시작"""
        session_id = st.session_state.get("session_id", "unknown")
        profile = PerformanceProfile(
            session_id=session_id,
            user_input=user_input,
            optimization_enabled=optimization_enabled
        )
        self.current_profile = profile
        return profile
    
    def finish_current_profile(self):
        """현재 프로파일 완료"""
        if self.current_profile:
            self.current_profile.finish()
            self.profiles.append(self.current_profile)
            # 최근 100개만 유지
            if len(self.profiles) > 100:
                self.profiles = self.profiles[-100:]
            self.current_profile = None
    
    def get_current_profile(self) -> Optional[PerformanceProfile]:
        """현재 프로파일 반환"""
        return self.current_profile
    
    @contextmanager
    def measure_step(self, name: str, metadata: Optional[Dict[str, Any]] = None):
        """단계 측정 컨텍스트 매니저"""
        if not self.current_profile:
            raise ValueError("프로파일이 시작되지 않았습니다. start_profile()을 먼저 호출하세요.")
        
        step = self.current_profile.add_step(name, metadata)
        try:
            yield step
        finally:
            step.finish()
    
    def get_comparison_report(self) -> Dict[str, Any]:
        """개선 전/후 비교 리포트"""
        optimized = [p for p in self.profiles if p.optimization_enabled]
        non_optimized = [p for p in self.profiles if not p.optimization_enabled]
        
        if not optimized or not non_optimized:
            return {"error": "비교할 데이터가 부족합니다. 최적화 전/후 데이터가 모두 필요합니다."}
        
        # 평균 시간 계산
        avg_optimized = sum(p.total_duration_ms for p in optimized if p.total_duration_ms) / len(optimized)
        avg_non_optimized = sum(p.total_duration_ms for p in non_optimized if p.total_duration_ms) / len(non_optimized)
        
        # 단계별 평균 시간
        step_avg_optimized = {}
        step_avg_non_optimized = {}
        
        for profile in optimized:
            for step in profile.steps:
                if step.duration_ms:
                    if step.name not in step_avg_optimized:
                        step_avg_optimized[step.name] = []
                    step_avg_optimized[step.name].append(step.duration_ms)
        
        for profile in non_optimized:
            for step in profile.steps:
                if step.duration_ms:
                    if step.name not in step_avg_non_optimized:
                        step_avg_non_optimized[step.name] = []
                    step_avg_non_optimized[step.name].append(step.duration_ms)
        
        # 평균 계산
        step_avg_optimized = {k: sum(v)/len(v) for k, v in step_avg_optimized.items()}
        step_avg_non_optimized = {k: sum(v)/len(v) for k, v in step_avg_non_optimized.items()}
        
        improvement = ((avg_non_optimized - avg_optimized) / avg_non_optimized * 100) if avg_non_optimized > 0 else 0
        
        return {
            "total": {
                "before_ms": round(avg_non_optimized, 2),
                "after_ms": round(avg_optimized, 2),
                "improvement_percent": round(improvement, 2),
                "improvement_ms": round(avg_non_optimized - avg_optimized, 2)
            },
            "steps": {
                step_name: {
                    "before_ms": round(step_avg_non_optimized.get(step_name, 0), 2),
                    "after_ms": round(step_avg_optimized.get(step_name, 0), 2),
                    "improvement_ms": round(step_avg_non_optimized.get(step_name, 0) - step_avg_optimized.get(step_name, 0), 2),
                    "improvement_percent": round(
                        ((step_avg_non_optimized.get(step_name, 0) - step_avg_optimized.get(step_name, 0)) / 
                         step_avg_non_optimized.get(step_name, 1) * 100) if step_avg_non_optimized.get(step_name, 0) > 0 else 0, 
                        2
                    )
                }
                for step_name in set(list(step_avg_optimized.keys()) + list(step_avg_non_optimized.keys()))
            },
            "sample_count": {
                "optimized": len(optimized),
                "non_optimized": len(non_optimized)
            }
        }


# 전역 성능 추적기 인스턴스
_performance_tracker = None

def get_performance_tracker() -> PerformanceTracker:
    """성능 추적기 싱글톤 인스턴스 반환"""
    global _performance_tracker
    if _performance_tracker is None:
        _performance_tracker = PerformanceTracker()
    return _performance_tracker


def render_performance_report():
    """성능 리포트 UI 렌더링"""
    tracker = get_performance_tracker()
    
    st.markdown("### 📊 성능 분석 리포트")
    
    if not tracker.profiles:
        st.info("아직 측정된 성능 데이터가 없습니다. 챗봇에 질문을 해보세요!")
        return
    
    # 최근 프로파일 표시
    if tracker.profiles:
        latest = tracker.profiles[-1]
        st.markdown("#### 최근 응답 성능")
        
        if latest.total_duration_ms:
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("총 응답 시간", f"{latest.total_duration_ms:.0f}ms")
            with col2:
                st.metric("단계 수", len([s for s in latest.steps if s.duration_ms]))
            with col3:
                bottleneck = latest.get_summary().get("bottleneck", "N/A")
                st.metric("병목 지점", bottleneck)
            
            # 단계별 시간 차트
            finished_steps = [s for s in latest.steps if s.duration_ms is not None]
            if finished_steps:
                import pandas as pd
                df = pd.DataFrame([
                    {
                        "단계": step.name,
                        "시간 (ms)": round(step.duration_ms, 2),
                        "비율 (%)": round((step.duration_ms / latest.total_duration_ms * 100) if latest.total_duration_ms else 0, 2)
                    }
                    for step in finished_steps
                ])
                st.dataframe(df, use_container_width=True)
    
    # 개선 전/후 비교
    comparison = tracker.get_comparison_report()
    if "error" not in comparison:
        st.markdown("#### 개선 전/후 비교")
        
        total = comparison.get("total", {})
        if total:
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("개선 전", f"{total.get('before_ms', 0):.0f}ms")
            with col2:
                st.metric("개선 후", f"{total.get('after_ms', 0):.0f}ms")
            with col3:
                st.metric("개선율", f"{total.get('improvement_percent', 0):.1f}%", 
                         delta=f"-{total.get('improvement_ms', 0):.0f}ms")
            with col4:
                st.metric("샘플 수", 
                         f"전: {comparison.get('sample_count', {}).get('non_optimized', 0)}\n"
                         f"후: {comparison.get('sample_count', {}).get('optimized', 0)}")
        
        # 단계별 비교
        steps = comparison.get("steps", {})
        if steps:
            st.markdown("##### 단계별 상세 비교")
            import pandas as pd
            step_df = pd.DataFrame([
                {
                    "단계": step_name,
                    "개선 전 (ms)": data.get("before_ms", 0),
                    "개선 후 (ms)": data.get("after_ms", 0),
                    "개선 (ms)": data.get("improvement_ms", 0),
                    "개선율 (%)": data.get("improvement_percent", 0)
                }
                for step_name, data in steps.items()
            ])
            st.dataframe(step_df, use_container_width=True)

