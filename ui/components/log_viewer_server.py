"""
서버 중심 로그 뷰어
서버 API에서 데이터를 가져와서 표시합니다.
event_log 중심 모드에서는 Supabase에서 직접 데이터를 가져옵니다.
"""

from core.config import API_BASE_URL, API_ENABLE, SUPABASE_ENABLE
from core.logger import _get_user_id, _get_backend_session_id, _ensure_backend_session, get_supabase_client
import streamlit as st
import pandas as pd
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import json
import importlib
import re
import os

# wordcloud 라이브러리
try:
    from wordcloud import WordCloud
    import matplotlib.pyplot as plt
    import matplotlib
    matplotlib.use('Agg')  # GUI 백엔드 없이 사용
    WORDCLOUD_AVAILABLE = True
except ImportError:
    WORDCLOUD_AVAILABLE = False
    if SUPABASE_ENABLE:
        try:
            st.warning("⚠️ wordcloud 라이브러리가 없습니다. pip install wordcloud matplotlib를 실행해주세요.")
        except:
            pass

px = None
try:
    if importlib.util.find_spec("plotly.express"):
        px = importlib.import_module("plotly.express")
        try:
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots
        except Exception:
            go = None
            make_subplots = None
    else:
        go = None
        make_subplots = None
except Exception:
    px = None
    go = None
    make_subplots = None

# requests 라이브러리
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

# ============================================================================
# 공통 유틸리티 함수
# ============================================================================

def _parse_payload(payload: Any) -> Dict[str, Any]:
    """payload를 딕셔너리로 안전하게 변환"""
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            return json.loads(payload) if payload else {}
        except:
            return {}
    return {}

def _extract_from_payload(payload: Any, key: str, default=None):
    """payload에서 특정 키 값을 추출"""
    parsed = _parse_payload(payload)
    return parsed.get(key, default)

def _get_rag_chat_question_sessions(df_view: pd.DataFrame, session_column: str = "session_id") -> set:
    """
    chat_question 이벤트 중 RAG 질문인 세션만 반환
    
    chat_question은 세 가지 타입으로 나뉩니다:
    1. RAG 질문: 이후 glossary_answer 이벤트 발생
    2. 링크: 이후 news_url_added_from_chat 이벤트 발생
    3. 일반 질문: 이후 chat_response 이벤트 발생
    
    Returns:
        RAG 질문인 chat_question이 발생한 세션 ID 집합
    """
    if df_view.empty or "event_name" not in df_view.columns or session_column not in df_view.columns:
        return set()
    
    chat_questions = df_view[df_view["event_name"] == "chat_question"].copy()
    if chat_questions.empty:
        return set()
    
    # 세션별로 그룹화하여 각 chat_question 이후 이벤트 확인
    rag_sessions = set()
    
    for session_id in chat_questions[session_column].dropna().unique():
        session_events = df_view[df_view[session_column] == session_id].sort_values("event_time")
        chat_question_indices = session_events[session_events["event_name"] == "chat_question"].index
        
        for chat_idx in chat_question_indices:
            # chat_question 이후의 이벤트 확인
            after_chat = session_events.loc[session_events.index > chat_idx]
            
            # RAG 질문인지 확인: glossary_answer 이벤트가 발생했는지
            has_glossary_answer = (after_chat["event_name"] == "glossary_answer").any()
            
            # 링크나 검색 요청이 아닌지 확인 (이 경우 제외)
            has_url_added = (after_chat["event_name"] == "news_url_added_from_chat").any()
            has_search = (after_chat["event_name"] == "news_search_from_chat").any()
            
            # RAG 질문이고, 링크나 검색 요청이 아닌 경우만 포함
            if has_glossary_answer and not has_url_added and not has_search:
                rag_sessions.add(session_id)
                break  # 한 세션에 여러 RAG 질문이 있어도 한 번만 추가
    
    return rag_sessions

def _extract_perf_data(row: pd.Series) -> Optional[Dict[str, Any]]:
    """payload에서 성능 데이터 추출 (event_name 기반)"""
    try:
        payload_raw = row.get("payload")
        event_name = row.get("event_name")
        
        if not payload_raw:
            return None
        
        payload = _parse_payload(payload_raw)
        if not payload:
            return None
        
        # event_name에 따라 다른 처리
        if event_name == "news_detail_open":
            perf_steps = payload.get("perf_steps", {})
            if isinstance(perf_steps, dict) and "highlight_ms" in perf_steps:
                return {
                    "highlight_ms": perf_steps.get("highlight_ms"),
                    "terms_filter_ms": perf_steps.get("terms_filter_ms"),
                    "total_ms": perf_steps.get("total_ms"),
                    "terms_count": perf_steps.get("terms_count"),
                    "content_length": perf_steps.get("content_length"),
                    "cache_hit": payload.get("cache_hit", False),
                    "highlight_cache_hit": payload.get("highlight_cache_hit", False),
                    "terms_cache_hit": payload.get("terms_cache_hit", False),
                }
        
        elif event_name == "news_click":
            click_process_ms = payload.get("click_process_ms")
            if click_process_ms is not None:
                return {
                    "click_process_ms": click_process_ms,
                    "content_length": payload.get("content_length"),
                }
        
        elif event_name in ("glossary_click", "glossary_answer"):
            perf_steps = payload.get("perf_steps", {})
            if isinstance(perf_steps, dict) and "explanation_ms" in perf_steps:
                return {
                    "explanation_ms": perf_steps.get("explanation_ms"),
                    "total_ms": perf_steps.get("total_ms"),
                    "answer_length": perf_steps.get("answer_length"),
                }
        
        # RAG 응답 시간 (latency_ms 직접 사용)
        if event_name in ("chat_response", "glossary_answer"):
            latency_ms = payload.get("latency_ms") or row.get("latency_ms")
            if latency_ms is not None:
                return {
                    "latency_ms": latency_ms,
                    "answer_length": payload.get("answer_len") or payload.get("answer_length"),
                }
        
        return None
    except Exception:
        return None

def _get_news_id_from_row(row: pd.Series) -> Optional[str]:
    """row에서 news_id 추출 (여러 소스 확인)"""
    news_id = row.get("news_id")
    if news_id and not pd.isna(news_id):
        return str(news_id)
    
    # payload에서 추출 시도
    payload = _parse_payload(row.get("payload"))
    if payload:
        news_id = payload.get("news_id") or payload.get("article_id")
        if news_id:
            return str(news_id)
    
    # ref_id 확인
    ref_id = row.get("ref_id")
    if ref_id and not pd.isna(ref_id):
        return str(ref_id)
    
    return None

def _format_news_id_display(news_id: Optional[str]) -> str:
    """news_id를 표시용으로 포맷팅 (음수면 임시 뉴스로 표시)"""
    if not news_id:
        return "N/A"
    
    try:
        news_id_num = float(news_id)
        if news_id_num < 0:
            return f"임시 뉴스 ({news_id})"
        else:
            return str(int(news_id_num))
    except (ValueError, TypeError):
        return str(news_id)

def _get_term_from_row(row: pd.Series) -> Optional[str]:
    """row에서 term 추출 (여러 소스 확인)"""
    term = row.get("term")
    if term and not pd.isna(term) and term != "":
        return str(term)
    
    # payload에서 추출
    payload = _parse_payload(row.get("payload"))
    if payload:
        term = payload.get("term")
        if term:
            return str(term)
    
    # term_from_payload 컬럼 확인
    term_from_payload = row.get("term_from_payload")
    if term_from_payload and not pd.isna(term_from_payload):
        return str(term_from_payload)
    
    return None

# ============================================================================
# 데이터 가져오기 함수들
# ============================================================================

def _fetch_news_from_supabase(limit: int = 1000) -> pd.DataFrame:
    """
    Supabase에서 news 테이블 데이터 가져오기
    
    정렬 기준 (우선순위 순):
    1. published_at 최신순 (가장 중요 - 최신성 필수)
    2. impact_score 높은 순 (두 번째 - 최신 뉴스 중 영향도 높은 것)
    3. urgency_score 높은 순 (세 번째)
    4. credibility_score 높은 순 (네 번째)
    
    필터:
    - deleted_at이 NULL인 뉴스만 (삭제되지 않은 뉴스)
    """
    if not SUPABASE_ENABLE:
        return pd.DataFrame()
    
    supabase = get_supabase_client()
    if not supabase:
        return pd.DataFrame()
    
    try:
        # deleted_at이 NULL인 뉴스만 가져오기 (삭제되지 않은 뉴스)
        # 충분히 많이 가져온 후, Python에서 점수 기준으로 재정렬
        query = (
            supabase.table("news")
            .select("*")
            .is_("deleted_at", "null")
        )
        
        # limit이 매우 크면 제한 없이 가져오기 (모든 데이터 분석)
        if limit < 999999:
            query = query.limit(limit * 10)  # 충분히 많이 가져온 후 정렬 (높은 점수 뉴스 확보)
        
        response = query.execute()
        
        if response.data:
            df = pd.DataFrame(response.data)
            
            # 날짜 컬럼 변환
            date_columns = ["published_at", "created_at", "updated_at", "deleted_at"]
            for col in date_columns:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], errors="coerce")
            
            # 정렬 기준: published_at > impact_score > urgency_score > credibility_score
            # 점수가 NULL인 경우 -1로 변환하여 낮은 우선순위로 처리
            sort_columns = []
            ascending_list = []
            
            # 1순위: published_at 최신순 (가장 중요 - 최신성 필수)
            if "published_at" in df.columns:
                sort_columns.append("published_at")
                ascending_list.append(False)
            
            # 2순위: impact_score 높은 순 (최신 뉴스 중 영향도 높은 것)
            if "impact_score" in df.columns:
                df["impact_score_sorted"] = df["impact_score"].fillna(-1)
                sort_columns.append("impact_score_sorted")
                ascending_list.append(False)
            
            # 3순위: urgency_score 높은 순
            if "urgency_score" in df.columns:
                df["urgency_score_sorted"] = df["urgency_score"].fillna(-1)
                sort_columns.append("urgency_score_sorted")
                ascending_list.append(False)
            
            # 4순위: credibility_score 높은 순
            if "credibility_score" in df.columns:
                df["credibility_score_sorted"] = df["credibility_score"].fillna(-1)
                sort_columns.append("credibility_score_sorted")
                ascending_list.append(False)
            
            # 정렬 실행
            if sort_columns:
                df = df.sort_values(sort_columns, ascending=ascending_list)
                # 임시 컬럼 제거
                temp_cols = [col for col in df.columns if col.endswith("_sorted")]
                df = df.drop(columns=temp_cols)
                # 상위 limit개만 반환
                df = df.head(limit)
            else:
                # 점수 컬럼이 없으면 published_at 기준으로만 정렬
                if "published_at" in df.columns:
                    df = df.sort_values("published_at", ascending=False).head(limit)
                else:
                    df = df.head(limit)
            
            return df
        return pd.DataFrame()
    except Exception as e:
        st.warning(f"⚠️ Supabase에서 뉴스 데이터 조회 실패: {str(e)}")
        return pd.DataFrame()

def _fetch_event_logs_from_supabase(user_id: Optional[str] = None, limit: int = 1000) -> pd.DataFrame:
    """Supabase에서 event_logs 데이터 가져오기"""
    if not SUPABASE_ENABLE:
        return pd.DataFrame()
    
    supabase = get_supabase_client()
    if not supabase:
        return pd.DataFrame()
    
    try:
        query = supabase.table("event_logs").select("*")
        
        if user_id:
            query = query.eq("user_id", user_id)
        
        query = query.order("event_time", desc=True)
        # Supabase의 기본 limit이 1000이므로 명시적으로 limit 설정
        if limit > 0:
            query = query.limit(limit)
        
        response = query.execute()
        
        if response.data:
            df = pd.DataFrame(response.data)
            if "event_time" in df.columns:
                df["event_time"] = pd.to_datetime(df["event_time"], errors="coerce")
            if "payload" in df.columns:
                def _extract_from_payload(payload, key):
                    """payload에서 특정 키 값을 추출"""
                    parsed = _parse_payload(payload)
                    return parsed.get(key)
                
                # term 추출
                df["term_from_payload"] = df["payload"].apply(lambda p: _extract_from_payload(p, "term"))
                
                # news_id 추출
                if "news_id" not in df.columns or df["news_id"].isna().all():
                    df["news_id_from_payload"] = df["payload"].apply(
                        lambda p: _extract_from_payload(p, "news_id") or _extract_from_payload(p, "article_id")
                    )
                    if "news_id" not in df.columns:
                        df["news_id"] = df["news_id_from_payload"]
                    else:
                        df["news_id"] = df["news_id"].fillna(df["news_id_from_payload"])
                
                # latency_ms 추출
                if "latency_ms" not in df.columns or df["latency_ms"].isna().all():
                    df["latency_ms_from_payload"] = df["payload"].apply(lambda p: _extract_from_payload(p, "latency_ms"))
                    if "latency_ms" not in df.columns:
                        df["latency_ms"] = df["latency_ms_from_payload"]
                    else:
                        df["latency_ms"] = df["latency_ms"].fillna(df["latency_ms_from_payload"])
            return df
        return pd.DataFrame()
    except Exception as e:
        st.warning(f"⚠️ Supabase에서 이벤트 로그 조회 실패: {str(e)}")
        return pd.DataFrame()

def _to_kst(series):
    """UTC 시간을 KST로 변환"""
    dt = pd.to_datetime(series, errors="coerce", utc=True)
    return dt.dt.tz_convert("Asia/Seoul")

def _fill_sessions_from_time(
    df: pd.DataFrame,
    *,
    threshold_minutes: int = 30,
    time_column: str = "event_time",
    user_column: str = "user_id",
) -> pd.DataFrame:
    """
    세션 ID 계산: 이벤트 시간 기준으로 세션 구분
    
    로직:
    1. user_id별로 이벤트를 시간순 정렬
    2. 이전 이벤트와의 시간 차이가 threshold_minutes(기본 30분)를 초과하면 새 세션으로 구분
    3. 첫 이벤트는 항상 새 세션 시작
    
    Args:
        df: 이벤트 로그 DataFrame
        threshold_minutes: 세션 구분 기준 시간(분) - 기본값 30분
        time_column: 시간 컬럼명
        user_column: 사용자 ID 컬럼명
    
    Returns:
        session_id_resolved 컬럼이 추가된 DataFrame
    """
    """event_time 기반으로 세션 ID를 추산합니다."""
    if df.empty or time_column not in df.columns:
        result = df.copy()
        if "session_id" in result.columns:
            result["session_id_resolved"] = result["session_id"]
        return result

    work = df.copy()
    work[time_column] = pd.to_datetime(work[time_column], errors="coerce")

    has_user_column = user_column in work.columns
    if has_user_column:
        session_users = work[user_column].fillna("anonymous").astype(str)
        session_users = session_users.where(session_users.str.len() > 0, "anonymous")
    else:
        session_users = pd.Series(["anonymous"] * len(work), index=work.index)

    threshold = pd.Timedelta(minutes=threshold_minutes)
    order = work.index.to_series(name="_session_order")
    work = work.assign(_session_user=session_users, _session_order=order)
    work = work.sort_values(["_session_user", time_column, "_session_order"])

    gaps = work.groupby("_session_user")[time_column].diff()
    new_session_flags = gaps.isna() | (gaps > threshold) | work[time_column].isna()
    session_sequence = new_session_flags.astype(int).groupby(work["_session_user"]).cumsum()

    inferred_ids = work["_session_user"].astype(str) + "-" + session_sequence.astype(str)
    work["session_id_inferred"] = inferred_ids

    resolved = work.sort_values("_session_order")["session_id_inferred"]
    result = df.copy()
    result["session_id_inferred"] = resolved

    if "session_id" in result.columns:
        session_series = result["session_id"]
        session_series = session_series.where(session_series.notna(), None)
        if session_series.dtype != object:
            session_series = session_series.astype("object")
        missing_mask = session_series.isna() | (session_series.astype(str).str.len() == 0)
        session_series = session_series.astype("object")
        session_series.loc[missing_mask] = result.loc[missing_mask, "session_id_inferred"]
        result["session_id"] = session_series
    else:
        result["session_id"] = result["session_id_inferred"]

    result["session_id_resolved"] = result["session_id"]
    return result

# ============================================================================
# 메인 렌더링 함수
# ============================================================================

def render(show_mode: str = "dashboard"):
    """
    메인 렌더링 함수: 서버에서 데이터를 가져와서 대시보드/로그 뷰어 렌더링
    
    전체 흐름:
    1. Supabase에서 이벤트 로그 가져오기 (최대 2000건)
    2. UTC 시간을 KST로 변환
    3. 세션 계산 (30분 간격)
    4. show_mode에 따라 대시보드 또는 로그 뷰어 표시
    
    Args:
        show_mode: "dashboard" (대시보드) 또는 "log_viewer" (로그 뷰어)
    """
    from core.logger import _get_user_id
    
    # Supabase에서 이벤트 로그 가져오기
    with st.spinner("🔄 Supabase에서 이벤트 로그를 가져오는 중..."):
        # 전체 데이터를 가져오기 위해 limit을 충분히 크게 설정
        # 전체 데이터가 4000개 정도이므로 limit을 더 크게 설정
        df = _fetch_event_logs_from_supabase(user_id=None, limit=10000)  # 5000 -> 10000으로 증가

        if df.empty:
            st.info("📭 아직 이벤트 로그가 없습니다. 앱을 사용하면 데이터가 수집됩니다.")
            return

        # 시간대 변환: UTC → KST (한국 표준시)
        df["event_time"] = _to_kst(df["event_time"])
        df = df.sort_values("event_time")

        # 세션 계산: 30분 간격으로 세션 구분 (모든 탭에서 사용)
        # user_id별로 이벤트를 시간순 정렬하고, 30분 이상 간격이 있으면 새 세션으로 구분
        session_gap_minutes = 30
        df = _fill_sessions_from_time(df, threshold_minutes=session_gap_minutes)
        session_column = "session_id_resolved" if "session_id_resolved" in df.columns else "session_id"

        # show_mode에 따라 다른 페이지 표시
        if show_mode == "dashboard":
            st.markdown("## 📊 대시보드")
            
            # 상위 레벨 탭: 4개 카테고리
            tab1, tab2, tab3, tab4 = st.tabs([
                "📊 KPI Dashboard",      # 핵심 지표 요약 (DAU, WAU, 세션 길이 등)
                "🔴 Service Health",     # 서비스 성능 및 안정성
                "🟡 Content Quality",     # 뉴스 콘텐츠 품질
                "🟢 User Behavior"       # 사용자 행동 분석
            ])
            
            # 탭 1: KPI Dashboard - 핵심 지표 요약
            with tab1:
                _render_kpi_dashboard(df, session_column)
            
            # 탭 2: Service Health - 성능 메트릭, RAG 응답 시간, URL 파싱 등
            with tab2:
                _render_service_health_tab(df, session_column)
            
            # 탭 3: Content Quality - 뉴스 소스 분석, 본문 품질, 워드클라우드 등
            with tab3:
                _render_content_quality_tab(df)
            
            # 탭 4: User Behavior - 클릭률, 읽기 시간, 용어 클릭률 등
            with tab4:
                _render_user_behavior_tab(df, session_column)
        
        elif show_mode == "log_viewer":
            st.markdown("## 📁 로그 뷰어")
            # 로그 뷰어: 개별 이벤트 로그를 필터링하여 상세 확인
            _render_log_viewer_tab(df, session_column)

# ============================================================================
# 탭 1: 서비스 성능 데이터 (Service Health)
# ============================================================================

def _render_service_health_tab(df_view: pd.DataFrame, session_column: str):
    """
    🔴 서비스 성능 데이터 탭: 핵심 4개 지표만 표시
    - 뉴스 상세 로딩 시간 평균
    - 챗봇 응답 시간 평균
    - URL 파싱 실패율
    - 전체 오류 발생률 (RAG 에러 포함)
    """
    st.markdown("### 🔴 서비스 성능 데이터 (Service Health)")
    st.markdown("**목표**: 서비스의 기술적 안정성 측정 - 핵심 지표만 표시")
    
    # 1. 뉴스 상세 로딩 시간 평균
    detail_events = df_view[df_view["event_name"] == "news_detail_open"].copy()
    detail_latencies = []
    for idx, row in detail_events.iterrows():
        perf_data = _extract_perf_data(row)
        if perf_data and isinstance(perf_data, dict):
            total_ms = perf_data.get("total_ms")
            if total_ms is None:
                highlight_ms = perf_data.get("highlight_ms", 0)
                terms_filter_ms = perf_data.get("terms_filter_ms", 0)
                total_ms = highlight_ms + terms_filter_ms
            if total_ms and total_ms > 0:
                try:
                    detail_latencies.append(float(total_ms))
                except (ValueError, TypeError):
                    pass
    avg_detail_latency = sum(detail_latencies) / len(detail_latencies) if detail_latencies else None
    
    # 2. 챗봇 응답 시간 평균
    chat_response_events = df_view[df_view["event_name"].isin(["chat_response", "glossary_answer"])].copy()
    chat_latencies = []
    for idx, row in chat_response_events.iterrows():
        latency_ms = None
        perf_data = _extract_perf_data(row)
        if perf_data and isinstance(perf_data, dict):
            latency_ms = perf_data.get("latency_ms") or perf_data.get("total_ms")
        if latency_ms is None:
            payload = _parse_payload(row.get("payload"))
            if payload:
                latency_ms = payload.get("latency_ms") or payload.get("total_ms")
        if latency_ms is None:
            latency_ms = row.get("latency_ms")
        if latency_ms is not None:
            try:
                latency_value = float(latency_ms)
                if latency_value > 0 and latency_value < 1000000:
                    chat_latencies.append(latency_value)
            except (ValueError, TypeError):
                pass
    avg_chat_latency = sum(chat_latencies) / len(chat_latencies) if chat_latencies else None
    
    # 3. URL 파싱 실패율
    url_events = df_view[df_view["event_name"].isin(["news_url_added_from_chat", "news_url_add_error"])]
    url_error_count = int((url_events["event_name"] == "news_url_add_error").sum()) if len(url_events) > 0 else 0
    url_total_count = len(url_events)
    url_error_rate = (url_error_count / url_total_count * 100) if url_total_count > 0 else 0
    
    # 4. 전체 오류 발생률 (RAG 에러 포함)
    # RAG 에러는 payload에 error가 있는 경우로 판단
    error_events = df_view[df_view["event_name"].isin([
        "news_url_add_error",
        "glossary_answer",
        "chat_response"
    ])]
    total_errors = url_error_count
    for idx, row in error_events.iterrows():
        if row["event_name"] in ["glossary_answer", "chat_response"]:
            payload = _parse_payload(row.get("payload"))
            if payload and payload.get("error"):
                total_errors += 1
    total_events = len(df_view)
    total_error_rate = (total_errors / total_events * 100) if total_events > 0 else 0
    
    # 핵심 4개 지표 표시
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if avg_detail_latency is not None:
            st.metric("뉴스 상세 로딩 시간", f"{avg_detail_latency:.0f}ms")
            st.caption(f"측정 건수: {len(detail_latencies)}건")
        else:
            st.metric("뉴스 상세 로딩 시간", "N/A")
    with col2:
        if avg_chat_latency is not None:
            st.metric("챗봇 응답 시간", f"{avg_chat_latency:.0f}ms")
            st.caption(f"측정 건수: {len(chat_latencies)}건")
        else:
            st.metric("챗봇 응답 시간", "N/A")
    with col3:
        st.metric("URL 파싱 실패율", f"{url_error_rate:.1f}%")
        st.caption(f"실패: {url_error_count}건 / 전체: {url_total_count}건")
    with col4:
        st.metric("전체 오류 발생률", f"{total_error_rate:.2f}%")
        st.caption(f"오류: {total_errors}건 / 전체: {total_events}건")

def _render_detail_performance(perf_events_with_data: pd.DataFrame):
    """뉴스 상세 보기 성능 분석"""
    detail_events = perf_events_with_data[perf_events_with_data["event_name"] == "news_detail_open"]
    
    if detail_events.empty:
        return
    
    st.markdown("#### 📰 뉴스 상세 보기 로딩 시간")
    
    perf_data_list = []
    for idx, row in detail_events.iterrows():
        perf = row["perf_data"]
        if perf and isinstance(perf, dict):
            news_id = _get_news_id_from_row(row)
            highlight_ms = perf.get("highlight_ms", 0)
            terms_filter_ms = perf.get("terms_filter_ms", 0)
            total_ms = perf.get("total_ms") or (highlight_ms + terms_filter_ms)
            
            cache_status = []
            if perf.get("highlight_cache_hit"):
                cache_status.append("하이라이트✅")
            if perf.get("terms_cache_hit"):
                cache_status.append("용어✅")
            if not cache_status:
                cache_status.append("❌")
            
            perf_data_list.append({
                "event_time": row.get("event_time"),
                "news_id": _format_news_id_display(news_id),
                "하이라이트 처리 (ms)": highlight_ms,
                "용어 필터링 (ms)": terms_filter_ms,
                "전체 렌더링 (ms)": total_ms,
                "발견된 용어 수": perf.get("terms_count", 0),
                "기사 길이 (자)": perf.get("content_length", 0),
                "캐시 히트": " / ".join(cache_status),
            })
    
    if perf_data_list:
        perf_df = pd.DataFrame(perf_data_list)
        perf_df = perf_df.sort_values("event_time", ascending=False)
        
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("##### 📊 성능 통계")
            avg_highlight = perf_df["하이라이트 처리 (ms)"].mean()
            avg_filter = perf_df["용어 필터링 (ms)"].mean()
            avg_total = perf_df["전체 렌더링 (ms)"].mean()
            cache_hit_rate = (perf_df["캐시 히트"].str.contains("✅", na=False).sum() / len(perf_df) * 100) if len(perf_df) > 0 else 0
            
            st.metric("평균 하이라이트 처리", f"{avg_highlight:.0f}ms")
            st.metric("평균 용어 필터링", f"{avg_filter:.0f}ms")
            st.metric("평균 전체 렌더링", f"{avg_total:.0f}ms")
            st.metric("캐시 히트율", f"{cache_hit_rate:.1f}%")
        
        # 시각화
        if px is not None and len(perf_df) > 0:
            fig = px.scatter(
                perf_df.head(100),
                x="하이라이트 처리 (ms)",
                y="용어 필터링 (ms)",
                size="전체 렌더링 (ms)",
                color="캐시 히트",
                hover_data=["news_id", "발견된 용어 수", "기사 길이 (자)"],
                title="뉴스 상세 보기 성능 분포"
            )
            st.plotly_chart(fig, use_container_width=True)
        
        st.dataframe(perf_df.head(20), use_container_width=True, height=300)

def _render_rag_performance(perf_events_with_data: pd.DataFrame):
    """RAG 응답 시간 분석"""
    rag_events = perf_events_with_data[perf_events_with_data["event_name"].isin(["glossary_answer", "chat_response"])]
    
    if rag_events.empty:
        return
    
    st.markdown("#### 🤖 RAG 응답 시간")
    
    rag_data_list = []
    for idx, row in rag_events.iterrows():
        perf = row["perf_data"]
        if perf and isinstance(perf, dict):
            term = _get_term_from_row(row)
            latency_ms = perf.get("latency_ms") or perf.get("total_ms") or perf.get("explanation_ms")
            answer_length = perf.get("answer_length") or perf.get("answer_len", 0)
            
            if latency_ms is not None:
                rag_data_list.append({
                    "event_time": row.get("event_time"),
                    "event_name": row.get("event_name"),
                    "term": term or "",
                    "응답 시간 (ms)": latency_ms,
                    "답변 길이 (자)": answer_length,
                })
    
    if rag_data_list:
        rag_df = pd.DataFrame(rag_data_list)
        rag_df = rag_df.sort_values("event_time", ascending=False)
        
        col1, col2 = st.columns(2)
        with col1:
            avg_latency = rag_df["응답 시간 (ms)"].mean()
            st.metric("평균 RAG 응답 시간", f"{avg_latency:.0f}ms")
        with col2:
            avg_length = rag_df["답변 길이 (자)"].mean()
            st.metric("평균 답변 길이", f"{avg_length:.0f}자")
        
        # 시각화
        if px is not None and len(rag_df) > 0:
            fig = px.histogram(
                rag_df,
                x="응답 시간 (ms)",
                nbins=30,
                title="RAG 응답 시간 분포",
                labels={"응답 시간 (ms)": "응답 시간 (밀리초)", "count": "빈도"}
            )
            st.plotly_chart(fig, use_container_width=True)
        
        st.dataframe(rag_df.head(20), use_container_width=True, height=300)

def _render_search_performance(df_view: pd.DataFrame):
    """자연어 검색 처리 속도"""
    search_events = df_view[df_view["event_name"] == "news_search_from_chat"]
    
    if search_events.empty:
        return
    
    st.markdown("#### 🔍 자연어 검색 처리 속도")
    
    search_data_list = []
    for idx, row in search_events.iterrows():
        payload = _parse_payload(row.get("payload"))
        latency_ms = payload.get("latency_ms") or row.get("latency_ms")
        message = payload.get("message") or row.get("message", "")
        
        # latency_ms를 숫자로 변환하고 유효한 값만 사용
        try:
            if latency_ms is not None:
                latency_ms = pd.to_numeric(latency_ms, errors='coerce')
                if pd.notna(latency_ms) and latency_ms > 0:
                    search_data_list.append({
                        "event_time": row.get("event_time"),
                        "검색어": message[:50] if message else "",
                        "처리 시간 (ms)": float(latency_ms),
                    })
        except (ValueError, TypeError):
            continue
    
    if search_data_list:
        search_df = pd.DataFrame(search_data_list)
        search_df = search_df.sort_values("event_time", ascending=False)
        
        # 유효한 값만으로 평균 계산
        valid_latencies = search_df["처리 시간 (ms)"].dropna()
        if len(valid_latencies) > 0:
            avg_latency = valid_latencies.mean()
            st.metric("평균 검색 처리 시간", f"{avg_latency:.0f}ms")
        else:
            st.metric("평균 검색 처리 시간", "N/A")
        
        if px is not None and len(search_df) > 0 and len(valid_latencies) > 0:
            fig = px.box(
                search_df,
                y="처리 시간 (ms)",
                title="검색 처리 시간 분포"
            )
            st.plotly_chart(fig, use_container_width=True)
        
        st.dataframe(search_df.head(20), use_container_width=True, height=200)
    else:
        st.info("📊 검색 처리 시간 데이터가 없습니다.")

def _render_url_parsing_quality(df_view: pd.DataFrame):
    """URL 파싱 성공/실패 이벤트"""
    url_events = df_view[df_view["event_name"].isin(["news_url_added_from_chat", "news_url_add_error"])]
    
    if url_events.empty:
        return
    
    st.markdown("#### 🔗 URL 파싱 품질")
    
    success_count = int((url_events["event_name"] == "news_url_added_from_chat").sum())
    error_count = int((url_events["event_name"] == "news_url_add_error").sum())
    total_count = success_count + error_count
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("URL 파싱 성공", success_count)
    with col2:
        st.metric("URL 파싱 실패", error_count)
    with col3:
        if total_count > 0:
            success_rate = (success_count / total_count) * 100
            st.metric("성공률", f"{success_rate:.1f}%")
        else:
            st.metric("성공률", "N/A")
    
    if total_count > 0 and px is not None:
        fig = px.pie(
            values=[success_count, error_count],
            names=["성공", "실패"],
            title="URL 파싱 성공/실패 비율"
        )
        st.plotly_chart(fig, use_container_width=True)

def _render_session_load(df_view: pd.DataFrame, session_column: str):
    """Streamlit 세션 수 / 동시 접속 부하"""
    if session_column not in df_view.columns:
        return
    
    st.markdown("#### 👥 세션 부하 분석")
    
    # 시간대별 세션 수
    df_view_copy = df_view.copy()
    df_view_copy["hour"] = df_view_copy["event_time"].dt.floor("H")
    hourly_sessions = df_view_copy.groupby("hour")[session_column].nunique().reset_index()
    hourly_sessions.columns = ["시간", "세션 수"]
    
    col1, col2 = st.columns(2)
    with col1:
        max_sessions = hourly_sessions["세션 수"].max() if len(hourly_sessions) > 0 else 0
        st.metric("최대 동시 세션 수", f"{max_sessions}개")
    with col2:
        avg_sessions = hourly_sessions["세션 수"].mean() if len(hourly_sessions) > 0 else 0
        st.metric("평균 세션 수", f"{avg_sessions:.1f}개")
    
    if px is not None and len(hourly_sessions) > 0:
        fig = px.line(
            hourly_sessions,
            x="시간",
            y="세션 수",
            title="시간대별 세션 수 추이"
        )
        st.plotly_chart(fig, use_container_width=True)

# ============================================================================
# 탭 2: 뉴스 콘텐츠 품질 데이터 (Content Quality)
# ============================================================================

def _render_content_quality_tab(df_view: pd.DataFrame):
    """
    🟡 뉴스 콘텐츠 품질 데이터 탭: 핵심 지표만 표시
    - 뉴스 수집량 추세
    - 금융/비금융 기사 비중
    - 본문 누락 비율
    - URL 파싱 실패율
    - 언론사 분포
    - 뉴스 카테고리 분포 (LLM 결과)
    - 카테고리별 사용자 참여도
    """
    st.markdown("### 🟡 뉴스 콘텐츠 품질 데이터 (Content Quality)")
    st.markdown("**목표**: 뉴스 데이터가 망가지지 않았는지 빠르게 확인하는 품질 체크")
    
    # 1. URL 파싱 실패율 (이벤트 로그 기반)
    _render_url_parsing_quality_for_content(df_view)
    
    # Supabase news 테이블 연동 분석
    with st.spinner("🔄 Supabase에서 뉴스 데이터를 가져오는 중..."):
        # 모든 데이터 분석 (limit 제거)
        news_df = _fetch_news_from_supabase(limit=999999)
        
        if news_df.empty:
            st.warning("⚠️ Supabase `news` 테이블에서 데이터를 가져올 수 없습니다.")
            st.info("💡 Supabase 연결을 확인하거나 뉴스 데이터가 있는지 확인해주세요.")
        else:
            st.success(f"✅ {len(news_df):,}개의 뉴스 데이터를 불러왔습니다.")
            
            # 2. 뉴스 수집량 추세
            _render_news_collection_trends(news_df)
            
            # 3. 금융/비금융 기사 비중
            _render_financial_news_ratio(news_df)
            
            # 4. 본문 누락 비율
            _render_content_missing_analysis(news_df)
            
            # 5. 언론사 분포
            _render_news_source_distribution(news_df)
            
            # 6. 뉴스 카테고리 분포 (LLM 결과)
            st.markdown("---")
            st.markdown("### 📊 뉴스 카테고리 분포 (LLM 결과)")
            _render_category_distribution_for_prompt(news_df)
            
            # 7. 카테고리별 사용자 참여도
            st.markdown("---")
            st.markdown("### 📊 카테고리별 사용자 참여도")
            _render_category_engagement_analysis(news_df, df_view)

# ============================================================================
# Supabase news 테이블 기반 콘텐츠 품질 분석 함수들
# ============================================================================

def _render_news_source_distribution(news_df: pd.DataFrame):
    """뉴스 출처(언론사) 분포"""
    if "source" not in news_df.columns:
        return
    
    st.markdown("#### 📰 뉴스 출처(언론사) 분포")
    
    # source가 있는 뉴스만 필터링
    news_with_source = news_df[news_df["source"].notna() & (news_df["source"] != "")]
    
    if news_with_source.empty:
        st.info("📊 출처 정보가 있는 뉴스가 없습니다.")
        return
    
    source_counts = news_with_source["source"].value_counts()
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("고유 출처 수", len(source_counts))
    with col2:
        st.metric("총 뉴스 수", len(news_with_source))
    
    # Top 10 출처
    top_sources = source_counts.head(10).reset_index()
    top_sources.columns = ["출처", "건수"]
    
    if px is not None and len(top_sources) > 0:
        fig = px.bar(
            top_sources,
            x="출처",
            y="건수",
            title="뉴스 출처 Top 10",
            labels={"출처": "언론사", "건수": "기사 수"},
            text="건수"  # 막대 위에 숫자 표시
        )
        fig.update_traces(texttemplate='%{text}', textposition='outside')
        fig.update_xaxes(tickangle=-45)
        fig.update_layout(
            height=400,
            showlegend=False
        )
        st.plotly_chart(fig, use_container_width=True)
    
def _render_financial_news_ratio(news_df: pd.DataFrame):
    """금융/비금융 기사 비중 (키워드 기반 분석)"""
    # title 또는 content 컬럼이 없으면 분석 불가
    if "title" not in news_df.columns and "content" not in news_df.columns:
        return
    
    st.markdown("#### 💰 금융/비금융 기사 비중 (키워드 기반)")
    
    # 금융 관련 키워드 (제목/본문에서 검색)
    financial_keywords = [
        "금융", "은행", "증권", "주식", "채권", "부동산", "경제", "시장", "투자", "자산",
        "이자", "금리", "환율", "인플레이션", "디플레이션", "경기", "경제성장", "GDP",
        "기업", "상장", "IPO", "배당", "수익", "손실", "재무", "회계", "세금", "정책",
        "한국은행", "금융감독원", "금융위원회", "증선위", "코스피", "코스닥", "나스닥",
        "비트코인", "암호화폐", "블록체인", "금융권", "금융사", "은행권"
    ]
    
    def is_financial(row):
        """뉴스가 금융 관련인지 판단"""
        title = str(row.get("title", "")).lower()
        content = str(row.get("content", "")).lower()
        
        text = title + " " + content[:500]  # 본문 앞부분 500자만 확인
        
        for keyword in financial_keywords:
            if keyword in text:
                return True
        return False
    
    news_df_copy = news_df.copy()
    news_df_copy["is_financial"] = news_df_copy.apply(is_financial, axis=1)
    
    financial_count = news_df_copy["is_financial"].sum()
    non_financial_count = (~news_df_copy["is_financial"]).sum()
    total_count = len(news_df_copy)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("금융 기사", f"{financial_count:,}건")
        if total_count > 0:
            financial_ratio = (financial_count / total_count) * 100
            st.caption(f"비율: {financial_ratio:.1f}%")
    with col2:
        st.metric("비금융 기사", f"{non_financial_count:,}건")
        if total_count > 0:
            non_financial_ratio = (non_financial_count / total_count) * 100
            st.caption(f"비율: {non_financial_ratio:.1f}%")
    with col3:
        st.metric("총 뉴스 수", f"{total_count:,}건")
    
    if total_count > 0 and px is not None:
        ratio_df = pd.DataFrame({
            "분류": ["금융 기사", "비금융 기사"],
            "건수": [financial_count, non_financial_count]
        })
        # Donut chart (hole 파라미터 사용)
        fig = px.pie(
            ratio_df,
            values="건수",
            names="분류",
            title="금융/비금융 기사 비중",
            hole=0.4  # 도넛 차트로 만들기
        )
        st.plotly_chart(fig, use_container_width=True)

def _render_content_length_analysis(news_df: pd.DataFrame):
    """본문 길이 분포"""
    # content 또는 raw_content_length 컬럼 확인
    content_col = None
    if "raw_content_length" in news_df.columns:
        content_col = "raw_content_length"
    elif "content" in news_df.columns:
        content_col = "content"
    else:
        return
    
    st.markdown("#### 📏 본문 길이 분포")
    
    if content_col == "raw_content_length":
        # raw_content_length가 숫자 컬럼인 경우
        news_with_content = news_df[news_df[content_col].notna()].copy()
        news_with_content["content_length"] = pd.to_numeric(news_with_content[content_col], errors='coerce')
    else:
        # content 컬럼에서 길이 계산
        news_with_content = news_df[news_df[content_col].notna() & (news_df[content_col] != "")].copy()
        news_with_content["content_length"] = news_with_content[content_col].astype(str).str.len()
    
    news_with_content = news_with_content[news_with_content["content_length"].notna() & (news_with_content["content_length"] > 0)]
    
    if news_with_content.empty:
        st.info("📊 본문 길이 정보가 있는 뉴스가 없습니다.")
        return
    
    col1, col2, col3 = st.columns(3)
    with col1:
        avg_length = news_with_content["content_length"].mean()
        st.metric("평균 본문 길이", f"{avg_length:.0f}자")
    with col2:
        median_length = news_with_content["content_length"].median()
        st.metric("중간값 본문 길이", f"{median_length:.0f}자")
    with col3:
        min_length = news_with_content["content_length"].min()
        max_length = news_with_content["content_length"].max()
        st.metric("최소/최대 길이", f"{min_length:.0f} / {max_length:.0f}자")
    
    if px is not None and len(news_with_content) > 0:
        fig = px.histogram(
            news_with_content,
            x="content_length",
            nbins=50,
            title="본문 길이 분포",
            labels={"content_length": "본문 길이 (자)", "count": "빈도"}
        )
        st.plotly_chart(fig, use_container_width=True)

def _render_content_missing_analysis(news_df: pd.DataFrame):
    """본문 누락 비율"""
    # content 또는 raw_content_length 컬럼 확인
    content_col = None
    if "content" in news_df.columns:
        content_col = "content"
    elif "raw_content_length" in news_df.columns:
        content_col = "raw_content_length"
    else:
        return
    
    st.markdown("#### 📝 본문 누락 비율")
    
    total_count = len(news_df)
    
    if content_col == "raw_content_length":
        # raw_content_length가 숫자 컬럼인 경우
        missing_content = news_df[news_df[content_col].isna() | (pd.to_numeric(news_df[content_col], errors='coerce') == 0)]
        missing_count = len(missing_content)
        
        # 본문이 너무 짧은 경우도 누락으로 간주 (300자 미만 - 사용 불가 수준)
        # 100자 미만: 매우 짧음 (사용 불가)
        # 200자 미만: 짧음 (사용 어려움)
        # 300자 미만: 경고 (너무 짧음)
        very_short_content = news_df[
            news_df[content_col].notna() &
            (pd.to_numeric(news_df[content_col], errors='coerce') < 100)
        ]
        short_content = news_df[
            news_df[content_col].notna() &
            (pd.to_numeric(news_df[content_col], errors='coerce') >= 100) &
            (pd.to_numeric(news_df[content_col], errors='coerce') < 300)
        ]
        very_short_count = len(very_short_content)
        short_count = len(short_content)
    else:
        # content 컬럼인 경우
        missing_content = news_df[news_df[content_col].isna() | (news_df[content_col] == "")]
        missing_count = len(missing_content)
        
        # 본문이 너무 짧은 경우도 누락으로 간주 (300자 미만 - 사용 불가 수준)
        # 100자 미만: 매우 짧음 (사용 불가)
        # 200자 미만: 짧음 (사용 어려움)
        # 300자 미만: 경고 (너무 짧음)
        very_short_content = news_df[
            news_df[content_col].notna() & 
            (news_df[content_col] != "") &
            (news_df[content_col].astype(str).str.len() < 100)
        ]
        short_content = news_df[
            news_df[content_col].notna() & 
            (news_df[content_col] != "") &
            (news_df[content_col].astype(str).str.len() >= 100) &
            (news_df[content_col].astype(str).str.len() < 300)
        ]
        very_short_count = len(very_short_content)
        short_count = len(short_content)
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("본문 완전 누락", f"{missing_count:,}건")
        if total_count > 0:
            missing_rate = (missing_count / total_count) * 100
            st.caption(f"누락률: {missing_rate:.1f}%")
    with col2:
        st.metric("매우 짧음 (<100자)", f"{very_short_count:,}건")
        if total_count > 0:
            very_short_rate = (very_short_count / total_count) * 100
            st.caption(f"비율: {very_short_rate:.1f}%")
    with col3:
        st.metric("짧음 (100-300자)", f"{short_count:,}건")
        if total_count > 0:
            short_rate = (short_count / total_count) * 100
            st.caption(f"비율: {short_rate:.1f}%")
    with col4:
        total_issue = missing_count + very_short_count + short_count
        st.metric("총 문제 기사", f"{total_issue:,}건")
        if total_count > 0:
            issue_rate = (total_issue / total_count) * 100
            st.caption(f"문제 비율: {issue_rate:.1f}%")
    
    if total_count > 0 and px is not None:
        quality_df = pd.DataFrame({
            "상태": ["정상", "누락", "매우 짧음 (<100자)", "짧음 (100-300자)"],
            "건수": [total_count - total_issue, missing_count, very_short_count, short_count]
        })
        fig = px.pie(
            quality_df,
            values="건수",
            names="상태",
            title="본문 품질 상태",
            color_discrete_map={
                "정상": "#10b981",
                "누락": "#ef4444",
                "매우 짧음 (<100자)": "#dc2626",
                "짧음 (100-300자)": "#b91c1c"
            }
        )
        st.plotly_chart(fig, use_container_width=True)

def _render_title_content_duplication(news_df: pd.DataFrame):
    """제목·본문 중복률"""
    if "title" not in news_df.columns or "content" not in news_df.columns:
        return
    
    st.markdown("#### 🔄 제목·본문 중복률")
    
    # title과 content가 모두 있는 뉴스만 분석
    valid_news = news_df[
        news_df["title"].notna() & 
        (news_df["title"] != "") &
        news_df["content"].notna() & 
        (news_df["content"] != "")
    ].copy()
    
    if valid_news.empty:
        st.info("📊 제목과 본문이 모두 있는 뉴스가 없습니다.")
        return
    
    # 제목이 본문 앞부분에 포함되어 있는지 확인
    def check_duplication(row):
        title = str(row["title"]).strip()
        content = str(row["content"]).strip()
        
        if not title or not content:
            return False
        
        # 본문 앞부분(제목 길이의 2배)에서 제목 포함 여부 확인
        content_preview = content[:len(title) * 2]
        return title in content_preview
    
    valid_news["has_duplication"] = valid_news.apply(check_duplication, axis=1)
    
    duplication_count = valid_news["has_duplication"].sum()
    total_count = len(valid_news)
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("중복 발견", f"{duplication_count:,}건")
    with col2:
        if total_count > 0:
            dup_rate = (duplication_count / total_count) * 100
            st.metric("중복률", f"{dup_rate:.1f}%")
        else:
            st.metric("중복률", "N/A")
    
    if total_count > 0 and px is not None:
        dup_df = pd.DataFrame({
            "상태": ["중복 없음", "중복 있음"],
            "건수": [total_count - duplication_count, duplication_count]
        })
        fig = px.pie(
            dup_df,
            values="건수",
            names="상태",
            title="제목·본문 중복 분포"
        )
        st.plotly_chart(fig, use_container_width=True)

def _render_data_quality_consistency(news_df: pd.DataFrame):
    """
    데이터 품질 일치 여부 분석: 제목-URL-content-summary 일치도
    
    분석 기준:
    1. 제목-content 일치도: 제목의 핵심 키워드가 content에 포함되는지 (가중치: 70%)
    2. URL-content 일치도: URL 도메인/경로와 content의 관련성 (가중치: 10%)
    3. summary-content 일치도: summary가 content를 정확히 요약하는지 (가중치: 20%)
    4. 종합 품질 점수: 위 3가지 기준의 가중 평균
    """
    required_columns = ["title", "content"]
    missing_columns = [col for col in required_columns if col not in news_df.columns]
    
    if missing_columns:
        return
    
    st.markdown("#### 🔍 데이터 품질 일치 여부 분석 (제목-URL-content-summary)")
    st.markdown("**목적**: 제목, URL, content, summary 간의 일치 여부를 확인하여 데이터 품질 문제를 발견")
    
    # 필수 컬럼이 있는 뉴스만 분석
    valid_news = news_df[
        news_df["title"].notna() & 
        (news_df["title"] != "") &
        news_df["content"].notna() & 
        (news_df["content"] != "")
    ].copy()
    
    if valid_news.empty:
        st.info("📊 제목과 본문이 모두 있는 뉴스가 없습니다.")
        return
    
    # news_id가 없으면 display_id 추가 (표시용)
    if "news_id" not in valid_news.columns:
        valid_news["display_id"] = valid_news.index
    
    # 키워드 추출 함수 (한글, 영문, 숫자만)
    def extract_keywords(text, min_length=2):
        """텍스트에서 핵심 키워드 추출"""
        if not text or pd.isna(text):
            return set()
        text_str = str(text).strip()
        if not text_str:
            return set()
        
        # 한글, 영문, 숫자만 추출
        import re
        keywords = re.findall(r'[가-힣a-zA-Z0-9]+', text_str)
        # 최소 길이 이상이고, 너무 일반적인 단어 제외
        stopwords = {'그', '이', '저', '것', '수', '때', '등', '및', '또', '또한', '그리고', 
                     'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'have', 'has', 'had'}
        keywords = [kw for kw in keywords if len(kw) >= min_length and kw.lower() not in stopwords]
        return set(keywords)
    
    # 제목-content 일치도 계산 (불량 뉴스 필터링을 위해 엄격한 기준)
    def calculate_title_content_match(row):
        """제목과 content의 일치도 계산 (0-100) - 엄격한 기준"""
        title = str(row.get("title", "")).strip()
        content = str(row.get("content", "")).strip()
        
        if not title or not content:
            return 30  # 데이터가 없으면 낮은 점수
        
        # content 길이 체크 (너무 짧으면 감점)
        content_length = len(content)
        length_penalty = 0
        if content_length < 100:  # 100자 미만
            length_penalty = -30  # 30점 감점
        elif content_length < 200:  # 200자 미만
            length_penalty = -20  # 20점 감점
        elif content_length < 300:  # 300자 미만
            length_penalty = -10  # 10점 감점
        
        # 제목의 키워드 추출
        title_keywords = extract_keywords(title, min_length=2)
        if not title_keywords:
            return 30  # 키워드가 없으면 낮은 점수
        
        # content의 키워드 추출 (앞부분 2000자)
        content_preview = content[:2000]
        content_keywords = extract_keywords(content_preview, min_length=2)
        
        # 제목 키워드가 content에 포함된 비율
        matched_keywords = title_keywords & content_keywords
        match_ratio = len(matched_keywords) / len(title_keywords) if title_keywords else 0
        
        # 제목 자체가 content 앞부분에 포함되는지 확인 (더 엄격하게)
        title_in_content = title in content[:300]  # 범위 축소
        title_match_bonus = 20 if title_in_content else 0
        
        # 키워드 매칭이 핵심 (더 엄격한 기준)
        # 키워드 매칭 비율이 낮으면 낮은 점수
        if match_ratio < 0.3:  # 30% 미만 매칭
            base_score = 20
        elif match_ratio < 0.5:  # 50% 미만 매칭
            base_score = 35
        elif match_ratio < 0.7:  # 70% 미만 매칭
            base_score = 50
        else:  # 70% 이상 매칭
            base_score = 65
        
        # 최종 점수: 기본 점수 + 키워드 매칭 비율(30%) + 제목 포함 여부(보너스) + 길이 감점
        score = base_score + (match_ratio * 30) + title_match_bonus + length_penalty
        return min(100, max(0, int(score)))  # 최소 점수 보장 제거
    
    # URL-content 일치도 계산
    def calculate_url_content_match(row):
        """URL과 content의 일치도 계산 (0-100) - 완화된 기준"""
        url = str(row.get("url", "")).strip() if pd.notna(row.get("url")) else ""
        content = str(row.get("content", "")).strip()
        
        if not url or not content:
            return 60  # URL이 없어도 기본 점수 (완화)
        
        # URL에서 도메인과 경로 키워드 추출
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc.replace("www.", "")
            path = parsed.path
            
            # 도메인과 경로에서 키워드 추출
            url_keywords = extract_keywords(domain + " " + path, min_length=2)
            
            # content에서 URL 키워드가 포함되는지 확인 (범위 확대)
            content_keywords = extract_keywords(content[:1000], min_length=2)
            matched = url_keywords & content_keywords
            
            # URL이 content에 직접 언급되는지 확인
            url_mentioned = domain in content or url in content
            
            # 점수 계산 (완화된 기준)
            if url_mentioned:
                return 100
            elif matched:
                match_ratio = len(matched) / len(url_keywords) if url_keywords else 0
                # 기본 점수 50점 + 매칭 비율에 따른 추가 점수
                return min(100, int(50 + match_ratio * 50))
            else:
                # URL이 있고 content도 있으면 기본적으로 관련 있다고 가정 (완화)
                return 50  # 관련성 낮아도 기본 점수
        except:
            return 60  # 파싱 실패 시 기본 점수 (완화)
    
    # summary-content 일치도 계산
    def calculate_summary_content_match(row):
        """summary와 content의 일치도 계산 (0-100) - 완화된 기준"""
        summary = str(row.get("summary", "")).strip() if pd.notna(row.get("summary")) else ""
        content = str(row.get("content", "")).strip()
        
        if not summary or not content:
            return 60  # summary가 없어도 기본 점수 (완화)
        
        # summary의 키워드 추출
        summary_keywords = extract_keywords(summary, min_length=2)
        if not summary_keywords:
            return 60  # 키워드가 없어도 기본 점수 (완화)
        
        # content의 키워드 추출 (앞부분 3000자로 확대)
        content_preview = content[:3000]
        content_keywords = extract_keywords(content_preview, min_length=2)
        
        # summary 키워드가 content에 포함된 비율
        matched_keywords = summary_keywords & content_keywords
        match_ratio = len(matched_keywords) / len(summary_keywords) if summary_keywords else 0
        
        # summary가 content의 앞부분과 유사한지 확인
        content_start_keywords = extract_keywords(content[:1000], min_length=2)
        start_match_ratio = len(summary_keywords & content_start_keywords) / len(summary_keywords) if summary_keywords else 0
        
        # 최소한 1개 이상 키워드가 매칭되면 기본 점수 부여 (완화)
        base_score = 50 if len(matched_keywords) > 0 else 45
        
        # 최종 점수: 기본 점수 + 키워드 매칭 비율(40%) + 앞부분 일치(10%)
        score = base_score + (match_ratio * 40) + (start_match_ratio * 10)
        return min(100, max(45, int(score)))  # 최소 45점 보장
    
    # 각 뉴스에 대해 일치도 계산
    valid_news["title_content_match"] = valid_news.apply(calculate_title_content_match, axis=1)
    valid_news["url_content_match"] = valid_news.apply(calculate_url_content_match, axis=1)
    valid_news["summary_content_match"] = valid_news.apply(calculate_summary_content_match, axis=1)
    
    # 종합 품질 점수 (가중 평균)
    # 제목-content: 70% (가중치 크게), URL-content: 10%, summary-content: 20%
    valid_news["quality_score"] = (
        valid_news["title_content_match"] * 0.7 +
        valid_news["url_content_match"] * 0.1 +
        valid_news["summary_content_match"] * 0.2
    ).round(1)
    
    # 품질 등급 분류 (제목-본문 일치도가 낮으면 등급 강등, 보통 카테고리 제거)
    def get_quality_grade(row):
        score = row["quality_score"]
        title_match = row["title_content_match"]
        
        # 40점 이상이면 무난한 품질로 간주 (불량 제외)
        if score >= 40:
            # 제목-본문 일치도가 50점 미만이면 등급을 한 단계 낮춤
            if title_match < 50:
                if score >= 70:
                    return "양호"  # 우수 → 양호
                elif score >= 50:
                    return "양호"  # 양호 유지
                else:  # 40-50점
                    return "양호"  # 무난한 품질로 양호 처리
            
            # 제목-본문 일치도가 50-60점이면 등급을 한 단계 낮춤
            if title_match < 60:
                if score >= 70:
                    return "양호"  # 우수 → 양호
                elif score >= 50:
                    return "양호"  # 양호 유지
                else:  # 40-50점
                    return "양호"  # 무난한 품질로 양호 처리
            
            # 제목-본문 일치도가 정상이면 일반 기준 적용
            if score >= 70:
                return "우수"
            elif score >= 50:
                return "양호"
            else:  # 40-50점
                return "양호"  # 무난한 품질로 양호 처리
        
        # 40점 미만만 불량으로 분류
        return "불량"
    
    valid_news["quality_grade"] = valid_news.apply(get_quality_grade, axis=1)
    
    # 통계 요약
    total_count = len(valid_news)
    
    # 히스토그램 평균선 표시용 평균 계산 (안전하게 처리)
    avg_quality_score = 0.0
    if not valid_news.empty and "quality_score" in valid_news.columns:
        avg_quality_score = valid_news["quality_score"].mean()
        if pd.isna(avg_quality_score):
            avg_quality_score = 0.0
    
    # 품질 등급별 기술통계
    st.markdown("##### 📊 품질 등급별 점수 기술통계")
    
    grade_stats_list = []
    for grade in ["우수", "양호", "불량"]:
        grade_data = valid_news[valid_news["quality_grade"] == grade]
        if not grade_data.empty:
            stats = {
                "등급": grade,
                "개수": len(grade_data),
                "평균": grade_data["quality_score"].mean(),
                "표준편차": grade_data["quality_score"].std(),
                "최소값": grade_data["quality_score"].min(),
                "최대값": grade_data["quality_score"].max(),
                "중간값": grade_data["quality_score"].median()
            }
            grade_stats_list.append(stats)
    
    if grade_stats_list:
        grade_stats_df = pd.DataFrame(grade_stats_list)
        # 소수점 2자리로 반올림
        grade_stats_df["평균"] = grade_stats_df["평균"].round(2)
        grade_stats_df["표준편차"] = grade_stats_df["표준편차"].round(2)
        grade_stats_df["최소값"] = grade_stats_df["최소값"].round(2)
        grade_stats_df["최대값"] = grade_stats_df["최대값"].round(2)
        grade_stats_df["중간값"] = grade_stats_df["중간값"].round(2)
        
        # 표준편차가 NaN인 경우 0으로 처리
        grade_stats_df["표준편차"] = grade_stats_df["표준편차"].fillna(0)
        
        st.dataframe(grade_stats_df, use_container_width=True, height=200)
    
    # 품질 등급 분포 (보통 제거)
    grade_counts = valid_news["quality_grade"].value_counts()
    grade_order = ["우수", "양호", "불량"]
    grade_counts = grade_counts.reindex(grade_order, fill_value=0)
    
    if px is not None and len(grade_counts) > 0:
        grade_df = pd.DataFrame({
            "등급": grade_counts.index,
            "건수": grade_counts.values
        })
        fig = px.pie(
            grade_df,
            values="건수",
            names="등급",
            title="데이터 품질 등급 분포",
            color="등급",
            color_discrete_map={"우수": "#10b981", "양호": "#3b82f6", "불량": "#ef4444"}
        )
        st.plotly_chart(fig, use_container_width=True)
    
    # 품질 점수 분포 히스토그램
    if px is not None:
        fig = px.histogram(
            valid_news,
            x="quality_score",
            nbins=20,
            title="종합 품질 점수 분포",
            labels={"quality_score": "품질 점수", "count": "뉴스 수"},
            color_discrete_sequence=["#3b82f6"]
        )
        fig.add_vline(x=avg_quality_score, line_dash="dash", line_color="red", 
                     annotation_text=f"평균: {avg_quality_score:.1f}점")
        st.plotly_chart(fig, use_container_width=True)
    
    # 불량 데이터 상세 목록 (불량 등급만 필터링)
    st.markdown("#### ⚠️ 불량 뉴스 (전체 목록)")
    
    # 불량 등급인 뉴스만 필터링
    bad_quality_news = valid_news[valid_news["quality_grade"] == "불량"].copy()
    
    if bad_quality_news.empty:
        st.info("✅ 불량 등급인 뉴스가 없습니다.")
    else:
        # news_id 컬럼이 있으면 포함, 없으면 display_id 사용
        display_columns = []
        if "news_id" in bad_quality_news.columns:
            display_columns.append("news_id")
        elif "display_id" in bad_quality_news.columns:
            display_columns.append("display_id")
        
        display_columns.extend(["title", "url", "content", "quality_score", "title_content_match", 
                               "url_content_match", "summary_content_match", "quality_grade"])
        
        # 존재하는 컬럼만 선택
        available_columns = [col for col in display_columns if col in bad_quality_news.columns]
        # 품질 점수 낮은 순으로 정렬
        bad_quality = bad_quality_news.nsmallest(len(bad_quality_news), "quality_score")[available_columns].copy()
        
        # 불량 뉴스 개수 표시
        st.markdown(f"**총 {len(bad_quality):,}건의 불량 뉴스가 발견되었습니다.**")
        
        # 불량 뉴스의 뉴스처(언론사) 비율 파이그래프
        if "source" in bad_quality_news.columns:
            source_counts = bad_quality_news["source"].value_counts()
            if len(source_counts) > 0:
                st.markdown("##### 📊 불량 뉴스 뉴스처(언론사) 비율")
                
                # 뉴스처별 개수와 비율 계산
                source_df = pd.DataFrame({
                    "뉴스처": source_counts.index,
                    "건수": source_counts.values
                })
                source_df["비율 (%)"] = (source_df["건수"] / len(bad_quality_news) * 100).round(1)
                
                # 파이그래프 생성
                if px is not None:
                    fig_source = px.pie(
                        source_df,
                        values="건수",
                        names="뉴스처",
                        title="불량 뉴스 뉴스처(언론사) 비율",
                        hover_data=["비율 (%)"]
                    )
                    fig_source.update_layout(
                        height=400,
                        showlegend=True
                    )
                    st.plotly_chart(fig_source, use_container_width=True)
    
        # 컬럼명 한글화
        column_mapping = {
            "news_id": "뉴스 ID",
            "display_id": "뉴스 ID",
            "title": "제목",
            "url": "URL",
            "content": "본문 내용",
            "quality_score": "종합 점수",
            "title_content_match": "제목-본문 일치도",
            "url_content_match": "URL-본문 일치도",
            "summary_content_match": "요약-본문 일치도",
            "quality_grade": "등급"
        }
        bad_quality.columns = [column_mapping.get(col, col) for col in bad_quality.columns]
        
        # 제목, URL, 본문 내용 길이 제한 (표시용)
        if "제목" in bad_quality.columns:
            bad_quality["제목"] = bad_quality["제목"].apply(lambda x: str(x)[:50] + "..." if len(str(x)) > 50 else str(x))
        if "URL" in bad_quality.columns:
            bad_quality["URL"] = bad_quality["URL"].apply(lambda x: str(x)[:50] + "..." if len(str(x)) > 50 else str(x))
        if "본문 내용" in bad_quality.columns:
            # 본문 내용은 200자로 제한 (더 길게 표시)
            bad_quality["본문 내용"] = bad_quality["본문 내용"].apply(
                lambda x: str(x)[:200] + "..." if len(str(x)) > 200 else str(x) if pd.notna(x) and str(x).strip() else "(내용 없음)"
            )
        
        st.dataframe(bad_quality, use_container_width=True, height=600)
    

def _render_duplicate_news_analysis(news_df: pd.DataFrame):
    """중복 기사 비율"""
    if "url" not in news_df.columns:
        return
    
    st.markdown("#### 🔁 중복 기사 비율")
    
    # url이 있는 뉴스만 필터링
    news_with_url = news_df[news_df["url"].notna() & (news_df["url"] != "")]
    
    if news_with_url.empty:
        st.info("📊 URL이 있는 뉴스가 없습니다.")
        return
    
    # URL 기준으로 중복 확인
    url_counts = news_with_url["url"].value_counts()
    duplicate_urls = url_counts[url_counts > 1]
    
    total_news = len(news_with_url)
    unique_urls = len(url_counts)
    duplicate_count = len(duplicate_urls)
    total_duplicate_instances = duplicate_urls.sum() - duplicate_count  # 중복 인스턴스 수
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("고유 URL 수", f"{unique_urls:,}개")
    with col2:
        st.metric("중복 URL 수", f"{duplicate_count:,}개")
    with col3:
        if total_news > 0:
            dup_rate = (total_duplicate_instances / total_news) * 100
            st.metric("중복 비율", f"{dup_rate:.1f}%")
        else:
            st.metric("중복 비율", "N/A")
    
    # 중복이 많은 URL Top 10
    if len(duplicate_urls) > 0:
        top_duplicates = duplicate_urls.head(10).reset_index()
        top_duplicates.columns = ["URL", "중복 횟수"]
        st.dataframe(top_duplicates, use_container_width=True, height=200)

def _render_news_collection_trends(news_df: pd.DataFrame):
    """RSS/크롤링별 수집량 추세"""
    if "published_at" not in news_df.columns:
        return
    
    st.markdown("#### 📈 뉴스 수집량 추세")
    
    # published_at이 있는 뉴스만 필터링
    news_with_date = news_df[news_df["published_at"].notna()].copy()
    
    if news_with_date.empty:
        st.info("📊 발행일 정보가 있는 뉴스가 없습니다.")
        return
    
    # 일별 수집량
    news_with_date["date"] = news_with_date["published_at"].dt.date
    daily_counts = news_with_date.groupby("date").size().reset_index(name="건수")
    daily_counts = daily_counts.sort_values("date")
    
    col1, col2 = st.columns(2)
    with col1:
        total_news = len(news_with_date)
        st.metric("총 뉴스 수", f"{total_news:,}건")
    with col2:
        if len(daily_counts) > 0:
            avg_daily = daily_counts["건수"].mean()
            st.metric("일평균 수집량", f"{avg_daily:.1f}건")
    
    if px is not None and len(daily_counts) > 0:
        fig = px.line(
            daily_counts,
            x="date",
            y="건수",
            title="일별 뉴스 수집량 추이",
            labels={"date": "날짜", "건수": "수집 건수"}
        )
        st.plotly_chart(fig, use_container_width=True)
    
    # source별 수집량 (source가 있는 경우)
    if "source" in news_df.columns:
        news_with_source = news_with_date[news_with_date["source"].notna() & (news_with_date["source"] != "")]
        if not news_with_source.empty:
            source_counts = news_with_source["source"].value_counts().head(10)
            
            if px is not None and len(source_counts) > 0:
                source_df = source_counts.reset_index()
                source_df.columns = ["출처", "건수"]
                fig2 = px.bar(
                    source_df,
                    x="출처",
                    y="건수",
                    title="출처별 수집량 Top 10",
                    labels={"출처": "언론사/소스", "건수": "수집 건수"}
                )
                fig2.update_xaxes(tickangle=-45)
                st.plotly_chart(fig2, use_container_width=True)

def _get_korean_font_path():
    """한글 폰트 경로 찾기"""
    # Windows 폰트 경로들
    windows_font_paths = [
        "C:/Windows/Fonts/NanumGothic.ttf",
        "C:/Windows/Fonts/NanumBarunGothic.ttf",
        "C:/Windows/Fonts/malgun.ttf",  # 맑은 고딕
        "C:/Windows/Fonts/gulim.ttc",  # 굴림
    ]
    
    # Linux/Mac 폰트 경로들
    linux_font_paths = [
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf",
        "/System/Library/Fonts/AppleGothic.ttf",  # Mac
    ]
    
    # Windows 경로 확인
    for font_path in windows_font_paths:
        if os.path.exists(font_path):
            return font_path
    
    # Linux/Mac 경로 확인
    for font_path in linux_font_paths:
        if os.path.exists(font_path):
            return font_path
    
    return None

def _extract_korean_words(text: str) -> List[str]:
    """한국어 단어 추출 (조사/불용어 제거)"""
    if not text:
        return []
    
    # 한국어 불용어 및 조사 (뉴스 특화)
    stopwords = {
        # 조사
        "은", "는", "이", "가", "을", "를", "의", "에", "와", "과", "도", "로", "으로",
        "에서", "에게", "한테", "께", "부터", "까지", "만", "조차", "마저", "뿐",
        
        # 대명사
        "그", "그것", "이것", "저것", "그들", "이들", "저들", "그녀", "그분",
        
        # 접속사/부사
        "그리고", "또한", "그러나", "하지만", "그런데", "그래서", "따라서", "그러므로",
        "때문에", "위해", "대해", "관련", "더", "또", "또는", "및",
        
        # 뉴스 관련 용어
        "기자", "연합뉴스", "뉴스", "기사", "보도", "취재", "전문", "인터뷰",
        "발표", "발생", "확인", "밝혔다", "말했다", "했다", "있다", "없다",
        "전망", "예상", "예측", "추정", "분석", "조사", "결과", "발견",
        "이번", "이날", "오늘", "어제", "내일", "지난", "올해", "작년", "내년",
        "지난해", "올", "작", "내",
        
        # 시간 관련
        "월", "일", "년", "시", "분", "초", "요일", "주", "개월", "년도",
        "오전", "오후", "새벽", "밤", "낮", "저녁", "날짜",
        
        # 수량/단위 (너무 일반적인 것들)
        "만", "억", "조", "원", "달러", "퍼센트", "프로",
        "개", "명", "건", "곳", "차례", "번", "회", "차",
        
        # 일반 동사/형용사 (너무 빈번한 것들)
        "있다", "없다", "되다", "하다", "이다", "않다", "아니다",
        "같다", "다르다", "크다", "작다", "많다", "적다", "높다", "낮다",
        "좋다", "나쁘다", "새롭다", "오래되다", "최근", "최신",
        "있는", "없는", "되는", "하는", "것으로", "것이다", "것이", "것을", "것을",
        
        # 일반적인 형용사/부사
        "매우", "아주", "너무", "정말", "진짜", "완전", "전혀", "별로",
        "가장", "최고", "최대", "최소",
        
        # 뉴스 문체 특화
        "따르면", "에 따르면", "밝혔다", "말했다", "전했다", "알려졌다",
        "확인됐다", "발생했다", "나타났다", "지적했다", "강조했다",
        "주장했다", "제기했다", "요구했다", "촉구했다", "제안했다",
        "발표했다", "공개했다", "발표됐다", "공개됐다",
        
        # 기관/직책 (너무 일반적인 것들)
        "정부", "국가", "기관", "단체", "조직", "회사", "기업", "법인",
        "대표", "사장", "회장", "이사", "직원", "관계자", "당국",
        
        # 일반적인 명사 (뉴스에서 너무 자주 나오는 것들)
        "사실", "내용", "상황", "문제", "이슈", "사건", "사고", "사례",
        "경우", "때문", "이유", "원인", "결과", "영향", "효과",
        "방법", "방안", "대책", "정책", "제도", "시스템",
        "과정", "절차", "단계", "수준", "정도", "범위",
        "국내", "대비",
        
        # 위치/방향 (너무 일반적인 것들)
        "위", "아래", "앞", "뒤", "왼쪽", "오른쪽", "중앙", "중심",
        "내부", "외부", "앞쪽", "뒤쪽", "양쪽",
        
        # 기타 빈번한 단어
        "등", "및", "또", "그리고", "그러나",
        "이미", "아직", "벌써", "곧", "곧바로", "즉시", "바로",
    }
    
    # 의미없는 숫자 패턴 제거 (1-31일, 1-12월 등)
    # 단어 추출 후 숫자만 있는 단어 제거
    
    # 한글만 추출 (한글, 공백, 숫자)
    korean_text = re.sub(r'[^가-힣\s0-9]', ' ', text)
    
    # 단어 분리 (공백 기준)
    words = korean_text.split()
    
    # 필터링 함수
    def should_keep_word(word):
        word = word.strip()
        
        # 2글자 미만 제거
        if len(word) < 2:
            return False
        
        # 불용어 제거
        if word in stopwords:
            return False
        
        # 의미없는 숫자 패턴 제거 (1-31일, 1-12월 등)
        # 숫자만 있거나 숫자+일/월/년/시/분 등으로 끝나는 단어
        if re.match(r'^\d+[일월년시분초]?$', word):
            # 1-31일, 1-12월 같은 의미없는 숫자는 제거
            num_match = re.match(r'^(\d+)([일월년시분초]?)$', word)
            if num_match:
                num = int(num_match.group(1))
                suffix = num_match.group(2)
                # 1-31일, 1-12월 같은 패턴은 제거
                if suffix in ['일', '월'] and 1 <= num <= 31:
                    return False
                # 1-24시 같은 패턴도 제거
                if suffix == '시' and 1 <= num <= 24:
                    return False
                # 1-60분 같은 패턴도 제거
                if suffix == '분' and 1 <= num <= 60:
                    return False
                # 숫자만 있는 경우 (너무 짧은 숫자)
                if not suffix and num < 100:
                    return False
        
        return True
    
    # 필터링 적용
    filtered_words = [
        word.strip() 
        for word in words 
        if should_keep_word(word.strip())
    ]
    
    return filtered_words

def _calculate_news_scores(news: Dict[str, Any]) -> Dict[str, float]:
    """
    뉴스의 5가지 지표를 계산하여 라이다 차트에 사용할 점수를 반환
    
    계산 지표:
    1. 시장 영향도: 금융 시장 관련 키워드 기반 (0-100)
    2. 정보 밀도: 본문 길이 및 숫자 포함 여부 (0-100)
    3. 초보자 난이도: RAG 용어 사전에 있는 전문 용어가 많을수록 감점 (0-100, 높을수록 쉬움)
    4. 학습 가치: 교육적 키워드 기반 (0-100)
    5. 실행 가치: 실용적 조언 키워드 기반 (0-100)
    
    Args:
        news: 뉴스 딕셔너리 (title, content 등 포함)
    
    Returns:
        5가지 지표 점수가 담긴 딕셔너리
    """
    title = str(news.get("title", "")).strip()
    content = str(news.get("content", "")).strip()
    
    # 기본 점수: 모든 지표는 50점에서 시작 (초보자 난이도는 100점에서 시작)
    scores = {
        "market_impact": 50.0,      # 시장 영향도: 기본 50점
        "info_density": 50.0,       # 정보 밀도: 기본 50점 (본문 길이에 따라 재설정됨)
        "beginner_friendly": 100.0, # 초보자 난이도: 기본 100점 (전문 용어에 따라 감점)
        "learning_value": 50.0,     # 학습 가치: 기본 50점
        "action_value": 50.0        # 실행 가치: 기본 50점
    }
    
    # 텍스트 합치기 (제목 + 본문, 소문자로 변환하여 키워드 매칭)
    text = f"{title} {content}".lower()
    content_len = len(content)
    title_len = len(title)
    
    # ========== 1. 시장 영향도 (Market Impact) 계산 ==========
    # 목적: 뉴스가 금융 시장에 미치는 영향의 크기를 측정
    # 계산 방법: 금융 관련 키워드 + 숫자 포함 여부
    
    # 금융 관련 키워드 목록 (16개)
    market_keywords = [
        "금리", "금융", "증권", "주식", "시장", "경제", "정책", "한국은행",
        "코스피", "코스닥", "인플레이션", "디플레이션", "환율", "부동산", "투자", "자산"
    ]
    market_count = sum(1 for keyword in market_keywords if keyword in text)
    # 키워드 1개당 +5점 (최대 50점 추가 가능)
    scores["market_impact"] = min(100, 50 + market_count * 5)
    
    # 숫자 포함 여부 (금리, 퍼센트, 금액 등)
    # 패턴: 숫자 + 단위(%, 원, 억, 만, 조)
    numbers = len(re.findall(r'\d+[%원억만조]?', text))
    # 숫자 1개당 +2점 (최대 20점 추가 가능)
    scores["market_impact"] = min(100, scores["market_impact"] + min(numbers * 2, 20))
    
    # ========== 2. 정보 밀도 (Info Density) 계산 ==========
    # 목적: 뉴스에 포함된 정보의 양과 질을 측정
    # 계산 방법: 본문 길이 + 숫자/통계 포함 여부
    
    if content_len > 0:
        # 본문 길이에 따른 기본 점수 설정
        if content_len >= 2000:
            scores["info_density"] = 80  # 매우 긴 기사: 정보가 풍부함
        elif content_len >= 1000:
            scores["info_density"] = 70  # 긴 기사: 정보가 많음
        elif content_len >= 500:
            scores["info_density"] = 60  # 중간 길이: 적당한 정보
        else:
            scores["info_density"] = 40  # 짧은 기사: 정보가 부족함
        
        # 숫자/통계 포함 여부 (본문 내에서만 검색)
        numbers = len(re.findall(r'\d+[%원억만조]?', content))
        # 숫자 1개당 +1점 (최대 20점 추가 가능)
        scores["info_density"] = min(100, scores["info_density"] + min(numbers, 20))
    else:
        # 본문이 없으면 정보 밀도는 0점
        scores["info_density"] = 0
    
    # ========== 3. 초보자 난이도 (Beginner Friendly) 계산 ==========
    # 목적: 초보자가 이해하기 쉬운 정도를 측정 (높을수록 쉬움)
    # 계산 방법: RAG 금융 용어 사전의 용어 감점 + 본문 길이 감점
    
    # RAG 금융 용어 사전에서 용어 가져오기
    try:
        from rag.glossary import ensure_financial_terms, DEFAULT_TERMS
        ensure_financial_terms()  # RAG 용어 사전 초기화
        financial_terms = st.session_state.get("financial_terms", DEFAULT_TERMS)
        expert_terms = list(financial_terms.keys()) if financial_terms else []
    except Exception:
        # RAG 로드 실패 시 기본 전문 용어 목록 사용 (fallback)
        expert_terms = [
            "파생상품", "옵션", "선물", "스왑", "헤지", "레버리지", "마진콜", "증거금",
            "M&A", "IPO", "공모주", "배당락일", "액면분할", "유상증자"
        ]
    
    # RAG 용어 사전에 있는 용어가 뉴스에 포함된 개수 계산
    # 긴 용어부터 매칭하여 부분 매칭 방지 (예: "기준금리"가 "금리"보다 먼저 매칭)
    expert_terms_sorted = sorted(expert_terms, key=len, reverse=True)
    matched_terms = []
    text_lower = text.lower()
    
    for term in expert_terms_sorted:
        if term.lower() in text_lower:
            matched_terms.append(term)
            # 이미 매칭된 부분을 제거하여 중복 카운트 방지 (간단한 방법)
            # 실제로는 더 정교한 매칭이 필요할 수 있지만, 성능을 위해 단순화
    
    expert_count = len(matched_terms)
    
    # RAG 용어가 많을수록 감점
    # RAG 용어 사전 크기에 따라 감점 비율 조정
    # - 용어 사전이 작으면(50개 이하): 용어 1개당 -2점
    # - 용어 사전이 중간(51-200개): 용어 1개당 -1점
    # - 용어 사전이 크면(200개 이상): 용어 1개당 -0.5점
    if len(expert_terms) <= 50:
        penalty_per_term = 2.0
    elif len(expert_terms) <= 200:
        penalty_per_term = 1.0
    else:
        penalty_per_term = 0.5
    
    total_penalty = min(50, expert_count * penalty_per_term)  # 최대 50점 감점
    scores["beginner_friendly"] = max(0, 100 - total_penalty)
    
    # 본문이 너무 짧으면 정보가 부족하여 이해하기 어려움
    if content_len < 300:
        scores["beginner_friendly"] = max(0, scores["beginner_friendly"] - 20)
    
    # ========== 4. 학습 가치 (Learning Value) 계산 ==========
    # 목적: 뉴스가 교육적 가치를 제공하는 정도를 측정
    # 계산 방법: 교육적 키워드 + 본문 길이 보너스
    
    # 교육적 키워드 목록 (14개)
    learning_keywords = [
        "설명", "이유", "배경", "과정", "방법", "원리", "개념", "의미",
        "영향", "효과", "결과", "분석", "전망", "예상"
    ]
    learning_count = sum(1 for keyword in learning_keywords if keyword in text)
    # 키워드 1개당 +5점
    scores["learning_value"] = min(100, 50 + learning_count * 5)
    
    # 본문 길이가 길수록 더 많은 배경 정보와 설명을 포함할 가능성이 높음
    if content_len >= 1500:
        scores["learning_value"] = min(100, scores["learning_value"] + 20)  # 매우 긴 기사: +20점
    elif content_len >= 800:
        scores["learning_value"] = min(100, scores["learning_value"] + 10)   # 긴 기사: +10점
    
    # ========== 5. 실행 가치 (Action Value) 계산 ==========
    # 목적: 뉴스가 실용적인 조언이나 행동 지침을 제공하는 정도를 측정
    # 계산 방법: 행동 지침 키워드 + 구체적 숫자/기간 보너스
    
    # 행동 지침 키워드 목록 (14개)
    action_keywords = [
        "권장", "제안", "조언", "방안", "대책", "전략", "계획", "방법",
        "해야", "필요", "중요", "주의", "경고", "시사점"
    ]
    action_count = sum(1 for keyword in action_keywords if keyword in text)
    # 키워드 1개당 +5점
    scores["action_value"] = min(100, 50 + action_count * 5)
    
    # 구체적인 숫자나 기간이 있으면 실행 가능성이 높음
    # 패턴: 숫자 + 단위(%, 원, 억, 만, 조, 일, 월, 년)
    specific_numbers = len(re.findall(r'\d+[%원억만조일월년]', text))
    if specific_numbers >= 3:
        scores["action_value"] = min(100, scores["action_value"] + 15)  # 구체적 정보 보너스
    
    # ========== 최종 점수 정규화 ==========
    # 모든 점수를 0-100 범위로 제한 (안전장치)
    for key in scores:
        scores[key] = max(0, min(100, scores[key]))
    
    return scores

def _render_search_result_news_popularity(df_view: pd.DataFrame):
    """검색 결과 뉴스 인기 분석"""
    search_events = df_view[df_view["event_name"] == "news_search_from_chat"].copy()
    selected_events = df_view[df_view["event_name"] == "news_selected_from_chat"].copy()
    
    if search_events.empty:
        return
    
    st.markdown("#### 🔍 검색 결과 뉴스 인기 분석")
    st.markdown("**목적**: 챗봇 검색 결과에서 어떤 뉴스가 가장 인기 있는지 분석")
    
    # 검색 결과에 포함된 뉴스 ID 수집
    news_appearances = {}  # {news_id: {count: int, keywords: set}}
    
    for idx, row in search_events.iterrows():
        payload = _parse_payload(row.get("payload"))
        # article_ids 외에 다른 필드명도 확인 (supabase_results 등)
        article_ids = []
        if payload:
            # 여러 가능한 필드명 확인
            if "article_ids" in payload:
                article_ids = payload.get("article_ids", [])
            elif "supabase_results" in payload:
                # supabase_results가 리스트인 경우
                results = payload.get("supabase_results", [])
                if isinstance(results, list):
                    article_ids = [item.get("id") or item.get("news_id") for item in results if item]
            elif "results" in payload:
                results = payload.get("results", [])
                if isinstance(results, list):
                    article_ids = [item.get("id") or item.get("news_id") for item in results if item]
            
            keyword = payload.get("keyword", "")
            
            for news_id in article_ids:
                if news_id:
                    news_id_str = str(news_id)
                    if news_id_str not in news_appearances:
                        news_appearances[news_id_str] = {"count": 0, "keywords": set()}
                    news_appearances[news_id_str]["count"] += 1
                    if keyword:
                        news_appearances[news_id_str]["keywords"].add(keyword)
    
    # 실제 클릭된 뉴스 ID 수집
    news_clicks = {}  # {news_id: count}
    news_titles = {}  # {news_id: title}
    
    for idx, row in selected_events.iterrows():
        news_id = row.get("news_id")
        if news_id:
            news_id_str = str(news_id)
            news_clicks[news_id_str] = news_clicks.get(news_id_str, 0) + 1
            
            # 제목 정보 수집 (payload에서 먼저 시도)
            payload = _parse_payload(row.get("payload"))
            if payload and "title" in payload and news_id_str not in news_titles:
                news_titles[news_id_str] = payload.get("title", "")
    
    # Supabase news 테이블에서 제목 가져오기 (payload에 없는 경우)
    all_news_ids = set(news_appearances.keys()) | set(news_clicks.keys())
    missing_title_ids = [nid for nid in all_news_ids if nid not in news_titles]
    
    if missing_title_ids:
        try:
            # Supabase에서 뉴스 제목 가져오기
            news_df = _fetch_news_from_supabase(limit=10000)  # 충분히 많이 가져오기
            if not news_df.empty and "news_id" in news_df.columns and "title" in news_df.columns:
                # news_id를 문자열로 변환하여 매칭 (양방향 변환 시도)
                news_df["news_id_str"] = news_df["news_id"].astype(str)
                # 정수로도 변환 시도 (news_id가 정수인 경우)
                try:
                    news_df["news_id_int"] = news_df["news_id"].astype(int)
                except:
                    news_df["news_id_int"] = None
                
                for news_id_str in missing_title_ids:
                    matched_news = None
                    
                    # 문자열로 먼저 매칭 시도
                    matched_news = news_df[news_df["news_id_str"] == news_id_str]
                    
                    # 문자열 매칭 실패 시 정수로 변환하여 매칭 시도
                    if matched_news.empty:
                        try:
                            news_id_int = int(news_id_str)
                            if "news_id_int" in news_df.columns:
                                matched_news = news_df[news_df["news_id_int"] == news_id_int]
                        except (ValueError, TypeError):
                            pass
                    
                    if not matched_news.empty:
                        title = matched_news.iloc[0].get("title", "")
                        if title and pd.notna(title) and str(title).strip():
                            news_titles[news_id_str] = str(title).strip()
        except Exception as e:
            # Supabase 조회 실패 시 에러 로깅 (디버깅용)
            import traceback
            print(f"⚠️ Supabase에서 뉴스 제목 조회 실패: {e}")
            print(f"에러 상세: {traceback.format_exc()}")
            # 에러가 발생해도 계속 진행 (payload에서 가져온 제목만 사용)
    
    # 인기 뉴스 분석 데이터 생성
    # 클릭된 뉴스도 포함 (검색 결과에 포함되지 않았더라도)
    all_news_ids_for_analysis = set(news_appearances.keys()) | set(news_clicks.keys())
    
    if all_news_ids_for_analysis:
        popularity_data = []
        for news_id in all_news_ids_for_analysis:
            appearance_count = news_appearances.get(news_id, {}).get("count", 0)
            click_count = news_clicks.get(news_id, 0)
            # appearance_count가 0이면 클릭률 계산 불가 (N/A 또는 0으로 표시)
            # 실제로는 검색 결과에 포함되지 않았지만 클릭된 경우일 수 있음
            if appearance_count > 0:
                click_rate = (click_count / appearance_count * 100)
            else:
                # 검색 결과에 포함되지 않았지만 클릭된 경우
                click_rate = 0  # 또는 N/A로 표시할 수도 있음
            title = news_titles.get(news_id, f"뉴스 ID: {news_id}")
            
            popularity_data.append({
                "news_id": news_id,
                "제목": title[:50] + "..." if len(title) > 50 else title,
                "검색 결과 포함": appearance_count if appearance_count > 0 else 0,
                "클릭 수": click_count,
                "클릭률 (%)": round(click_rate, 1) if appearance_count > 0 else 0.0
            })
        
        if popularity_data:
            popularity_df = pd.DataFrame(popularity_data)
            popularity_df = popularity_df.sort_values("클릭 수", ascending=False)
            
            # 주요 메트릭
            col1, col2, col3 = st.columns(3)
            with col1:
                total_searches = len(search_events)
                st.metric("총 검색 실행", f"{total_searches:,}건")
            with col2:
                unique_news = len(news_appearances)
                st.metric("검색 결과에 포함된 뉴스", f"{unique_news:,}개")
            with col3:
                total_clicks = sum(news_clicks.values())
                st.metric("총 클릭 수", f"{total_clicks:,}건")
            
            # Top 10 인기 뉴스 (클릭 수 높은 순으로 정렬)
            top_10_df = popularity_df.head(10).copy()
            # 차트에서도 클릭 수 높은 순으로 표시되도록 정렬 (내림차순)
            top_10_df = top_10_df.sort_values("클릭 수", ascending=True)  # 차트는 아래에서 위로 올라가므로 오름차순
            
            if px is not None and len(top_10_df) > 0:
                fig = px.bar(
                    top_10_df,
                    x="클릭 수",
                    y="제목",
                    orientation='h',
                    title="검색 결과에서 가장 많이 클릭된 뉴스 Top 10",
                    labels={"클릭 수": "클릭 수", "제목": "뉴스 제목"},
                    hover_data=["검색 결과 포함", "클릭률 (%)"],
                    text="클릭 수"  # 막대 옆에 숫자 표시
                )
                fig.update_traces(texttemplate='%{text}건', textposition='outside')
                fig.update_layout(
                    height=500,
                    showlegend=False
                )
                st.plotly_chart(fig, use_container_width=True)
            
            # 전체 데이터는 expander로 숨김 처리 (필요시 펼쳐서 확인 가능)
            with st.expander("📋 전체 뉴스 클릭 데이터 보기", expanded=False):
                st.dataframe(popularity_df, use_container_width=True, height=400)
        else:
            st.info("📊 검색 결과 데이터가 없습니다.")

def _render_url_parsing_quality_for_content(df_view: pd.DataFrame):
    """콘텐츠 품질 탭용 URL 파싱 품질"""
    url_events = df_view[df_view["event_name"].isin(["news_url_added_from_chat", "news_url_add_error"])]
    
    if url_events.empty:
        st.info("📊 URL 파싱 이벤트가 없습니다.")
        return
    
    st.markdown("#### 📰 URL 파싱 품질 (크롤링/파싱 실패율)")
    
    # 이벤트 건수 (중복 포함)
    success_events = url_events[url_events["event_name"] == "news_url_added_from_chat"]
    error_events = url_events[url_events["event_name"] == "news_url_add_error"]
    success_count = len(success_events)
    error_count = len(error_events)
    total_count = success_count + error_count
    
    # 고유 URL 기준으로 카운트 (중복 제거) - payload에서 URL 추출 시도
    unique_urls_success = set()
    unique_urls_error = set()
    
    for idx, row in success_events.iterrows():
        payload = _parse_payload(row.get("payload"))
        if payload:
            url = payload.get("url") or payload.get("link") or payload.get("news_url")
            if url:
                unique_urls_success.add(str(url).strip())
    
    for idx, row in error_events.iterrows():
        payload = _parse_payload(row.get("payload"))
        if payload:
            url = payload.get("url") or payload.get("link") or payload.get("news_url") or payload.get("error_url")
            if url:
                unique_urls_error.add(str(url).strip())
    
    unique_success_count = len(unique_urls_success) if unique_urls_success else success_count
    unique_error_count = len(unique_urls_error) if unique_urls_error else error_count
    unique_total_count = unique_success_count + unique_error_count
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("파싱 성공", f"{unique_success_count:,}건")
        if success_count > unique_success_count:
            st.caption(f"이벤트 건수: {success_count:,}건")
    with col2:
        st.metric("파싱 실패", f"{unique_error_count:,}건")
        if error_count > unique_error_count:
            st.caption(f"이벤트 건수: {error_count:,}건")
    with col3:
        if unique_total_count > 0:
            failure_rate = (unique_error_count / unique_total_count) * 100
            st.metric("실패율", f"{failure_rate:.1f}%")
        else:
            st.metric("실패율", "N/A")
    
    # 참고 정보 표시
    if total_count > unique_total_count:
        st.info(f"💡 **참고**: 고유 URL {unique_total_count:,}개에 대해 총 {total_count:,}개의 파싱 이벤트가 발생했습니다. (같은 URL을 여러 번 파싱한 경우 포함)")
    
    # 시간대별 실패율 추이
    if total_count > 0:
        url_events_copy = url_events.copy()
        url_events_copy["hour"] = url_events_copy["event_time"].dt.floor("H")
        
        # 성공/실패별로 그룹화
        success_by_hour = url_events_copy[url_events_copy["event_name"] == "news_url_added_from_chat"].groupby("hour").size().reset_index(name="성공")
        error_by_hour = url_events_copy[url_events_copy["event_name"] == "news_url_add_error"].groupby("hour").size().reset_index(name="실패")
        
        # 병합
        hourly_stats = success_by_hour.merge(error_by_hour, on="hour", how="outer").fillna(0)
        
        if len(hourly_stats) > 0 and px is not None:
            hourly_stats["실패율"] = (hourly_stats["실패"] / (hourly_stats["성공"] + hourly_stats["실패"]) * 100).fillna(0)
            fig = px.line(
                hourly_stats,
                x="hour",
                y="실패율",
                title="시간대별 URL 파싱 실패율 추이"
            )
            st.plotly_chart(fig, use_container_width=True)

# ============================================================================
# 탭 3: 사용자 행동 데이터 (User Behavior)
# ============================================================================

def _render_user_behavior_tab(df_view: pd.DataFrame, session_column: str):
    """
    🟢 사용자 행동 데이터 탭: 핵심 지표만 표시
    - 뉴스 클릭률 (CTR)
    - 기사 읽기 시간 (Dwell Time, 평균)
    - Glossary 사용률
    - 질문(RAG) 사용률
    - 용어 클릭률
    - 뉴스 검색 사용률 / 검색 성공률 (간단 버전)
    - 재방문 세션 비율 (간단)
    """
    st.markdown("### 🟢 사용자 행동 데이터 (User Behavior)")
    st.markdown("**목표**: 사용자의 핵심 행동 패턴을 한눈에 파악")
    
    # 1. 뉴스 클릭률 (CTR)
    _render_news_ctr(df_view)
    
    # 2. 기사 읽기 시간 (Dwell Time, 평균)
    _render_dwell_time(df_view)
    
    # 3. Glossary 사용률
    _render_glossary_usage_rate(df_view, session_column)
    
    # 4. 질문(RAG) 사용률
    _render_rag_question_usage_rate(df_view, session_column)
    
    # 5. 용어 클릭률
    _render_term_clicks(df_view)
    
    # 6. 뉴스 검색 사용률 / 검색 성공률 (간단 버전)
    _render_search_usage_simple(df_view, session_column)
    
    # 7. 재방문 세션 비율 (간단)
    _render_returning_sessions_simple(df_view, session_column)

def _render_news_ctr(df_view: pd.DataFrame):
    """뉴스 클릭률 분석"""
    st.markdown("#### 📊 뉴스 클릭률 (CTR)")
    
    clicks = df_view[df_view["event_name"] == "news_click"]
    views = df_view[df_view["event_name"].isin(["news_click", "news_detail_open"])]
    
    if len(views) > 0:
        ctr = (len(clicks) / len(views)) * 100
        st.metric("클릭률", f"{ctr:.1f}%")
        
        # 시간대별 CTR
        if len(clicks) > 0:
            clicks["hour"] = clicks["event_time"].dt.floor("H")
            hourly_clicks = clicks.groupby("hour").size().reset_index(name="클릭 수")
            
            if px is not None and len(hourly_clicks) > 0:
                fig = px.bar(
                    hourly_clicks,
                    x="hour",
                    y="클릭 수",
                    title="시간대별 뉴스 클릭 수"
                )
                st.plotly_chart(fig, use_container_width=True)

def _render_dwell_time(df_view: pd.DataFrame):
    """기사 읽기 시간 분석 (평균만 표시)"""
    st.markdown("#### ⏱️ 기사 읽기 시간 (Dwell Time)")
    
    duration_data = []
    
    # 방법 1: view_duration 이벤트에서 duration_sec 추출
    view_duration_events = df_view[df_view["event_name"] == "view_duration"]
    for idx, row in view_duration_events.iterrows():
        payload = _parse_payload(row.get("payload"))
        duration_sec = payload.get("duration_sec")
        if duration_sec is not None:
            try:
                duration_data.append(float(duration_sec))
            except (ValueError, TypeError):
                pass
    
    # 방법 2: news_detail_back 이벤트의 payload에서 duration_sec 추출 (실제 사용되는 방법)
    detail_back_events = df_view[df_view["event_name"] == "news_detail_back"]
    for idx, row in detail_back_events.iterrows():
        payload = _parse_payload(row.get("payload"))
        if payload:
            duration_sec = payload.get("duration_sec")
            if duration_sec is not None:
                try:
                    duration_data.append(float(duration_sec))
                except (ValueError, TypeError):
                    pass
    
    # 방법 3: news_detail_open 이벤트의 payload에서 duration_sec 추출 (혹시 있을 경우)
    detail_open_events = df_view[df_view["event_name"] == "news_detail_open"]
    for idx, row in detail_open_events.iterrows():
        payload = _parse_payload(row.get("payload"))
        if payload:
            duration_sec = payload.get("duration_sec")
            if duration_sec is not None:
                try:
                    duration_data.append(float(duration_sec))
                except (ValueError, TypeError):
                    pass
    
    # 방법 4: 세션 내에서 news_detail_open과 news_detail_back 간의 시간 차이 계산
    if "session_id" in df_view.columns and "event_time" in df_view.columns:
        for session_id in df_view["session_id"].dropna().unique():
            session_events = df_view[df_view["session_id"] == session_id].sort_values("event_time")
            detail_open_events = session_events[session_events["event_name"] == "news_detail_open"]
            detail_back_events = session_events[session_events["event_name"] == "news_detail_back"]
            
            for open_idx in detail_open_events.index:
                open_time = session_events.loc[open_idx, "event_time"]
                open_news_id = session_events.loc[open_idx, "news_id"] if "news_id" in session_events.columns else None
                
                # 같은 news_id를 가진 news_detail_back 이벤트 찾기
                after_open = session_events.loc[session_events.index > open_idx]
                matching_back = after_open[
                    (after_open["event_name"] == "news_detail_back") &
                    (after_open["news_id"] == open_news_id if open_news_id else True)
                ]
                
                if not matching_back.empty:
                    back_time = matching_back.iloc[0]["event_time"]
                    duration = (back_time - open_time).total_seconds()
                    if duration > 0 and duration < 3600:  # 1시간 이내만 유효
                        duration_data.append(duration)
    
    if duration_data:
        avg_duration = sum(duration_data) / len(duration_data)
        st.metric("평균 읽기 시간", f"{avg_duration:.1f}초")
        st.caption(f"📊 분석된 읽기 시간 데이터: {len(duration_data)}건")
    else:
        st.info("📊 읽기 시간 데이터가 없습니다.")
        st.caption("💡 읽기 시간은 다음 방법으로 계산됩니다:")
        st.caption("   1. view_duration 이벤트의 duration_sec")
        st.caption("   2. news_detail_back 이벤트의 payload duration_sec (주요 방법)")
        st.caption("   3. news_detail_open과 news_detail_back 간의 시간 차이")

def _render_summary_clicks(df_view: pd.DataFrame):
    """요약 클릭률 분석"""
    # 요약 관련 이벤트가 있으면 분석
    summary_events = df_view[df_view["event_name"].str.contains("summary", case=False, na=False)]
    
    if summary_events.empty:
        return
    
    st.markdown("#### 📝 요약 클릭률")
    summary_clicks = len(summary_events)
    st.metric("요약 클릭", summary_clicks)

def _render_term_clicks(df_view: pd.DataFrame):
    """용어 클릭률"""
    # Glossary 클릭만 집계 (용어 클릭률)
    glossary_clicks = df_view[df_view["event_name"] == "glossary_click"].copy()
    
    if glossary_clicks.empty:
        st.markdown("#### 💡 용어 클릭률")
        st.info("📊 Glossary 클릭 데이터가 없습니다.")
        return
    
    st.markdown("#### 💡 용어 클릭률")
    
    # 용어 클릭률 계산
    total_news_clicks = len(df_view[df_view["event_name"] == "news_click"])
    glossary_click_count = len(glossary_clicks)
    term_ctr = (glossary_click_count / total_news_clicks * 100) if total_news_clicks > 0 else 0
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Glossary 클릭 수", glossary_click_count)
    with col2:
        st.metric("용어 클릭률", f"{term_ctr:.1f}%")

def _render_glossary_usage_rate(df_view: pd.DataFrame, session_column: str):
    """Glossary 사용률"""
    if session_column not in df_view.columns:
        return
    
    st.markdown("#### 📚 Glossary 사용률")
    
    glossary_sessions = set(df_view[df_view["event_name"] == "glossary_click"][session_column].dropna().unique())
    total_sessions = df_view[session_column].nunique() if session_column in df_view.columns else 1
    glossary_usage_count = len(glossary_sessions)
    glossary_usage_rate = (glossary_usage_count / total_sessions * 100) if total_sessions > 0 else 0
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Glossary 사용 세션", glossary_usage_count)
    with col2:
        st.metric("Glossary 사용률", f"{glossary_usage_rate:.1f}%")

def _render_rag_question_usage_rate(df_view: pd.DataFrame, session_column: str):
    """질문(RAG) 사용률"""
    if session_column not in df_view.columns:
        return
    
    st.markdown("#### ❓ 질문(RAG) 사용률")
    
    rag_chat_question_sessions = _get_rag_chat_question_sessions(df_view, session_column)
    total_sessions = df_view[session_column].nunique() if session_column in df_view.columns else 1
    question_usage_count = len(rag_chat_question_sessions)
    question_usage_rate = (question_usage_count / total_sessions * 100) if total_sessions > 0 else 0
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("질문(RAG) 사용 세션", question_usage_count)
    with col2:
        st.metric("질문(RAG) 사용률", f"{question_usage_rate:.1f}%")

def _render_search_usage_simple(df_view: pd.DataFrame, session_column: str):
    """뉴스 검색 사용률 / 검색 성공률 (간단 버전)"""
    if session_column not in df_view.columns:
        return
    
    st.markdown("#### 🔍 뉴스 검색 사용률 / 검색 성공률")
    
    # 검색 사용 세션
    search_sessions = set(df_view[df_view["event_name"] == "news_search_from_chat"][session_column].dropna().unique())
    total_sessions = df_view[session_column].nunique() if session_column in df_view.columns else 1
    search_usage_count = len(search_sessions)
    search_usage_rate = (search_usage_count / total_sessions * 100) if total_sessions > 0 else 0
    
    # 검색 성공률
    search_success = df_view[df_view["event_name"] == "news_search_from_chat"]
    search_failed = df_view[df_view["event_name"] == "news_search_failed"]
    success_count = len(search_success)
    failed_count = len(search_failed)
    total_search_attempts = success_count + failed_count
    success_rate = (success_count / total_search_attempts * 100) if total_search_attempts > 0 else 0
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("검색 사용 세션", search_usage_count)
        st.caption(f"사용률: {search_usage_rate:.1f}%")
    with col2:
        st.metric("검색 성공", success_count)
    with col3:
        st.metric("검색 성공률", f"{success_rate:.1f}%")

def _render_returning_sessions_simple(df_view: pd.DataFrame, session_column: str):
    """재방문 세션 비율 (간단 버전)"""
    if session_column not in df_view.columns or "user_id" not in df_view.columns:
        return
    
    st.markdown("#### 🔄 재방문 세션 비율")
    
    user_sessions = df_view.groupby("user_id")[session_column].nunique().reset_index()
    user_sessions.columns = ["user_id", "세션 수"]
    
    total_users = len(user_sessions)
    returning_users = len(user_sessions[user_sessions["세션 수"] > 1])
    return_rate = (returning_users / total_users * 100) if total_users > 0 else 0
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("총 사용자", total_users)
    with col2:
        st.metric("재방문 사용자", returning_users)
        st.caption(f"재방문률: {return_rate:.1f}%")


# ============================================================================
# Log Viewer 탭
# ============================================================================

def _render_log_viewer_tab(df_view: pd.DataFrame, session_column: str):
    """
    📁 Log Viewer 탭
    → 상세 이벤트 로그 뷰어
    """
    st.markdown("### 📁 Log Viewer")
    st.markdown("**목적**: 상세 이벤트 로그 확인 및 분석")
    
    # 필터 옵션
    col1, col2, col3 = st.columns(3)
    with col1:
        event_filter = st.multiselect(
            "이벤트 필터",
            options=sorted(df_view["event_name"].unique()) if "event_name" in df_view.columns else [],
            default=[],
            key="log_viewer_event_filter"
        )
    with col2:
        user_filter = st.text_input(
            "사용자 ID 필터",
            value="",
            key="log_viewer_user_filter"
        )
    with col3:
        limit = st.number_input(
            "표시할 로그 수",
            min_value=10,
            max_value=1000,
            value=100,
            step=10,
            key="log_viewer_limit"
        )
    
    # 필터 적용
    filtered_df = df_view.copy()
    
    if event_filter:
        filtered_df = filtered_df[filtered_df["event_name"].isin(event_filter)]
    
    if user_filter:
        filtered_df = filtered_df[filtered_df["user_id"].astype(str).str.contains(user_filter, case=False, na=False)]
    
    # 최신순 정렬
    filtered_df = filtered_df.sort_values("event_time", ascending=False).head(limit)
    
    # 통계
    st.markdown("#### 📊 로그 통계")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("총 로그 수", f"{len(df_view):,}건")
    with col2:
        st.metric("필터된 로그", f"{len(filtered_df):,}건")
    with col3:
        unique_events = filtered_df["event_name"].nunique() if "event_name" in filtered_df.columns else 0
        st.metric("고유 이벤트", f"{unique_events}개")
    with col4:
        unique_users = filtered_df["user_id"].nunique() if "user_id" in filtered_df.columns else 0
        st.metric("고유 사용자", f"{unique_users}명")
    
    st.markdown("---")
    
    # 로그 테이블
    st.markdown("#### 📋 이벤트 로그")
    
    # 표시할 컬럼 선택
    display_cols = ["event_time", "event_name", "user_id", session_column]
    if "news_id" in filtered_df.columns:
        display_cols.append("news_id")
    if "term" in filtered_df.columns:
        display_cols.append("term")
    if "message" in filtered_df.columns:
        display_cols.append("message")
    if "latency_ms" in filtered_df.columns:
        display_cols.append("latency_ms")
    
    # 존재하는 컬럼만 선택
    available_cols = [col for col in display_cols if col in filtered_df.columns]
    
    if len(filtered_df) > 0:
        st.dataframe(
            filtered_df[available_cols],
            use_container_width=True,
            height=600
        )
        
        # Payload 상세 보기 (선택적)
        if st.checkbox("Payload 상세 보기", key="log_viewer_show_payload"):
            st.markdown("#### 🔍 Payload 상세")
            selected_index = st.selectbox(
                "로그 선택",
                options=range(len(filtered_df)),
                format_func=lambda x: f"{filtered_df.iloc[x]['event_time']} - {filtered_df.iloc[x]['event_name']}" if x < len(filtered_df) else ""
            )
            
            if selected_index < len(filtered_df):
                selected_row = filtered_df.iloc[selected_index]
                payload = _parse_payload(selected_row.get("payload"))
                if payload:
                    st.json(payload)
                else:
                    st.info("Payload가 없습니다.")
    else:
        st.info("📭 필터 조건에 맞는 로그가 없습니다.")

# ============================================================================
# KPI 대시보드
# ============================================================================

def _render_kpi_dashboard(df_view: pd.DataFrame, session_column: str):
    """
    📊 KPI 대시보드 메인 페이지
    → "금융 초보자의 뉴스 이해"를 돕는 서비스의 핵심 지표 모니터링
    """
    st.markdown("#### 📊 KPI 대시보드 요약")
    st.markdown("**핵심 질문**: 사용자는 실제로 뉴스를 읽고 있는가? 용어/Glossary 기능은 이해를 돕고 있는가? 챗봇은 진짜 사용되는가? 성능은 UX를 망치지 않는가?")
    
    # 날짜 필터
    selected_start_date = None
    selected_end_date = None
    date_range_days = None
    
    if "event_time" in df_view.columns and not df_view.empty:
        df_view = df_view.copy()
        df_view["date"] = pd.to_datetime(df_view["event_time"]).dt.date
        df_view["datetime"] = pd.to_datetime(df_view["event_time"])
        df_view["hour"] = df_view["datetime"].dt.hour
        
        min_date = df_view["date"].min()
        max_date = df_view["date"].max()
        
        if min_date and max_date:
            date_range = st.date_input(
                "기간 선택",
                value=(min_date, max_date),
                min_value=min_date,
                max_value=max_date,
                key="kpi_date_range"
            )
            
            if isinstance(date_range, tuple) and len(date_range) == 2:
                selected_start_date, selected_end_date = date_range
                df_view = df_view[(df_view["date"] >= selected_start_date) & (df_view["date"] <= selected_end_date)]
                date_range_days = (selected_end_date - selected_start_date).days + 1
    
    # ========== A. 상단 Summary (메트릭 카드 9개) ==========
    st.markdown("#### 📈 핵심 지표 요약")
    
    # 1. DAU / WAU 계산 (한국 시간 기준)
    # DAU: 오늘 날짜에 이벤트를 발생시킨 고유 사용자 수
    # WAU: 최근 7일간 이벤트를 발생시킨 고유 사용자 수
    # 주의: 날짜 필터가 적용된 경우에도 전체 기간 기준으로 계산
    if "user_id" in df_view.columns and "date" in df_view.columns:
        # 원본 데이터에서 날짜 컬럼이 있는지 확인 (필터링 전)
        # 한국 시간 기준으로 오늘 날짜 계산
        today_kst = pd.Timestamp.now(tz="Asia/Seoul").date()
        week_ago = today_kst - pd.Timedelta(days=7)
        
        # DAU: 오늘 날짜의 고유 사용자 수 (필터링된 df_view 기준)
        dau = df_view[df_view["date"] == today_kst]["user_id"].nunique()
        
        # WAU: 최근 7일간 고유 사용자 수
        # 날짜 필터가 적용된 경우, 필터 범위 내에서만 계산
        # 하지만 원본 데이터 전체를 사용하려면 render 함수에서 전체 데이터를 전달해야 함
        wau_df = df_view[df_view["date"] >= week_ago]
        wau = wau_df["user_id"].nunique()
        
        # 디버깅 정보 (확장 가능한 섹션에 표시)
        with st.expander("🔍 DAU/WAU 계산 상세 정보", expanded=False):
            st.markdown(f"**계산 기준 날짜**: {today_kst}")
            st.markdown(f"**7일 전 날짜**: {week_ago}")
            st.markdown(f"**데이터 범위**: {df_view['date'].min()} ~ {df_view['date'].max()}")
            st.markdown(f"**필터링된 데이터 건수**: {len(df_view):,}건")
            st.markdown(f"**최근 7일 데이터 건수**: {len(wau_df):,}건")
            st.markdown(f"**전체 고유 user_id 수**: {df_view['user_id'].nunique()}명")
            st.markdown(f"**최근 7일 고유 user_id 수**: {wau}명")
            
            # user_id 목록 표시 (상위 20개)
            if wau > 0:
                st.markdown("**최근 7일 활동 user_id 목록 (상위 20개)**:")
                user_counts = wau_df.groupby("user_id").size().sort_values(ascending=False).head(20)
                st.dataframe(user_counts.reset_index().rename(columns={0: "이벤트 수", "user_id": "User ID"}), use_container_width=True)
                
                st.info("💡 **참고**: user_id는 브라우저 localStorage에 저장됩니다. 로컬(`localhost`)과 배포 사이트는 다른 도메인이므로 각각 다른 user_id가 생성됩니다. 같은 사용자가 로컬과 배포 사이트에서 접속하면 2개의 user_id로 집계됩니다.")
    else:
        dau = 0
        wau = 0
    
    # 2. 평균 세션 길이 계산
    # 각 세션의 첫 이벤트와 마지막 이벤트 시간 차이를 계산하여 평균
    if session_column in df_view.columns and "event_time" in df_view.columns:
        session_durations = []
        for session_id in df_view[session_column].dropna().unique():
            session_events = df_view[df_view[session_column] == session_id]
            if len(session_events) > 1:
                session_start = session_events["event_time"].min()
                session_end = session_events["event_time"].max()
                duration = (session_end - session_start).total_seconds() / 60  # 분 단위
                if duration > 0:
                    session_durations.append(duration)
        avg_session_length = sum(session_durations) / len(session_durations) if session_durations else 0
    else:
        avg_session_length = 0
    
    # 3. 세션당 뉴스 클릭 수
    news_clicks = int((df_view["event_name"] == "news_click").sum())
    total_sessions = df_view[session_column].nunique() if session_column in df_view.columns else 1
    news_clicks_per_session = news_clicks / total_sessions if total_sessions > 0 else 0
    
    # 4. Glossary 사용률 (Glossary 클릭만)
    glossary_sessions = set(df_view[df_view["event_name"] == "glossary_click"][session_column].dropna().unique()) if session_column in df_view.columns else set()
    glossary_usage_count = len(glossary_sessions)
    glossary_usage_rate = (glossary_usage_count / total_sessions * 100) if total_sessions > 0 else 0
    
    # 5. 질문 사용률 (RAG 질문만)
    rag_chat_question_sessions = _get_rag_chat_question_sessions(df_view, session_column)
    question_usage_count = len(rag_chat_question_sessions)
    question_usage_rate = (question_usage_count / total_sessions * 100) if total_sessions > 0 else 0
    
    # 6. 신규/재방문 비율
    if "user_id" in df_view.columns and session_column in df_view.columns:
        # 각 사용자의 첫 세션 찾기
        user_first_sessions = {}
        for idx, row in df_view.iterrows():
            user_id = row.get("user_id")
            session_id = row.get(session_column)
            if user_id and session_id:
                if user_id not in user_first_sessions:
                    user_first_sessions[user_id] = session_id
        
        # 신규 사용자: 첫 세션이 현재 기간 내에 있는 사용자
        new_users = set(user_first_sessions.keys())
        new_user_sessions = set(user_first_sessions.values())
        new_session_count = len(new_user_sessions & set(df_view[session_column].dropna().unique()))
        
        # 재방문 사용자: 첫 세션이 현재 기간 이전에 있는 사용자
        returning_session_count = total_sessions - new_session_count
        new_return_rate = (new_session_count / total_sessions * 100) if total_sessions > 0 else 0
        returning_rate = (returning_session_count / total_sessions * 100) if total_sessions > 0 else 0
    else:
        new_session_count = 0
        returning_session_count = 0
        new_return_rate = 0
        returning_rate = 0
    
    # 메트릭 카드 표시 (핵심 15개 지표 중 KPI/Usage 부분)
    st.markdown("##### 🔵 KPI / Usage")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("DAU", f"{dau}명")
        st.metric("WAU", f"{wau}명")
    with col2:
        st.metric("신규 세션", f"{new_session_count}개")
        st.caption(f"신규 비율: {new_return_rate:.1f}%")
        st.metric("재방문 세션", f"{returning_session_count}개")
        st.caption(f"재방문 비율: {returning_rate:.1f}%")
    with col3:
        st.metric("세션당 뉴스 클릭", f"{news_clicks_per_session:.1f}건")
        st.metric("Glossary 사용률", f"{glossary_usage_rate:.1f}%")
    with col4:
        st.metric("질문 사용률", f"{question_usage_rate:.1f}%")
    
    st.markdown("---")
    
    # ========== B. 시간대별 뉴스 클릭 추이 ==========
    st.markdown("#### 📈 시간대별 뉴스 클릭 추이")
    
    if "date" in df_view.columns and "hour" in df_view.columns and px is not None:
        # 시간대별 뉴스 클릭 추이
        hourly_news_clicks = df_view[df_view["event_name"] == "news_click"].groupby("hour").size().reset_index(name="클릭 수")
        
        if len(hourly_news_clicks) > 0:
            hourly_news_clicks = hourly_news_clicks.sort_values("hour")
            
            fig1 = px.line(
                hourly_news_clicks,
                x="hour",
                y="클릭 수",
                title="시간대별 뉴스 클릭 추이",
                labels={"hour": "시간 (시)", "클릭 수": "클릭 수"}
            )
            fig1.update_xaxes(tickmode='linear', tick0=0, dtick=3, tickformat='%H시')
            st.plotly_chart(fig1, use_container_width=True)
    
    st.markdown("---")
    
    # ========== C. 행동 흐름 (Funnel Chart) ==========
    st.markdown("#### 🔽 행동 흐름 분석")
    
    # ========== 퍼널 1: 뉴스 기반 이해 퍼널 (News-based Understanding Funnel) ==========
    # 목적: 초보자가 뉴스를 얼마나 '이해'했는가 측정
    # 뉴스 클릭 → Glossary 클릭 → 질문 → 재탐색
    st.markdown("##### 1️⃣ 뉴스 기반 이해 퍼널 (뉴스 클릭 → Glossary 클릭 → 질문 → 재탐색)")
    st.caption("**목적**: 홈 화면에서 추천 뉴스를 본 사용자의 학습 흐름 분석")
    st.caption("**참고**: Glossary 클릭(용어 학습)과 질문(뉴스 이해)을 분리하여 분석합니다.")
    
    # 홈에서 뉴스 클릭한 세션 (검색이 아닌 직접 클릭)
    # source가 "list" 또는 "home"인 news_click만 포함 (검색 결과에서 온 것은 제외)
    home_news_clicks = df_view[
        (df_view["event_name"] == "news_click") &
        (df_view["source"].isin(["list", "home", ""]) | df_view["source"].isna())
    ]
    news_click_sessions = home_news_clicks[session_column].nunique() if session_column in home_news_clicks.columns and not home_news_clicks.empty else 0
    
    if news_click_sessions > 0:
        # 각 이벤트별 세션 집합 생성
        news_sessions = set(home_news_clicks[session_column].dropna().unique())
        
        # 2단계: Glossary 클릭 (용어 학습)
        glossary_sessions = set(df_view[df_view["event_name"] == "glossary_click"][session_column].dropna().unique())
        glossary_after_news = len(news_sessions & glossary_sessions)
        
        # 3단계: 질문 (뉴스 이해 질문)
        # 뉴스 클릭 이후 발생한 chat_question만 포함 (RAG 여부, 출처 무관)
        # 어느 뉴스 뒤라도 질문을 한 세션을 잡기 위해 첫 번째 뉴스 이후를 기준으로 확인
        question_sessions = set()
        for session_id in news_sessions:
            session_events = df_view[df_view[session_column] == session_id].sort_values("event_time")
            # 뉴스 클릭 이후 질문 확인 (첫 번째 뉴스 클릭 이후 발생한 chat_question만)
            news_click_indices = session_events[session_events["event_name"] == "news_click"].index
            if len(news_click_indices) > 0:
                first_news_idx = news_click_indices[0]
                after_first_news = session_events.loc[session_events.index > first_news_idx]
                # 첫 번째 뉴스 클릭 이후 chat_question 발생 확인 (RAG 여부 무관)
                if (after_first_news["event_name"] == "chat_question").any():
                    question_sessions.add(session_id)
        question_count = len(question_sessions)
        
        # 4단계: 재탐색 (질문 또는 Glossary 클릭 이후 다시 뉴스 클릭)
        re_explore_sessions = set()
        for session_id in news_sessions:
            session_events = df_view[df_view[session_column] == session_id].sort_values("event_time")
            # Glossary 클릭 또는 질문 이후 재탐색 확인
            glossary_indices = session_events[session_events["event_name"] == "glossary_click"].index
            question_indices = session_events[session_events["event_name"] == "chat_question"].index
            
            # 마지막 Glossary 클릭 또는 질문 찾기
            last_interaction_idx = None
            if len(glossary_indices) > 0:
                last_interaction_idx = max(glossary_indices.tolist())
            if len(question_indices) > 0:
                last_question_idx = max(question_indices.tolist())
                if last_interaction_idx is None or last_question_idx > last_interaction_idx:
                    last_interaction_idx = last_question_idx
            
            if last_interaction_idx is not None:
                after_interaction = session_events.loc[session_events.index > last_interaction_idx]
                if len(after_interaction) > 0:
                    has_re_explore = (
                        (after_interaction["event_name"] == "news_click").any() or
                        (after_interaction["event_name"] == "news_search_from_chat").any()
                    )
                    if has_re_explore:
                        re_explore_sessions.add(session_id)
        re_explore_count = len(re_explore_sessions)
        
        # 전환율 계산
        glossary_rate = (glossary_after_news / news_click_sessions * 100) if news_click_sessions > 0 else 0
        question_rate = (question_count / news_click_sessions * 100) if news_click_sessions > 0 else 0
        re_explore_rate = (re_explore_count / news_click_sessions * 100) if news_click_sessions > 0 else 0
        
        funnel1_data = pd.DataFrame({
            "단계": ["뉴스 클릭", "Glossary 클릭", "질문", "재탐색"],
            "세션 수": [news_click_sessions, glossary_after_news, question_count, re_explore_count],
            "전환율 (%)": [100.0, glossary_rate, question_rate, re_explore_rate]
        })
        
        st.dataframe(funnel1_data, use_container_width=True)
        
        if px is not None:
            fig1 = px.funnel(
                funnel1_data,
                x="세션 수",
                y="단계",
                title="뉴스 기반 이해 퍼널 (뉴스 → 용어 → 질문 → 재탐색)"
            )
            st.plotly_chart(fig1, use_container_width=True)
        
        # 핵심 지표 강조
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Glossary 사용률", f"{glossary_rate:.1f}%", 
                     help="뉴스 클릭 후 용어 학습 비율")
        with col2:
            st.metric("질문 비율", f"{question_rate:.1f}%",
                     help="뉴스 클릭 후 질문 비율")
        with col3:
            st.metric("재탐색율", f"{re_explore_rate:.1f}%",
                     help="학습 후 추가 탐색으로 이어졌는지")
    
    # ========== 퍼널 2: 챗봇 기반 탐색 퍼널 (Chatbot-based Exploration Funnel) ==========
    # 목적: 챗봇을 통한 탐색 기능이 얼마나 도움이 되는지 측정
    # 질문 → 챗봇 응답 → 추천 뉴스 클릭 → Glossary 클릭 → 추가 질문
    st.markdown("---")
    st.markdown("##### 2️⃣ 챗봇 기반 탐색 퍼널 (질문 → 챗봇 응답 → 추천 뉴스 클릭 → Glossary 클릭 → 추가 질문)")
    st.caption("**목적**: 챗봇을 통한 탐색 기능의 효과성 및 추천 뉴스 품질 평가")
    st.caption("**참고**: 챗봇이 추천한 뉴스를 클릭한 후의 학습 흐름을 분석합니다.")
    
    # 1단계: 질문 시작 (chat_question)
    # chat_question 중에서 이후 chat_response가 발생한 것만 (RAG 질문만 제외)
    # 같은 세션 내에 일반 질문과 RAG 질문이 섞여 있어도 일반 질문이 있으면 포함
    all_chat_questions = df_view[df_view["event_name"] == "chat_question"].copy()
    question_sessions = set()
    
    for session_id in all_chat_questions[session_column].dropna().unique():
        session_events = df_view[df_view[session_column] == session_id].sort_values("event_time")
        chat_question_indices = list(session_events[session_events["event_name"] == "chat_question"].index)
        
        for i, chat_idx in enumerate(chat_question_indices):
            # 이 질문의 '끝'을 다음 질문 직전까지로 설정 (해당 질문만의 윈도우)
            if i < len(chat_question_indices) - 1:
                end_idx = chat_question_indices[i + 1]
                window = session_events.loc[(session_events.index > chat_idx) & (session_events.index < end_idx)]
            else:
                # 마지막 질문인 경우 세션 끝까지
                window = session_events.loc[session_events.index > chat_idx]
            
            # RAG 질문인지 확인 (해당 질문 윈도우 내에서 glossary_answer 발생)
            has_glossary_answer = (window["event_name"] == "glossary_answer").any()
            # 일반 질문인지 확인 (해당 질문 윈도우 내에서 chat_response 발생)
            has_chat_response = (window["event_name"] == "chat_response").any()
            
            # 일반 질문이고, RAG 질문이 아닌 경우만 질문으로 간주
            if has_chat_response and not has_glossary_answer:
                question_sessions.add(session_id)
                break  # 한 세션에 여러 질문이 있어도 한 번만 추가
    
    question_count = len(question_sessions)
    
    if question_count > 0:
        # 2단계: 챗봇 응답 (chat_response)
        chat_response_sessions = set()
        for session_id in question_sessions:
            session_events = df_view[df_view[session_column] == session_id].sort_values("event_time")
            chat_question_indices = session_events[session_events["event_name"] == "chat_question"].index
            
            for chat_idx in chat_question_indices:
                after_chat = session_events.loc[session_events.index > chat_idx]
                chat_responses = after_chat[after_chat["event_name"] == "chat_response"]
                
                if len(chat_responses) > 0:
                    chat_response_sessions.add(session_id)
                    break
        
        chat_response_count = len(chat_response_sessions)
        
        # 3단계: 추천 뉴스 클릭 (news_click source="chat" 또는 news_selected_from_chat)
        # chat_response 이후에 챗봇이 추천한 뉴스를 클릭한 세션
        news_click_sessions = set()
        for session_id in chat_response_sessions:
            session_events = df_view[df_view[session_column] == session_id].sort_values("event_time")
            chat_response_indices = session_events[session_events["event_name"] == "chat_response"].index
            
            for resp_idx in chat_response_indices:
                after_response = session_events.loc[session_events.index > resp_idx]
                # news_click (source="chat") 또는 news_selected_from_chat 발생
                has_news_click = (
                    ((after_response["event_name"] == "news_click") & (after_response["source"] == "chat")).any() or
                    (after_response["event_name"] == "news_selected_from_chat").any()
                )
                if has_news_click:
                    news_click_sessions.add(session_id)
                    break
        
        news_click_count = len(news_click_sessions)
        
        # 4단계: Glossary 클릭
        glossary_sessions = set(df_view[df_view["event_name"] == "glossary_click"][session_column].dropna().unique())
        glossary_after_news = len(news_click_sessions & glossary_sessions)
        
        # 5단계: 추가 질문 (chat_question - 뉴스 클릭 이후 질문)
        # 뉴스 클릭 이후에 질문이 발생한 세션 (RAG 질문 여부와 관계없이)
        additional_question_sessions = set()
        for session_id in news_click_sessions:
            session_events = df_view[df_view[session_column] == session_id].sort_values("event_time")
            # 뉴스 클릭 이후 질문 확인
            news_click_indices = session_events[
                ((session_events["event_name"] == "news_click") & (session_events["source"] == "chat")) |
                (session_events["event_name"] == "news_selected_from_chat")
            ].index
            if len(news_click_indices) > 0:
                last_news_idx = news_click_indices[-1]
                after_news = session_events.loc[session_events.index > last_news_idx]
                # chat_question 발생 확인
                if (after_news["event_name"] == "chat_question").any():
                    additional_question_sessions.add(session_id)
        additional_question_count = len(additional_question_sessions)
        
        # 전환율 계산
        response_rate = (chat_response_count / question_count * 100) if question_count > 0 else 0
        news_click_rate = (news_click_count / chat_response_count * 100) if chat_response_count > 0 else 0
        glossary_rate = (glossary_after_news / news_click_count * 100) if news_click_count > 0 else 0
        additional_question_rate = (additional_question_count / news_click_count * 100) if news_click_count > 0 else 0
        
        funnel2_data = pd.DataFrame({
            "단계": ["질문", "챗봇 응답", "추천 뉴스 클릭", "Glossary 클릭", "추가 질문"],
            "세션 수": [question_count, chat_response_count, news_click_count, glossary_after_news, additional_question_count],
            "전환율 (%)": [100.0, response_rate, news_click_rate, glossary_rate, additional_question_rate]
        })
        
        st.dataframe(funnel2_data, use_container_width=True)
        
        if px is not None:
            fig2 = px.funnel(
                funnel2_data,
                x="세션 수",
                y="단계",
                title="챗봇 기반 탐색 퍼널 (질문 → 뉴스를 통한 학습 흐름)"
            )
            st.plotly_chart(fig2, use_container_width=True)
        
        # 핵심 지표 강조
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("추천 뉴스 클릭률", f"{news_click_rate:.1f}%",
                     help="챗봇 응답 후 추천 뉴스 클릭률")
        with col2:
            st.metric("Glossary 사용률", f"{glossary_rate:.1f}%",
                     help="뉴스 클릭 후 Glossary 사용률")
        with col3:
            st.metric("추가 질문 비율", f"{additional_question_rate:.1f}%",
                     help="뉴스 클릭 후 추가 질문 비율")
    
    # ========== 퍼널 3: 전체 학습 여정 퍼널 (Overall Learning Journey) ==========
    # 목적: 전체 서비스 사용 흐름 분석
    # 진입 → 뉴스/검색 중 선택 → 뉴스 탐색 → Glossary/질문 (RAG 사용) → 재탐색
    st.markdown("---")
    st.markdown("##### 3️⃣ 전체 학습 여정 퍼널 (Overall Learning Journey)")
    st.caption("**목적**: 전체 서비스 사용 흐름 및 학습 여정 분석")
    st.caption("**참고**: Glossary 클릭과 챗봇 질문은 모두 RAG를 사용하므로 하나로 묶어서 분석합니다. 응답/해설은 질문이 들어오면 100% 생성되므로 퍼널에서 제외합니다.")
    
    # 전체 세션 수
    total_sessions = df_view[session_column].nunique() if session_column in df_view.columns else 0
    
    if total_sessions > 0:
        all_sessions = set(df_view[session_column].dropna().unique())
        
        # 1단계: 진입 (세션 시작)
        entry_sessions = total_sessions
        
        # 2단계: 뉴스/챗봇 시작
        # 첫 뉴스 클릭 또는 첫 챗봇 질문 (성격과 무관하게)
        news_sessions_all = set(df_view[df_view["event_name"] == "news_click"][session_column].dropna().unique())
        # 첫 챗봇 질문으로 시작한 세션 (RAG 여부, 링크 여부 무관)
        chat_question_sessions = set(df_view[df_view["event_name"] == "chat_question"][session_column].dropna().unique())
        news_or_chat_sessions = news_sessions_all | chat_question_sessions
        selected_path_count = len(news_or_chat_sessions)
        
        # 3단계: 뉴스 탐색 (뉴스 클릭 또는 상세 열기)
        news_explore_sessions = set(df_view[df_view["event_name"].isin(["news_click", "news_detail_open"])][session_column].dropna().unique())
        news_explore_count = len(news_explore_sessions & news_or_chat_sessions)
        
        # 4단계: Glossary/질문 (RAG 사용)
        glossary_all_sessions = set(df_view[df_view["event_name"] == "glossary_click"][session_column].dropna().unique())
        rag_chat_question_all_sessions = _get_rag_chat_question_sessions(df_view, session_column)
        rag_usage_all_sessions = glossary_all_sessions | rag_chat_question_all_sessions  # Glossary 또는 RAG 질문
        # 2단계에서 시작한 사용자들 중 → 3단계 → 4단계로 간 비율을 정확히 보기 위해 세 집합 모두 교집합
        rag_usage_count = len(rag_usage_all_sessions & news_explore_sessions & news_or_chat_sessions)
        
        # 5단계: 재탐색 (Glossary/질문 이후 다시 뉴스 클릭 또는 검색)
        re_explore_all = set()
        for session_id in rag_usage_all_sessions & news_explore_sessions:
            session_events = df_view[df_view[session_column] == session_id].sort_values("event_time")
            # Glossary/질문 이벤트 찾기 (RAG 질문만)
            glossary_indices = session_events[session_events["event_name"] == "glossary_click"].index
            rag_chat_indices = session_events[
                (session_events["event_name"] == "chat_question") & 
                (session_events[session_column] == session_id)
            ].index
            # RAG 챗봇 질문인지 확인 (이후 glossary_answer가 있는지)
            rag_chat_valid_indices = []
            for chat_idx in rag_chat_indices:
                after_chat = session_events.loc[session_events.index > chat_idx]
                if (after_chat["event_name"] == "glossary_answer").any():
                    rag_chat_valid_indices.append(chat_idx)
            rag_indices = glossary_indices.tolist() + rag_chat_valid_indices
            if len(rag_indices) > 0:
                last_rag_idx = max(rag_indices)
                after_rag = session_events.loc[session_events.index > last_rag_idx]
                if len(after_rag) > 0:
                    has_re_explore = (
                        (after_rag["event_name"] == "news_click").any() or
                        (after_rag["event_name"] == "news_search_from_chat").any()
                    )
                    if has_re_explore:
                        re_explore_all.add(session_id)
        re_explore_all_count = len(re_explore_all)
        
        # 전환율 계산
        path_selection_rate = (selected_path_count / entry_sessions * 100) if entry_sessions > 0 else 0
        news_explore_rate = (news_explore_count / selected_path_count * 100) if selected_path_count > 0 else 0
        rag_usage_journey_rate = (rag_usage_count / news_explore_count * 100) if news_explore_count > 0 else 0
        re_explore_journey_rate = (re_explore_all_count / rag_usage_count * 100) if rag_usage_count > 0 else 0
        
        funnel3_data = pd.DataFrame({
            "단계": ["진입", "뉴스/챗봇 시작", "뉴스 탐색", "Glossary/질문 (RAG)", "재탐색"],
            "세션 수": [entry_sessions, selected_path_count, news_explore_count, rag_usage_count, re_explore_all_count],
            "전환율 (%)": [100.0, path_selection_rate, news_explore_rate, rag_usage_journey_rate, re_explore_journey_rate]
        })
        
        st.dataframe(funnel3_data, use_container_width=True)
        
        if px is not None:
            fig3 = px.funnel(
                funnel3_data,
                x="세션 수",
                y="단계",
                title="전체 학습 여정 퍼널 (Overall Learning Journey)"
            )
            st.plotly_chart(fig3, use_container_width=True)
    


# ============================================================================
# 뉴스 카테고리 및 키워드 분석 패널 (5개)
# ============================================================================

def _render_category_distribution_for_prompt(news_df: pd.DataFrame):
    """
    1️⃣ 카테고리별 분포 (프롬프트 개선 검증용)
    LLM 분류 결과가 균형 있게 나오는지 확인
    basic_concept, macro_market, major_industry, investment_basic 등
    """
    if news_df.empty:
        return
    
    if "primary_category" not in news_df.columns:
        st.info("📊 primary_category 컬럼이 없습니다.")
        return
    
    st.markdown("##### 1️⃣ 카테고리별 분포 (LLM 분류 결과 검증)")
    
    # primary_category가 NULL이 아닌 데이터만 필터링
    valid_categories = news_df[news_df["primary_category"].notna() & (news_df["primary_category"] != "")]
    
    if valid_categories.empty:
        st.info("📊 카테고리 데이터가 없습니다.")
        return
    
    total_count = len(valid_categories)
    
    # 카테고리별 개수 집계
    category_counts = valid_categories["primary_category"].value_counts()
    
    # 초보자 뉴스 카테고리 매핑 (프롬프트 개선 검증용)
    beginner_categories = {
        "basic_concept": "기초 개념",
        "macro_market": "거시 시장",
        "major_industry": "주요 산업",
        "investment_basic": "투자 기초"
    }
    
    # 기타 카테고리도 포함
    all_categories = {}
    for cat in category_counts.index:
        if cat in beginner_categories:
            all_categories[cat] = beginner_categories[cat]
        else:
            all_categories[cat] = cat
    
    # 카테고리별 건수 및 비율 계산
    category_data = []
    for cat, count in category_counts.items():
        category_data.append({
            "카테고리": all_categories.get(cat, cat),
            "건수": count,
            "비율 (%)": round((count / total_count) * 100, 1) if total_count > 0 else 0
        })
    
    category_df = pd.DataFrame(category_data).sort_values("건수", ascending=False)
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Bar 차트
        if px is not None:
            fig_bar = px.bar(
                category_df,
                x="카테고리",
                y="건수",
                title="카테고리별 수집 건수",
                labels={"카테고리": "카테고리", "건수": "건수"},
                text="건수"
            )
            fig_bar.update_traces(texttemplate='%{text}', textposition='outside')
            fig_bar.update_layout(height=400, showlegend=False)
            st.plotly_chart(fig_bar, use_container_width=True)
    
    with col2:
        # Pie 차트
        if px is not None:
            fig_pie = px.pie(
                category_df,
                values="건수",
                names="카테고리",
                title="카테고리 분포 비율"
            )
            fig_pie.update_layout(height=400)
            st.plotly_chart(fig_pie, use_container_width=True)
    
    # 균형도 경고
    if len(category_counts) > 0:
        max_ratio = category_df["비율 (%)"].max()
        if max_ratio > 60:
            st.warning(f"⚠️ 특정 카테고리가 {max_ratio:.1f}%로 편중되어 있습니다. LLM 분류 기준을 재검토하세요.")
        elif max_ratio < 20 and len(category_counts) >= 4:
            st.info("✅ 카테고리 분포가 비교적 균형 잡혀 있습니다.")

def _render_category_engagement_analysis(news_df: pd.DataFrame, event_logs_df: pd.DataFrame):
    """카테고리별 사용자 참여도 분석 (체류시간 / Glossary 클릭률)"""
    if news_df.empty or event_logs_df.empty:
        return
    
    if "primary_category" not in news_df.columns:
        return
    
    st.markdown("#### 📊 카테고리별 사용자 참여도 분석")
    
    # 뉴스 클릭 및 상세 열기 이벤트 추출
    news_clicks = event_logs_df[event_logs_df["event_name"] == "news_click"].copy()
    detail_opens = event_logs_df[event_logs_df["event_name"] == "news_detail_open"].copy()
    glossary_clicks = event_logs_df[event_logs_df["event_name"] == "glossary_click"].copy()
    
    if news_clicks.empty and detail_opens.empty:
        st.info("📊 뉴스 클릭 데이터가 없습니다.")
        return
    
    # news_id 추출 및 카테고리 매핑
    def _get_news_id_from_row(row):
        news_id = row.get("news_id")
        if pd.notna(news_id) and news_id != "":
            return str(news_id)
        payload = _parse_payload(row.get("payload"))
        if payload:
            news_id = payload.get("news_id")
            if news_id:
                return str(news_id)
        return None
    
    # 뉴스 ID별 카테고리 매핑
    news_id_to_category = {}
    for idx, row in news_df.iterrows():
        news_id = str(row.get("news_id", ""))
        category = row.get("primary_category")
        if pd.notna(category) and category != "":
            news_id_to_category[news_id] = category
    
    # 카테고리별 통계 수집
    category_stats = {}
    
    # 뉴스 클릭 수
    for idx, row in news_clicks.iterrows():
        news_id = _get_news_id_from_row(row)
        if news_id and news_id in news_id_to_category:
            category = news_id_to_category[news_id]
            if category not in category_stats:
                category_stats[category] = {
                    "clicks": 0,
                    "detail_opens": 0,
                    "glossary_clicks": 0,
                    "dwell_times": []
                }
            category_stats[category]["clicks"] += 1
    
    # 상세 열기 수 및 체류시간 계산
    for idx, row in detail_opens.iterrows():
        news_id = _get_news_id_from_row(row)
        if news_id and news_id in news_id_to_category:
            category = news_id_to_category[news_id]
            if category not in category_stats:
                category_stats[category] = {
                    "clicks": 0,
                    "detail_opens": 0,
                    "glossary_clicks": 0,
                    "dwell_times": []
                }
            category_stats[category]["detail_opens"] += 1
            
            # 체류시간 계산 (payload에서 duration_sec 추출)
            payload = _parse_payload(row.get("payload"))
            if payload:
                duration_sec = payload.get("duration_sec")
                if duration_sec is not None:
                    try:
                        category_stats[category]["dwell_times"].append(float(duration_sec))
                    except:
                        pass
    
    # Glossary 클릭 수
    for idx, row in glossary_clicks.iterrows():
        news_id = _get_news_id_from_row(row)
        if news_id and news_id in news_id_to_category:
            category = news_id_to_category[news_id]
            if category not in category_stats:
                category_stats[category] = {
                    "clicks": 0,
                    "detail_opens": 0,
                    "glossary_clicks": 0,
                    "dwell_times": []
                }
            category_stats[category]["glossary_clicks"] += 1
    
    if not category_stats:
        st.info("📊 카테고리별 참여 데이터가 없습니다.")
        return
    
    # 통계 데이터프레임 생성
    stats_data = []
    for category, stats in category_stats.items():
        avg_dwell = sum(stats["dwell_times"]) / len(stats["dwell_times"]) if stats["dwell_times"] else 0
        glossary_rate = (stats["glossary_clicks"] / stats["clicks"] * 100) if stats["clicks"] > 0 else 0
        
        stats_data.append({
            "카테고리": category,
            "뉴스 클릭 수": stats["clicks"],
            "상세 열기 수": stats["detail_opens"],
            "평균 체류시간 (초)": round(avg_dwell, 1),
            "Glossary 클릭 수": stats["glossary_clicks"],
            "Glossary 클릭률 (%)": round(glossary_rate, 1)
        })
    
    stats_df = pd.DataFrame(stats_data).sort_values("뉴스 클릭 수", ascending=False)
    
    # 시각화
    col1, col2 = st.columns(2)
    
    with col1:
        # 평균 체류시간 비교
        if px is not None and len(stats_df) > 0:
            fig_dwell = px.bar(
                stats_df,
                x="카테고리",
                y="평균 체류시간 (초)",
                title="카테고리별 평균 체류시간",
                labels={"카테고리": "카테고리", "평균 체류시간 (초)": "체류시간 (초)"},
                text="평균 체류시간 (초)"
            )
            fig_dwell.update_traces(texttemplate='%{text:.1f}초', textposition='outside')
            fig_dwell.update_layout(height=400, showlegend=False)
            st.plotly_chart(fig_dwell, use_container_width=True)
    
    with col2:
        # Glossary 클릭률 비교
        if px is not None and len(stats_df) > 0:
            fig_glossary = px.bar(
                stats_df,
                x="카테고리",
                y="Glossary 클릭률 (%)",
                title="카테고리별 Glossary 클릭률",
                labels={"카테고리": "카테고리", "Glossary 클릭률 (%)": "클릭률 (%)"},
                text="Glossary 클릭률 (%)"
            )
            fig_glossary.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
            fig_glossary.update_layout(height=400, showlegend=False)
            st.plotly_chart(fig_glossary, use_container_width=True)
    
    # 상세 통계 테이블
    st.markdown("**카테고리별 상세 참여 통계**")
    st.dataframe(stats_df, use_container_width=True, height=300)


