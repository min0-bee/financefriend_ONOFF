import os
import csv
import json
import pandas as pd
from datetime import datetime, timezone
from core.config import LOG_DIR, LOG_FILE

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
    - 헤더(컬럼명)는 고정된 표준 스키마를 사용합니다.
    """
    os.makedirs(LOG_DIR, exist_ok=True)  # logs 폴더 없으면 생성

    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "event_time",   # 이벤트 발생 시각 (UTC)
                    "event_name",   # 이벤트 종류 (예: news_click)
                    "user_id",      # 유저 식별자
                    "session_id",   # 세션 식별자
                    "news_id",      # 뉴스 ID (해당 시에만 기록)
                    "term",         # 금융 용어 (해당 시에만 기록)
                    "source",       # 이벤트 발생 위치 (list/chat 등)
                    "surface",      # 화면 위치 (home/detail/sidebar 등)
                    "message",      # 사용자가 입력한 메시지 (챗봇 등)
                    "payload_json", # 추가 정보(JSON으로 직렬화된 데이터)
                ],
            )
            writer.writeheader()  # CSV 헤더 추가


# ─────────────────────────────────────────────────────────────
# 🧾 (3) 로그 CSV 파일을 DataFrame으로 로드
# ─────────────────────────────────────────────────────────────
def load_logs_as_df(log_file: str) -> pd.DataFrame:
    """
    🧮 logs/events.csv → pandas DataFrame으로 로드합니다.
    주요 기능:
      - payload_json 컬럼을 JSON으로 풀어서 별도 컬럼으로 확장
      - event_time을 datetime 타입으로 변환
      - 표준 컬럼 순서대로 정렬 후 반환
    """
    if not os.path.exists(log_file):
        # 파일이 없으면 빈 DataFrame 반환
        return pd.DataFrame()

    # 1️⃣ CSV 읽기
    df = pd.read_csv(log_file)

    # 2️⃣ 표준 컬럼 보장 (없는 경우 빈 컬럼으로 채움)
    base_cols = [
        "event_time",
        "event_name",
        "user_id",
        "session_id",
        "news_id",
        "term",
        "source",
        "surface",
        "message",
        "payload_json",
    ]
    for col in base_cols:
        if col not in df.columns:
            df[col] = ""

    # 3️⃣ event_time 문자열 → datetime 변환 (UTC 기준)
    df["event_time"] = pd.to_datetime(df["event_time"], errors="coerce", utc=True)

    # 4️⃣ payload_json 컬럼을 안전하게 JSON → dict로 변환
    def _safe_json_loads(x):
        try:
            return json.loads(x) if isinstance(x, str) and x.strip() else {}
        except Exception:
            return {}

    payloads = df["payload_json"].apply(_safe_json_loads)

    # 5️⃣ payload 내용을 별도의 컬럼으로 확장 (json_normalize)
    payload_df = pd.json_normalize(payloads)

    # 6️⃣ 기존 컬럼과 이름이 겹치는 경우 뒤에 "__2" 같은 숫자를 붙임
    for c in list(payload_df.columns):
        new_c, i = c, 1
        while new_c in df.columns:  # 충돌 방지
            i += 1
            new_c = f"{c}__{i}"
        if new_c != c:
            payload_df = payload_df.rename(columns={c: new_c})

    # 7️⃣ 원본 df와 payload_df 합치기
    df = pd.concat([df.drop(columns=["payload_json"]), payload_df], axis=1)

    # 8️⃣ 컬럼 순서 재정렬 (보기 쉽게)
    order_cols = [
        "event_time",
        "event_name",
        "user_id",
        "session_id",
        "surface",
        "source",
        "news_id",
        "term",
        "message",
    ]
    other_cols = [c for c in df.columns if c not in order_cols]

    # 최종 DataFrame: 표준 컬럼 + 나머지 payload 확장 컬럼
    df = df[order_cols + other_cols].sort_values("event_time").reset_index(drop=True)
    return df


# ─────────────────────────────────────────────────────────────
#   (4)  --- OpenAI: 클라이언트 & 호출 헬퍼 ---
# ─────────────────────────────────────────────────────────────

_openai_client = None

def get_openai_client(api_key : str = None):
    """
    OpenAI Python SDK v1.x 클라이언트 생성 (싱글톤)
    """
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        api_key = api_key or os.getnv("OPENAI_API_KEY")
        try:
            import streamlit as st
            if not api_key and "OPENAI_API_KEY" in st.secrets:
                api_key = st.secrets["OPENAI_API_KEY"]
        except Exception:
            pass
        _openai_client = openAI(api_key=api_key)

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
