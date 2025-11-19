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
    except:
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
    1. published_at 최신순 (가장 중요)
    2. impact_score 높은 순 (두 번째)
    3. credibility_score 높은 순 (세 번째)
    4. urgency_score 높은 순 (네 번째)
    
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
        # Supabase에서는 최신순으로 가져온 후, Python에서 점수 기준으로 재정렬
        query = (
            supabase.table("news")
            .select("*")
            .is_("deleted_at", "null")
            .order("published_at", desc=True)  # 먼저 최신순으로 가져오기
            .limit(limit * 3)  # 더 많이 가져온 후 정렬 (높은 점수의 최신 뉴스 확보)
        )
        
        response = query.execute()
        
        if response.data:
            df = pd.DataFrame(response.data)
            
            # 날짜 컬럼 변환
            date_columns = ["published_at", "created_at", "updated_at", "deleted_at"]
            for col in date_columns:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], errors="coerce")
            
            # 정렬 기준: published_at > impact_score > credibility_score > urgency_score
            # 점수가 NULL인 경우 -1로 변환하여 낮은 우선순위로 처리
            sort_columns = []
            ascending_list = []
            
            # 1순위: published_at 최신순
            if "published_at" in df.columns:
                sort_columns.append("published_at")
                ascending_list.append(False)
            
            # 2순위: impact_score 높은 순
            if "impact_score" in df.columns:
                df["impact_score_sorted"] = df["impact_score"].fillna(-1)
                sort_columns.append("impact_score_sorted")
                ascending_list.append(False)
            
            # 3순위: credibility_score 높은 순
            if "credibility_score" in df.columns:
                df["credibility_score_sorted"] = df["credibility_score"].fillna(-1)
                sort_columns.append("credibility_score_sorted")
                ascending_list.append(False)
            
            # 4순위: urgency_score 높은 순
            if "urgency_score" in df.columns:
                df["urgency_score_sorted"] = df["urgency_score"].fillna(-1)
                sort_columns.append("urgency_score_sorted")
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
        
        query = query.order("event_time", desc=True).limit(limit)
        
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
        # WAU 계산을 위해 최근 7일 데이터를 충분히 가져와야 함
        # limit을 늘려서 최근 데이터를 더 많이 가져오기
        df = _fetch_event_logs_from_supabase(user_id=None, limit=5000)  # 2000 -> 5000으로 증가

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
    🔴 서비스 성능 데이터 탭: "MVP가 멈추지 않고 버틸 수 있는가?"
    
    주요 분석 항목:
    - 뉴스 클릭/상세 진입 메트릭
    - 뉴스 상세 보기 로딩 시간 (하이라이트, 용어 필터링)
    - RAG 응답 시간 (glossary_answer, chat_response)
    - 자연어 검색 처리 속도
    - URL 파싱 성공/실패율
    - Streamlit 세션 수 및 동시 접속 부하
    """
    st.markdown("### 🔴 서비스 성능 데이터 (Service Health)")
    st.markdown("**목표**: 서비스의 기술적 안정성 측정 - 모든 분석의 기반")
    
    # 주요 성능 메트릭
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        news_clicks = int((df_view["event_name"] == "news_click").sum())
        st.metric("뉴스 클릭", news_clicks)
    with col2:
        detail_opens = int((df_view["event_name"] == "news_detail_open").sum())
        st.metric("상세 진입", detail_opens)
    with col3:
        chat_questions = int((df_view["event_name"] == "chat_question").sum())
        st.metric("챗 질문", chat_questions)
    with col4:
        url_errors = int((df_view["event_name"] == "news_url_add_error").sum())
        st.metric("URL 파싱 실패", url_errors)
    
    # 성능 데이터 추출
    perf_events = df_view[df_view["event_name"].isin([
        "news_click", "news_detail_open", "glossary_click", "glossary_answer",
        "chat_response", "news_search_from_chat"
    ])].copy()
    
    if not perf_events.empty:
        perf_events["perf_data"] = perf_events.apply(_extract_perf_data, axis=1)
        perf_events_with_data = perf_events[perf_events["perf_data"].notna()]
        
        # 1. 뉴스 상세 보기 로딩 시간
        _render_detail_performance(perf_events_with_data)
        
        # 2. RAG 응답 시간
        _render_rag_performance(perf_events_with_data)
        
        # 3. 자연어 검색 처리 속도
        _render_search_performance(df_view)
        
        # 4. 하이라이트 계산 시간 (detail 성능에 포함)
        
        # 5. URL 파싱 성공/실패
        _render_url_parsing_quality(df_view)
        
        # 6. Streamlit 세션 수 / 동시 접속 부하
        _render_session_load(df_view, session_column)
    else:
        st.info("📊 성능 데이터가 아직 없습니다.")
    
    # 최근 이벤트 로그
    st.markdown("### 📄 최근 성능 이벤트")
    perf_recent = df_view[df_view["event_name"].isin([
        "news_click", "news_detail_open", "glossary_click", "glossary_answer",
        "chat_question", "chat_response", "news_url_add_error"
    ])].sort_values("event_time", ascending=False).head(50)
    
    display_cols = ["event_time", "event_name", "user_id", "session_id", "latency_ms"]
    available_cols = [col for col in display_cols if col in perf_recent.columns]
    if available_cols:
        st.dataframe(perf_recent[available_cols], use_container_width=True, height=300)

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
        
        with col2:
            st.markdown("##### 🔍 병목 지점 분석")
            if len(perf_df) > 0:
                highlight_pct = (perf_df["하이라이트 처리 (ms)"] / perf_df["전체 렌더링 (ms)"] * 100).mean()
                filter_pct = (perf_df["용어 필터링 (ms)"] / perf_df["전체 렌더링 (ms)"] * 100).mean()
                
                st.write(f"**하이라이트 처리 비율**: {highlight_pct:.1f}%")
                st.write(f"**용어 필터링 비율**: {filter_pct:.1f}%")
                
                if highlight_pct > 50:
                    st.warning("⚠️ 하이라이트 처리가 주요 병목입니다!")
                elif filter_pct > 30:
                    st.warning("⚠️ 용어 필터링이 병목일 수 있습니다.")
                else:
                    st.success("✅ 성능이 양호합니다.")
        
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
    🟡 뉴스 콘텐츠 품질 데이터 탭: "우리 제품이 제공하는 뉴스 데이터 자체가 좋은가?"
    
    주요 분석 항목:
    - 뉴스 소스 분석 (DB 뉴스 vs 임시 뉴스)
    - 뉴스 출처(언론사) 분포
    - 금융/비금융 기사 비중
    - 본문 길이 분포 및 누락 비율
    - 제목·본문 중복률
    - 임팩트 점수 분포
    - 중복 기사 비율
    - 뉴스 수집량 추세
    - 워드클라우드 (특정 날짜)
    - 기초 뉴스 지표 분석 + 라이다 차트
    - 프롬프트 튜닝용 샘플 기사 상세 비교
    - 검색 결과 뉴스 인기 분석
    - URL 파싱 품질
    """
    st.markdown("### 🟡 뉴스 콘텐츠 품질 데이터 (Content Quality)")
    st.markdown("**목표**: 뉴스 콘텐츠의 품질 측정 - 서비스의 핵심 자산")
    
    # 뉴스 소스 분석 (DB 뉴스 vs 임시 뉴스) - 이벤트 로그 기반
    _render_news_source_analysis(df_view)
    
    # URL 파싱 품질 (이벤트 로그 기반)
    _render_url_parsing_quality_for_content(df_view)
    
    # 검색 결과 뉴스 인기 분석 (이벤트 로그 기반)
    _render_search_result_news_popularity(df_view)
    
    # Supabase news 테이블 연동 분석
    with st.spinner("🔄 Supabase에서 뉴스 데이터를 가져오는 중..."):
        news_df = _fetch_news_from_supabase(limit=5000)
        
        if news_df.empty:
            st.warning("⚠️ Supabase `news` 테이블에서 데이터를 가져올 수 없습니다.")
            st.info("💡 Supabase 연결을 확인하거나 뉴스 데이터가 있는지 확인해주세요.")
        else:
            st.success(f"✅ {len(news_df):,}개의 뉴스 데이터를 불러왔습니다.")
            
            # 주요 분석 항목들
            _render_news_source_distribution(news_df)
            _render_financial_news_ratio(news_df)
            _render_content_length_analysis(news_df)
            _render_content_missing_analysis(news_df)
            _render_title_content_duplication(news_df)
            _render_impact_score_distribution(news_df)
            _render_duplicate_news_analysis(news_df)
            _render_news_collection_trends(news_df)
            
            # 워드클라우드 (사용자 설정 가능)
            st.markdown("---")
            _render_wordcloud(news_df)
            
            # 기초 뉴스 지표 분석 + 라이다 차트
            st.markdown("---")
            _render_news_radar_analysis(news_df)
            
            # 프롬프트 튜닝용 샘플 기사 상세 비교
            st.markdown("---")
            _render_prompt_tuning_comparison(news_df)

def _render_news_source_analysis(df_view: pd.DataFrame):
    """뉴스 소스 분석 (DB 뉴스 vs 임시 뉴스)"""
    # news_id가 있는 이벤트 필터링
    news_events = df_view[df_view["news_id"].notna()].copy()
    
    if news_events.empty:
        return
    
    st.markdown("#### 📰 뉴스 소스 분석")
    
    # news_id를 숫자로 변환 시도
    def is_temp_news(news_id):
        """news_id가 임시 뉴스(음수)인지 확인"""
        try:
            news_id_num = float(news_id)
            return news_id_num < 0
        except (ValueError, TypeError):
            return False
    
    news_events["is_temp"] = news_events["news_id"].apply(is_temp_news)
    
    db_news_count = (~news_events["is_temp"]).sum()
    temp_news_count = news_events["is_temp"].sum()
    total_count = len(news_events)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("DB 뉴스", f"{db_news_count:,}건")
    with col2:
        st.metric("임시 뉴스 (URL 직접 입력)", f"{temp_news_count:,}건")
    with col3:
        if total_count > 0:
            temp_ratio = (temp_news_count / total_count) * 100
            st.metric("임시 뉴스 비율", f"{temp_ratio:.1f}%")
        else:
            st.metric("임시 뉴스 비율", "N/A")
    
    if total_count > 0 and px is not None:
        source_df = pd.DataFrame({
            "소스": ["DB 뉴스", "임시 뉴스"],
            "건수": [db_news_count, temp_news_count]
        })
        fig = px.pie(
            source_df,
            values="건수",
            names="소스",
            title="뉴스 소스 분포"
        )
        st.plotly_chart(fig, use_container_width=True)

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
            labels={"출처": "언론사", "건수": "기사 수"}
        )
        fig.update_xaxes(tickangle=-45)
        st.plotly_chart(fig, use_container_width=True)
    
    st.dataframe(top_sources, use_container_width=True, height=300)

def _render_financial_news_ratio(news_df: pd.DataFrame):
    """금융/비금융 기사 비중"""
    # is_finance_news 컬럼이 있으면 우선 사용
    if "is_finance_news" in news_df.columns:
        news_with_flag = news_df[news_df["is_finance_news"].notna()].copy()
        
        if not news_with_flag.empty:
            financial_count = (news_with_flag["is_finance_news"] == True).sum()
            non_financial_count = (news_with_flag["is_finance_news"] == False).sum()
            total_count = len(news_with_flag)
            
            st.markdown("#### 💰 금융/비금융 기사 비중 (is_finance_news 컬럼 기준)")
            
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
            return
    
    # is_finance_news 컬럼이 없으면 키워드 기반 분석
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
        
        short_content = news_df[
            news_df[content_col].notna() &
            (pd.to_numeric(news_df[content_col], errors='coerce') < 50)
        ]
        short_count = len(short_content)
    else:
        # content 컬럼인 경우
        missing_content = news_df[news_df[content_col].isna() | (news_df[content_col] == "")]
        missing_count = len(missing_content)
        
        # 본문이 너무 짧은 경우도 누락으로 간주 (50자 미만)
        short_content = news_df[
            news_df[content_col].notna() & 
            (news_df[content_col] != "") &
            (news_df[content_col].astype(str).str.len() < 50)
        ]
        short_count = len(short_content)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("본문 완전 누락", f"{missing_count:,}건")
        if total_count > 0:
            missing_rate = (missing_count / total_count) * 100
            st.caption(f"누락률: {missing_rate:.1f}%")
    with col2:
        st.metric("본문 짧음 (<50자)", f"{short_count:,}건")
        if total_count > 0:
            short_rate = (short_count / total_count) * 100
            st.caption(f"비율: {short_rate:.1f}%")
    with col3:
        total_issue = missing_count + short_count
        st.metric("총 문제 기사", f"{total_issue:,}건")
        if total_count > 0:
            issue_rate = (total_issue / total_count) * 100
            st.caption(f"문제 비율: {issue_rate:.1f}%")
    
    # 시간대별 누락/짧은 기사 비율 추이 (Line chart)
    if "published_at" in news_df.columns and total_count > 0:
        news_with_date = news_df[news_df["published_at"].notna()].copy()
        if not news_with_date.empty:
            news_with_date["date"] = news_with_date["published_at"].dt.date
            
            if content_col == "raw_content_length":
                news_with_date["is_missing"] = news_with_date[content_col].isna() | (pd.to_numeric(news_with_date[content_col], errors='coerce') == 0)
                news_with_date["is_short"] = news_with_date[content_col].notna() & (pd.to_numeric(news_with_date[content_col], errors='coerce') < 50)
            else:
                news_with_date["is_missing"] = news_with_date[content_col].isna() | (news_with_date[content_col] == "")
                news_with_date["is_short"] = (
                    news_with_date[content_col].notna() & 
                    (news_with_date[content_col] != "") &
                    (news_with_date[content_col].astype(str).str.len() < 50)
                )
            
            daily_stats = news_with_date.groupby("date").agg({
                "is_missing": "sum",
                "is_short": "sum"
            }).reset_index()
            daily_stats["total"] = news_with_date.groupby("date").size().values
            daily_stats["missing_rate"] = (daily_stats["is_missing"] / daily_stats["total"] * 100).fillna(0)
            daily_stats["short_rate"] = (daily_stats["is_short"] / daily_stats["total"] * 100).fillna(0)
            daily_stats["issue_rate"] = ((daily_stats["is_missing"] + daily_stats["is_short"]) / daily_stats["total"] * 100).fillna(0)
            
            if px is not None and len(daily_stats) > 0:
                fig = px.line(
                    daily_stats,
                    x="date",
                    y=["missing_rate", "short_rate", "issue_rate"],
                    title="일별 본문 품질 문제 비율 추이",
                    labels={"date": "날짜", "value": "비율 (%)", "variable": "유형"},
                    color_discrete_map={
                        "missing_rate": "#ef4444",
                        "short_rate": "#f59e0b",
                        "issue_rate": "#3b82f6"
                    }
                )
                fig.update_traces(mode='lines+markers')
                st.plotly_chart(fig, use_container_width=True)
    
    if total_count > 0 and px is not None:
        quality_df = pd.DataFrame({
            "상태": ["정상", "누락", "짧음"],
            "건수": [total_count - total_issue, missing_count, short_count]
        })
        fig = px.pie(
            quality_df,
            values="건수",
            names="상태",
            title="본문 품질 상태"
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

def _render_impact_score_distribution(news_df: pd.DataFrame):
    """임팩트 점수 분포"""
    if "impact_score" not in news_df.columns:
        return
    
    st.markdown("#### 📊 임팩트 점수 분포")
    
    # impact_score가 있는 뉴스만 필터링
    news_with_score = news_df[news_df["impact_score"].notna()].copy()
    
    if news_with_score.empty:
        st.info("📊 임팩트 점수가 있는 뉴스가 없습니다.")
        return
    
    col1, col2, col3 = st.columns(3)
    with col1:
        avg_score = news_with_score["impact_score"].mean()
        st.metric("평균 임팩트 점수", f"{avg_score:.1f}")
    with col2:
        median_score = news_with_score["impact_score"].median()
        st.metric("중간값 점수", f"{median_score:.1f}")
    with col3:
        min_score = news_with_score["impact_score"].min()
        max_score = news_with_score["impact_score"].max()
        st.metric("최소/최대 점수", f"{min_score:.0f} / {max_score:.0f}")
    
    if px is not None and len(news_with_score) > 0:
        fig = px.histogram(
            news_with_score,
            x="impact_score",
            nbins=30,
            title="임팩트 점수 분포",
            labels={"impact_score": "임팩트 점수", "count": "빈도"}
        )
        st.plotly_chart(fig, use_container_width=True)
        
        # 점수 구간별 분포
        score_bins = [0, 10, 20, 30, 40, 50, 100, float('inf')]
        score_labels = ["0-10", "10-20", "20-30", "30-40", "40-50", "50-100", "100+"]
        news_with_score["score_range"] = pd.cut(
            news_with_score["impact_score"], 
            bins=score_bins, 
            labels=score_labels, 
            right=False
        )
        range_counts = news_with_score["score_range"].value_counts().sort_index()
        
        if len(range_counts) > 0:
            range_df = range_counts.reset_index()
            range_df.columns = ["점수 구간", "건수"]
            fig2 = px.bar(
                range_df,
                x="점수 구간",
                y="건수",
                title="임팩트 점수 구간별 분포"
            )
            st.plotly_chart(fig2, use_container_width=True)

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

def _render_wordcloud(news_df: pd.DataFrame):
    """워드클라우드 생성"""
    if not WORDCLOUD_AVAILABLE:
        st.info("💡 워드클라우드를 사용하려면 `pip install wordcloud matplotlib`을 실행해주세요.")
        return
    
    st.markdown("#### ☁️ 뉴스 키워드 워드클라우드")
    
    # 날짜 선택 UI
    if "published_at" in news_df.columns:
        news_with_date = news_df[news_df["published_at"].notna()].copy()
        if not news_with_date.empty:
            news_with_date["date"] = pd.to_datetime(news_with_date["published_at"]).dt.date
            available_dates = sorted(news_with_date["date"].unique(), reverse=True)
            
            if len(available_dates) > 0:
                # 기본값: 가장 최근 날짜
                default_index = 0
                selected_date = st.selectbox(
                    "날짜 선택",
                    options=available_dates,
                    index=default_index,
                    format_func=lambda x: x.strftime("%Y년 %m월 %d일") if hasattr(x, 'strftime') else str(x),
                    key="wordcloud_date"
                )
                
                # 선택한 날짜의 뉴스만 필터링
                selected_news = news_with_date[
                    news_with_date["date"] == selected_date
                ].copy()
                
                if selected_news.empty:
                    date_str = selected_date.strftime('%Y년 %m월 %d일') if hasattr(selected_date, 'strftime') else str(selected_date)
                    st.info(f"📊 {date_str}에 수집된 뉴스가 없습니다.")
                    return
            else:
                st.info("📊 날짜 정보가 있는 뉴스가 없습니다.")
                return
        else:
            st.info("📊 날짜 정보가 있는 뉴스가 없습니다.")
            return
    else:
        # published_at이 없으면 전체 뉴스 사용
        selected_news = news_df.copy()
        st.info("⚠️ published_at 컬럼이 없어 전체 뉴스를 사용합니다.")
        selected_date = None
    
    if selected_news.empty:
        st.info("📊 선택한 날짜에 수집된 뉴스가 없습니다.")
        return
    
    recent_news = selected_news
    
    # title과 content 합치기
    text_list = []
    for idx, row in recent_news.iterrows():
        title = str(row.get("title", "")).strip()
        content = str(row.get("content", "")).strip()
        
        if title or content:
            combined_text = f"{title} {content}"
            text_list.append(combined_text)
    
    if not text_list:
        st.info("📊 제목과 본문이 있는 뉴스가 없습니다.")
        return
    
    # 전체 텍스트 합치기
    all_text = " ".join(text_list)
    
    # 한국어 단어 추출
    words = _extract_korean_words(all_text)
    
    if not words:
        st.info("📊 추출된 한국어 단어가 없습니다.")
        return
    
    # 단어 빈도수 계산
    word_freq = {}
    for word in words:
        word_freq[word] = word_freq.get(word, 0) + 1
    
    if not word_freq:
        st.info("📊 키워드 빈도수가 계산되지 않았습니다.")
        return
    
    # 한글 폰트 경로 찾기
    font_path = _get_korean_font_path()
    
    if not font_path:
        st.warning("⚠️ 한글 폰트를 찾을 수 없습니다. 워드클라우드가 제대로 표시되지 않을 수 있습니다.")
        st.info("💡 Windows: C:/Windows/Fonts/NanumGothic.ttf 경로를 확인해주세요.")
    
    # 워드클라우드 생성
    try:
        wordcloud_params = {
            "width": 800,
            "height": 400,
            "background_color": "white",
            "max_words": 100,
            "relative_scaling": 0.5,
            "colormap": "viridis"
        }
        
        if font_path:
            wordcloud_params["font_path"] = font_path
        
        wordcloud = WordCloud(**wordcloud_params).generate_from_frequencies(word_freq)
        
        # 이미지 표시
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.imshow(wordcloud, interpolation='bilinear')
        ax.axis('off')
        if selected_date:
            date_str = selected_date.strftime('%Y년 %m월 %d일') if hasattr(selected_date, 'strftime') else str(selected_date)
            title = f"{date_str} 뉴스 키워드 워드클라우드"
        else:
            title = "뉴스 키워드 워드클라우드"
        ax.set_title(title, fontsize=16, pad=20)
        
        st.pyplot(fig)
        plt.close(fig)
        
        # 상위 키워드 표시
        top_keywords = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:20]
        if top_keywords:
            st.markdown("##### 🔝 상위 키워드 Top 20")
            keyword_df = pd.DataFrame(top_keywords, columns=["키워드", "빈도"])
            st.dataframe(keyword_df, use_container_width=True, height=300)
    
    except Exception as e:
        st.error(f"❌ 워드클라우드 생성 중 오류가 발생했습니다: {str(e)}")
        st.info("💡 한글 폰트 경로를 확인하거나 wordcloud 라이브러리를 재설치해주세요.")

def _render_news_radar_analysis(news_df: pd.DataFrame):
    """
    뉴스 점수 분석 + 라이다 차트
    
    분석 지표:
    - impact_score: 뉴스의 영향도 점수
    - credibility_score: 뉴스의 신뢰도 점수
    - urgency_score: 뉴스의 긴급도 점수
    """
    st.markdown("### 📊 뉴스 점수 분석 + 라이다 차트")
    st.markdown("**목적**: 뉴스의 3가지 점수(impact_score, credibility_score, urgency_score)를 시각화")
    
    if news_df.empty:
        st.info("📊 분석할 뉴스 데이터가 없습니다.")
        return
    
    # 필요한 점수 컬럼 확인
    required_columns = ["impact_score", "credibility_score", "urgency_score"]
    missing_columns = [col for col in required_columns if col not in news_df.columns]
    
    if missing_columns:
        st.warning(f"⚠️ 필요한 점수 컬럼이 없습니다: {', '.join(missing_columns)}")
        st.info("💡 뉴스 데이터에 impact_score, credibility_score, urgency_score 컬럼이 있는지 확인해주세요.")
        return
    
    # 뉴스 선택 UI
    st.markdown("#### 📰 분석할 뉴스 선택")
    
    if "title" in news_df.columns:
        # 제목으로 선택
        if "news_id" in news_df.columns:
            titles_with_id = [f"[{row['news_id']}] {row['title']}" if pd.notna(row['title']) else f"[{row['news_id']}] 제목 없음" 
                             for _, row in news_df.iterrows()]
        else:
            titles_with_id = news_df["title"].fillna("제목 없음").tolist()
        
        selected_index = st.selectbox(
            "뉴스 선택",
            range(len(titles_with_id)),
            format_func=lambda x: titles_with_id[x][:100] + "..." if len(titles_with_id[x]) > 100 else titles_with_id[x],
            key="radar_news_selection"
        )
        
        selected_news = news_df.iloc[selected_index].to_dict()
    else:
        st.warning("⚠️ 제목 컬럼이 없어 뉴스를 선택할 수 없습니다.")
        return
    
    # 선택한 뉴스의 점수 가져오기
    impact_score = float(selected_news.get("impact_score", 0)) if pd.notna(selected_news.get("impact_score")) else 0
    credibility_score = float(selected_news.get("credibility_score", 0)) if pd.notna(selected_news.get("credibility_score")) else 0
    urgency_score = float(selected_news.get("urgency_score", 0)) if pd.notna(selected_news.get("urgency_score")) else 0
    
    # 라이다 차트 생성
    if go is not None:
        st.markdown("#### 📈 선택한 뉴스 라이다 차트")
        
        # 라이다 차트 데이터 준비
        categories = ["Impact Score", "Credibility Score", "Urgency Score"]
        values = [impact_score, credibility_score, urgency_score]
        
        # 최대값 계산 (점수 범위가 0-100이 아닐 수 있으므로)
        max_score = max(values) if values else 100
        max_range = max(100, max_score * 1.2)  # 여유 공간을 위해 20% 추가
        
        # 라이다 차트 생성
        fig = go.Figure()
        
        fig.add_trace(go.Scatterpolar(
            r=values,
            theta=categories,
            fill='toself',
            name='선택한 뉴스',
            line_color='rgb(59, 130, 246)'  # 파란색
        ))
        
        fig.update_layout(
            polar=dict(
                radialaxis=dict(
                    visible=True,
                    range=[0, max_range]
                )),
            showlegend=True,
            title="뉴스 점수 분석",
            height=500
        )
        
        st.plotly_chart(fig, use_container_width=True)
        
        # 점수 상세 정보
        st.markdown("##### 📋 상세 점수")
        score_df = pd.DataFrame([
            {"지표": "Impact Score", "점수": f"{impact_score:.1f}"},
            {"지표": "Credibility Score", "점수": f"{credibility_score:.1f}"},
            {"지표": "Urgency Score", "점수": f"{urgency_score:.1f}"},
        ])
        st.dataframe(score_df, use_container_width=True)
        
        # 최근 7일 평균 라이다 차트
        st.markdown("#### 📊 최근 7일 기사 평균 라이다 차트")
        
        # 최근 7일 뉴스 필터링
        if "published_at" in news_df.columns:
            cutoff_date = datetime.now() - timedelta(days=7)
            recent_news = news_df[
                news_df["published_at"].notna() & 
                (pd.to_datetime(news_df["published_at"]) >= cutoff_date)
            ].copy()
        else:
            recent_news = news_df.copy()
            st.info("⚠️ published_at 컬럼이 없어 전체 뉴스를 사용합니다.")
        
        if not recent_news.empty:
            # 최근 7일 뉴스들의 점수 수집
            impact_scores = []
            credibility_scores = []
            urgency_scores = []
            
            for idx, row in recent_news.iterrows():
                impact = row.get("impact_score")
                credibility = row.get("credibility_score")
                urgency = row.get("urgency_score")
                
                if pd.notna(impact):
                    impact_scores.append(float(impact))
                if pd.notna(credibility):
                    credibility_scores.append(float(credibility))
                if pd.notna(urgency):
                    urgency_scores.append(float(urgency))
            
            if impact_scores or credibility_scores or urgency_scores:
                # 기술통계 계산 함수
                def calc_stats(scores):
                    """점수 리스트로부터 기술통계 계산"""
                    if not scores:
                        return {
                            "평균": 0.0,
                            "표준편차": 0.0,
                            "최소값": 0.0,
                            "최대값": 0.0,
                            "중앙값": 0.0,
                            "개수": 0
                        }
                    # numpy를 사용하여 기술통계 계산
                    try:
                        import numpy as np
                        scores_array = np.array(scores)
                        return {
                            "평균": float(np.mean(scores_array)),
                            "표준편차": float(np.std(scores_array)),
                            "최소값": float(np.min(scores_array)),
                            "최대값": float(np.max(scores_array)),
                            "중앙값": float(np.median(scores_array)),
                            "개수": len(scores)
                        }
                    except ImportError:
                        # numpy가 없으면 기본 Python으로 계산
                        n = len(scores)
                        mean = sum(scores) / n
                        variance = sum((x - mean) ** 2 for x in scores) / n
                        std_dev = variance ** 0.5
                        sorted_scores = sorted(scores)
                        median = sorted_scores[n // 2] if n % 2 == 1 else (sorted_scores[n // 2 - 1] + sorted_scores[n // 2]) / 2
                        return {
                            "평균": float(mean),
                            "표준편차": float(std_dev),
                            "최소값": float(min(scores)),
                            "최대값": float(max(scores)),
                            "중앙값": float(median),
                            "개수": n
                        }
                
                # 각 점수별 기술통계 계산
                impact_stats = calc_stats(impact_scores)
                credibility_stats = calc_stats(credibility_scores)
                urgency_stats = calc_stats(urgency_scores)
                
                # 평균값 (라이다 차트용)
                avg_impact = impact_stats["평균"]
                avg_credibility = credibility_stats["평균"]
                avg_urgency = urgency_stats["평균"]
                
                avg_values = [avg_impact, avg_credibility, avg_urgency]
                avg_max_range = max(100, max(avg_values) * 1.2) if avg_values else 100
                
                # 평균 라이다 차트 생성
                avg_fig = go.Figure()
                
                avg_fig.add_trace(go.Scatterpolar(
                    r=avg_values,
                    theta=categories,
                    fill='toself',
                    name='최근 7일 평균',
                    line_color='rgb(34, 197, 94)'  # 초록색
                ))
                
                avg_fig.update_layout(
                    polar=dict(
                        radialaxis=dict(
                            visible=True,
                            range=[0, avg_max_range]
                        )),
                    showlegend=True,
                    title="최근 7일 기사 평균 점수",
                    height=500
                )
                
                st.plotly_chart(avg_fig, use_container_width=True)
                
                # 기술통계 상세 정보
                st.markdown("##### 📋 최근 7일 기술통계")
                stats_df = pd.DataFrame([
                    {
                        "지표": "Impact Score",
                        "평균": f"{impact_stats['평균']:.1f}",
                        "표준편차": f"{impact_stats['표준편차']:.1f}",
                        "최소값": f"{impact_stats['최소값']:.1f}",
                        "최대값": f"{impact_stats['최대값']:.1f}",
                        "중앙값": f"{impact_stats['중앙값']:.1f}",
                        "개수": f"{impact_stats['개수']:,}건"
                    },
                    {
                        "지표": "Credibility Score",
                        "평균": f"{credibility_stats['평균']:.1f}",
                        "표준편차": f"{credibility_stats['표준편차']:.1f}",
                        "최소값": f"{credibility_stats['최소값']:.1f}",
                        "최대값": f"{credibility_stats['최대값']:.1f}",
                        "중앙값": f"{credibility_stats['중앙값']:.1f}",
                        "개수": f"{credibility_stats['개수']:,}건"
                    },
                    {
                        "지표": "Urgency Score",
                        "평균": f"{urgency_stats['평균']:.1f}",
                        "표준편차": f"{urgency_stats['표준편차']:.1f}",
                        "최소값": f"{urgency_stats['최소값']:.1f}",
                        "최대값": f"{urgency_stats['최대값']:.1f}",
                        "중앙값": f"{urgency_stats['중앙값']:.1f}",
                        "개수": f"{urgency_stats['개수']:,}건"
                    },
                ])
                st.dataframe(stats_df, use_container_width=True)
                st.caption(f"📊 분석 기사 수: {len(recent_news):,}건")
            else:
                st.info("📊 점수를 계산할 수 있는 뉴스가 없습니다.")
        else:
            st.info("📊 최근 7일간 수집된 뉴스가 없습니다.")
    else:
        st.warning("⚠️ Plotly가 설치되지 않아 라이다 차트를 표시할 수 없습니다.")

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
        if payload and "article_ids" in payload:
            article_ids = payload.get("article_ids", [])
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
    if news_appearances:
        popularity_data = []
        for news_id, data in news_appearances.items():
            appearance_count = data["count"]
            click_count = news_clicks.get(news_id, 0)
            click_rate = (click_count / appearance_count * 100) if appearance_count > 0 else 0
            title = news_titles.get(news_id, f"뉴스 ID: {news_id}")
            
            popularity_data.append({
                "news_id": news_id,
                "제목": title[:50] + "..." if len(title) > 50 else title,
                "검색 결과 포함": appearance_count,
                "클릭 수": click_count,
                "클릭률 (%)": round(click_rate, 1)
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
            
            # Top 10 인기 뉴스
            top_10_df = popularity_df.head(10)
            
            if px is not None and len(top_10_df) > 0:
                fig = px.bar(
                    top_10_df,
                    x="클릭 수",
                    y="제목",
                    orientation='h',
                    title="검색 결과에서 가장 많이 클릭된 뉴스 Top 10",
                    labels={"클릭 수": "클릭 수", "제목": "뉴스 제목"},
                    hover_data=["검색 결과 포함", "클릭률 (%)"]
                )
                st.plotly_chart(fig, use_container_width=True)
            
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
    
    success_count = int((url_events["event_name"] == "news_url_added_from_chat").sum())
    error_count = int((url_events["event_name"] == "news_url_add_error").sum())
    total_count = success_count + error_count
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("파싱 성공", success_count)
    with col2:
        st.metric("파싱 실패", error_count)
    with col3:
        if total_count > 0:
            failure_rate = (error_count / total_count) * 100
            st.metric("실패율", f"{failure_rate:.1f}%")
        else:
            st.metric("실패율", "N/A")
    
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

def _render_prompt_tuning_comparison(news_df: pd.DataFrame):
    """프롬프트 튜닝용 샘플 기사 상세 비교 블록"""
    st.markdown("### 4️⃣ 샘플 기사 상세 비교 (프롬프트 튜닝용)")
    st.markdown("**목적**: 뉴스 원문 + LLM 요약 결과를 비교하여 프롬프트 개선 포인트 발견")
    
    if news_df.empty:
        st.info("📊 비교할 뉴스 데이터가 없습니다.")
        return
    
    # 필터링 UI
    st.markdown("#### 🔍 기사 필터링")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        # 날짜 필터
        if "published_at" in news_df.columns:
            news_with_date = news_df[news_df["published_at"].notna()].copy()
            if not news_with_date.empty:
                min_date = news_with_date["published_at"].min().date()
                max_date = news_with_date["published_at"].max().date()
                date_range = st.date_input(
                    "발행일 범위",
                    value=(min_date, max_date),
                    min_value=min_date,
                    max_value=max_date,
                    key="prompt_tuning_date_range"
                )
            else:
                date_range = None
        else:
            date_range = None
    
    with col2:
        # 언론사 필터
        if "source" in news_df.columns:
            sources = ["전체"] + sorted(news_df[news_df["source"].notna()]["source"].unique().tolist())
            selected_source = st.selectbox("언론사", sources, key="prompt_tuning_source")
        else:
            selected_source = "전체"
    
    with col3:
        # 본문 길이 필터
        if "content" in news_df.columns:
            news_with_content = news_df[news_df["content"].notna() & (news_df["content"] != "")].copy()
            if not news_with_content.empty:
                news_with_content["content_length"] = news_with_content["content"].astype(str).str.len()
                min_len = int(news_with_content["content_length"].min())
                max_len = int(news_with_content["content_length"].max())
                length_range = st.slider(
                    "본문 길이 (자)",
                    min_value=min_len,
                    max_value=max_len,
                    value=(min_len, max_len),
                    key="prompt_tuning_length"
                )
            else:
                length_range = None
        else:
            length_range = None
    
    with col4:
        # 금융/비금융 필터
        if "is_finance_news" in news_df.columns:
            category_options = ["전체", "금융", "비금융"]
            selected_category = st.selectbox("카테고리", category_options, key="prompt_tuning_category")
        else:
            selected_category = "전체"
    
    # 필터링 적용
    filtered_df = news_df.copy()
    
    # 날짜 필터
    if date_range and len(date_range) == 2 and "published_at" in filtered_df.columns:
        start_date, end_date = date_range
        filtered_df = filtered_df[
            (pd.to_datetime(filtered_df["published_at"]).dt.date >= start_date) &
            (pd.to_datetime(filtered_df["published_at"]).dt.date <= end_date)
        ]
    
    # 언론사 필터
    if selected_source != "전체" and "source" in filtered_df.columns:
        filtered_df = filtered_df[filtered_df["source"] == selected_source]
    
    # 길이 필터
    if length_range and "content" in filtered_df.columns:
        filtered_df = filtered_df[
            filtered_df["content"].notna() & (filtered_df["content"] != "")
        ].copy()
        filtered_df["content_length"] = filtered_df["content"].astype(str).str.len()
        filtered_df = filtered_df[
            (filtered_df["content_length"] >= length_range[0]) &
            (filtered_df["content_length"] <= length_range[1])
        ]
    
    # 카테고리 필터
    if selected_category != "전체" and "is_finance_news" in filtered_df.columns:
        if selected_category == "금융":
            filtered_df = filtered_df[filtered_df["is_finance_news"] == True]
        else:
            filtered_df = filtered_df[filtered_df["is_finance_news"] == False]
    
    if filtered_df.empty:
        st.warning("⚠️ 필터 조건에 맞는 기사가 없습니다.")
        return
    
    st.info(f"📊 필터링된 기사: {len(filtered_df):,}건")
    
    # 요약 품질 통계 분석
    st.markdown("---")
    st.markdown("#### 📊 요약 품질 통계 분석")
    
    # 필터링된 기사들에 대해 체크리스트 실행
    quality_stats = {
        "제목 그대로 포함": 0,
        "요약 과도하게 장황": 0,
        "요약 너무 짧음": 0,
        "금융 뉴스 숫자 누락": 0,
        "본문 앞부분 복사": 0,
        "품질 통과": 0,
        "요약 없음": 0
    }
    
    # 체크리스트 함수
    def check_summary_quality(row, selected_category):
        """기사별 요약 품질 체크"""
        title = row.get("title", "")
        content = row.get("content", "")
        summary = row.get("summary", "")
        
        if not content or not summary or pd.isna(summary) or str(summary).strip() == "":
            return "요약 없음"
        
        content_str = str(content)
        summary_str = str(summary)
        
        # 1. 제목 그대로 복붙 여부
        if title and str(title) in summary_str:
            return "제목 그대로 포함"
        
        # 2. 본문 길이 대비 요약 길이
        content_len = len(content_str)
        summary_len = len(summary_str)
        if content_len > 0:
            summary_ratio = (summary_len / content_len) * 100
            if content_len < 500 and summary_ratio > 50:
                return "요약 과도하게 장황"
            elif summary_ratio < 5:
                return "요약 너무 짧음"
        
        # 3. 숫자/변화폭 포함 여부 (금융/정책 뉴스)
        if selected_category == "금융":
            numbers_in_content = len(re.findall(r'\d+[%원억만조]?', content_str))
            numbers_in_summary = len(re.findall(r'\d+[%원억만조]?', summary_str))
            if numbers_in_content > 0 and numbers_in_summary == 0:
                return "금융 뉴스 숫자 누락"
        
        # 4. 본문 앞부분만 복사 여부
        if content_str[:200] in summary_str:
            return "본문 앞부분 복사"
        
        return "품질 통과"
    
    # 필터링된 모든 기사에 대해 체크리스트 실행
    for idx, row in filtered_df.iterrows():
        quality_result = check_summary_quality(row, selected_category)
        if quality_result in quality_stats:
            quality_stats[quality_result] += 1
    
    # 통계 표시
    total_checked = sum(quality_stats.values())
    if total_checked > 0:
        # 파이 그래프용 데이터 준비
        quality_items = []
        quality_counts = []
        
        for key, count in quality_stats.items():
            if count > 0:
                quality_items.append(key)
                quality_counts.append(count)
        
        if quality_items and px is not None:
            quality_df = pd.DataFrame({
                "항목": quality_items,
                "건수": quality_counts
            })
            
            # 파이 그래프 생성
            fig = px.pie(
                quality_df,
                values="건수",
                names="항목",
                title="요약 품질 체크리스트 항목별 비율",
                hole=0.4  # 도넛 차트
            )
            st.plotly_chart(fig, use_container_width=True)
        
        # 통계 테이블
        st.markdown("##### 📋 상세 통계")
        stats_df = pd.DataFrame([
            {"항목": key, "건수": count, "비율": f"{(count/total_checked*100):.1f}%"}
            for key, count in quality_stats.items() if count > 0
        ])
        st.dataframe(stats_df, use_container_width=True)
    else:
        st.info("📊 요약이 있는 기사가 없습니다.")
    
    # 기사 선택 UI
    st.markdown("---")
    st.markdown("#### 📰 기사 선택")
    
    # 기사 선택을 위한 selectbox
    if "title" in filtered_df.columns:
        # 제목으로 선택
        if "news_id" in filtered_df.columns:
            titles_with_id = [f"[{row['news_id']}] {row['title']}" if pd.notna(row['title']) else f"[{row['news_id']}] 제목 없음" 
                             for _, row in filtered_df.iterrows()]
        else:
            titles_with_id = filtered_df["title"].fillna("제목 없음").tolist()
        
        selected_index = st.selectbox(
            "기사 선택",
            range(len(titles_with_id)),
            format_func=lambda x: titles_with_id[x][:100] + "..." if len(titles_with_id[x]) > 100 else titles_with_id[x],
            key="prompt_tuning_selected_article"
        )
        
        selected_article = filtered_df.iloc[selected_index].to_dict()
    else:
        st.warning("⚠️ 제목 컬럼이 없어 기사를 선택할 수 없습니다.")
        return
    
    # 좌우 비교 화면
    st.markdown("---")
    st.markdown("#### 📊 원문 vs 요약 비교")
    
    col_left, col_right = st.columns(2)
    
    with col_left:
        st.markdown("##### 📄 원문")
        
        # 제목
        title = selected_article.get("title", "제목 없음")
        st.markdown(f"**{title}**")
        
        # 메타 정보
        meta_info = []
        if "source" in selected_article and pd.notna(selected_article.get("source")):
            meta_info.append(f"출처: {selected_article['source']}")
        if "published_at" in selected_article and pd.notna(selected_article.get("published_at")):
            pub_date = pd.to_datetime(selected_article["published_at"])
            meta_info.append(f"날짜: {pub_date.strftime('%Y-%m-%d %H:%M')}")
        if "content" in selected_article:
            content_len = len(str(selected_article.get("content", "")))
            meta_info.append(f"길이: {content_len:,}자")
        
        if meta_info:
            st.caption(" | ".join(meta_info))
        
        # 본문
        content = selected_article.get("content", "")
        if content:
            st.markdown("**본문:**")
            st.text_area(
                "본문 내용",
                value=str(content),
                height=400,
                disabled=True,
                key="original_content_display"
            )
        else:
            st.warning("⚠️ 본문이 없습니다.")
    
    with col_right:
        st.markdown("##### 🤖 LLM 요약 결과")
        
        # 요약 가져오기
        summary = selected_article.get("summary", "")
        
        if summary and pd.notna(summary) and str(summary).strip():
            st.markdown("**요약:**")
            st.text_area(
                "요약 내용",
                value=str(summary),
                height=400,
                disabled=True,
                key="summary_display"
            )
        else:
            st.info("💡 요약이 없습니다. Supabase `summary` 컬럼을 확인하거나 on-demand 생성 기능을 구현해주세요.")
            st.caption("(향후 on-demand 요약 생성 기능 추가 예정)")
        
        # 요약 품질 체크리스트
        st.markdown("**🔍 프롬프트 개선 체크리스트:**")
        
        if content and summary:
            content_str = str(content)
            summary_str = str(summary)
            
            checks = []
            
            # 1. 제목 그대로 복붙 여부
            if title and title in summary_str:
                checks.append("⚠️ 제목이 요약에 그대로 포함됨 → 제목 재작성 규칙 강화 필요")
            
            # 2. 본문 길이 대비 요약 길이
            content_len = len(content_str)
            summary_len = len(summary_str)
            if content_len > 0:
                summary_ratio = (summary_len / content_len) * 100
                if content_len < 500 and summary_ratio > 50:
                    checks.append("⚠️ 짧은 기사인데 요약이 과도하게 장황함 → 단신은 해석 줄이기")
                elif summary_ratio < 5:
                    checks.append("⚠️ 요약이 너무 짧음 → 핵심 정보 포함 강화")
            
            # 3. 숫자/변화폭 포함 여부 (금융/정책 뉴스)
            # selected_category가 "금융"이면 이미 금융 기사로 필터링된 상태
            # is_finance_news 컬럼이 없어도 selected_category로 판단 가능
            if selected_category == "금융":
                numbers_in_content = len(re.findall(r'\d+[%원억만조]?', content_str))
                numbers_in_summary = len(re.findall(r'\d+[%원억만조]?', summary_str))
                if numbers_in_content > 0 and numbers_in_summary == 0:
                    checks.append("⚠️ 금리/정책 뉴스인데 숫자/변화폭이 요약에 없음 → 숫자 필수 규칙 추가")
            
            # 4. 본문 앞부분만 복사 여부
            if content_str[:200] in summary_str:
                checks.append("⚠️ 본문 앞부분을 그대로 복사한 듯함 → 요약 재작성 강화")
            
            if checks:
                for check in checks:
                    st.warning(check)
            else:
                st.success("✅ 기본적인 품질 체크를 통과했습니다.")
        else:
            st.info("💡 원문과 요약을 비교하려면 둘 다 필요합니다.")

# ============================================================================
# 탭 3: 사용자 행동 데이터 (User Behavior)
# ============================================================================

def _render_user_behavior_tab(df_view: pd.DataFrame, session_column: str):
    """
    🟢 사용자 행동 데이터 탭: "사용자가 우리가 만든 기능을 실제로 사용하고 있는가?"
    
    주요 분석 항목:
    - 뉴스 클릭률 (CTR)
    - 기사 읽기 시간 (Dwell Time)
    - 요약 클릭률
    - 용어 클릭률 및 인기 용어 Top 10
    - 자연어 검색 성공률
    - 검색 → 클릭 전환률
    - URL 입력 기능 사용률
    - 챗봇 질문 타입 분포
    - 재방문 세션 수
    """
    st.markdown("### 🟢 사용자 행동 데이터 (User Behavior)")
    st.markdown("**목표**: 사용자의 실제 행동 패턴 분석 - MVP 기능의 가치 여부 판단")
    
    # 주요 메트릭
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        news_clicks = int((df_view["event_name"] == "news_click").sum())
        st.metric("뉴스 클릭", news_clicks)
    with col2:
        detail_opens = int((df_view["event_name"] == "news_detail_open").sum())
        st.metric("상세 진입", detail_opens)
        if news_clicks > 0:
            ctr = (detail_opens / news_clicks) * 100
            st.caption(f"진입률: {ctr:.1f}%")
    with col3:
        chat_questions = int((df_view["event_name"] == "chat_question").sum())
        st.metric("챗 질문", chat_questions)
    with col4:
        search_requests = int((df_view["event_name"] == "news_search_from_chat").sum())
        st.metric("뉴스 검색", search_requests)
    
    # 1. 뉴스 클릭률 (CTR)
    _render_news_ctr(df_view)
    
    # 2. 기사 상세 진입률 (위에 포함)
    
    # 3. 기사 읽기 시간(dwell time)
    _render_dwell_time(df_view)
    
    # 4. 요약 클릭률
    _render_summary_clicks(df_view)
    
    # 5. 용어 클릭률
    _render_term_clicks(df_view)
    
    # 6. 자연어 검색 성공률
    _render_search_success_rate(df_view)
    
    # 7. 검색 → 클릭 전환률
    _render_search_to_click_conversion(df_view)
    
    # 8. URL 입력 기능 사용률
    _render_url_input_usage(df_view)
    
    # 9. 챗봇 질문 타입 분포
    _render_chat_question_types(df_view)
    
    # 10. 재방문 세션 수
    _render_returning_sessions(df_view, session_column)

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
    """기사 읽기 시간 분석"""
    view_duration_events = df_view[df_view["event_name"] == "view_duration"]
    
    if view_duration_events.empty:
        return
    
    st.markdown("#### ⏱️ 기사 읽기 시간 (Dwell Time)")
    
    duration_data = []
    for idx, row in view_duration_events.iterrows():
        payload = _parse_payload(row.get("payload"))
        duration_sec = payload.get("duration_sec")
        if duration_sec is not None:
            duration_data.append({
                "event_time": row.get("event_time"),
                "읽기 시간 (초)": duration_sec,
            })
    
    if duration_data:
        duration_df = pd.DataFrame(duration_data)
        avg_duration = duration_df["읽기 시간 (초)"].mean()
        st.metric("평균 읽기 시간", f"{avg_duration:.1f}초")
        
        if px is not None and len(duration_df) > 0:
            fig = px.histogram(
                duration_df,
                x="읽기 시간 (초)",
                nbins=30,
                title="기사 읽기 시간 분포"
            )
            st.plotly_chart(fig, use_container_width=True)

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
    """용어 클릭률 분석"""
    term_clicks = df_view[df_view["event_name"] == "glossary_click"]
    term_answers = df_view[df_view["event_name"] == "glossary_answer"]
    
    if term_clicks.empty and term_answers.empty:
        return
    
    st.markdown("#### 💡 용어 클릭률")
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("용어 클릭", len(term_clicks))
    with col2:
        st.metric("용어 답변", len(term_answers))
    
    # 인기 용어 Top 10
    if not term_clicks.empty:
        term_list = []
        for idx, row in term_clicks.iterrows():
            term = _get_term_from_row(row)
            if term:
                term_list.append(term)
        
        if term_list:
            term_counts = pd.Series(term_list).value_counts().head(10)
            if px is not None and len(term_counts) > 0:
                fig = px.bar(
                    x=term_counts.index,
                    y=term_counts.values,
                    title="인기 용어 Top 10",
                    labels={"x": "용어", "y": "클릭 수"}
                )
                st.plotly_chart(fig, use_container_width=True)

def _render_search_success_rate(df_view: pd.DataFrame):
    """자연어 검색 성공률"""
    search_success = df_view[df_view["event_name"] == "news_search_from_chat"]
    search_failed = df_view[df_view["event_name"] == "news_search_failed"]
    
    if search_success.empty and search_failed.empty:
        return
    
    st.markdown("#### 🔍 자연어 검색 성공률")
    
    success_count = len(search_success)
    failed_count = len(search_failed)
    total_count = success_count + failed_count
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("검색 성공", success_count)
    with col2:
        st.metric("검색 실패", failed_count)
    with col3:
        if total_count > 0:
            success_rate = (success_count / total_count) * 100
            st.metric("성공률", f"{success_rate:.1f}%")
        else:
            st.metric("성공률", "N/A")

def _render_search_to_click_conversion(df_view: pd.DataFrame):
    """검색 → 클릭 전환률"""
    search_events = df_view[df_view["event_name"] == "news_search_from_chat"]
    selected_from_search = df_view[df_view["event_name"] == "news_selected_from_chat"]
    
    if search_events.empty:
        return
    
    st.markdown("#### 🎯 검색 → 클릭 전환률")
    
    search_count = len(search_events)
    selected_count = len(selected_from_search)
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("검색 실행", search_count)
    with col2:
        st.metric("검색 결과 선택", selected_count)
        if search_count > 0:
            conversion_rate = (selected_count / search_count) * 100
            st.caption(f"전환율: {conversion_rate:.1f}%")

def _render_url_input_usage(df_view: pd.DataFrame):
    """URL 입력 기능 사용률"""
    url_added = df_view[df_view["event_name"] == "news_url_added_from_chat"]
    
    if url_added.empty:
        return
    
    st.markdown("#### 🔗 URL 입력 기능 사용률")
    
    url_count = len(url_added)
    total_sessions = df_view["session_id"].nunique() if "session_id" in df_view.columns else 0
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("URL로 추가된 기사", url_count)
    with col2:
        if total_sessions > 0:
            usage_rate = (url_count / total_sessions) * 100
            st.metric("세션당 사용률", f"{usage_rate:.1f}%")
        else:
            st.metric("세션당 사용률", "N/A")

def _render_chat_question_types(df_view: pd.DataFrame):
    """챗봇 질문 타입 분포"""
    chat_events = df_view[df_view["event_name"].isin([
        "chat_question", "glossary_answer", "chat_response", "news_search_from_chat", "news_url_added_from_chat"
    ])]
    
    if chat_events.empty:
        return
    
    st.markdown("#### 💬 챗봇 질문 타입 분포")
    
    question_types = {
        "용어 질문": len(df_view[df_view["event_name"] == "glossary_answer"]),
        "일반 질문": len(df_view[df_view["event_name"] == "chat_response"]),
        "뉴스 검색": len(df_view[df_view["event_name"] == "news_search_from_chat"]),
        "URL 입력": len(df_view[df_view["event_name"] == "news_url_added_from_chat"]),
    }
    
    question_types = {k: v for k, v in question_types.items() if v > 0}
    
    if question_types:
        type_df = pd.DataFrame(list(question_types.items()), columns=["타입", "건수"])
        
        if px is not None:
            fig = px.pie(
                type_df,
                values="건수",
                names="타입",
                title="챗봇 질문 타입 분포"
            )
            st.plotly_chart(fig, use_container_width=True)
        
        st.dataframe(type_df, use_container_width=True)

def _render_returning_sessions(df_view: pd.DataFrame, session_column: str):
    """재방문 세션 수"""
    if session_column not in df_view.columns:
        return
    
    st.markdown("#### 🔄 재방문 세션 분석")
    
    user_sessions = df_view.groupby("user_id")[session_column].nunique().reset_index()
    user_sessions.columns = ["user_id", "세션 수"]
    
    total_users = len(user_sessions)
    returning_users = len(user_sessions[user_sessions["세션 수"] > 1])
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("총 사용자", total_users)
    with col2:
        st.metric("재방문 사용자", returning_users)
        if total_users > 0:
            return_rate = (returning_users / total_users) * 100
            st.caption(f"재방문률: {return_rate:.1f}%")
    
    if px is not None and len(user_sessions) > 0:
        fig = px.histogram(
            user_sessions,
            x="세션 수",
            nbins=20,
            title="사용자별 세션 수 분포"
        )
        st.plotly_chart(fig, use_container_width=True)

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
    
    # 4. Glossary 사용 세션 비율
    glossary_sessions = df_view[df_view["event_name"] == "glossary_click"][session_column].nunique() if session_column in df_view.columns else 0
    glossary_usage_rate = (glossary_sessions / total_sessions * 100) if total_sessions > 0 else 0
    
    # 5. 챗봇 사용 세션 비율
    chat_sessions = df_view[df_view["event_name"].isin(["chat_question", "chat_response"])][session_column].nunique() if session_column in df_view.columns else 0
    chat_usage_rate = (chat_sessions / total_sessions * 100) if total_sessions > 0 else 0
    
    # 6. 평균 뉴스 하이라이트 속도 (캐시 히트/미스 구분)
    # news_detail_open 이벤트에서 하이라이트 처리 시간 추출
    # 캐시 히트는 매우 빠르므로(3ms 정도) 별도로 구분하여 표시
    detail_events = df_view[df_view["event_name"] == "news_detail_open"].copy()
    highlight_latencies = []
    highlight_latencies_cache_miss = []  # 캐시 미스만 (실제 성능 문제 파악용)
    highlight_latencies_cache_hit = []   # 캐시 히트만 (참고용)
    
    for idx, row in detail_events.iterrows():
        perf_data = _extract_perf_data(row)
        if perf_data and isinstance(perf_data, dict):
            highlight_ms = perf_data.get("highlight_ms")
            cache_hit = perf_data.get("highlight_cache_hit", False)
            
            if highlight_ms is not None:
                try:
                    highlight_value = float(highlight_ms)
                    # 유효한 값만 추가 (0보다 크고 합리적인 범위 내)
                    if highlight_value > 0 and highlight_value < 100000:  # 100초 이상은 제외
                        highlight_latencies.append(highlight_value)
                        # 캐시 히트/미스 구분
                        if cache_hit:
                            highlight_latencies_cache_hit.append(highlight_value)
                        else:
                            highlight_latencies_cache_miss.append(highlight_value)
                except (ValueError, TypeError):
                    pass
    
    avg_highlight_latency = sum(highlight_latencies) / len(highlight_latencies) if highlight_latencies else None
    avg_highlight_cache_miss = sum(highlight_latencies_cache_miss) / len(highlight_latencies_cache_miss) if highlight_latencies_cache_miss else None
    avg_highlight_cache_hit = sum(highlight_latencies_cache_hit) / len(highlight_latencies_cache_hit) if highlight_latencies_cache_hit else None
    
    # 메트릭 카드 표시
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("DAU", f"{dau}명")
        st.metric("WAU", f"{wau}명")
    with col2:
        st.metric("평균 세션 길이", f"{avg_session_length:.1f}분")
        st.metric("세션당 뉴스 클릭", f"{news_clicks_per_session:.1f}건")
    with col3:
        st.metric("Glossary 사용 세션", f"{glossary_usage_rate:.1f}%")
        st.metric("챗봇 사용 세션", f"{chat_usage_rate:.1f}%")
    
    col4, col5, col6 = st.columns(3)
    with col4:
        if avg_highlight_latency is not None:
            st.metric("평균 하이라이트 속도", f"{avg_highlight_latency:.0f}ms")
            # 캐시 히트/미스 정보 표시
            if avg_highlight_cache_hit is not None and avg_highlight_cache_miss is not None:
                st.caption(f"캐시 히트: {avg_highlight_cache_hit:.0f}ms | 캐시 미스: {avg_highlight_cache_miss:.0f}ms")
            elif avg_highlight_cache_hit is not None:
                st.caption(f"캐시 히트: {avg_highlight_cache_hit:.0f}ms")
            elif avg_highlight_cache_miss is not None:
                st.caption(f"캐시 미스: {avg_highlight_cache_miss:.0f}ms")
        else:
            st.metric("평균 하이라이트 속도", "N/A")
    
    # 95 percentile latency
    if highlight_latencies:
        p95_latency = pd.Series(highlight_latencies).quantile(0.95)
        with col5:
            st.metric("95% 하이라이트 속도", f"{p95_latency:.0f}ms")
    else:
        with col5:
            st.metric("95% 하이라이트 속도", "N/A")
    
    # 챗봇 응답 속도
    chat_response_events = df_view[df_view["event_name"].isin(["chat_response", "glossary_answer"])].copy()
    chat_latencies = []
    for idx, row in chat_response_events.iterrows():
        # 여러 소스에서 latency_ms 추출 시도
        latency_ms = None
        
        # 1. perf_data에서 추출
        perf_data = _extract_perf_data(row)
        if perf_data and isinstance(perf_data, dict):
            latency_ms = perf_data.get("latency_ms")
            # latency_ms가 없으면 total_ms 사용
            if latency_ms is None:
                latency_ms = perf_data.get("total_ms")
        
        # 2. payload에서 직접 추출
        if latency_ms is None:
            payload = _parse_payload(row.get("payload"))
            if payload:
                latency_ms = payload.get("latency_ms")
                if latency_ms is None:
                    latency_ms = payload.get("total_ms")
        
        # 3. 컬럼에서 직접 추출
        if latency_ms is None:
            latency_ms = row.get("latency_ms")
        
        if latency_ms is not None:
            try:
                latency_value = float(latency_ms)
                # 유효한 값만 추가 (0보다 크고 합리적인 범위 내)
                if latency_value > 0 and latency_value < 1000000:  # 1000초 이상은 제외
                    chat_latencies.append(latency_value)
            except (ValueError, TypeError):
                pass
    avg_chat_latency = sum(chat_latencies) / len(chat_latencies) if chat_latencies else None
    with col6:
        if avg_chat_latency is not None:
            st.metric("평균 챗봇 응답 속도", f"{avg_chat_latency:.0f}ms")
        else:
            st.metric("평균 챗봇 응답 속도", "N/A")
    
    st.markdown("---")
    
    # ========== B. 이용 패턴 (Line Chart) ==========
    st.markdown("#### 📈 이용 패턴 추이")
    
    # 선택한 기간이 1일 이하면 시간별, 그 외에는 일자별로 표시
    use_hourly = date_range_days is not None and date_range_days <= 1
    
    if "date" in df_view.columns and px is not None:
        if use_hourly and "hour" in df_view.columns:
            # 시간별 추이 (하루만 선택한 경우)
            # 1. 시간별 뉴스 클릭 추이
            hourly_news_clicks = df_view[df_view["event_name"] == "news_click"].groupby("hour").size().reset_index(name="클릭 수")
            
            if len(hourly_news_clicks) > 0:
                hourly_news_clicks = hourly_news_clicks.sort_values("hour")
                
                fig1 = px.line(
                    hourly_news_clicks,
                    x="hour",
                    y="클릭 수",
                    title="시간별 뉴스 클릭 추이",
                    labels={"hour": "시간 (시)", "클릭 수": "클릭 수"}
                )
                fig1.update_xaxes(tickmode='linear', tick0=0, dtick=3, tickformat='%H시')
                st.plotly_chart(fig1, use_container_width=True)
                st.dataframe(hourly_news_clicks, use_container_width=True, height=200)
            
            # 2. 시간별 Glossary 사용 세션 비율 추이
            hourly_sessions = df_view.groupby("hour")[session_column].nunique().reset_index(name="전체 세션")
            hourly_glossary_sessions = df_view[df_view["event_name"] == "glossary_click"].groupby("hour")[session_column].nunique().reset_index(name="Glossary 세션")
            
            if len(hourly_sessions) > 0 and len(hourly_glossary_sessions) > 0:
                hourly_usage = hourly_sessions.merge(hourly_glossary_sessions, on="hour", how="left")
                hourly_usage["Glossary 세션"] = hourly_usage["Glossary 세션"].fillna(0)
                hourly_usage["사용 비율 (%)"] = (hourly_usage["Glossary 세션"] / hourly_usage["전체 세션"] * 100).fillna(0)
                hourly_usage = hourly_usage.sort_values("hour")
                
                fig2 = px.line(
                    hourly_usage,
                    x="hour",
                    y="사용 비율 (%)",
                    title="시간별 Glossary 사용 세션 비율 추이",
                    labels={"hour": "시간 (시)", "사용 비율 (%)": "비율 (%)"}
                )
                fig2.update_xaxes(tickmode='linear', tick0=0, dtick=3, tickformat='%H시')
                st.plotly_chart(fig2, use_container_width=True)
                st.dataframe(hourly_usage[["hour", "전체 세션", "Glossary 세션", "사용 비율 (%)"]], use_container_width=True, height=200)
        else:
            # 일자별 추이 (여러 날짜 선택한 경우)
            # 1. 일자별 뉴스 클릭 추이
            daily_news_clicks = df_view[df_view["event_name"] == "news_click"].groupby("date").size().reset_index(name="클릭 수")
            
            if len(daily_news_clicks) > 0:
                # 날짜를 datetime으로 변환 (시간 정보 제거)
                daily_news_clicks["date_dt"] = pd.to_datetime(daily_news_clicks["date"])
                daily_news_clicks = daily_news_clicks.sort_values("date_dt")
                
                fig1 = px.line(
                    daily_news_clicks,
                    x="date_dt",
                    y="클릭 수",
                    title="일자별 뉴스 클릭 추이",
                    labels={"date_dt": "날짜", "클릭 수": "클릭 수"}
                )
                # X축 포맷을 날짜만 표시하도록 설정
                fig1.update_xaxes(tickformat='%Y-%m-%d', dtick="D1")
                st.plotly_chart(fig1, use_container_width=True)
                # 날짜를 문자열로 변환하여 표시
                display_df1 = daily_news_clicks.copy()
                display_df1["날짜"] = display_df1["date"].astype(str)
                st.dataframe(display_df1[["날짜", "클릭 수"]], use_container_width=True, height=200)
            
            # 2. Glossary 사용 세션 비율 추이
            daily_sessions = df_view.groupby("date")[session_column].nunique().reset_index(name="전체 세션")
            daily_glossary_sessions = df_view[df_view["event_name"] == "glossary_click"].groupby("date")[session_column].nunique().reset_index(name="Glossary 세션")
            
            if len(daily_sessions) > 0 and len(daily_glossary_sessions) > 0:
                daily_usage = daily_sessions.merge(daily_glossary_sessions, on="date", how="left")
                daily_usage["Glossary 세션"] = daily_usage["Glossary 세션"].fillna(0)
                daily_usage["사용 비율 (%)"] = (daily_usage["Glossary 세션"] / daily_usage["전체 세션"] * 100).fillna(0)
                # 날짜를 datetime으로 변환 (시간 정보 제거)
                daily_usage["date_dt"] = pd.to_datetime(daily_usage["date"])
                daily_usage = daily_usage.sort_values("date_dt")
                
                fig2 = px.line(
                    daily_usage,
                    x="date_dt",
                    y="사용 비율 (%)",
                    title="일자별 Glossary 사용 세션 비율 추이",
                    labels={"date_dt": "날짜", "사용 비율 (%)": "비율 (%)"}
                )
                # X축 포맷을 날짜만 표시하도록 설정
                fig2.update_xaxes(tickformat='%Y-%m-%d', dtick="D1")
                st.plotly_chart(fig2, use_container_width=True)
                # 날짜를 문자열로 변환하여 표시
                display_df2 = daily_usage.copy()
                display_df2["날짜"] = display_df2["date"].astype(str)
                st.dataframe(display_df2[["날짜", "전체 세션", "Glossary 세션", "사용 비율 (%)"]], use_container_width=True, height=200)
    
    st.markdown("---")
    
    # ========== C. 행동 흐름 (Funnel Chart) ==========
    st.markdown("#### 🔽 행동 흐름 분석")
    
    # 뉴스 → Glossary → 챗봇 전환 퍼널 (세션 기반, 순차적)
    # 순차적 퍼널: 각 단계는 이전 단계를 수행한 세션 중에서만 계산
    # 1단계: 뉴스 클릭한 세션 수
    news_click_sessions = df_view[df_view["event_name"] == "news_click"][session_column].nunique() if session_column in df_view.columns else 0
    
    if news_click_sessions > 0:
        # 각 이벤트별 세션 집합 생성 (교집합 계산을 위해 set 사용)
        news_sessions = set(df_view[df_view["event_name"] == "news_click"][session_column].dropna().unique())
        glossary_sessions = set(df_view[df_view["event_name"] == "glossary_click"][session_column].dropna().unique())
        chat_sessions = set(df_view[df_view["event_name"] == "chat_question"][session_column].dropna().unique())
        
        # 2단계: 뉴스 클릭한 세션 중에서 Glossary도 클릭한 세션 수 (순차적)
        # 교집합(&)을 사용하여 두 이벤트를 모두 수행한 세션만 계산
        glossary_after_news_sessions = len(news_sessions & glossary_sessions)  # 교집합
        
        # 3단계: 뉴스 클릭 AND Glossary 클릭한 세션 중에서 챗봇도 질문한 세션 수 (순차적)
        # 즉, 뉴스 → Glossary → 챗봇 순서로 모두 수행한 세션 수
        news_and_glossary_sessions = news_sessions & glossary_sessions
        chat_after_glossary_sessions = len(news_and_glossary_sessions & chat_sessions)  # 3단계 모두 수행한 세션
        
        # 전환율 계산 (이전 단계 대비)
        glossary_rate = (glossary_after_news_sessions / news_click_sessions * 100) if news_click_sessions > 0 else 0
        chat_rate = (chat_after_glossary_sessions / glossary_after_news_sessions * 100) if glossary_after_news_sessions > 0 else 0
        
        funnel_data = pd.DataFrame({
            "단계": ["뉴스 클릭", "Glossary 클릭", "챗봇 질문"],
            "세션 수": [news_click_sessions, glossary_after_news_sessions, chat_after_glossary_sessions],
            "전환율 (%)": [100.0, glossary_rate, chat_rate]
        })
        
        st.dataframe(funnel_data, use_container_width=True)
        
        if px is not None:
            fig3 = px.funnel(
                funnel_data,
                x="세션 수",
                y="단계",
                title="뉴스 → Glossary → 챗봇 전환 퍼널 (세션 기반, 순차적)"
            )
            st.plotly_chart(fig3, use_container_width=True)
    
    # 챗봇 검색 → 뉴스 클릭 전환 퍼널 (세션 기반)
    # 1단계: 챗봇 검색 실행한 세션 수
    search_sessions = df_view[df_view["event_name"] == "news_search_from_chat"][session_column].nunique() if session_column in df_view.columns else 0
    
    if search_sessions > 0:
        # 2단계: 검색 실행한 세션 중에서 뉴스도 클릭한 세션 수
        search_session_set = set(df_view[df_view["event_name"] == "news_search_from_chat"][session_column].dropna().unique())
        selected_session_set = set(df_view[df_view["event_name"] == "news_selected_from_chat"][session_column].dropna().unique())
        selected_after_search_sessions = len(search_session_set & selected_session_set)  # 교집합
        
        # 전환율 계산
        selected_rate = (selected_after_search_sessions / search_sessions * 100) if search_sessions > 0 else 0
        
        chat_funnel_data = pd.DataFrame({
            "단계": ["챗봇 검색 실행", "검색 결과 뉴스 클릭"],
            "세션 수": [search_sessions, selected_after_search_sessions],
            "전환율 (%)": [100.0, selected_rate]
        })
        
        st.dataframe(chat_funnel_data, use_container_width=True)
        
        if px is not None:
            fig3b = px.funnel(
                chat_funnel_data,
                x="세션 수",
                y="단계",
                title="챗봇 검색 → 뉴스 클릭 전환 퍼널 (세션 기반)"
            )
            st.plotly_chart(fig3b, use_container_width=True)
    
    st.markdown("---")
    
    # ========== D. 검색 결과 뉴스 인기 분석 ==========
    st.markdown("#### 🔍 검색 결과 뉴스 인기 분석")
    
    # 검색 결과에 포함된 뉴스와 실제 클릭된 뉴스 분석
    search_events = df_view[df_view["event_name"] == "news_search_from_chat"].copy()
    selected_events = df_view[df_view["event_name"] == "news_selected_from_chat"].copy()
    
    if len(search_events) > 0:
        # 검색 결과에 포함된 뉴스 ID 수집
        news_appearances = {}  # {news_id: {count: int, keywords: set}}
        
        for idx, row in search_events.iterrows():
            payload = _parse_payload(row.get("payload"))
            if payload and "article_ids" in payload:
                article_ids = payload.get("article_ids", [])
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
                
                # 제목 정보 수집
                payload = _parse_payload(row.get("payload"))
                if payload and "title" in payload and news_id_str not in news_titles:
                    news_titles[news_id_str] = payload.get("title", "")
        
        # 인기 뉴스 분석 데이터 생성
        if news_appearances:
            popularity_data = []
            for news_id, data in news_appearances.items():
                appearance_count = data["count"]
                click_count = news_clicks.get(news_id, 0)
                click_rate = (click_count / appearance_count * 100) if appearance_count > 0 else 0
                title = news_titles.get(news_id, f"뉴스 ID: {news_id}")
                
                popularity_data.append({
                    "news_id": news_id,
                    "제목": title[:50] + "..." if len(title) > 50 else title,
                    "검색 결과 포함": appearance_count,
                    "클릭 수": click_count,
                    "클릭률 (%)": round(click_rate, 1)
                })
            
            if popularity_data:
                popularity_df = pd.DataFrame(popularity_data)
                popularity_df = popularity_df.sort_values("클릭 수", ascending=False).head(10)
                
                if px is not None and len(popularity_df) > 0:
                    fig_pop = px.bar(
                        popularity_df,
                        x="클릭 수",
                        y="제목",
                        orientation='h',
                        title="검색 결과에서 가장 많이 클릭된 뉴스 Top 10",
                        labels={"클릭 수": "클릭 수", "제목": "뉴스 제목"},
                        hover_data=["검색 결과 포함", "클릭률 (%)"]
                    )
                    st.plotly_chart(fig_pop, use_container_width=True)
                
                st.dataframe(popularity_df, use_container_width=True, height=300)
    
    st.markdown("---")
    
    # ========== E. 용어별 인기 분석 (Bar Chart) ==========
    st.markdown("#### 📊 용어별 인기 분석")
    
    glossary_clicks = df_view[df_view["event_name"] == "glossary_click"].copy()
    
    if len(glossary_clicks) > 0:
        # term 추출
        terms_list = []
        for idx, row in glossary_clicks.iterrows():
            term = _get_term_from_row(row)
            if term:
                terms_list.append(term)
        
        if terms_list:
            term_counts = pd.Series(terms_list).value_counts().head(10)
            term_df = pd.DataFrame({
                "용어": term_counts.index,
                "클릭 수": term_counts.values
            })
            
            if px is not None:
                fig4 = px.bar(
                    term_df,
                    x="클릭 수",
                    y="용어",
                    orientation='h',
                    title="Top 10 Glossary 용어",
                    labels={"클릭 수": "클릭 수", "용어": "용어"}
                )
                st.plotly_chart(fig4, use_container_width=True)
            
            st.dataframe(term_df, use_container_width=True, height=300)
    
    st.markdown("---")
    
    # ========== E. 성능 분석 ==========
    st.markdown("#### ⚡ 성능 분석")
    
    # 하이라이트 latency 데이터 추출 (캐시 히트/미스 구분)
    # Content Quality 탭의 성능 분석에서 사용
    detail_events = df_view[df_view["event_name"] == "news_detail_open"].copy()
    highlight_latencies_cache_miss = []  # 캐시 미스만 (실제 성능 문제 파악용)
    highlight_latencies_cache_hit = []   # 캐시 히트만 (참고용)
    highlight_latencies = []  # 전체 (fallback용 - 캐시 정보가 없을 때)
    
    for idx, row in detail_events.iterrows():
        perf_data = _extract_perf_data(row)
        if perf_data and isinstance(perf_data, dict):
            highlight_ms = perf_data.get("highlight_ms")
            cache_hit = perf_data.get("highlight_cache_hit", False)
            
            if highlight_ms is not None:
                try:
                    highlight_value = float(highlight_ms)
                    # 유효한 값만 추가 (0보다 크고 합리적인 범위 내)
                    if highlight_value > 0 and highlight_value < 100000:  # 100초 이상은 제외
                        highlight_latencies.append(highlight_value)
                        # 캐시 히트/미스 구분
                        if cache_hit:
                            highlight_latencies_cache_hit.append(highlight_value)
                        else:
                            highlight_latencies_cache_miss.append(highlight_value)
                except (ValueError, TypeError):
                    pass
    
    # 1. 하이라이트 latency 히스토그램 (캐시 히트/미스 구분)
    # 캐시 미스만 표시 (실제 성능 문제 파악용)
    if highlight_latencies_cache_miss and px is not None:
        fig5 = px.histogram(
            x=highlight_latencies_cache_miss,
            nbins=30,
            title="하이라이트 Latency 분포 (캐시 미스만)",
            labels={"x": "Latency (ms)", "count": "빈도"}
        )
        # 경고 영역 표시 (2초 이상)
        fig5.add_vline(x=2000, line_dash="dash", line_color="red", annotation_text="경고 영역 (2초)")
        st.plotly_chart(fig5, use_container_width=True)
        
        # 캐시 히트 분포도 별도로 표시 (참고용)
        if highlight_latencies_cache_hit and len(highlight_latencies_cache_hit) > 0:
            fig5b = px.histogram(
                x=highlight_latencies_cache_hit,
                nbins=30,
                title="하이라이트 Latency 분포 (캐시 히트만, 참고용)",
                labels={"x": "Latency (ms)", "count": "빈도"}
            )
            st.plotly_chart(fig5b, use_container_width=True)
    elif highlight_latencies and px is not None:
        # 캐시 정보가 없는 경우 전체 데이터 표시
        fig5 = px.histogram(
            x=highlight_latencies,
            nbins=30,
            title="하이라이트 Latency 분포",
            labels={"x": "Latency (ms)", "count": "빈도"}
        )
        # 경고 영역 표시 (2초 이상)
        fig5.add_vline(x=2000, line_dash="dash", line_color="red", annotation_text="경고 영역 (2초)")
        st.plotly_chart(fig5, use_container_width=True)
    
    # 2. 일자별 평균 하이라이트 latency
    if "date" in df_view.columns and highlight_latencies and len(detail_events) > 0:
        detail_events_with_date = detail_events.copy()
        if "date" not in detail_events_with_date.columns:
            detail_events_with_date["date"] = pd.to_datetime(detail_events_with_date["event_time"]).dt.date
        
        daily_highlight_latencies = []
        for date in detail_events_with_date["date"].unique():
            daily_events = detail_events_with_date[detail_events_with_date["date"] == date]
            daily_latencies = []
            for idx, row in daily_events.iterrows():
                perf_data = _extract_perf_data(row)
                if perf_data and isinstance(perf_data, dict):
                    highlight_ms = perf_data.get("highlight_ms")
                    if highlight_ms is not None:
                        try:
                            daily_latencies.append(float(highlight_ms))
                        except (ValueError, TypeError):
                            pass
            if daily_latencies:
                daily_highlight_latencies.append({
                    "date": date,
                    "평균 Latency (ms)": sum(daily_latencies) / len(daily_latencies)
                })
        
        if daily_highlight_latencies and px is not None:
            daily_latency_df = pd.DataFrame(daily_highlight_latencies)
            # 날짜를 datetime으로 변환 (시간 정보 제거)
            daily_latency_df["date_dt"] = pd.to_datetime(daily_latency_df["date"])
            daily_latency_df = daily_latency_df.sort_values("date_dt")
            fig6 = px.line(
                daily_latency_df,
                x="date_dt",
                y="평균 Latency (ms)",
                title="일자별 평균 하이라이트 Latency",
                labels={"date_dt": "날짜", "평균 Latency (ms)": "Latency (ms)"}
            )
            # X축 포맷을 날짜만 표시하도록 설정
            fig6.update_xaxes(tickformat='%Y-%m-%d', dtick="D1")
            st.plotly_chart(fig6, use_container_width=True)
    
    # 3. 챗봇 응답속도 Box plot
    if chat_latencies and px is not None:
        fig7 = px.box(
            y=chat_latencies,
            title="챗봇 응답속도 분포",
            labels={"y": "Latency (ms)"}
        )
        st.plotly_chart(fig7, use_container_width=True)
