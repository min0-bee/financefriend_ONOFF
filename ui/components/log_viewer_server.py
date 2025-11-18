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
import json

# requests 라이브러리
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

def _fetch_news_interactions(user_id: str) -> List[Dict[str, Any]]:
    """뉴스 상호작용 데이터 가져오기"""
    if not API_ENABLE or not REQUESTS_AVAILABLE:
        return []
    
    try:
        url = f"{API_BASE_URL}/api/v1/news/user/{user_id}/interactions"
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            # 리스트인지 확인
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return [data]
            return []
        return []
    except Exception as e:
        if API_ENABLE:
            st.warning(f"⚠️ 뉴스 상호작용 데이터 조회 실패: {str(e)}")
        return []


def _fetch_dialogues(session_id: Optional[int] = None, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """대화 데이터 가져오기
    
    서버가 session_id를 필수로 요구하므로:
    - session_id가 있으면 직접 조회
    - user_id만 있으면 먼저 세션을 조회한 후 각 세션의 대화를 조회
    """
    if not API_ENABLE or not REQUESTS_AVAILABLE:
        return []
    
    # session_id가 있으면 직접 조회
    if session_id:
        try:
            url = f"{API_BASE_URL}/api/v1/dialogues/"
            params = {"session_id": session_id}
            response = requests.get(url, params=params, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict):
                    return [data]
                return []
            else:
                if API_ENABLE:
                    try:
                        error_detail = response.json()
                        st.warning(f"⚠️ 대화 데이터 조회 실패 (코드: {response.status_code}): {error_detail}")
                    except:
                        st.warning(f"⚠️ 대화 데이터 조회 실패 (코드: {response.status_code})")
            return []
        except Exception as e:
            if API_ENABLE:
                st.warning(f"⚠️ 대화 데이터 조회 실패: {str(e)}")
            return []
    
    # user_id만 있으면 세션을 먼저 조회한 후 각 세션의 대화를 조회
    if user_id:
        try:
            # 먼저 해당 user_id의 모든 세션 조회
            sessions_url = f"{API_BASE_URL}/api/v1/sessions/"
            sessions_params = {"user_id": user_id}
            sessions_response = requests.get(sessions_url, params=sessions_params, timeout=5)
            
            if sessions_response.status_code != 200:
                return []
            
            sessions_data = sessions_response.json()
            if not isinstance(sessions_data, list):
                return []
            
            # 각 세션의 session_id로 대화 조회
            all_dialogues = []
            seen_dialogue_ids = set()  # 중복 제거용
            
            for session in sessions_data:
                sess_id = session.get("session_id")
                if not sess_id:
                    continue
                
                try:
                    url = f"{API_BASE_URL}/api/v1/dialogues/"
                    params = {"session_id": sess_id}
                    response = requests.get(url, params=params, timeout=5)
                    
                    if response.status_code == 200:
                        data = response.json()
                        dialogues = data if isinstance(data, list) else [data]
                        
                        # 중복 제거 (dialogue_id 기준)
                        for dialogue in dialogues:
                            dialogue_id = dialogue.get("dialogue_id")
                            if dialogue_id and dialogue_id not in seen_dialogue_ids:
                                seen_dialogue_ids.add(dialogue_id)
                                all_dialogues.append(dialogue)
                except Exception:
                    continue  # 개별 세션 조회 실패해도 계속 진행
            
            return all_dialogues
        except Exception as e:
            if API_ENABLE:
                st.warning(f"⚠️ 대화 데이터 조회 실패: {str(e)}")
            return []
    
    # session_id와 user_id가 모두 없으면 빈 리스트 반환
    return []


def _fetch_sessions(user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """세션 데이터 가져오기"""
    if not API_ENABLE or not REQUESTS_AVAILABLE:
        return []
    
    try:
        url = f"{API_BASE_URL}/api/v1/sessions/"
        params = {}
        if user_id:
            params["user_id"] = user_id
        
        response = requests.get(url, params=params, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            # 리스트인지 확인
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return [data]
            return []
        return []
    except Exception as e:
        if API_ENABLE:
            st.warning(f"⚠️ 세션 데이터 조회 실패: {str(e)}")
        return []


def _fetch_agent_tasks(session_id: Optional[int] = None, dialogue_id: Optional[int] = None, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """에이전트 작업 데이터 가져오기 (TERM 정보 포함)
    
    서버가 session_id를 필수로 요구할 수 있으므로:
    - session_id가 있으면 직접 조회
    - user_id만 있으면 먼저 세션을 조회한 후 각 세션의 agent_tasks를 조회
    """
    if not API_ENABLE or not REQUESTS_AVAILABLE:
        return []
    
    # session_id가 있으면 직접 조회
    if session_id:
        try:
            url = f"{API_BASE_URL}/api/v1/agent-tasks/"
            params = {"session_id": session_id}
            if dialogue_id:
                params["dialogue_id"] = dialogue_id
            
            response = requests.get(url, params=params, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict):
                    return [data]
                return []
            else:
                # 에러 응답 로깅 (디버깅용)
                if API_ENABLE:
                    try:
                        error_detail = response.json()
                        st.warning(f"⚠️ 에이전트 작업 조회 실패 (코드: {response.status_code}): {error_detail}")
                    except:
                        st.warning(f"⚠️ 에이전트 작업 조회 실패 (코드: {response.status_code})")
            return []
        except Exception as e:
            if API_ENABLE:
                st.warning(f"⚠️ 에이전트 작업 데이터 조회 실패: {str(e)}")
            return []
    
    # user_id만 있으면 세션을 먼저 조회한 후 각 세션의 agent_tasks를 조회
    if user_id:
        try:
            # 먼저 해당 user_id의 모든 세션 조회
            sessions_url = f"{API_BASE_URL}/api/v1/sessions/"
            sessions_params = {"user_id": user_id}
            sessions_response = requests.get(sessions_url, params=sessions_params, timeout=5)
            
            if sessions_response.status_code != 200:
                return []
            
            sessions_data = sessions_response.json()
            if not isinstance(sessions_data, list):
                return []
            
            # 각 세션의 session_id로 agent_tasks 조회
            all_agent_tasks = []
            seen_task_ids = set()  # 중복 제거용
            
            for session in sessions_data:
                sess_id = session.get("session_id")
                if not sess_id:
                    continue
                
                try:
                    url = f"{API_BASE_URL}/api/v1/agent-tasks/"
                    params = {"session_id": sess_id}
                    if dialogue_id:
                        params["dialogue_id"] = dialogue_id
                    
                    response = requests.get(url, params=params, timeout=5)
                    
                    if response.status_code == 200:
                        data = response.json()
                        tasks = data if isinstance(data, list) else [data]
                        
                        # 중복 제거 (task_id 기준)
                        for task in tasks:
                            task_id = task.get("task_id")
                            if task_id and task_id not in seen_task_ids:
                                seen_task_ids.add(task_id)
                                all_agent_tasks.append(task)
                except Exception:
                    continue  # 개별 세션 조회 실패해도 계속 진행
            
            return all_agent_tasks
        except Exception as e:
            if API_ENABLE:
                st.warning(f"⚠️ 에이전트 작업 데이터 조회 실패: {str(e)}")
            return []
    
    # session_id와 user_id가 모두 없으면 빈 리스트 반환
    return []


def _fetch_users(user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """사용자 데이터 가져오기"""
    if not API_ENABLE or not REQUESTS_AVAILABLE:
        return []
    
    try:
        url = f"{API_BASE_URL}/api/v1/users/"
        params = {}
        if user_id:
            params["user_id"] = user_id
        
        response = requests.get(url, params=params, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            # 리스트인지 확인
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return [data]
            return []
        return []
    except Exception as e:
        if API_ENABLE:
            st.warning(f"⚠️ 사용자 데이터 조회 실패: {str(e)}")
        return []


def _fetch_news(news_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """뉴스 데이터 가져오기"""
    if not API_ENABLE or not REQUESTS_AVAILABLE:
        return []
    
    try:
        if news_id:
            url = f"{API_BASE_URL}/api/v1/news/{news_id}"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                return [data] if isinstance(data, dict) else []
        else:
            url = f"{API_BASE_URL}/api/v1/news/"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict):
                    return [data]
        return []
    except Exception as e:
        if API_ENABLE:
            st.warning(f"⚠️ 뉴스 데이터 조회 실패: {str(e)}")
        return []


def _convert_to_events_df(
    news_interactions: List[Dict],
    dialogues: List[Dict],
    sessions: List[Dict],
    agent_tasks: List[Dict] = None
) -> pd.DataFrame:
    """서버 데이터를 이벤트 DataFrame으로 변환"""
    events = []

    # 세션 정보에서 user_id 매핑 준비
    session_user_map: Dict[str, str] = {}
    session_surface_map: Dict[str, str] = {}
    if sessions:
        for sess in sessions:
            sess_id = sess.get("session_id")
            if sess_id is None:
                continue
            sess_key = str(sess_id)
            session_user_map[sess_key] = sess.get("user_id", "") or ""
            context = sess.get("context") or {}
            if isinstance(context, dict):
                session_surface_map[sess_key] = context.get("surface", "") or ""
    
    # agent_tasks를 dialogue_id로 매핑 (TERM 정보 추출용)
    term_map = {}  # dialogue_id -> term
    if agent_tasks:
        for task in agent_tasks:
            dialogue_id = task.get("dialogue_id")
            if dialogue_id:
                input_data = task.get("input_data", {})
                if isinstance(input_data, dict):
                    term = input_data.get("term", "")
                    if term:
                        term_map[dialogue_id] = term
    
    # 뉴스 상호작용 → 이벤트 (원래 이벤트 이름 복원)
    for interaction in news_interactions:
        interaction_type = interaction.get('interaction_type', 'unknown')
        
        # 원래 이벤트 이름 복원 시도
        # 1. metadata에서 original_event_name 찾기
        original_event_name = None
        metadata = interaction.get('metadata') or interaction.get('payload') or {}
        if isinstance(metadata, dict):
            original_event_name = metadata.get('original_event_name')
        
        # 2. 원래 이벤트 이름이 없으면 interaction_type 기반으로 추론
        if not original_event_name:
            # interaction_type → 이벤트 이름 역매핑
            if interaction_type == "click":
                original_event_name = "news_click"
            elif interaction_type == "view":
                # view는 news_detail_open 또는 news_view일 수 있음
                # 추가 정보가 없으면 기본값으로 news_detail_open 추정
                original_event_name = "news_detail_open"
            elif interaction_type == "share":
                original_event_name = "news_share"
            elif interaction_type == "like":
                original_event_name = "news_like"
            elif interaction_type == "bookmark":
                original_event_name = "news_bookmark"
            else:
                original_event_name = f"news_{interaction_type}"
        
        events.append({
            "event_id": f"interaction_{interaction.get('interaction_id', '')}",
            "event_time": interaction.get("created_at", ""),
            "event_name": original_event_name or f"news_{interaction_type}",
            "user_id": interaction.get("user_id", ""),
            "session_id": "",  # 상호작용에는 session_id가 없을 수 있음
            "news_id": interaction.get("news_id", ""),
            "term": "",
            "message": "",
            "surface": metadata.get("surface", "") if isinstance(metadata, dict) else "",
            "source": metadata.get("source", "") if isinstance(metadata, dict) else "",
        })
    
    # 대화 → 이벤트 (TERM 정보 포함)
    for dialogue in dialogues:
        sender_type = dialogue.get("sender_type", "")
        intent = dialogue.get("intent", "")
        dialogue_id = dialogue.get("dialogue_id")
        
        # intent 기반 이벤트 이름 결정
        if sender_type == "user":
            if intent in ("question", "glossary_question"):
                event_name = "chat_question" if intent == "question" else "glossary_click"
            else:
                event_name = "chat_message"
        elif sender_type == "assistant":
            if intent in ("answer", "glossary_explanation"):
                event_name = "chat_answer" if intent == "answer" else "glossary_answer"
            else:
                event_name = "chat_response"
        else:
            event_name = "chat_message"
        
        # TERM 정보 추출 (agent_tasks에서)
        term = ""
        if dialogue_id and dialogue_id in term_map:
            term = term_map[dialogue_id]
        # intent에서도 term 추출 시도
        if not term and intent in ("glossary_question", "glossary_explanation"):
            # intent에서 term 추출이 가능한지 확인 (현재는 agent_tasks에서만 가능)
            pass
        
        session_id_val = dialogue.get("session_id")
        session_key = str(session_id_val) if session_id_val is not None else ""
        user_id_val = dialogue.get("user_id") or session_user_map.get(session_key, "")
        surface_val = dialogue.get("surface") or session_surface_map.get(session_key, "")

        events.append({
            "event_id": f"dialogue_{dialogue_id or ''}",
            "event_time": dialogue.get("created_at", ""),
            "event_name": event_name,
            "user_id": user_id_val,
            "session_id": session_id_val or "",
            "news_id": "",
            "term": term,  # agent_tasks에서 가져온 TERM 정보
            "message": dialogue.get("content", ""),  # 대화 내용 (MESSAGE)
            "surface": surface_val,
            "source": "",
            "intent": intent,  # 추가 정보
        })
    
    if not events:
        return pd.DataFrame()
    
    df = pd.DataFrame(events)
    
    # event_time을 datetime으로 변환
    if "event_time" in df.columns:
        df["event_time"] = pd.to_datetime(df["event_time"], errors="coerce")
    
    # 시간순 정렬
    if "event_time" in df.columns:
        df = df.sort_values("event_time", ascending=False)
    
    return df


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
                    if isinstance(payload, dict):
                        return payload.get(key)
                    if isinstance(payload, str):
                        try:
                            data = json.loads(payload)
                            if isinstance(data, dict):
                                return data.get(key)
                        except Exception:
                            return None
                    return None
                
                # term 추출
                df["term_from_payload"] = df["payload"].apply(lambda p: _extract_from_payload(p, "term"))
                
                # ✅ news_id 추출 (payload에서)
                if "news_id" not in df.columns or df["news_id"].isna().all():
                    df["news_id_from_payload"] = df["payload"].apply(lambda p: _extract_from_payload(p, "news_id") or _extract_from_payload(p, "article_id"))
                    # 기존 news_id가 없거나 모두 None이면 payload에서 추출한 값 사용
                    if "news_id" not in df.columns:
                        df["news_id"] = df["news_id_from_payload"]
                    else:
                        df["news_id"] = df["news_id"].fillna(df["news_id_from_payload"])
                
                # ✅ latency_ms 추출 (payload에서)
                if "latency_ms" not in df.columns or df["latency_ms"].isna().all():
                    df["latency_ms_from_payload"] = df["payload"].apply(lambda p: _extract_from_payload(p, "latency_ms"))
                    # 기존 latency_ms가 없거나 모두 None이면 payload에서 추출한 값 사용
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
    event_time 기반으로 세션 ID를 추산합니다.
    세션 간 간격 임계값(threshold_minutes)보다 큰 경우 새로운 세션으로 간주합니다.
    """
    if df.empty or time_column not in df.columns:
        result = df.copy()
        if "session_id" in result.columns:
            result["session_id_resolved"] = result["session_id"]
        return result

    work = df.copy()
    work[time_column] = pd.to_datetime(work[time_column], errors="coerce")

    # 세션 분리를 위한 사용자 구분 값 준비
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
        # 빈 문자열 또는 NaN을 차례대로 채우기
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


def render():
    """
    서버에서 데이터를 가져와서 로그 뷰어 렌더링
    
    ✅ 멘토링용: 모든 사용자가 접근 가능
    """
    from core.logger import _get_user_id
    
    st.markdown("## 📊 로그 뷰어")

    # event_log 중심 모드 (Supabase에서 직접 가져오기) - 프로덕션 환경에서는 숨김
    # if not API_ENABLE and SUPABASE_ENABLE:
    #     st.info("📊 event_log 중심 모드: Supabase에서 데이터를 가져옵니다.")

    viewer_user_id = _get_user_id()

    with st.spinner("🔄 Supabase에서 이벤트 로그를 가져오는 중..."):
        df = _fetch_event_logs_from_supabase(user_id=None, limit=2000)

        if df.empty:
            st.info("📭 아직 이벤트 로그가 없습니다. 앱을 사용하면 데이터가 수집됩니다.")
            return

        df["event_time"] = _to_kst(df["event_time"])
        df = df.sort_values("event_time")

        unique_users = df["user_id"].dropna().unique().tolist()
        with st.expander("필터", expanded=True):
            col_user, col_time, col_event = st.columns([2, 2, 2])
            with col_user:
                if unique_users:
                    selected_user = st.selectbox(
                        "👤 사용자 필터",
                        options=["전체"] + unique_users,
                        index=0
                    )
                else:
                    selected_user = "전체"
            with col_time:
                now_kst = pd.Timestamp.now(tz="Asia/Seoul")
                time_ranges = {
                    "최근 10분": now_kst - pd.Timedelta(minutes=10),
                    "최근 1시간": now_kst - pd.Timedelta(hours=1),
                    "최근 6시간": now_kst - pd.Timedelta(hours=6),
                    "최근 24시간": now_kst - pd.Timedelta(hours=24),
                    "최근 3일": now_kst - pd.Timedelta(days=3),
                    "최근 7일": now_kst - pd.Timedelta(days=7),
                    "전체 기간": None,
                }
                selected_time_range = st.selectbox("⏱️ 기간 범위", list(time_ranges.keys()), index=2)
            with col_event:
                event_types = ["전체"] + sorted(df["event_name"].dropna().unique().tolist())
                selected_event_type = st.selectbox("🏷️ 이벤트 타입 필터", event_types)
            session_gap_minutes = st.slider(
                "세션 간 최대 허용 공백 (분)",
                min_value=5,
                max_value=240,
                step=5,
                value=st.session_state.get("log_viewer_session_gap_supabase", 30),
                help="이 값보다 긴 시간 간격이 발생하면 새로운 세션으로 간주합니다."
            )
            st.session_state["log_viewer_session_gap_supabase"] = session_gap_minutes

        df = _fill_sessions_from_time(df, threshold_minutes=session_gap_minutes)
        session_column = "session_id_resolved" if "session_id_resolved" in df.columns else "session_id"

        df_view = df.copy()
        if selected_user != "전체":
            df_view = df_view[df_view["user_id"] == selected_user]
        if selected_time_range != "전체 기간":
            cutoff_time = time_ranges[selected_time_range]
            df_view = df_view[df_view["event_time"] >= cutoff_time]
        if selected_event_type != "전체":
            df_view = df_view[df_view["event_name"] == selected_event_type]

        session_count = df_view[session_column].nunique() if session_column in df_view.columns else 0
        st.caption(
            f"필터 결과: {len(df_view):,}건 / 세션 {session_count:,}개 / 사용자 {df_view['user_id'].nunique()}명 / 이벤트 종류 {df_view['event_name'].nunique()}개"
        )

        colA, colB, colC = st.columns(3)
        with colA:
            st.metric("뉴스 클릭", int((df_view["event_name"] == "news_click").sum()))
        with colB:
            st.metric("챗 질문", int((df_view["event_name"] == "chat_question").sum()))
        with colC:
            st.metric("RAG 답변", int((df_view["event_name"] == "glossary_answer").sum()))

        # ✅ 성능 분석 섹션 추가
        st.markdown("### ⚡ 성능 분석 (병목 지점 파악)")
        perf_events = df_view[df_view["event_name"].isin(["news_click", "news_detail_open", "glossary_click", "glossary_answer"])].copy()
        
        if not perf_events.empty and "payload" in perf_events.columns:
            import json
            
            def extract_perf_data(row):
                """payload에서 성능 데이터 추출 (event_name을 고려)"""
                try:
                    payload = row.get("payload") if isinstance(row, pd.Series) else row
                    event_name = row.get("event_name") if isinstance(row, pd.Series) else None
                    
                    if isinstance(payload, str):
                        payload = json.loads(payload)
                    if not isinstance(payload, dict):
                        return None
                    
                    # ✅ event_name에 따라 다른 처리
                    if event_name == "news_detail_open":
                        # news_detail_open 이벤트의 perf_steps 추출
                        perf_steps = payload.get("perf_steps")
                        if perf_steps and isinstance(perf_steps, dict):
                            # highlight_ms가 있으면 news_detail_open
                            if "highlight_ms" in perf_steps:
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
                        # news_click 이벤트의 성능 데이터 추출
                        click_process_ms = payload.get("click_process_ms")
                        if click_process_ms is not None:
                            return {
                                "click_process_ms": click_process_ms,
                                "content_length": payload.get("content_length"),
                            }
                    
                    elif event_name in ("glossary_click", "glossary_answer"):
                        # glossary_click/glossary_answer 이벤트의 성능 데이터 추출
                        perf_steps = payload.get("perf_steps")
                        if perf_steps and isinstance(perf_steps, dict):
                            # explanation_ms가 있으면 glossary_click
                            if "explanation_ms" in perf_steps:
                                return {
                                    "explanation_ms": perf_steps.get("explanation_ms"),
                                    "total_ms": perf_steps.get("total_ms"),
                                    "answer_length": perf_steps.get("answer_length"),
                                }
                    
                    # ✅ event_name이 없거나 알 수 없는 경우, perf_steps 구조로 판단
                    perf_steps = payload.get("perf_steps")
                    if perf_steps and isinstance(perf_steps, dict):
                        # highlight_ms가 있으면 news_detail_open
                        if "highlight_ms" in perf_steps:
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
                        # explanation_ms가 있으면 glossary_click
                        elif "explanation_ms" in perf_steps:
                            return {
                                "explanation_ms": perf_steps.get("explanation_ms"),
                                "total_ms": perf_steps.get("total_ms"),
                                "answer_length": perf_steps.get("answer_length"),
                            }
                    
                    # news_click 이벤트 체크 (perf_steps가 없는 경우)
                    click_process_ms = payload.get("click_process_ms")
                    if click_process_ms is not None:
                        return {
                            "click_process_ms": click_process_ms,
                            "content_length": payload.get("content_length"),
                        }
                    
                    return None
                except:
                    return None
            
            perf_events["perf_data"] = perf_events.apply(extract_perf_data, axis=1)
            perf_events_with_data = perf_events[perf_events["perf_data"].notna()]
            
            if not perf_events_with_data.empty:
                # news_detail_open 성능 분석
                detail_events = perf_events_with_data[perf_events_with_data["event_name"] == "news_detail_open"]
                if not detail_events.empty:
                    perf_df_data = []
                    for idx, row in detail_events.iterrows():
                        perf = row["perf_data"]
                        if perf and isinstance(perf, dict):
                            # ✅ news_id와 latency_ms를 payload에서도 추출 시도
                            news_id = row.get("news_id")
                            if not news_id or pd.isna(news_id):
                                # payload에서 추출 시도
                                payload_raw = row.get("payload")
                                if payload_raw:
                                    if isinstance(payload_raw, str):
                                        try:
                                            payload_dict = json.loads(payload_raw)
                                            news_id = news_id or payload_dict.get("news_id") or payload_dict.get("article_id")
                                        except:
                                            pass
                                    elif isinstance(payload_raw, dict):
                                        news_id = news_id or payload_raw.get("news_id") or payload_raw.get("article_id")
                            
                            latency_ms = row.get("latency_ms")
                            if not latency_ms or pd.isna(latency_ms):
                                # payload에서 추출 시도
                                payload_raw = row.get("payload")
                                if payload_raw:
                                    if isinstance(payload_raw, str):
                                        try:
                                            payload_dict = json.loads(payload_raw)
                                            latency_ms = latency_ms or payload_dict.get("latency_ms")
                                        except:
                                            pass
                                    elif isinstance(payload_raw, dict):
                                        latency_ms = latency_ms or payload_raw.get("latency_ms")
                            
                            cache_hit = perf.get("cache_hit", False)
                            highlight_cache_hit = perf.get("highlight_cache_hit", False)
                            terms_cache_hit = perf.get("terms_cache_hit", False)
                            
                            # 캐시 히트 표시 개선
                            cache_status = []
                            if highlight_cache_hit:
                                cache_status.append("하이라이트✅")
                            if terms_cache_hit:
                                cache_status.append("용어✅")
                            if not cache_status:
                                cache_status.append("❌")
                            
                            # ✅ 데이터 추출 및 검증
                            highlight_ms = perf.get("highlight_ms")
                            terms_filter_ms = perf.get("terms_filter_ms")
                            total_ms = perf.get("total_ms")
                            terms_count = perf.get("terms_count")
                            content_length = perf.get("content_length")
                            
                            # ✅ total_ms가 없거나 0이면 highlight_ms + terms_filter_ms로 추정
                            if not total_ms or total_ms == 0:
                                if highlight_ms is not None and terms_filter_ms is not None:
                                    total_ms = highlight_ms + terms_filter_ms
                            
                            perf_df_data.append({
                                "event_time": row.get("event_time"),
                                "news_id": news_id,
                                "latency_ms": latency_ms if latency_ms is not None else total_ms,  # latency_ms가 없으면 total_ms 사용
                                "하이라이트 처리 (ms)": highlight_ms if highlight_ms is not None else 0,
                                "용어 필터링 (ms)": terms_filter_ms if terms_filter_ms is not None else 0,
                                "전체 렌더링 (ms)": total_ms if total_ms is not None else 0,
                                "발견된 용어 수": terms_count if terms_count is not None else 0,
                                "기사 길이 (자)": content_length if content_length is not None else 0,
                                "캐시 히트": " / ".join(cache_status),  # ✅ 상세 캐시 히트 정보
                            })
                    
                    if perf_df_data:
                        perf_df = pd.DataFrame(perf_df_data)
                        perf_df = perf_df.sort_values("event_time", ascending=False)
                        
                        col1, col2 = st.columns(2)
                        with col1:
                            st.markdown("#### 📊 기사 렌더링 성능 통계")
                            if len(perf_df) > 0:
                                avg_highlight = perf_df["하이라이트 처리 (ms)"].mean()
                                avg_filter = perf_df["용어 필터링 (ms)"].mean()
                                avg_total = perf_df["전체 렌더링 (ms)"].mean()
                                # ✅ 캐시 히트율 계산 개선: 하이라이트 또는 용어 캐시 중 하나라도 히트면 캐시 히트로 간주
                                cache_hit_count = perf_df["캐시 히트"].str.contains("✅", na=False).sum()
                                cache_hit_rate = (cache_hit_count / len(perf_df) * 100) if len(perf_df) > 0 else 0
                                
                                st.metric("평균 하이라이트 처리", f"{avg_highlight:.0f}ms")
                                st.metric("평균 용어 필터링", f"{avg_filter:.0f}ms")
                                st.metric("평균 전체 렌더링", f"{avg_total:.0f}ms")
                                st.metric("캐시 히트율", f"{cache_hit_rate:.1f}%")
                        
                        with col2:
                            st.markdown("#### 🔍 병목 지점 분석")
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
                                    st.info("✅ 성능이 양호합니다.")
                        
                        st.markdown("#### 📋 상세 성능 데이터")
                        st.dataframe(perf_df.head(20), use_container_width=True, height=400)
                
                # news_click 성능 분석
                click_events = perf_events_with_data[perf_events_with_data["event_name"] == "news_click"]
                if not click_events.empty:
                    click_perf_data = []
                    for idx, row in click_events.iterrows():
                        perf = row["perf_data"]
                        if perf and isinstance(perf, dict):
                            click_perf_data.append({
                                "event_time": row.get("event_time"),
                                "news_id": row.get("news_id"),
                                "클릭 처리 (ms)": perf.get("click_process_ms"),
                                "기사 길이 (자)": perf.get("content_length"),
                            })
                    
                    if click_perf_data:
                        click_perf_df = pd.DataFrame(click_perf_data)
                        click_perf_df = click_perf_df.sort_values("event_time", ascending=False)
                        
                        st.markdown("#### 🖱️ 뉴스 클릭 성능")
                        avg_click = click_perf_df["클릭 처리 (ms)"].mean()
                        st.metric("평균 클릭 처리 시간", f"{avg_click:.0f}ms")
                        st.dataframe(click_perf_df.head(10), use_container_width=True, height=200)
                
                # glossary_click 성능 분석
                term_click_events = perf_events_with_data[perf_events_with_data["event_name"] == "glossary_click"]
                if not term_click_events.empty:
                    term_click_perf_data = []
                    for idx, row in term_click_events.iterrows():
                        perf = row["perf_data"]
                        if perf and isinstance(perf, dict):
                            # ✅ term과 news_id를 payload에서도 추출 시도
                            term = row.get("term")
                            if not term or pd.isna(term):
                                payload_raw = row.get("payload")
                                if payload_raw:
                                    if isinstance(payload_raw, str):
                                        try:
                                            payload_dict = json.loads(payload_raw)
                                            term = term or payload_dict.get("term")
                                        except:
                                            pass
                                    elif isinstance(payload_raw, dict):
                                        term = term or payload_raw.get("term")
                            
                            news_id = row.get("news_id")
                            if not news_id or pd.isna(news_id):
                                payload_raw = row.get("payload")
                                if payload_raw:
                                    if isinstance(payload_raw, str):
                                        try:
                                            payload_dict = json.loads(payload_raw)
                                            news_id = news_id or payload_dict.get("news_id") or payload_dict.get("article_id")
                                        except:
                                            pass
                                    elif isinstance(payload_raw, dict):
                                        news_id = news_id or payload_raw.get("news_id") or payload_raw.get("article_id")
                            
                            term_click_perf_data.append({
                                "event_time": row.get("event_time"),
                                "term": term,
                                "news_id": news_id,
                                "설명 생성 (ms)": perf.get("explanation_ms"),
                                "전체 처리 (ms)": perf.get("total_ms"),
                                "답변 길이 (자)": perf.get("answer_length"),
                            })
                    
                    if term_click_perf_data:
                        term_click_perf_df = pd.DataFrame(term_click_perf_data)
                        term_click_perf_df = term_click_perf_df.sort_values("event_time", ascending=False)
                        
                        col1, col2 = st.columns(2)
                        with col1:
                            st.markdown("#### 📌 용어 클릭 성능 통계")
                            if len(term_click_perf_df) > 0:
                                # ✅ nan 값 제외하고 평균 계산
                                explanation_col = term_click_perf_df["설명 생성 (ms)"].dropna()
                                total_col = term_click_perf_df["전체 처리 (ms)"].dropna()
                                answer_len_col = term_click_perf_df["답변 길이 (자)"].dropna()
                                
                                avg_explanation = explanation_col.mean() if len(explanation_col) > 0 else None
                                avg_total = total_col.mean() if len(total_col) > 0 else None
                                avg_answer_len = answer_len_col.mean() if len(answer_len_col) > 0 else None
                                
                                if avg_explanation is not None:
                                    st.metric("평균 설명 생성 시간", f"{avg_explanation:.0f}ms")
                                else:
                                    st.metric("평균 설명 생성 시간", "N/A")
                                
                                if avg_total is not None:
                                    st.metric("평균 전체 처리 시간", f"{avg_total:.0f}ms")
                                else:
                                    st.metric("평균 전체 처리 시간", "N/A")
                                
                                if avg_answer_len is not None:
                                    st.metric("평균 답변 길이", f"{avg_answer_len:.0f}자")
                                else:
                                    st.metric("평균 답변 길이", "N/A")
                        
                        with col2:
                            st.markdown("#### 🔍 용어 클릭 병목 분석")
                            if len(term_click_perf_df) > 0:
                                # ✅ nan 값 제외하고 비율 계산
                                valid_rows = term_click_perf_df[
                                    term_click_perf_df["설명 생성 (ms)"].notna() & 
                                    term_click_perf_df["전체 처리 (ms)"].notna() &
                                    (term_click_perf_df["전체 처리 (ms)"] > 0)
                                ]
                                
                                if len(valid_rows) > 0:
                                    explanation_pct = (valid_rows["설명 생성 (ms)"] / valid_rows["전체 처리 (ms)"] * 100).mean()
                                    st.write(f"**설명 생성 비율**: {explanation_pct:.1f}%")
                                    
                                    if explanation_pct > 80:
                                        st.warning("⚠️ 설명 생성이 주요 병목입니다!")
                                    elif explanation_pct > 50:
                                        st.info("💡 설명 생성 시간이 전체의 절반 이상을 차지합니다.")
                                    else:
                                        st.success("✅ 성능이 양호합니다.")
                                else:
                                    st.info("📊 유효한 성능 데이터가 부족합니다.")
                        
                        st.markdown("#### 📋 용어 클릭 상세 성능 데이터")
                        st.dataframe(term_click_perf_df.head(20), use_container_width=True, height=400)
            else:
                st.info("📊 성능 데이터가 아직 없습니다. 뉴스를 클릭하면 성능 데이터가 수집됩니다.")
        else:
            st.info("📊 성능 데이터를 분석할 수 없습니다. payload에 성능 정보가 없습니다.")

        st.markdown("### 🔄 전환 퍼널 요약")
        click_events = df_view[df_view["event_name"] == "news_click"]
        detail_events = df_view[df_view["event_name"] == "news_detail_open"]
        chat_events = df_view[df_view["event_name"] == "chat_question"]
        rag_events = df_view[df_view["event_name"] == "glossary_answer"]

        if not click_events.empty:
            first_click = click_events["event_time"].min()
            base_count = len(click_events)
            detail_count = (detail_events["event_time"] >= first_click).sum()
            chat_count = (chat_events["event_time"] >= first_click).sum()
            rag_count = (rag_events["event_time"] >= first_click).sum()
            funnel_df = pd.DataFrame([
                {"단계": "뉴스 클릭", "건수": base_count, "전환율 (%)": 100.0},
                {"단계": "뉴스 상세 열람", "건수": detail_count, "전환율 (%)": (detail_count / base_count * 100) if base_count else 0},
                {"단계": "챗 질문", "건수": chat_count, "전환율 (%)": (chat_count / base_count * 100) if base_count else 0},
                {"단계": "RAG 답변", "건수": rag_count, "전환율 (%)": (rag_count / base_count * 100) if base_count else 0},
            ])
            st.caption("기준 단위: 이벤트 발생 건수 (동일 유저의 여러 클릭 포함)")
            st.dataframe(funnel_df, use_container_width=True, height=200)
        else:
            st.info("퍼널을 계산할 클릭 이벤트가 없습니다.")

        st.markdown("### 📄 최근 이벤트 로그")
        display_columns = [
            "event_time", "event_name", "user_id", "session_id", "surface", "source", "ref_id"
        ]
        available_columns = [col for col in display_columns if col in df_view.columns]
        if available_columns:
            st.dataframe(
                df_view.sort_values("event_time", ascending=False)[available_columns].head(1000),
                use_container_width=True,
                height=420
            )
        else:
            st.dataframe(df_view.sort_values("event_time", ascending=False).head(1000), use_container_width=True, height=420)

        st.markdown("### 📊 이벤트 타입별 통계")
        event_counts = df_view["event_name"].value_counts().reset_index()
        event_counts.columns = ["이벤트 타입", "횟수"]
        st.dataframe(event_counts, use_container_width=True)
        if px is not None and not event_counts.empty:
            st.plotly_chart(
                px.pie(event_counts.head(15), names="이벤트 타입", values="횟수", title="이벤트 타입 비율(상위 15개)"),
                use_container_width=True
            )
        else:
            st.caption("⚠️ plotly 미설치 또는 데이터 부족으로 파이 차트를 표시할 수 없습니다.")

        st.markdown("### 🕒 세션 분석 (MVP)")
        if session_column in df_view.columns:
            sessions_summary = (
                df_view.dropna(subset=[session_column])
                      .groupby(session_column)
                      .agg(
                          사용자=("user_id", lambda x: next((u for u in x if isinstance(u, str) and u), "")),
                          첫_이벤트=("event_time", "min"),
                          마지막_이벤트=("event_time", "max"),
                          이벤트_수=("event_name", "count"),
                          이벤트_종류수=("event_name", "nunique"),
                      )
                      .reset_index()
            )
            if not sessions_summary.empty:
                durations = (sessions_summary["마지막_이벤트"] - sessions_summary["첫_이벤트"]).dt.total_seconds() / 60.0
                sessions_summary["세션_지속시간(분)"] = durations.fillna(0).round(1)
                st.dataframe(sessions_summary.head(50), use_container_width=True, height=320)

                duration_bins = [0, 5, 15, 30, 60, 120, 240, 480, float("inf")]
                duration_labels = ["0-5", "5-15", "15-30", "30-60", "60-120", "120-240", "240-480", "480+"]
                duration_hist = pd.Series(pd.cut(sessions_summary["세션_지속시간(분)"], bins=duration_bins, labels=duration_labels, right=False))
                duration_counts = duration_hist.value_counts().sort_index().rename_axis("지속시간 구간").reset_index(name="세션 수")
                if go is not None and make_subplots is not None and not duration_counts.empty:
                    total_sessions = duration_counts["세션 수"].sum()
                    duration_counts["누적 세션 수"] = duration_counts["세션 수"].cumsum()
                    duration_counts["누적 비율"] = (
                        duration_counts["누적 세션 수"] / total_sessions if total_sessions else 0
                    )
                    fig = make_subplots(specs=[[{"secondary_y": True}]])
                    fig.add_bar(
                        x=duration_counts["지속시간 구간"],
                        y=duration_counts["세션 수"],
                        name="세션 수",
                        marker_color="#1f77b4",
                    )
                    fig.add_trace(
                        go.Scatter(
                            x=duration_counts["지속시간 구간"],
                            y=duration_counts["누적 비율"],
                            name="누적 비율",
                            mode="lines+markers",
                            marker=dict(color="#ff7f0e"),
                        ),
                        secondary_y=True,
                    )
                    fig.update_yaxes(title_text="세션 수", secondary_y=False)
                    fig.update_yaxes(title_text="누적 비율", secondary_y=True, tickformat=".0%")
                    fig.update_layout(
                        title="세션 지속시간 분포",
                        hovermode="x unified",
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.bar_chart(duration_counts.set_index("지속시간 구간"))

                top_sessions = sessions_summary.sort_values("이벤트_수", ascending=False).head(15)
                st.bar_chart(top_sessions.set_index(session_column)["이벤트_수"])
            else:
                st.caption("세션 정보를 계산할 수 없습니다.")
        else:
            st.caption("세션 식별자를 계산하지 못했습니다.")

        st.markdown("### 🏷️ 용어 클릭/응답 통계")
        term_clicks = df_view[df_view["event_name"].isin(["glossary_click", "glossary_answer"])].copy()
        if "term" in term_clicks.columns:
            term_clicks["term_final"] = term_clicks["term"].fillna("")
        else:
            term_clicks["term_final"] = ""
        if "term_from_payload" in term_clicks.columns:
            term_clicks.loc[term_clicks["term_final"] == "", "term_final"] = term_clicks["term_from_payload"]
        term_clicks = term_clicks[term_clicks["term_final"].notna() & (term_clicks["term_final"] != "")]

        if not term_clicks.empty:
            term_summary = (
                term_clicks.groupby(["term_final", "event_name"])
                .size()
                .unstack(fill_value=0)
            )
            term_summary["total"] = term_summary.sum(axis=1)
            term_summary = term_summary.sort_values("total", ascending=False)
            st.dataframe(term_summary, use_container_width=True, height=260)
            top_terms = term_summary.head(15)
            st.bar_chart(top_terms["total"])
        else:
            st.caption("용어 클릭/응답 데이터가 없습니다.")

        st.markdown("### 👤 사용자 활동 요약")
        user_summary = (
            df_view.groupby("user_id", dropna=False)
                  .agg(
                      events=("event_name", "count"),
                      first_seen=("event_time", "min"),
                      last_seen=("event_time", "max"),
                      click_count=("event_name", lambda x: (x == "news_click").sum()),
                      detail_count=("event_name", lambda x: (x == "news_detail_open").sum()),
                      chat_count=("event_name", lambda x: (x == "chat_question").sum()),
                      rag_count=("event_name", lambda x: (x == "glossary_answer").sum()),
                  )
                  .reset_index()
                  .sort_values("events", ascending=False)
        )
        st.dataframe(user_summary, use_container_width=True, height=260)

        return
    
    # API 모드 (기존 로직)
    if not API_ENABLE:
        st.warning("⚠️ API가 비활성화되어 있고 Supabase도 비활성화되어 있습니다.")
        return
    
    # 현재 사용자 정보
    user_id = _get_user_id()
    
    # 세션이 없으면 생성 시도
    session_id = _get_backend_session_id()
    if not session_id:
        with st.spinner("🔄 세션 생성 중..."):
            session_id = _ensure_backend_session()
    
    if session_id:
        st.success(f"👤 사용자: `{user_id[:8]}...` | 세션: `{session_id}`")
    else:
        st.warning(f"⚠️ 사용자: `{user_id[:8]}...` | 세션: 생성 실패")
        st.info("💡 세션 생성 실패 원인 확인:")
        st.caption(f"- 서버 주소: `{API_BASE_URL}`")
        st.caption("- 사이드바의 '❌ 실패한 이벤트' 섹션에서 상세 에러 확인")
        st.caption("- 서버가 실행 중인지 확인하세요")
    
    # 데이터 가져오기
    with st.spinner("🔄 서버에서 데이터를 가져오는 중..."):
        news_interactions = _fetch_news_interactions(user_id)
        
        # 먼저 모든 세션을 가져옴
        sessions = _fetch_sessions(user_id)
        
        # 대화는 user_id로 조회 (내부에서 세션을 조회한 후 각 세션의 대화를 가져옴)
        # _fetch_dialogues가 user_id를 받아서 세션을 먼저 조회한 후 각 세션의 대화를 조회함
        dialogues = _fetch_dialogues(user_id=user_id)
        
        # 현재 세션의 대화도 추가로 조회 (혹시 모를 경우를 위해)
        if session_id:
            current_session_dialogues = _fetch_dialogues(session_id=session_id)
            # 중복 제거 (dialogue_id 기준)
            existing_ids = {d.get("dialogue_id") for d in dialogues if d.get("dialogue_id")}
            for cd in current_session_dialogues:
                if cd.get("dialogue_id") not in existing_ids:
                    dialogues.append(cd)
        
        # 에이전트 작업 가져오기 (TERM 정보 포함)
        # user_id 기반으로 모든 세션의 agent_tasks를 조회
        # _fetch_agent_tasks가 내부에서 세션을 조회한 후 각 세션의 agent_tasks를 가져옴
        agent_tasks = _fetch_agent_tasks(user_id=user_id)
        
        # 현재 세션의 agent_tasks도 추가로 조회 (혹시 모를 경우를 위해)
        if session_id:
            current_session_tasks = _fetch_agent_tasks(session_id=session_id)
            # 중복 제거 (task_id 기준)
            existing_task_ids = {t.get("task_id") for t in agent_tasks if t.get("task_id")}
            for ct in current_session_tasks:
                if ct.get("task_id") not in existing_task_ids:
                    agent_tasks.append(ct)
        
        # 사용자 데이터 가져오기
        users = _fetch_users(user_id=user_id)
        # 뉴스 데이터 가져오기 (현재 사용자의 상호작용이 있는 뉴스만)
        news_ids = set()
        for interaction in news_interactions:
            nid = interaction.get("news_id")
            if nid:
                news_ids.add(nid)
        news_list = []
        for nid in list(news_ids)[:50]:  # 최대 50개만 (성능 고려)
            news_data = _fetch_news(news_id=nid)
            news_list.extend(news_data)
    
    # 데이터 통계
    total_events = len(news_interactions) + len(dialogues)
    
    # 디버깅 정보 (개발용)
    with st.expander("🔍 디버깅 정보", expanded=False):
        st.caption(f"**조회 파라미터:**")
        st.caption(f"- user_id: `{user_id}`")
        st.caption(f"- session_id: `{session_id}`")
        st.caption(f"- 대화 조회: `{API_BASE_URL}/api/v1/dialogues/?user_id={user_id}` (내부적으로 세션별 조회)")
        st.caption(f"- 에이전트 작업 조회: `{API_BASE_URL}/api/v1/agent-tasks/?user_id={user_id}` (내부적으로 세션별 조회)")
        if session_id:
            st.caption(f"- 현재 세션 ID: `{session_id}`")
        st.caption(f"**조회된 데이터:**")
        st.caption(f"- 세션 수: {len(sessions)}")
        st.caption(f"- 대화 수: {len(dialogues)}")
        st.caption(f"- 에이전트 작업 수: {len(agent_tasks)}")
        if len(agent_tasks) == 0:
            st.warning("⚠️ 에이전트 작업 데이터가 없습니다.")
            if len(dialogues) > 0:
                st.info("💡 대화는 있지만 에이전트 작업이 없습니다.")
                st.caption("   가능한 원인:")
                st.caption("   1. `_log_agent_task`가 호출되지 않았을 수 있음")
                st.caption("   2. `output_data`가 비어있어서 로깅이 건너뛰어졌을 수 있음 (이제 via가 있으면 로깅됨)")
                st.caption("   3. 서버에 저장되지 않았을 수 있음")
            else:
                st.info("💡 대화 데이터도 없습니다. 앱을 사용하여 이벤트를 생성해보세요.")
    
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        st.metric("👥 사용자", len(users))
    with col2:
        st.metric("📰 뉴스", len(news_list))
    with col3:
        st.metric("📰 상호작용", len(news_interactions))
    with col4:
        st.metric("💬 대화", len(dialogues))
    with col5:
        st.metric("🔐 세션", len(sessions))
    with col6:
        st.metric("🤖 에이전트", len(agent_tasks))
    
    if total_events == 0:
        st.info("📭 아직 서버에 데이터가 없습니다. 앱을 사용하면 데이터가 수집됩니다.")
        return
    
    st.markdown("---")
    
    # 필터 및 집계 옵션
    filter_col1, filter_col2 = st.columns(2)
    
    with filter_col1:
        # 기간 필터
        time_filter = st.selectbox(
            "⏰ 기간 필터",
            options=["전체", "30분", "1시간", "반나절 (6시간)", "하루"],
            index=0,
            help="특정 기간 내의 데이터만 표시합니다"
        )
    
    with filter_col2:
        # 유저 기준 집계 버튼
        aggregate_by_user = st.button(
            "👤 유저 기준 집계",
            help="유저별로 데이터를 집계하여 표시합니다"
        )

    session_gap_minutes_api = st.slider(
        "세션 간 최대 허용 공백 (분)",
        min_value=5,
        max_value=240,
        step=5,
        value=st.session_state.get("log_viewer_session_gap_api", 30),
        help="이 값보다 긴 시간 간격이 발생하면 새로운 세션으로 간주합니다.",
        key="log_viewer_session_gap_api_slider"
    )
    st.session_state["log_viewer_session_gap_api"] = session_gap_minutes_api
    
    # 기간 필터 적용
    time_cutoff = None
    if time_filter != "전체":
        now = datetime.now()
        if time_filter == "30분":
            time_cutoff = now - timedelta(minutes=30)
        elif time_filter == "1시간":
            time_cutoff = now - timedelta(hours=1)
        elif time_filter == "반나절 (6시간)":
            time_cutoff = now - timedelta(hours=6)
        elif time_filter == "하루":
            time_cutoff = now - timedelta(days=1)
    
    # 기간 필터 적용 함수
    def filter_by_time(data_list: List[Dict], time_field: str = "created_at") -> List[Dict]:
        if not time_cutoff or not data_list:
            return data_list
        
        filtered = []
        for item in data_list:
            time_str = item.get(time_field)
            if time_str:
                try:
                    item_time = pd.to_datetime(time_str)
                    if item_time >= time_cutoff:
                        filtered.append(item)
                except:
                    # 파싱 실패 시 포함
                    filtered.append(item)
            else:
                # 시간 정보가 없으면 포함
                filtered.append(item)
        return filtered
    
    # 기간 필터 적용
    if time_cutoff:
        news_interactions = filter_by_time(news_interactions, "created_at")
        dialogues = filter_by_time(dialogues, "created_at")
        sessions = filter_by_time(sessions, "created_at")
        agent_tasks = filter_by_time(agent_tasks, "created_at")
    
    st.markdown("---")
    
    # 이벤트 통합 뷰 (TERM 정보 포함)
    df = _convert_to_events_df(news_interactions, dialogues, sessions, agent_tasks)
    
    # 세션 정보에서 session_start 이벤트 추가
    session_start_events = []
    for session in sessions:
        context = session.get("context", {})
        if isinstance(context, dict) and context.get("session_start"):
            session_start_events.append({
                "event_id": f"session_{session.get('session_id', '')}",
                "event_time": session.get("created_at", ""),
                "event_name": "session_start",
                "user_id": session.get("user_id", ""),
                "session_id": session.get("session_id", ""),
                "news_id": "",
                "term": "",
                "message": "",
                "surface": context.get("surface", ""),
                "source": "",
                "intent": "",
            })
    
    if session_start_events:
        session_start_df = pd.DataFrame(session_start_events)
        if "event_time" in session_start_df.columns:
            session_start_df["event_time"] = pd.to_datetime(session_start_df["event_time"], errors="coerce")
        if not df.empty:
            df = pd.concat([df, session_start_df], ignore_index=True)
            # 시간순 정렬
            if "event_time" in df.columns:
                df = df.sort_values("event_time", ascending=False)
        else:
            df = session_start_df
    
    df = _fill_sessions_from_time(df, threshold_minutes=session_gap_minutes_api)
    session_column = "session_id_resolved" if "session_id_resolved" in df.columns else "session_id"

    st.markdown("### 🕒 세션 분석 (MVP)")
    if session_column in df.columns:
        api_sessions_summary = (
            df.dropna(subset=[session_column])
              .groupby(session_column)
              .agg(
                  사용자=("user_id", lambda x: next((u for u in x if isinstance(u, str) and u), "")),
                  첫_이벤트=("event_time", "min"),
                  마지막_이벤트=("event_time", "max"),
                  이벤트_수=("event_name", "count"),
                  이벤트_종류수=("event_name", "nunique"),
              )
              .reset_index()
        )
        if not api_sessions_summary.empty:
            durations = (api_sessions_summary["마지막_이벤트"] - api_sessions_summary["첫_이벤트"]).dt.total_seconds() / 60.0
            api_sessions_summary["세션_지속시간(분)"] = durations.fillna(0).round(1)
            st.dataframe(api_sessions_summary.head(50), use_container_width=True, height=320)

            duration_bins = [0, 5, 15, 30, 60, 120, 240, 480, float("inf")]
            duration_labels = ["0-5", "5-15", "15-30", "30-60", "60-120", "120-240", "240-480", "480+"]
            duration_hist = pd.Series(pd.cut(api_sessions_summary["세션_지속시간(분)"], bins=duration_bins, labels=duration_labels, right=False))
            duration_counts = duration_hist.value_counts().sort_index().rename_axis("지속시간 구간").reset_index(name="세션 수")
            if go is not None and make_subplots is not None and not duration_counts.empty:
                total_sessions = duration_counts["세션 수"].sum()
                duration_counts["누적 세션 수"] = duration_counts["세션 수"].cumsum()
                duration_counts["누적 비율"] = (
                    duration_counts["누적 세션 수"] / total_sessions if total_sessions else 0
                )
                fig = make_subplots(specs=[[{"secondary_y": True}]])
                fig.add_bar(
                    x=duration_counts["지속시간 구간"],
                    y=duration_counts["세션 수"],
                    name="세션 수",
                    marker_color="#1f77b4",
                )
                fig.add_trace(
                    go.Scatter(
                        x=duration_counts["지속시간 구간"],
                        y=duration_counts["누적 비율"],
                        name="누적 비율",
                        mode="lines+markers",
                        marker=dict(color="#ff7f0e"),
                    ),
                    secondary_y=True,
                )
                fig.update_yaxes(title_text="세션 수", secondary_y=False)
                fig.update_yaxes(title_text="누적 비율", secondary_y=True, tickformat=".0%")
                fig.update_layout(
                    title="세션 지속시간 분포",
                    hovermode="x unified",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.bar_chart(duration_counts.set_index("지속시간 구간"))

            top_sessions = api_sessions_summary.sort_values("이벤트_수", ascending=False).head(15)
            st.bar_chart(top_sessions.set_index(session_column)["이벤트_수"])
        else:
            st.caption("세션 정보를 계산할 수 없습니다.")
    else:
        st.caption("세션 식별자를 계산하지 못했습니다.")
    
    # 유저 기준 집계 모드
    if aggregate_by_user:
        # 유저별 집계 데이터 생성
        user_stats = []
        
        # 각 유저별 통계
        for user in users:
            user_id_val = user.get("user_id")
            if not user_id_val:
                continue
            
            # 해당 유저의 데이터 필터링
            user_interactions = [ni for ni in news_interactions if ni.get("user_id") == user_id_val]
            user_sessions = [s for s in sessions if s.get("user_id") == user_id_val]
            user_session_ids = [s.get("session_id") for s in user_sessions]
            user_dialogues = [d for d in dialogues if d.get("session_id") in user_session_ids]
            user_agent_tasks = [at for at in agent_tasks if at.get("session_id") in user_session_ids]
            
            # 이벤트별 집계
            user_df_filtered = df[df["user_id"] == user_id_val] if not df.empty else pd.DataFrame()
            event_counts = user_df_filtered["event_name"].value_counts().to_dict() if not user_df_filtered.empty else {}
            
            user_stats.append({
                "user_id": user_id_val,
                "username": user.get("username", ""),
                "email": user.get("email", ""),
                "user_type": user.get("user_type", ""),
                "뉴스 상호작용": len(user_interactions),
                "대화": len(user_dialogues),
                "세션": len(user_sessions),
                "에이전트 작업": len(user_agent_tasks),
                "총 이벤트": len(user_interactions) + len(user_dialogues),
                "생성일": user.get("created_at", ""),
                **{f"{event}_횟수": count for event, count in event_counts.items()}
            })
        
        if user_stats:
            user_stats_df = pd.DataFrame(user_stats)
            st.markdown("### 👤 유저별 집계")
            if time_cutoff:
                st.caption(f"⏰ 기간 필터: {time_filter}")
            st.dataframe(user_stats_df, use_container_width=True, height=420)
            
            # 선택된 유저의 상세 데이터 보기
            if len(user_stats) > 0:
                st.markdown("---")
                selected_user_id = st.selectbox(
                    "📋 유저 선택 (상세 데이터 보기)",
                    options=[u["user_id"] for u in user_stats],
                    format_func=lambda x: next((u["username"] or u["user_id"][:8] for u in user_stats if u["user_id"] == x), x[:8])
                )
                
                if selected_user_id:
                    st.markdown(f"### 📊 유저 상세 데이터: `{selected_user_id[:8]}...`")
                    
                    # 선택된 유저의 데이터 필터링
                    selected_user_interactions = [ni for ni in news_interactions if ni.get("user_id") == selected_user_id]
                    selected_user_sessions = [s for s in sessions if s.get("user_id") == selected_user_id]
                    selected_user_session_ids = [s.get("session_id") for s in selected_user_sessions]
                    selected_user_dialogues = [d for d in dialogues if d.get("session_id") in selected_user_session_ids]
                    selected_user_df = df[df["user_id"] == selected_user_id] if not df.empty else pd.DataFrame()
                    
                    detail_tab1, detail_tab2, detail_tab3, detail_tab4, detail_tab5 = st.tabs([
                        "📄 전체 이벤트", 
                        "📰 상호작용", 
                        "💬 대화", 
                        "🔐 세션",
                        "📊 관심사 분석"
                    ])
                    
                    with detail_tab1:
                        st.caption(f"이벤트 스키마 기반 통합 뷰 ({len(selected_user_df)}개)")
                        if not selected_user_df.empty:
                            # 이벤트 스키마에 맞는 컬럼 표시
                            schema_columns = ["event_time", "event_name", "user_id", "session_id", "surface", "source", 
                                             "news_id", "term", "message", "note", "title", "click_count", "answer_len", 
                                             "via", "latency_ms", "payload"]
                            available_schema_columns = [col for col in schema_columns if col in selected_user_df.columns]
                            if available_schema_columns:
                                st.dataframe(selected_user_df[available_schema_columns], use_container_width=True, height=300)
                            else:
                                st.dataframe(selected_user_df, use_container_width=True, height=300)
                        else:
                            st.info("이벤트 데이터가 없습니다.")
                    
                    with detail_tab2:
                        st.caption(f"뉴스 상호작용 ({len(selected_user_interactions)}개)")
                        if selected_user_interactions:
                            st.dataframe(pd.DataFrame(selected_user_interactions), use_container_width=True, height=300)
                        else:
                            st.info("상호작용 데이터가 없습니다.")
                    
                    with detail_tab3:
                        st.caption(f"대화 기록 ({len(selected_user_dialogues)}개)")
                        if selected_user_dialogues:
                            st.dataframe(pd.DataFrame(selected_user_dialogues), use_container_width=True, height=300)
                        else:
                            st.info("대화 데이터가 없습니다.")
                    
                    with detail_tab4:
                        st.caption(f"세션 정보 ({len(selected_user_sessions)}개)")
                        if selected_user_sessions:
                            st.dataframe(pd.DataFrame(selected_user_sessions), use_container_width=True, height=300)
                        else:
                            st.info("세션 데이터가 없습니다.")
                    
                    with detail_tab5:
                        st.markdown("### 📊 유저 관심사 분석")
                        
                        # 초기화
                        news_counts = pd.DataFrame()
                        term_counts = pd.DataFrame()
                        
                        # 1. 뉴스 관심사 분석
                        st.markdown("#### 📰 관심 있는 뉴스 (클릭/조회 빈도)")
                        if selected_user_interactions:
                            interactions_df = pd.DataFrame(selected_user_interactions)
                            if "news_id" in interactions_df.columns:
                                # news_id별 집계
                                news_counts = interactions_df["news_id"].value_counts().reset_index()
                                news_counts.columns = ["news_id", "상호작용 횟수"]
                                news_counts = news_counts.sort_values("상호작용 횟수", ascending=False)
                                
                                # 뉴스 제목 정보 추가 (가능한 경우)
                                if news_list:
                                    news_df = pd.DataFrame(news_list)
                                    if "news_id" in news_df.columns and "title" in news_df.columns:
                                        news_counts = news_counts.merge(
                                            news_df[["news_id", "title"]], 
                                            on="news_id", 
                                            how="left"
                                        )
                                        # 컬럼 순서 조정
                                        news_counts = news_counts[["news_id", "title", "상호작용 횟수"]]
                                
                                st.dataframe(news_counts.head(20), use_container_width=True, height=300)
                                st.caption(f"총 {len(news_counts)}개의 서로 다른 뉴스에 관심을 보였습니다.")
                            else:
                                st.info("뉴스 ID 정보가 없습니다.")
                        else:
                            st.info("뉴스 상호작용 데이터가 없습니다.")
                        
                        st.markdown("---")
                        
                        # 2. 금융용어 관심사 분석 (클릭/질문 빈도)
                        st.markdown("#### 💡 관심 있는 금융용어 (클릭/질문 빈도)")
                        
                        # agent_tasks에서 term 추출
                        selected_user_agent_tasks = []
                        for sess in selected_user_sessions:
                            sess_id = sess.get("session_id")
                            if sess_id:
                                for at in agent_tasks:
                                    if at.get("session_id") == sess_id:
                                        selected_user_agent_tasks.append(at)
                        
                        if selected_user_agent_tasks:
                            terms_list = []
                            for task in selected_user_agent_tasks:
                                input_data = task.get("input_data", {})
                                if isinstance(input_data, dict):
                                    term = input_data.get("term", "")
                                    if term:
                                        terms_list.append(term)
                            
                            if terms_list:
                                # term별 빈도 집계
                                terms_df = pd.DataFrame({"term": terms_list})
                                term_counts = terms_df["term"].value_counts().reset_index()
                                term_counts.columns = ["용어", "클릭/질문 횟수"]
                                term_counts = term_counts.sort_values("클릭/질문 횟수", ascending=False)
                                
                                st.dataframe(term_counts.head(20), use_container_width=True, height=300)
                                st.caption(f"총 {len(term_counts)}개의 서로 다른 금융용어를 클릭/질문했습니다.")
                                
                                # 시각화 (선택)
                                if len(term_counts) > 0:
                                    if px is not None:
                                        top_terms = term_counts.head(10)
                                        fig = px.bar(
                                            top_terms, 
                                            x="용어", 
                                            y="클릭/질문 횟수",
                                            title="Top 10 관심 금융용어",
                                            labels={"용어": "금융용어", "클릭/질문 횟수": "클릭/질문 횟수"}
                                        )
                                        fig.update_xaxes(tickangle=45)
                                        st.plotly_chart(fig, use_container_width=True)
                                    else:
                                        st.caption("💡 plotly를 설치하면 시각화를 볼 수 있습니다: `pip install plotly`")
                            else:
                                st.info("금융용어 클릭/질문 데이터가 없습니다.")
                        else:
                            st.info("에이전트 작업 데이터가 없습니다.")
                        
                        st.markdown("---")
                        
                        # 3. 종합 통계
                        st.markdown("#### 📈 종합 통계")
                        stat_col1, stat_col2, stat_col3 = st.columns(3)
                        with stat_col1:
                            news_count_val = len(news_counts) if not news_counts.empty else 0
                            st.metric("관심 뉴스 수", news_count_val)
                        with stat_col2:
                            term_count_val = len(term_counts) if not term_counts.empty else 0
                            st.metric("관심 용어 수", term_count_val)
                        with stat_col3:
                            total_term_clicks = term_counts["클릭/질문 횟수"].sum() if not term_counts.empty else 0
                            st.metric("총 용어 클릭/질문", int(total_term_clicks))
        else:
            st.info("유저 데이터가 없습니다.")
        
        return  # 유저 집계 모드에서는 일반 탭을 표시하지 않음
    
    # 탭 구성 - 각 테이블별로 구분 (df가 비어있어도 다른 테이블은 표시)
    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
        "📄 전체 이벤트",
        "👥 Users",
        "📰 News",
        "📰 News Interactions",
        "💬 Dialogues",
        "🔐 Sessions",
        "🤖 Agent Tasks",
        "📊 관심사 분석"
    ])
    
    with tab1:
        if df.empty:
            if time_cutoff:
                st.warning(f"⚠️ 선택한 기간 ({time_filter}) 내에 이벤트 데이터가 없습니다.")
                st.info("💡 다른 기간을 선택하거나 다른 탭에서 데이터를 확인해보세요.")
            else:
                st.info("데이터를 변환할 수 없습니다.")
        else:
            # 기간 필터 적용된 이벤트 수 표시
            filtered_count = len(df)
            session_count = df[session_column].nunique() if session_column in df.columns else 0
            if time_cutoff:
                st.caption(f"총 {filtered_count}개의 이벤트 / 세션 {session_count:,}개 (기간 필터: {time_filter})")
            else:
                st.caption(f"총 {filtered_count}개의 이벤트 / 세션 {session_count:,}개 (뉴스 상호작용 + 대화 통합)")
            
            # 이벤트 스키마에 맞는 컬럼 표시
            schema_columns = ["event_time", "event_name", "user_id", "session_id", "surface", "source", 
                             "news_id", "term", "message", "note", "title", "click_count", "answer_len", 
                             "via", "latency_ms", "payload"]
            available_schema_columns = [col for col in schema_columns if col in df.columns]
            if available_schema_columns:
                st.dataframe(df[available_schema_columns], use_container_width=True, height=420)
            else:
                # 스키마 컬럼이 없으면 기본 컬럼 사용
                display_columns = ["event_time", "event_name", "term", "message", "user_id", "session_id", "news_id", "intent"]
                available_columns = [col for col in display_columns if col in df.columns]
                if available_columns:
                    st.dataframe(df[available_columns], use_container_width=True, height=420)
                else:
                    st.dataframe(df, use_container_width=True, height=420)
    
    with tab2:
        st.caption("👥 Users 테이블 - 사용자 정보")
        if time_cutoff:
            st.caption(f"⏰ 기간 필터: {time_filter}")
        if users:
            users_df = pd.DataFrame(users)
            st.dataframe(users_df, use_container_width=True, height=420)
        else:
            st.info("사용자 데이터가 없습니다.")
    
    with tab3:
        st.caption("📰 News 테이블 - 뉴스 기사 정보")
        if time_cutoff:
            st.caption(f"⏰ 기간 필터: {time_filter}")
        if news_list:
            news_df = pd.DataFrame(news_list)
            st.dataframe(news_df, use_container_width=True, height=420)
        else:
            st.info("뉴스 데이터가 없습니다.")
    
    with tab4:
        st.caption("📰 News Interactions 테이블 - 뉴스 상호작용 기록")
        if time_cutoff:
            st.caption(f"⏰ 기간 필터: {time_filter} ({len(news_interactions)}개)")
        else:
            st.caption(f"총 {len(news_interactions)}개")
        if news_interactions:
            interactions_df = pd.DataFrame(news_interactions)
            st.dataframe(interactions_df, use_container_width=True, height=420)
        else:
            st.info("뉴스 상호작용 데이터가 없습니다.")
    
    with tab5:
        st.caption("💬 Dialogues 테이블 - 대화 기록")
        if time_cutoff:
            st.caption(f"⏰ 기간 필터: {time_filter} ({len(dialogues)}개)")
        else:
            st.caption(f"총 {len(dialogues)}개")
        if dialogues:
            dialogues_df = pd.DataFrame(dialogues)
            st.dataframe(dialogues_df, use_container_width=True, height=420)
        else:
            st.info("대화 데이터가 없습니다.")
    
    with tab6:
        st.caption("🔐 Sessions 테이블 - 세션 정보")
        if time_cutoff:
            st.caption(f"⏰ 기간 필터: {time_filter} ({len(sessions)}개)")
        else:
            st.caption(f"총 {len(sessions)}개")
        if sessions:
            sessions_df = pd.DataFrame(sessions)
            st.dataframe(sessions_df, use_container_width=True, height=420)
        else:
            st.info("세션 데이터가 없습니다.")
    
    with tab7:
        st.caption("🤖 Agent Tasks 테이블 - 에이전트 작업 (TERM 정보 포함)")
        if time_cutoff:
            st.caption(f"⏰ 기간 필터: {time_filter} ({len(agent_tasks)}개)")
        else:
            st.caption(f"총 {len(agent_tasks)}개")
        if agent_tasks:
            tasks_df = pd.DataFrame(agent_tasks)
            st.dataframe(tasks_df, use_container_width=True, height=420)
        else:
            st.info("에이전트 작업 데이터가 없습니다.")
    
    with tab8:
        st.markdown("### 📊 전체 관심사 분석")
        
        if time_cutoff:
            st.caption(f"⏰ 기간 필터: {time_filter}")
        
        # 초기화
        news_counts = pd.DataFrame()
        term_counts = pd.DataFrame()
        
        # 1. 뉴스 관심사 분석
        st.markdown("#### 📰 관심 있는 뉴스 (클릭/조회 빈도)")
        if news_interactions:
            interactions_df = pd.DataFrame(news_interactions)
            if "news_id" in interactions_df.columns:
                # news_id별 집계
                news_counts = interactions_df["news_id"].value_counts().reset_index()
                news_counts.columns = ["news_id", "상호작용 횟수"]
                news_counts = news_counts.sort_values("상호작용 횟수", ascending=False)
                
                # 뉴스 제목 정보 추가 (가능한 경우)
                if news_list:
                    news_df = pd.DataFrame(news_list)
                    if "news_id" in news_df.columns and "title" in news_df.columns:
                        news_counts = news_counts.merge(
                            news_df[["news_id", "title"]], 
                            on="news_id", 
                            how="left"
                        )
                        # 컬럼 순서 조정
                        news_counts = news_counts[["news_id", "title", "상호작용 횟수"]]
                
                st.dataframe(news_counts.head(20), use_container_width=True, height=300)
                st.caption(f"총 {len(news_counts)}개의 서로 다른 뉴스에 관심을 보였습니다.")
            else:
                st.info("뉴스 ID 정보가 없습니다.")
        else:
            st.info("뉴스 상호작용 데이터가 없습니다.")
        
        st.markdown("---")
        
        # 2. 금융용어 관심사 분석 (클릭/질문 빈도)
        st.markdown("#### 💡 관심 있는 금융용어 (클릭/질문 빈도)")
        
        if agent_tasks:
            terms_list = []
            for task in agent_tasks:
                input_data = task.get("input_data", {})
                if isinstance(input_data, dict):
                    term = input_data.get("term", "")
                    if term:
                        terms_list.append(term)
            
            if terms_list:
                # term별 빈도 집계
                terms_df = pd.DataFrame({"term": terms_list})
                term_counts = terms_df["term"].value_counts().reset_index()
                term_counts.columns = ["용어", "클릭/질문 횟수"]
                term_counts = term_counts.sort_values("클릭/질문 횟수", ascending=False)
                
                st.dataframe(term_counts.head(20), use_container_width=True, height=300)
                st.caption(f"총 {len(term_counts)}개의 서로 다른 금융용어를 클릭/질문했습니다.")
                
                # 시각화 (선택)
                if len(term_counts) > 0:
                    if px is not None:
                        top_terms = term_counts.head(10)
                        fig = px.bar(
                            top_terms, 
                            x="용어", 
                            y="클릭/질문 횟수",
                            title="Top 10 관심 금융용어",
                            labels={"용어": "금융용어", "클릭/질문 횟수": "클릭/질문 횟수"}
                        )
                        fig.update_xaxes(tickangle=45)
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.caption("💡 plotly를 설치하면 시각화를 볼 수 있습니다: `pip install plotly`")
            else:
                st.info("금융용어 클릭/질문 데이터가 없습니다.")
        else:
            st.info("에이전트 작업 데이터가 없습니다.")
        
        st.markdown("---")
        
        # 3. 종합 통계
        st.markdown("#### 📈 종합 통계")
        stat_col1, stat_col2, stat_col3 = st.columns(3)
        with stat_col1:
            news_count_val = len(news_counts) if not news_counts.empty else 0
            st.metric("관심 뉴스 수", news_count_val)
        with stat_col2:
            term_count_val = len(term_counts) if not term_counts.empty else 0
            st.metric("관심 용어 수", term_count_val)
        with stat_col3:
            total_term_clicks = term_counts["클릭/질문 횟수"].sum() if not term_counts.empty else 0
            st.metric("총 용어 클릭/질문", int(total_term_clicks))

