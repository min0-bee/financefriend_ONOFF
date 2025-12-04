import uuid
import streamlit as st
from streamlit_js_eval import streamlit_js_eval

BROWSER_STORAGE_KEY = "ff_user_id"

# ─────────────────────────────────────────────────────────────
# 🧩 (1) 브라우저 localStorage 처리
# ─────────────────────────────────────────────────────────────
# 로컬 파일 저장/읽기 함수는 제거되었습니다.
# 각 브라우저마다 고유한 user_id를 유지하기 위해 localStorage만 사용합니다.


def _get_user_id_from_browser_storage():
    """브라우저 localStorage에서 user_id 읽기"""
    try:
        value = streamlit_js_eval(
            js_expressions=f"window.localStorage.getItem('{BROWSER_STORAGE_KEY}')",
            key="get_user_id_from_storage",
            want_output=True,
        )
        if isinstance(value, str):
            value = value.strip()
            if value and value.lower() != "null":
                return value
        return None
    except Exception:
        return None


def _set_user_id_to_browser_storage(uid: str):
    """브라우저 localStorage에 user_id 저장"""
    try:
        streamlit_js_eval(
            js_expressions=f"window.localStorage.setItem('{BROWSER_STORAGE_KEY}', '{uid}')",
            key=f"set_user_id_{uid}",
            want_output=False,
        )
    except Exception:
        pass


def _set_query_param_uid(uid: str):
    """URL 쿼리 파라미터에 uid 반영"""
    try:
        st.query_params["uid"] = uid
    except Exception:
        try:
            st.experimental_set_query_params(uid=uid)
        except Exception:
            pass




# ─────────────────────────────────────────────────────────────
# 🧩 (3) user_id 생성 또는 복원
# ─────────────────────────────────────────────────────────────
def get_or_create_user_id() -> str:
    """
    🎯 user_id를 가져오거나 새로 생성합니다.
    순서:
      1️⃣ URL 쿼리파라미터(uid) → 페이지 새로고침 시에도 유지됨 (최우선)
      2️⃣ 브라우저 localStorage → 동일 브라우저 재방문
      3️⃣ 새 UUID 생성 → 최초 방문자

    ⚠️ URL 쿼리 파라미터를 주 저장소로 사용하여 새로고침 시에도 user_id 유지
    ⚠️ session_state는 이 함수에서 확인하지 않음 (순환 참조 방지)
    """

    # 1️⃣ URL query parameter에서 uid 가져오기 (최우선)
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
        # localStorage에도 동기화하여 일관성 유지
        _set_user_id_to_browser_storage(uid_from_qs)
        return uid_from_qs

    # 2️⃣ 브라우저 localStorage에 저장된 user_id 사용
    uid_browser = _get_user_id_from_browser_storage()
    if uid_browser:
        # localStorage에 있으면 URL에도 반영 (새로고침 시 유지)
        _set_query_param_uid(uid_browser)
        return uid_browser

    # 3️⃣ 위 모두 없으면 새 user_id 생성
    # 서버와 동일한 UUID 형식 사용 (36자리 UUID)
    new_uid = str(uuid.uuid4())  # UUID 형식: "7b4395ed-af96-41aa-b1ff-c24062b2986f"
    _set_user_id_to_browser_storage(new_uid)
    _set_query_param_uid(new_uid)
    return new_uid


# ─────────────────────────────────────────────────────────────
# 🧩 (4) 세션 및 유저 초기화
# ─────────────────────────────────────────────────────────────
def init_session_and_user():
    """
    🚀 Streamlit 세션 시작 시 기본 상태를 초기화합니다.
    - session_id : 브라우저를 새로 열 때마다 새로 생성
    - user_id    : get_or_create_user_id()로 식별 (URL/localStorage 기반)
    - 기타 상태  : 페이지 입장 시각, 용어 클릭 횟수 등
    """

    # 세션 ID가 없으면 생성 (매 방문마다 고유)
    if "session_id" not in st.session_state:
        st.session_state.session_id = f"sess_{uuid.uuid4().hex[:12]}"

    # 사용자 ID를 항상 최신 값으로 업데이트 (URL/localStorage 기반)
    # get_or_create_user_id()가 URL → localStorage 순으로 확인하므로 매번 호출
    user_id = get_or_create_user_id()
    st.session_state.user_id = user_id

    # 부가 상태값 초기화
    st.session_state.setdefault("page_enter_time", None)  # 페이지 입장 시각
    st.session_state.setdefault("term_click_count", 0)    # 용어 클릭 횟수 누적


# ─────────────────────────────────────────────────────────────
# 🔐 관리자 권한 체크
# ─────────────────────────────────────────────────────────────
def is_admin_user(user_id: str = None) -> bool:
    """
    현재 사용자가 관리자 권한을 가지고 있는지 확인합니다.
    
    Args:
        user_id: 확인할 user_id (None이면 현재 세션의 user_id 사용)
    
    Returns:
        관리자이면 True, 아니면 False
    """
    from core.config import ADMIN_USER_IDS
    
    # user_id가 없으면 현재 세션의 user_id 사용
    if user_id is None:
        user_id = st.session_state.get("user_id")
        if not user_id:
            return False
    
    # 관리자 목록이 비어있으면 모든 사용자 허용 (기본 동작 유지)
    if not ADMIN_USER_IDS:
        return False
    
    # 관리자 목록에 포함되어 있는지 확인
    return user_id in ADMIN_USER_IDS