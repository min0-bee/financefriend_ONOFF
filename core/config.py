import os

# 로그 경로
LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "events.csv")
USER_FILE = os.path.join(LOG_DIR, "user_info.json")

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
USE_OPENAI = True
OPENAI_API_KEY = None

# Streamlit Secrets가 있으면 그것을 우선 사용
try:
    import streamlit as st
    if "OPENAI_API_KEY" in st.secrets:
        OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
    if "OPENAI_MODEL" in st.secrets:
        DEFAULT_OPENAI_MODEL = st.secrets["OPENAI_MODEL"]
except Exception:
    pass

# API 설정
API_BASE_URL = "http://192.168.80.124:8000"  # 팀원 서버 주소
API_ENABLE = False  # API 사용 여부 (기본값 False - 배포 환경에서는 로컬 서버 접근 불가)
API_RETRY_COUNT = 3  # API 실패 시 재시도 횟수
API_RETRY_DELAY = 1  # 재시도 간격 (초)
API_SHOW_ERRORS = False  # 연결 실패 시 에러 메시지 표시 여부 (기본값 False - 배포 환경에서 에러 숨김)

# CSV 설정 (서버 중심 모드에서는 비활성화 권장)
CSV_ENABLE = False  # CSV 저장 여부 (False면 서버로만 전송, 로그 뷰어는 서버에서 조회)

# Supabase 설정 (로그 중심 DB)
SUPABASE_ENABLE = True  # Supabase event_log 사용 여부
SUPABASE_URL = None  # Supabase 프로젝트 URL
SUPABASE_KEY = None  # Supabase anon/service key

# Streamlit Secrets에서 Supabase 설정 가져오기
try:
    import streamlit as st
    if "SUPABASE_URL" in st.secrets:
        SUPABASE_URL = st.secrets["SUPABASE_URL"]
    if "SUPABASE_KEY" in st.secrets:
        SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    if "SUPABASE_ENABLE" in st.secrets:
        SUPABASE_ENABLE = st.secrets.get("SUPABASE_ENABLE", True)
except Exception:
    pass

# 환경변수에서도 확인 (로컬 개발용)
if not SUPABASE_URL:
    SUPABASE_URL = os.getenv("SUPABASE_URL")
if not SUPABASE_KEY:
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# 익명 사용자 UUID (디폴트)
ANONYMOUS_USER_ID = "00000000-0000-0000-0000-000000000000"

# 에이전트 매핑 (via → agent_id)
AGENT_ID_MAPPING = {
    "openai": 1,
    "claude": 2,
    "local": 3,
    "mock": 3,
}

# 이벤트 타입 → interaction_type 매핑
EVENT_TO_INTERACTION_TYPE = {
    "news_click": "click",
    "news_view": "view",
    "news_share": "share",
    "news_like": "like",
    "news_bookmark": "bookmark",
    "news_detail_open": "view",  # 상세 페이지 열기 = view로 처리
    "news_detail_back": "view",  # 상세 페이지 뒤로가기 = view로 처리
}

# Streamlit Secrets에서 API 설정 가져오기 (로컬 개발 시 True로 설정)
try:
    import streamlit as st
    if "API_BASE_URL" in st.secrets:
        API_BASE_URL = st.secrets["API_BASE_URL"]
    if "API_ENABLE" in st.secrets:
        # secrets에 있으면 그 값 사용 (로컬에서는 True로 설정 가능)
        API_ENABLE = st.secrets.get("API_ENABLE", False)
    if "API_SHOW_ERRORS" in st.secrets:
        # secrets에 있으면 그 값 사용 (로컬 개발 시 True로 설정 가능)
        API_SHOW_ERRORS = st.secrets.get("API_SHOW_ERRORS", False)
    if "CSV_ENABLE" in st.secrets:
        CSV_ENABLE = st.secrets.get("CSV_ENABLE", False)  # 기본값 False (서버 중심)
except Exception:
    pass