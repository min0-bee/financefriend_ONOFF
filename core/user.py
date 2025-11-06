import os
import json
import uuid
import streamlit as st
from financefriend_ONOFF.core.config import USER_FILE     # 로컬에 저장될 user_info.json 파일 경로
from financefriend_ONOFF.core.utils import now_utc_iso    # 현재 UTC 시각을 ISO 포맷으로 반환하는 함수

# ─────────────────────────────────────────────────────────────
# 🧩 (1) 로컬 user_id 읽기
# ─────────────────────────────────────────────────────────────
def _read_local_user_id():
    """
    💾 로컬에 저장된 user_info.json에서 user_id를 읽어옵니다.
    - Streamlit 앱은 로그인 기능이 없으므로, 
      익명 사용자에게도 고유 user_id를 부여하고 로컬에 저장해 재사용합니다.
    - 예: {"user_id": "user_12ab34cd", "created_at": "2025-10-22T07:30:00Z"}
    """
    try:
        if os.path.exists(USER_FILE):
            with open(USER_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("user_id")  # user_id 키 반환
    except Exception:
        pass  # 파일 손상/권한 문제 시 None 반환
    return None


# ─────────────────────────────────────────────────────────────
# 🧩 (2) 로컬 user_id 쓰기
# ─────────────────────────────────────────────────────────────
def _write_local_user_id(uid: str):
    """
    📁 로컬에 새 user_id를 저장합니다.
    - logs/user_info.json 형태로 저장
    - 디렉토리가 없으면 자동 생성
    """
    try:
        os.makedirs(os.path.dirname(USER_FILE), exist_ok=True)
        with open(USER_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "user_id": uid,
                    "created_at": now_utc_iso(),  # UTC 기준 생성 시각
                    "user_type": "anonymous"       # 로그인 없는 익명 사용자
                },
                f,
                ensure_ascii=False,
            )
    except Exception:
        pass  # 권한 등 문제 시 무시 (앱 실행엔 영향 없음)


# ─────────────────────────────────────────────────────────────
# 🧩 (3) user_id 생성 또는 복원
# ─────────────────────────────────────────────────────────────
def get_or_create_user_id() -> str:
    """
    🎯 user_id를 가져오거나 새로 생성합니다.
    순서:
      1️⃣ URL 쿼리파라미터(uid) → 외부에서 전달된 경우
      2️⃣ 로컬 파일(user_info.json) → 이전 방문자
      3️⃣ 새 UUID 생성 → 최초 방문자
    """

    # 1️⃣ URL query parameter에서 uid 가져오기
    try:
        uid_from_qs = st.query_params.get("uid", None)
    except Exception:
        # Streamlit 구버전 호환
        uid_from_qs = None
        try:
            qs = st.experimental_get_query_params()
            if "uid" in qs:
                uid_from_qs = qs["uid"][0]
        except Exception:
            pass

    if uid_from_qs:
        # URL에 ?uid=~~~가 있으면 그걸 user_id로 사용
        return uid_from_qs

    # 2️⃣ 로컬 캐시된 user_id 사용
    uid_local = _read_local_user_id()
    if uid_local:
        # URL 파라미터로 다시 세팅 (새로고침 시 유지)
        try:
            st.query_params["uid"] = uid_local
        except Exception:
            try:
                st.experimental_set_query_params(uid=uid_local)
            except Exception:
                pass
        return uid_local

    # 3️⃣ 위 두 가지 모두 없으면 새 user_id 생성
    new_uid = f"user_{uuid.uuid4().hex[:8]}"  # 랜덤 8자리 UUID
    _write_local_user_id(new_uid)             # 로컬 저장

    # 생성된 user_id를 URL 파라미터에도 반영
    try:
        st.query_params["uid"] = new_uid
    except Exception:
        try:
            st.experimental_set_query_params(uid=new_uid)
        except Exception:
            pass

    return new_uid


# ─────────────────────────────────────────────────────────────
# 🧩 (4) 세션 및 유저 초기화
# ─────────────────────────────────────────────────────────────
def init_session_and_user():
    """
    🚀 Streamlit 세션 시작 시 기본 상태를 초기화합니다.
    - session_id : 브라우저를 새로 열 때마다 새로 생성
    - user_id    : get_or_create_user_id()로 식별
    - 기타 상태  : 페이지 입장 시각, 용어 클릭 횟수 등
    """

    # 세션 ID가 없으면 생성 (매 방문마다 고유)
    if "session_id" not in st.session_state:
        st.session_state.session_id = f"sess_{uuid.uuid4().hex[:12]}"

    # 사용자 ID가 없으면 로컬/URL/신규 순으로 확보
    if "user_id" not in st.session_state:
        st.session_state.user_id = get_or_create_user_id()

    # 부가 상태값 초기화
    st.session_state.setdefault("page_enter_time", None)  # 페이지 입장 시각
    st.session_state.setdefault("term_click_count", 0)    # 용어 클릭 횟수 누적