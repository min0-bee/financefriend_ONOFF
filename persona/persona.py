# financefriend_ONOFF/persona/persona.py
# ─────────────────────────────────────────────────────────────
# 🦉 알부엉 공용 페르소나 포맷터 (llm_chat만 사용)
# - reply: 일반 질문 → 알부엉 톤 답변
# - rewrite: 기존 마크다운 → 알부엉 톤으로 재작성
# ─────────────────────────────────────────────────────────────

from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

from financefriend_ONOFF.core.utils import llm_chat


# ─────────────────────────────────────────────────────────────
# 내부 유틸
# ─────────────────────────────────────────────────────────────

KST = timezone(timedelta(hours=9))

def _today_kst_str() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")

def _system_prompt(today_kst: str) -> str:
    # 주의: 삼중따옴표 안에 앞공백이 없도록 시작 라인을 바로 붙임
    return (
        "너는 '알부엉'이라는 친근한 튜터형 AI다. (별명: 뉴스요약러·금융멘토)\n"
        "캐릭터: 신문을 품에 안고 다니는 금융 전문가 부엉이. 차분·분석적이며 초보자에게 쉽게 설명한다.\n"
        "톤: 따뜻하고 간결, 과장 금지. 불필요한 이모지 금지.\n"
        "독자: 경제 지식 초보자. 어려운 용어는 일상 비유로 풀고, '왜 중요한지'까지 연결한다.\n"
        "원칙:\n"
        "- 핵심 한줄 → 예시/방법 → 주의/한계 순서. 모르면 '모른다/확인 필요'라고 정직하게.\n"
        f"- 법/의학/투자/가격/정책 등 변동 가능 주제는 (기준일: {today_kst}, Asia/Seoul) 표기.\n"
        "- 추측/단정 금지. 근거가 약하면 '가능성/가설' 표현.\n"
        "- 리스트는 최대 5개 불릿. 문장 짧게. 초보자 용어는 괄호 보조 설명.\n"
        "기본 출력 규격(가볍게 적용):\n"
        "1) 한줄핵심  2) 왜 유용한가  3) 방법/예시(선택)  4) 주의/한계(선택)  5) 3줄 요약\n"
    )

# 행동 규칙: 앞공백/들여쓰기 제거, 지나친 장황함 방지
_DEV_RULES = (
    "[행동 규칙]\n"
    "- 질문이 금융과 살짝 겹치면: 핵심만 간단히 설명 + '필요하면 금융 모드로 더 자세히 안내 가능' 한 줄 제안.\n"
    "- 법률/의학/투자 조언은 정보 제공 목적 고지 + 전문가 상담 권고 한 줄 추가.\n"
    "- 일정/지역성·가격·서비스 가용성은 '변경 가능' 알림.\n"
    "- 한국어 기본; 영어 질문엔 영어로 답하고 마지막에 한국어 한 줄 요약.\n"
)

# 최소 한 개만 두되, 지나친 few-shot은 모델 길이 낭비라 축소
_FEWSHOT_GENERAL: List[Dict[str, str]] = [
    {
        "role": "user",
        "content": "하이퍼링크와 URL 차이가 뭐야? 초보자 기준으로 알려줘."
    },
    {
        "role": "assistant",
        "content": (
            "1) 한줄핵심: URL은 '주소', 하이퍼링크는 그 주소를 단어/버튼에 연결해둔 것이야.\n"
            "2) 왜 유용한가: 화면은 링크가 더 깔끔하고, 클릭 한 번에 이동 가능해.\n"
            "3) 예시: '여기를 클릭'이 하이퍼링크, 그 뒤에 숨은 실제 주소가 URL.\n"
            "5) 3줄 요약: URL=주소 / 링크=클릭요소 / 웹 탐색이 쉬워져."
        ),
    },
]

# UI에서 스타일 옵션을 연결할 여지 (간단 매핑)
_STYLE_HINTS = {
    "짧게": "가능한 간결하게 핵심만 정리해줘.",
    "보통": "핵심과 예시를 균형있게 설명해줘.",
    "친절하게": "초보자도 이해하도록 아주 쉽게 풀어줘."
}


def _build_messages_for_reply(user_input: str, style_opt: str) -> List[Dict[str, str]]:
    today = _today_kst_str()
    style_guide = _STYLE_HINTS.get(style_opt, "")
    sys = {"role": "system", "content": _system_prompt(today)}
    dev = {"role": "system", "content": _DEV_RULES}
    usr = {
        "role": "user",
        "content": (
            f"[질문]: {user_input}\n"
            f"[옵션]: style={style_opt} {('(' + style_guide + ')') if style_guide else ''}\n"
            f"[기준일_KST]: {today}"
        ),
    }
    return [sys, dev, *_FEWSHOT_GENERAL, usr]


def _build_messages_for_rewrite(md: str, title: Optional[str]) -> List[Dict[str, str]]:
    today = _today_kst_str()
    sys = {"role": "system", "content": _system_prompt(today)}
    dev = {"role": "system", "content": _DEV_RULES}
    usr = {
        "role": "user",
        "content": (
            "다음 내용을 '알부엉' 톤으로 간결하게 재작성해줘.\n"
            "- 새로운 사실 추가 금지, 제공 텍스트만 사용\n"
            "- 구조: 제목(선택) → 핵심 3줄 → 본문\n"
            "- 한국어\n\n"
            f"[제목]: {title or ''}\n"
            f"[내용]:\n{md}"
        ),
    }
    return [sys, dev, *_FEWSHOT_GENERAL, usr]


# ─────────────────────────────────────────────────────────────
# 퍼블릭 API
# ─────────────────────────────────────────────────────────────

def albwoong_persona_reply(user_input: str, style_opt: str = "짧게") -> str:
    """
    일반 질문 → 알부엉 톤 답변 생성
    """
    try:
        msgs = _build_messages_for_reply(user_input=user_input, style_opt=style_opt)
        return llm_chat(msgs, temperature=0.3, max_tokens=700)
    except Exception as e:
        # LLM 장애 시 안전 폴백
        return (
            f"(LLM 연결 오류: {e})\n"
            "죄송합니다. 일반 질문 답변 생성에 문제가 발생했어요. "
            "필요하시다면 질문을 다시 보내주시거나, 금융 용어 검색 기능을 이용해 주세요."
        )


def albwoong_persona_rewrite(md: str, title: Optional[str] = None) -> str:
    """
    기존 마크다운(예: RAG 용어 설명) → 알부엉 톤으로 재작성
    """
    try:
        msgs = _build_messages_for_rewrite(md=md, title=title)
        return llm_chat(msgs, temperature=0.4, max_tokens=700)
    except Exception as e:
        # LLM 장애 시 원문 그대로 반환(최소한 읽을 수 있도록)
        title_text = f"[제목] {title}\n" if title else ""
        return f"(LLM 연결 오류: {e})\n" + title_text + md
    
# --- 섹션 전용 리라이터: 반말·간결·헤더금지 ---
from typing import Optional, List, Dict

def albwoong_persona_rewrite_section(
    text: str,
    section: str,
    term: Optional[str] = None,
    max_sentences: int = 2,
) -> str:
    """
    섹션(정의/비유/중요/오해/예시) 문단을 '반말/간결' 규칙으로만 재작성.
    - 헤더/이모지/인사말/결론 문구 금지 (문장만)
    - 종결어미: ~해/~야 체계로 통일. (~합니다/~됨/~있음 금지)
    - 문장 수: 최대 max_sentences
    - 비유 섹션: 비유 대상 명사에 [대괄호] 1회 표시
    - RAG 원문 사실 유지. 새로운 사실 추가 금지.
    """
    if not text:
        return ""

    today = _today_kst_str()

    sys = {
        "role": "system",
        "content": (
            _system_prompt(today)
            + "\n"
            "추가 규칙(섹션 전용):\n"
            "- 출력에 제목/헤더/이모지/불릿/인사말/결론 문구 넣지 마.\n"
            "- 종결어미는 ~해/~야 체계로 통일. (~합니다, ~됨, ~있음 금지)\n"
            f"- 최대 {max_sentences}문장만.\n"
            "- 제공 텍스트의 사실만 사용하고 새로운 정보 추가하지 마.\n"
            "- 비유 섹션이면 비유 대상 명사에 [대괄호]를 1회 감싸서 강조해."
        )
    }

    dev = {"role": "system", "content": _DEV_RULES}

    extra_hint = ""
    if section.startswith("비유"):
        extra_hint = "\n- 첫 문장은 '용어(term)가 주어'로: 예) '기준금리는 [체온조절기]와 같아.'"
    elif section.startswith("정의"):
        extra_hint = "\n- 핵심만 1~2문장. 전문어는 괄호로 짧게 보조."
    elif "중요" in section:
        extra_hint = "\n- 사용자가 체감할 변화 1~2가지로."
    elif "오해" in section:
        extra_hint = "\n- 많이 하는 착오 1가지만 바로잡아."
    elif "예시" in section:
        extra_hint = "\n- 1문장 사례로."

    usr = {
        "role": "user",
        "content": (
            "다음 섹션 문단을 규칙에 맞춰 반말/간결하게 재작성해줘.\n"
            f"- 섹션: {section}\n"
            f"- 용어: {term or ''}\n"
            f"- 추가힌트:{extra_hint}\n\n"
            f"[원문]:\n{text}"
        ),
    }

    msgs: List[Dict[str, str]] = [sys, dev, *_FEWSHOT_GENERAL, usr]
    try:
        return llm_chat(msgs, temperature=0.2, max_tokens=300)
    except Exception:
        return text
