# core/logger.py
import os
import csv
import json
from datetime import datetime, timezone
import streamlit as st
from core.config import LOG_DIR, LOG_FILE

# 1) 실제 사용하는 모든 칼럼을 헤더에 “고정”
CSV_HEADER = [
    "event_time", "event_name",
    "user_id", "session_id",
    "surface", "source",
    "news_id", "term",
    "message", "note", "title", "click_count",
    "answer_len", "via", "latency_ms",
    "payload"
]

def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def ensure_log_file():
    """logs 폴더를 만들고, CSV가 없으면 헤더를 생성합니다."""
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
            writer.writerow(CSV_HEADER)

def _nz(v):
    """None → '' (CSV에 'None' 문자열 안 남게)"""
    return "" if v is None else v

def _as_json_text(x) -> str:
    """
    임의의 값(문자열/숫자/딕트/리스트)을 JSON 문자열로 직렬화.
    - 문자열도 JSON으로 감싸 쉼표/개행 안전 확보
    """
    try:
        return json.dumps(x if x is not None else "", ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return json.dumps(str(x), ensure_ascii=False, separators=(",", ":"))

def log_event(event_name: str, **kwargs):
    """
    CSV 기반 간단 로깅 함수 (MVP)
    --------------------------------------------------------
    ✅ 역할:
        - 사용자의 행동(이벤트)을 CSV 파일에 한 줄씩 기록합니다.
        - 예: 뉴스 클릭, 용어 클릭, 챗봇 질문 등
    --------------------------------------------------------
    """

    ensure_log_file()

    row = {
        # ================== 기본 메타 정보 ==================
        "event_time": now_utc_iso(),                     # 🕓 이벤트 발생 시각 (UTC 기준, ISO 포맷)
        "event_name": event_name,                        # 🏷️ 이벤트 이름 (예: "news_click", "chat_question")

        # ================== 사용자/세션 정보 ==================
        "user_id": st.session_state.get("user_id", "anon"),   # 👤 유저 식별자 (로그인 전: 익명 anon)
        "session_id": st.session_state.get("session_id", ""), # 💬 세션 식별자 (브라우저 새로고침마다 유지됨)

        # ================== UI 위치/출처 정보 ==================
        "surface": _nz(kwargs.get("surface", "")),       # 🧭 화면 구역 (예: "home", "detail", "sidebar")
        "source":  _nz(kwargs.get("source", "")),        # 🧩 이벤트가 발생한 세부 위치 (예: "chat", "list", "term_box")

        # ================== 콘텐츠 식별자 ==================
        "news_id": _nz(kwargs.get("news_id", "")),       # 📰 클릭/요약된 뉴스의 고유 ID
        "term":    _nz(kwargs.get("term", "")),          # 💡 클릭한 금융용어 (예: "양적완화")

        # ================== 사용자 입력/노트 관련 ==================
        "message": _as_json_text(kwargs.get("message", "")),  # 💬 사용자가 입력한 메시지 (챗봇 질문 등)
        "note":    _nz(kwargs.get("note", "")),               # 🗒️ 임시 메모/추가 코멘트
        "title":   _nz(kwargs.get("title", "")),              # 🏷️ 뉴스나 카드의 제목 (클릭된 항목 표시용)
        "click_count": _nz(kwargs.get("click_count", "")),    # 🔢 특정 UI 요소 클릭 횟수 (실험용)

        # ================== 챗봇 응답/성능 메타 ==================
        "answer_len": _nz(kwargs.get("answer_len", "")),      # 📏 챗봇 응답 길이 (토큰/문자 수)
        "via":        _nz(kwargs.get("via", "")),             # ⚙️ 사용된 모델 혹은 라우팅 경로 (예: "openai", "mock")
        "latency_ms": _nz(kwargs.get("latency_ms", "")),      # ⏱️ 응답 지연 시간(ms 단위)

        # ================== 추가 정보(JSON) ==================
        "payload": _as_json_text(kwargs.get("payload", {})),
        # 📦 상세 데이터(JSON 형태로 저장)
        # 예시: {"browser": "Chrome", "os": "Windows", "ref": "sidebar-term", "exp_group": "A"}
    }

    # DictWriter로 CSV에 한 줄씩 기록
    with open(LOG_FILE, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=CSV_HEADER,
            quoting=csv.QUOTE_MINIMAL,
            extrasaction="ignore"
        )
        writer.writerow(row)

