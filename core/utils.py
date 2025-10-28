import os
import csv
import json
import uuid
import pandas as pd
from datetime import datetime, timezone
from core.config import LOG_DIR, LOG_FILE
from openai import OpenAI
from core.logger import CSV_HEADER

# ─────────────────────────────────────────────────────────────
# 🕓 (1) 현재 UTC 시각을 ISO 형식 문자열로 반환
# ─────────────────────────────────────────────────────────────
def now_utc_iso() -> str:
    """
    🌍 현재 시각을 UTC 기준으로 ISO 8601 문자열로 반환합니다.
    예: "2025-10-22T08:30:25.123456+00:00"
    """
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────
# 📁 (2) 로그 파일(events.csv) 존재 확인 및 생성
# ─────────────────────────────────────────────────────────────
def ensure_log_file():
    """
    📋 logs/events.csv 파일이 없으면 자동으로 생성합니다.
    - 디렉토리(LOG_DIR)가 없으면 만들어줍니다.
    - 헤더(컬럼명)는 core.logger의 CSV_HEADER를 그대로 사용합니다.
    """
    os.makedirs(LOG_DIR, exist_ok=True)

    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
            writer.writeheader()


# ─────────────────────────────────────────────────────────────
# 🧾 (3) 로그 CSV 파일을 DataFrame으로 로드
# ─────────────────────────────────────────────────────────────
def load_logs_as_df(log_file: str) -> pd.DataFrame:
    """
    🧮 logs/events.csv → pandas DataFrame으로 로드합니다.
    주요 기능:
      - payload를 JSON 확장하지 않고 문자열 그대로 유지합니다.
      - event_time을 datetime 타입으로 변환
      - 누락된 컬럼은 빈 문자열로 채웁니다.
    """
    if not os.path.exists(log_file):
        # 파일이 없으면 빈 DataFrame 반환
        return pd.DataFrame(columns=CSV_HEADER)

    # 1️⃣ CSV 읽기
    df = pd.read_csv(
        log_file,
        dtype=str,
        engine="python",
        on_bad_lines="skip",
        encoding="utf-8-sig",
    )

    # 2️⃣ 표준 컬럼 보장 (없는 경우 빈 컬럼으로 채움)
    for col in CSV_HEADER:
        if col not in df.columns:
            df[col] = ""

    # 3️⃣ event_time 문자열 → datetime 변환 (UTC 기준)
    df["event_time"] = pd.to_datetime(df["event_time"], errors="coerce", utc=True)

    # # 4️⃣ payload_json 컬럼을 안전하게 JSON → dict로 변환
    # def _safe_json_loads(x):
    #     try:
    #         return json.loads(x) if isinstance(x, str) and x.strip() else {}
    #     except Exception:
    #         return {}

    # payloads = df["payload_json"].apply(_safe_json_loads)

    # 5️⃣ payload 내용을 별도의 컬럼으로 확장 (json_normalize)
    # payload_df = pd.json_normalize(payloads)

    # 4️⃣ 숫자형 컬럼 자동 변환
    for col in ["click_count", "answer_len", "latency_ms"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")


    # 컬럼 순서 재정렬 (보기 쉽게)
    order_cols = [
        "event_id",
        "event_time",
        "event_name",
        "user_id",
        "session_id",
        "surface",
        "source",
        "news_id",
        "term",
        "message",
        "note",
        "title",
        "click_count",
        "answer_len",
        "via",
        "latency_ms",
        "payload",  # ✅ 그대로 유지
    ]
    order_cols = [c for c in order_cols if c in df.columns]
    df = df[order_cols].sort_values("event_time").reset_index(drop=True)
    return df


# ─────────────────────────────────────────────────────────────
#   (4)  --- OpenAI: 클라이언트 & 호출 헬퍼 ---
# ─────────────────────────────────────────────────────────────

_openai_client = None

def get_openai_client(api_key: str = None):
    """
    OpenAI Python SDK v1.x 클라이언트 생성 (싱글톤)
    - 환경변수/Streamlit secrets에서 키를 찾고, 없으면 None 반환
    """
    global _openai_client
    if _openai_client is not None:
        return _openai_client

    # 1) 우선순위: 전달 인자 → 환경변수 → st.secrets
    key = api_key or os.getenv("OPENAI_API_KEY")
    try:
        import streamlit as st
        if not key and "OPENAI_API_KEY" in st.secrets:
            key = st.secrets["OPENAI_API_KEY"]
    except Exception:
        pass

    # 2) 키가 없으면 연결 건너뛰기
    if not key:
        return None

    # 3) 정상 생성
    _openai_client = OpenAI(api_key=key)
    return _openai_client


def llm_chat(messages, model: str = None, temperature: float = 0.3, max_tokens: int = 512):
    """
    💬 ChatGPT (Chat Completions API) 호출 헬퍼 함수
    --------------------------------------------------
    ✅ 기능:
        - OpenAI의 ChatCompletions API를 호출해 LLM 응답을 받아옴.
        - messages 형식의 대화 이력을 입력받아 모델의 답변을 반환함.
          (Streamlit 등에서 챗봇 기능 구현 시 자주 사용)

    ✅ 매개변수:
        messages : list[dict]
            [{"role": "system"|"user"|"assistant", "content": "..."}] 형식의 메시지 배열
            예시:
                [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "오늘의 금융 뉴스 요약해줘"}
                ]
        model : str, optional
            사용할 OpenAI 모델 이름 (기본값은 core.config의 DEFAULT_OPENAI_MODEL)
        temperature : float, optional
            생성 텍스트의 창의성 조절 (0~1, 낮을수록 일관성↑, 높을수록 다양성↑)
        max_tokens : int, optional
            모델이 생성할 최대 토큰 수 (응답 길이 제한)

    ✅ 반환값:
        str : 모델이 생성한 텍스트 응답 (문자열)
    """

    # ✅ 1. 설정값 가져오기
    #   - 기본 모델명 (예: "gpt-4o-mini")
    #   - OpenAI API 키
    from core.config import DEFAULT_OPENAI_MODEL, OPENAI_API_KEY

    # ✅ 2. OpenAI 클라이언트 초기화
    client = get_openai_client(OPENAI_API_KEY)

    # ✅ 3. 모델 지정 (직접 전달 없으면 기본값 사용)
    model = model or DEFAULT_OPENAI_MODEL

    # ✅ 4. ChatCompletions API 호출
    #   - messages: 대화 이력
    #   - temperature: 창의성 조절
    #   - max_tokens: 응답 길이 제한
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    # ✅ 5. 응답에서 모델의 텍스트 추출
    return resp.choices[0].message.content.strip()


# === LLM 연결 진단 패널 ===
def render_llm_diagnostics():
    import os, importlib, sys
    import streamlit as st

    st.markdown("### 🧪 LLM 연결 진단")
    problems = []

    # 1) openai 패키지 제대로 import 되는지
    try:
        import openai  # 패키지 모듈 (v1에서도 모듈명은 openai)
        st.write("✅ `import openai` OK", getattr(openai, "__version__", "unknown"))
    except Exception as e:
        st.error(f"❌ `import openai` 실패: {e}")
        problems.append("openai import 실패")

    # 2) 프로젝트에 openai.py / openai 폴더로 **이름충돌** 있는지
    import glob, os
    here = os.path.abspath(os.getcwd())
    shadow = []
    for pattern in ["openai.py", "openai/__init__.py"]:
        for p in glob.glob(os.path.join(here, "**", pattern), recursive=True):
            shadow.append(p)
    if shadow:
        st.error("❌ 프로젝트 안에 `openai` 이름 충돌 가능성:", icon="🚫")
        for p in shadow:
            st.code(p)
        problems.append("로컬 파일/폴더 이름충돌(openai)")
    else:
        st.write("✅ 프로젝트 내 이름충돌 없음")

    # 3) config 값 확인
    try:
        from core import config
        st.write("✅ `from core import config` OK")
        st.write({
            "DEFAULT_OPENAI_MODEL": getattr(config, "DEFAULT_OPENAI_MODEL", None),
            "USE_OPENAI": getattr(config, "USE_OPENAI", None),
            "OPENAI_API_KEY in config (bool)": bool(getattr(config, "OPENAI_API_KEY", None)),
        })
    except Exception as e:
        st.error(f"❌ config import 실패: {e}")
        problems.append("config import 실패")

    # 4) 환경변수 확인 (현재 프로세스)
    st.write({
        "env.OPENAI_API_KEY": bool(os.getenv("OPENAI_API_KEY")),
    })

    # 5) .streamlit/secrets.toml 읽히는지
    try:
        import streamlit as st
        st.write({
            "secrets.has_OPENAI_API_KEY": ("OPENAI_API_KEY" in st.secrets),
            "secrets.has_OPENAI_MODEL": ("OPENAI_MODEL" in st.secrets),
        })
    except Exception as e:
        st.warning(f"secrets 접근 경고: {e}")

    # 6) OpenAI v1 클라이언트 생성 & 간이 호출
    try:
        from openai import OpenAI
        api_key = getattr(config, "OPENAI_API_KEY", None) or os.getenv("OPENAI_API_KEY")
        if not api_key:
            st.error("❌ API 키 없음: config.OPENAI_API_KEY 또는 env.OPENAI_API_KEY가 비어있음")
            problems.append("API 키 없음")
        else:
            client = OpenAI(api_key=api_key)
            st.write("✅ OpenAI 클라이언트 생성 OK")
            # 모델 핑(가벼운 호출): 모델 리스트 혹은 최소 chat 호출 시그니처 확인
            try:
                # 가장 가벼운 확인: 모델 리스트
                _ = client.models.list()
                st.write("✅ `client.models.list()` OK")
            except Exception as e:
                st.warning(f"⚠️ models.list 경고: {e}")
            # 짧은 채팅 호출 시도 (모델명은 config 사용)
            try:
                mdl = getattr(config, "DEFAULT_OPENAI_MODEL", "gpt-4o-mini")
                resp = client.chat.completions.create(
                    model=mdl,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=5,
                )
                txt = resp.choices[0].message.content.strip()
                st.success(f"✅ chat.completions 응답 OK: {txt!r}")
            except Exception as e:
                st.error(f"❌ chat.completions 실패: {e}")
                problems.append("chat.completions 실패")
    except Exception as e:
        st.error(f"❌ OpenAI 클라이언트 생성 실패: {e}")
        problems.append("OpenAI 클라이언트 생성 실패")

    if problems:
        st.markdown("**요약 (의심 포인트)**: " + ", ".join(problems))
    else:
        st.success("🎉 진단상 문제 없음")

# 👉 호출 위치 예시
# with st.sidebar:
#     render_llm_diagnostics()
