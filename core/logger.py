# core/logger.py
import os
import csv
from datetime import datetime, timezone
import streamlit as st
from core.config import LOG_DIR, LOG_FILE
import time
import json


CSV_HEADER = [
    "event_time", "event_name", "surface", "source",
    "session_id", "user_id", "news_id", "term", "message", "payload"
]

def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def ensure_log_file():
    """logs 폴더를 만들고, CSV가 없으면 헤더를 생성합니다."""
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADER)

def _get(val, default=""):
    return "" if val is None else val



def log_event(event_name: str, **kwargs):
    """
    🧾 CSV 기반 간단 로깅 함수 (MVP 버전)
    --------------------------------------------------------
    ✅ 역할:
        - 사용자의 행동(이벤트)을 CSV 파일에 기록합니다.
        - 예: 뉴스 클릭, 용어 클릭, 챗봇 질문 등

    ✅ 구조:
        event_time, event_name, user_id, session_id, ...
        + payload_json (추가 메타데이터 JSON 형태로 저장)

    ✅ 예시:
        log_event("news_click", news_id="N001", source="list", surface="home")

    ✅ 매개변수:
        event_name : str  → 이벤트 이름 (예: 'chat_question', 'news_click')
        **kwargs   : dict → 추가 정보 (뉴스 ID, 용어명, 메시지, 기타 payload 등)
    --------------------------------------------------------
    """
    # 로그 파일이 없으면 생성 (헤더 포함)
    ensure_log_file()

    # 1️⃣ 표준화된 로그 한 줄(row) 구성
    row = {
        "event_time": now_utc_iso(),                     # UTC 기준 시각 (ISO 포맷)
        "event_name": event_name,                        # 이벤트 이름
        "user_id": st.session_state.get("user_id", "anon"),  # 세션 내 사용자 ID (없으면 anon)
        "session_id": st.session_state.get("session_id"),    # 현재 세션 ID
        "news_id": kwargs.get("news_id", ""),             # 뉴스 ID (없으면 빈칸)
        "term": kwargs.get("term", ""),                   # 클릭한 용어명 (없으면 빈칸)
        "source": kwargs.get("source", ""),               # 이벤트가 발생한 세부 위치 (예: chat / list)
        "surface": kwargs.get("surface", ""),             # 화면 구역 (예: home / detail / sidebar)
        "message": kwargs.get("message", ""),             # 메시지 내용 (챗봇 입력 등)
        "payload_json": json.dumps(                       # 기타 상세 데이터(JSON 형태로 직렬화)
            kwargs.get("payload", {}), 
            ensure_ascii=False                            # 한글 깨짐 방지
        ),
    }

    # 2️⃣ CSV 파일에 한 줄씩 추가 (append)
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=row.keys()).writerow(row)
