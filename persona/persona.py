# financefriend_ONOFF/persona/persona.py
# ─────────────────────────────────────────────────────────────
# 🦉 알부엉 공용 페르소나 포맷터 (llm_chat만 사용)
# - reply: 일반 질문 → 알부엉 톤 답변
# - rewrite: 기존 마크다운 → 알부엉 톤으로 재작성
# ─────────────────────────────────────────────────────────────

from __future__ import annotations
from datetime import datetime, timezone, timedelta
import json
import random
import re
import streamlit as st
from typing import List, Dict, Any, Optional, Union, Generator

from core.utils import llm_chat


# ─────────────────────────────────────────────────────────────
# 내부 유틸
# ─────────────────────────────────────────────────────────────

KST = timezone(timedelta(hours=9))

def _today_kst_str() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")

def _system_prompt(today_kst: str) -> str:
    # ⚡ 최적화: 프롬프트 간소화 (핵심만 유지하여 토큰 수 감소)
    return (
        "너는 '알부엉'이라는 친근한 튜터형 AI다. 신문을 품에 안고 다니는 금융 전문가 부엉이.\n"
        "\n"
        "## 핵심 역할\n"
        "- 전문가의 언어 → 일상 언어로 번역\n"
        "- 추상적 용어 → 구체적 상황으로 변환\n"
        "\n"
        "## 말투\n"
        "- 반말 사용 (~해, ~야, ~지)\n"
        "- 간결하고 따뜻하게. 핵심만 전달.\n"
        "- 설명 끝: '더 궁금한 거 있으면 편하게 물어봐!'\n"
        "\n"
        "## 응답 구조\n"
        "1️⃣ 이름: [용어]는~\n"
        "2️⃣ 뜻: ~라는 뜻이야 (일상 언어로)\n"
        "3️⃣ 영향: 우리 생활에 ~한 영향을 줘\n"
        "\n"
        "## 원칙\n"
        "- 핵심 → 예시 → 영향 순서\n"
        "- 일상 비유 활용 (마트 장보기, 온도조절기 등)\n"
        "- 문장 짧게 (15-20자 내외)\n"
        f"- 변동 가능 주제는 (기준일: {today_kst}) 표기\n"
    )

# 행동 규칙: 앞공백/들여쓰기 제거, 지나친 장황함 방지
# ⚡ 최적화: 간소화하여 토큰 수 감소
_DEV_RULES = (
    "[행동 규칙]\n"
    "- 핵심만 간단히 설명\n"
    "- 정보 제공 목적 고지\n"
    "- 한국어 기본\n"
)

# Few-shot 예제: 금융 + 일반 질문 혼합 + 다양한 스타일 시연
# ⚡ 최적화: 7개 → 3개로 축소하여 LLM 응답 시간 단축 (약 30% 개선 예상)
_FEWSHOT_GENERAL: List[Dict[str, str]] = [
    # 예시 1: 3단 구조 (이름-뜻-영향) - 가장 대표적인 금융 용어 설명 형식
    {
        "role": "user",
        "content": "인플레이션이 뭐야?"
    },
    {
        "role": "assistant",
        "content": (
            "1️⃣ 이름: 인플레이션은~\n"
            "2️⃣ 뜻: 마트에서 장볼 때 물가가 전반적으로 계속 오르는 현상이야.\n"
            "3️⃣ 영향: 같은 돈으로 살 수 있는 게 줄어들어서, 실질소득이 감소해. "
            "예를 들어 커피값이 4000원에서 5000원으로 오르면 부담이 커지지.\n\n"
            "더 궁금한 거 있으면 편하게 물어봐!"
        ),
    },
    # 예시 2: 흐름도 스타일 (화살표 사용) - 인과관계 설명 형식
    {
        "role": "user",
        "content": "금리가 오르면 주식이 왜 떨어져?"
    },
    {
        "role": "assistant",
        "content": (
            "간단히 말하면 이런 흐름이야:\n\n"
            "금리 인상 → 예금/채권 이자 ↑ → 안전자산 매력 ↑ → 주식 자금 이탈 → 주가 하락 ↓\n\n"
            "조금 더 풀어보면:\n"
            "1) 금리가 오르면 은행 예금이나 채권의 이자가 높아져.\n"
            "2) 투자자들이 '굳이 위험한 주식 안 해도 되겠네' 생각하게 돼.\n"
            "3) 게다가 기업들도 대출 이자 부담이 커져서 실적이 나빠질 수 있어.\n"
            "4) 그래서 주식에서 돈이 빠져나가 주가가 떨어지는 거야."
        ),
    },
    # 예시 3: 일반 대화 (인사) - 친근한 톤 유지
    {
        "role": "user",
        "content": "안녕"
    },
    {
        "role": "assistant",
        "content": "안녕! 오늘도 신문을 품에 안고 왔어. 궁금한 경제 이야기가 있으면 편하게 물어봐!"
    },
]

# ─────────────────────────────────────────────────────────────
# 새 구조화 응답 포맷 정의 (초보자용 3~4 문장 형식)
# ─────────────────────────────────────────────────────────────
_STRUCTURED_OUTPUT_GUIDE = (
    "## 기본 출력 포맷 (항상 동일)\n"
    "- 사용자는 반말 톤만 본다.\n"
    "- 출력 결과는 JSON 하나로만 반환하고 키는 definition, impact, analogy 세 개를 사용한다.\n"
    "- definition: 용어의 핵심 정의를 1~2 문장으로 간단하게 설명 (초보자가 바로 이해할 수 있게)\n"
    "- impact: 우리 생활에 어떤 영향을 주는지 3~4 문장으로 구체적으로 설명 (예: 대출 이자, 월급, 물가 등 실생활 예시 포함)\n"
    "- analogy: 일상 비유를 3~4 문장으로 설명. '[대상]처럼 ~. ~' 형식으로 작성하고, 왜 그렇게 느끼는지 이유를 포함\n"
    "- 전문 용어는 괄호()로 짧게 보조 설명 추가\n"
    "- 구체적이고 실용적인 예시를 포함하여 초보자도 바로 이해할 수 있게 작성\n"
    "- 모든 값은 문자열이고 이스케이프 없이 순수 텍스트만 넣는다.\n"
    "- JSON 이외의 텍스트나 주석은 절대 추가하지 않는다."
)

_STRUCTURED_JSON_PATTERN = re.compile(r"\{.*\}", re.DOTALL)

_OPENERS_WITH_TERM = [
    "신문에서 봤는데~ '{term}' 이야기 궁금했지? 내가 정리해볼게!",
    "내가 정리해둔 '{term}' 메모를 펼쳐볼게!",
    "뉴스에서 '{term}' 자주 들리더라. 지금 바로 풀어줄게!",
]

_OPENERS_GENERIC = [
    "신문에서 봤는데~ '{question}' 이런 이야기 많더라. 내가 쉽게 풀어볼게!",
    "내가 정리해둔 질문이 있는데 '{question}'였어. 같이 살펴보자!",
    "방금 본 뉴스 주제야. '{question}' 궁금했지? 간단히 정리해줄게!",
]


# ─────────────────────────────────────────────────────────────
# 💡 생활 속 비유 라이브러리
# - 경제 용어를 일상 언어로 '번역'하기 위한 검증된 비유 모음
# ─────────────────────────────────────────────────────────────
_ANALOGY_LIBRARY = {
    "인플레이션": "마트에서 장볼 때 물가가 점점 오르는 현상",
    "금리인상": "은행이 돈 빌릴 때 이자율을 올려서, 빚 내기가 어려워지는 상황",
    "경기침체": "가게 매출이 줄고, 사람들 지갑이 닫히는 시기",
    "환율": "우리나라 돈을 외국 돈으로 바꿀 때의 교환비율",
    "GDP": "나라 전체의 '한 해 동안의 매출액' 같은 것",
    "기준금리": "경제의 온도조절기. 높이면 경기가 식고, 낮추면 뜨거워져",
    "양적완화": "중앙은행이 경제라는 마른 땅에 돈이라는 물을 뿌려주는 것",
    "긴축정책": "돈의 수도꼭지를 조금씩 잠그는 것",
    "배당": "회사가 번 돈을 주주들과 나눠 갖는 것. 동업자들끼리 수익 배분하는 것과 같아",
    "주가": "회사의 인기도를 숫자로 나타낸 것",
}
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

def albwoong_persona_reply(
    user_input: str,
    term: Optional[str] = None,
    context: Optional[Dict[str, str]] = None,
    temperature: float = 0.3,
    stream: bool = False,
) -> str:
    """
    일반 질문 또는 RAG 참고자료 기반 질문 → 일관된 템플릿의 알부엉 답변 생성
    - term이 있으면: 구조화된 형식 사용
    - term이 없으면: 자연스러운 대화 형식 사용
    - stream=True: 스트리밍 응답 반환 (제너레이터)
    """
    # term이 없으면 자연스러운 대화 형식으로 답변
    if not term:
        try:
            today = _today_kst_str()
            base_prompt = _system_prompt(today)
            sys = {"role": "system", "content": base_prompt}
            dev = {"role": "system", "content": _DEV_RULES}
            usr = {"role": "user", "content": user_input}
            
            # 일반 대화 형식으로 답변 (few-shot 예제 포함)
            messages = [sys, dev, *_FEWSHOT_GENERAL, usr]
            # ⚡ 최적화: temperature 0.2로 감소 (더 빠른 응답, 더 일관된 출력)
            optimized_temp = min(temperature, 0.2)  # 최대 0.2로 제한
            if stream:
                return llm_chat(messages, temperature=optimized_temp, max_tokens=350, stream=True)  # ⚡ 최적화: 500 → 350
            raw = llm_chat(messages, temperature=optimized_temp, max_tokens=350)  # ⚡ 최적화: 500 → 350
            return raw.strip()
        except Exception as e:
            return (
                f"죄송해! 지금은 답변을 생성하기 어려워. "
                f"다시 시도하거나 다른 질문을 해줘! (오류: {e})"
            )
    
    # term이 있으면 구조화된 형식 사용
    return generate_structured_persona_reply(
        user_input=user_input,
        term=term,
        context=context,
        temperature=temperature,
        stream=stream,
    )


# ─────────────────────────────────────────────────────────────
# 캐싱된 응답 생성 함수
# ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=86400, show_spinner=False)  # ⚡ 최적화: 1시간 → 24시간 (더 긴 캐시)
def _cached_llm_response(
    messages_hash: str,
    temperature: float,
    max_tokens: int
) -> str:
    """LLM 응답 캐싱 (내부 함수, 직접 호출하지 않음)"""
    # 이 함수는 실제로 호출되지 않음 (캐시 키 생성용)
    pass


def _get_messages_hash(messages: List[Dict[str, str]]) -> str:
    """메시지 리스트의 해시값 생성 (캐시 키용)"""
    import hashlib
    messages_str = json.dumps(messages, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(messages_str.encode('utf-8')).hexdigest()


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
    min_sentences: int = 1,
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
            f"- 최소 {min_sentences}문장, 최대 {max_sentences}문장.\n"
            "- 제공 텍스트의 사실만 사용하고 새로운 정보 추가하지 마.\n"
            "- 비유 섹션이면 비유 대상 명사에 [대괄호]를 1회 감싸서 강조해."
        )
    }

    dev = {"role": "system", "content": _DEV_RULES}

    # 섹션별 맞춤형 규칙 (구체화 및 강화)
    extra_hint = ""
    if section.startswith("비유"):
        extra_hint = (
            "\n- 반드시 첫 문장은 '용어(term)가 주어'로 시작: 예) '기준금리는 [체온조절기]와 같아.'\n"
            "- 비유 대상은 [대괄호]로 1회만 감싸기.\n"
            "- 일상 사물/경험으로만 비유 (커피, 온도계, 물펌프, 자동차, 신호등 등).\n"
            "- 너무 전문적이거나 생소한 비유 금지 (예: 양자역학, 블랙홀 등은 X).\n"
            "- 두 문장으로: ① 무엇에 비유했는지 ② 왜 그렇게 느끼는지."
        )
    elif section.startswith("정의"):
        extra_hint = (
            "\n- 핵심만 1~2문장으로 압축.\n"
            "- 전문 용어는 괄호()로 짧게 보조 설명.\n"
            "- '~은 ~이야' 또는 '~는 ~하는 거야' 구조 사용.\n"
            "- 불필요한 배경 설명 제거. 첫 문장은 term이 주어."
        )
    elif "중요" in section:
        extra_hint = (
            "\n- 사용자가 체감할 수 있는 변화 1~2가지만 언급.\n"
            "- '내 월급', '내 대출', '내 통장' 등 1인칭 관점으로.\n"
            "- 추상적 표현 금지. 구체적 영향만.\n"
            "- 예) '대출 이자가 올라', '물가가 변해' 등.\n"
            "- 두 문장으로: ① 왜 중요한지 ② 생활 속 변화."
        )
    elif "오해" in section:
        extra_hint = (
            "\n- 가장 흔한 착오 1가지만 명확히 바로잡기.\n"
            "- '~가 아니라 ~이야' 구조 사용.\n"
            "- 왜 그렇게 착각하는지 간단히 언급 (선택).\n"
            "- 부정적 톤 금지. 긍정적으로 교정. 두 문장으로."
        )
    elif "예시" in section:
        extra_hint = (
            "\n- 실제 사례 1개만 간단히.\n"
            "- 가능하면 최근 뉴스나 일상 경험으로.\n"
            "- 구체적 숫자/날짜 포함하면 좋음.\n"
            "- 첫 문장은 상황, 두 번째 문장은 결과."
        )
    else:
        # 기타 섹션 (쉬운 설명 등)
        extra_hint = "\n- 초보자도 이해할 수 있게 쉬운 말로 풀어줘."

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


# ─────────────────────────────────────────────────────────────
# 구조화된 응답 생성기
# ─────────────────────────────────────────────────────────────

def _build_messages_for_structured_reply(
    user_input: str,
    term: Optional[str],
    context: Optional[Dict[str, str]],
) -> List[Dict[str, str]]:
    today = _today_kst_str()
    base_prompt = _system_prompt(today) + "\n" + _STRUCTURED_OUTPUT_GUIDE
    sys = {"role": "system", "content": base_prompt}
    dev = {"role": "system", "content": _DEV_RULES}

    context_lines: List[str] = []
    if context:
        for key, value in context.items():
            if value:
                label = key.replace("_", " ")
                context_lines.append(f"- {label}: {value}")

    user_blocks: List[str] = []
    if term:
        user_blocks.append(f"[관심 용어]: {term}")
    if context_lines:
        user_blocks.append("[참고 자료]")
        user_blocks.extend(context_lines)
    user_blocks.append(f"[질문]: {user_input}")
    user_blocks.append("[지시] 위 조건을 지킨 JSON 하나만 반환해줘.")

    usr = {"role": "user", "content": "\n".join(user_blocks)}
    return [sys, dev, usr]


def _parse_structured_response(raw: str) -> Dict[str, str]:
    default = {
        "definition": "",
        "impact": "",
        "analogy": "",
    }
    if not raw:
        return default
    try:
        parsed = json.loads(raw)
        return {**default, **parsed}
    except Exception:
        match = _STRUCTURED_JSON_PATTERN.search(raw)
        if match:
            try:
                parsed = json.loads(match.group())
                return {**default, **parsed}
            except Exception:
                pass
    # JSON 파싱 실패 시 원문을 definition으로 사용
    default["definition"] = raw.strip()
    return default


def _format_structured_output(data: Dict[str, str], term: Optional[str], prompt: str) -> str:
    question_snippet = (prompt or "").strip()
    if len(question_snippet) > 20:
        question_snippet = question_snippet[:20] + "..."

    if term:
        opener_template = random.choice(_OPENERS_WITH_TERM)
        opener = opener_template.format(term=term)
    elif question_snippet:
        opener_template = random.choice(_OPENERS_GENERIC)
        opener = opener_template.format(question=question_snippet)
    else:
        opener = "신문에서 봤는데~ 방금 이야기 쉽게 풀어볼게!"

    definition = (data.get("definition") or "").strip()
    impact = (data.get("impact") or "").strip()
    analogy = (data.get("analogy") or "").strip()

    # fallback 메시지
    if not definition:
        definition = "쉽게 말하면, 어렵게 느껴지는 개념을 일상 언어로 풀어낸 거야."
    if not impact:
        impact = "우리 생활의 돈 흐름과 소비에 직접적인 영향을 줘."
    if not analogy:
        analogy = "일상에서 쉽게 접할 수 있는 것에 비유하면 더 이해하기 쉬울 거야."

    # 구조화된 형식으로 출력 (각 섹션 3~4 문장)
    lines = [
        opener,
        "",
        f"📘 정의",
        "",
        definition,
        "",
        f"💡 영향",
        "",
        impact,
    ]

    if analogy:
        lines.extend([
            "",
            f"🌟 비유",
            "",
            analogy,
        ])

    lines.extend([
        "",
        "더 궁금한 거 있으면 편하게 물어봐!",
    ])
    return "\n".join(lines)


def generate_structured_persona_reply(
    user_input: str,
    term: Optional[str] = None,
    context: Optional[Dict[str, str]] = None,
    temperature: float = 0.3,
    stream: bool = False,
) -> str:
    """
    구조화된 템플릿을 따르는 알부엉 답변 생성 (RAG/일반 공용)
    - term이 있으면: 구조화된 형식 (📘 정의, 💡 영향, 🌟 비유) - 각 섹션 3~4 문장으로 초보자용 간결하게
    - term이 없어도: 구조화된 형식으로 답변 (RAG 답변과 일관성 유지)
    - stream=True: 스트리밍 응답 반환 (제너레이터)
    """
    # term이 없어도 구조화된 형식으로 답변 (RAG 답변과 일관성 유지)
    # term이 있으면 구조화된 형식으로 답변 (정의, 영향, 비유 각 3~4 문장)
    try:
        messages = _build_messages_for_structured_reply(
            user_input=user_input,
            term=term,  # term이 없어도 None으로 전달하여 구조화된 형식으로 답변
            context=context,
        )
        # ⚡ 최적화: temperature 0.2로 감소 (더 빠른 응답, 더 일관된 출력)
        optimized_temp = min(temperature, 0.2)  # 최대 0.2로 제한
        if stream:
            # 스트리밍 모드: 제너레이터 반환
            return llm_chat(messages, temperature=optimized_temp, max_tokens=300, stream=True)  # ⚡ 최적화: 400 → 300
        raw = llm_chat(messages, temperature=optimized_temp, max_tokens=300)  # ⚡ 최적화: 400 → 300
        structured = _parse_structured_response(raw)
        return _format_structured_output(structured, term, user_input)
    except Exception as e:
        return (
            f"(LLM 연결 오류: {e})\n"
            "죄송해! 지금은 내가 정리해둔 걸 바로 보여주기 어려워. "
            "다시 시도하거나 다른 질문을 해줘!"
        )


# ─────────────────────────────────────────────────────────────
# 🔍 응답 품질 검증 시스템
# ─────────────────────────────────────────────────────────────

def validate_albwoong_response(response: str) -> Dict[str, Any]:
    """
    알부엉 응답이 페르소나 규칙을 준수하는지 검증
    
    Args:
        response: 검증할 응답 텍스트
        
    Returns:
        {
            "valid": bool,           # 전체 검증 통과 여부
            "score": float,          # 품질 점수 (0-100)
            "issues": List[str],     # 발견된 문제점 목록
            "warnings": List[str],   # 경고 사항
            "suggestions": List[str] # 개선 제안
        }
    """
    issues = []
    warnings = []
    suggestions = []
    score = 100.0
    
    if not response or not response.strip():
        return {
            "valid": False,
            "score": 0,
            "issues": ["응답이 비어있음"],
            "warnings": [],
            "suggestions": ["응답을 생성해주세요"]
        }
    
    # 1. 존댓말 체크 (반말로 통일해야 함)
    formal_endings = ["합니다", "됩니다", "습니다", "있습니다", "없습니다", "입니다"]
    formal_count = sum(response.count(ending) for ending in formal_endings)
    if formal_count > 0:
        issues.append(f"존댓말 사용 감지 ({formal_count}회) - 반말로 통일 필요")
        score -= 20
        suggestions.append("'~합니다' → '~해', '~됩니다' → '~돼'로 변경")
    
    # 2. 응답 길이 체크
    char_count = len(response)
    if char_count < 30:
        warnings.append("응답이 너무 짧음 (30자 미만)")
        score -= 10
        suggestions.append("좀 더 자세한 설명 추가")
    elif char_count > 800:
        warnings.append("응답이 너무 김 (800자 초과)")
        score -= 5
        suggestions.append("핵심만 간추려서 설명")
    
    # 3. 이모지 과다 사용 체크
    emoji_count = sum(1 for char in response if ord(char) > 0x1F300 and ord(char) < 0x1F9FF)
    if emoji_count > 5:
        warnings.append(f"이모지 과다 사용 ({emoji_count}개)")
        score -= 5
        suggestions.append("핵심 포인트에만 1-2개 이모지 사용")
    
    # 4. 문장 길이 체크 (너무 긴 문장)
    sentences = [s.strip() for s in response.replace('\n', '. ').split('.') if s.strip()]
    long_sentences = [s for s in sentences if len(s) > 100]
    if long_sentences:
        warnings.append(f"긴 문장 발견 ({len(long_sentences)}개)")
        score -= 5
        suggestions.append("문장을 짧게 나눠주세요 (15-20자 권장)")
    
    # 5. 알부엉 특유 표현 포함 여부 (긍정 가산점)
    albwoong_phrases = ["신문에서", "정리해둔", "호우", "그건 말이야", "간단히 말하면", 
                        "물어봐", "편하게", "궁금한"]
    phrase_found = sum(1 for phrase in albwoong_phrases if phrase in response)
    if phrase_found > 0:
        score += min(phrase_found * 2, 10)  # 최대 +10점
    else:
        suggestions.append("알부엉 특유의 표현을 추가하면 더 좋아요")
    
    # 6. 비유 품질 체크 (비유 섹션인 경우)
    if "[" in response and "]" in response:
        # 대괄호가 있으면 비유 섹션으로 간주
        bracket_count = response.count("[")
        if bracket_count > 1:
            warnings.append("비유 대상 대괄호가 2개 이상 - 1개만 사용 권장")
            score -= 3
    
    # 7. 부정적 표현 체크
    negative_words = ["못해", "안돼", "불가능", "어려워", "복잡해"]
    negative_count = sum(1 for word in negative_words if word in response)
    if negative_count > 2:
        warnings.append("부정적 표현이 많음")
        suggestions.append("긍정적이고 격려하는 톤으로 변경")
    
    # 8. 투자 조언 경고 체크 (중요)
    investment_keywords = ["사라", "팔아라", "추천", "무조건", "반드시 투자"]
    risky_advice = [kw for kw in investment_keywords if kw in response]
    if risky_advice:
        issues.append(f"투자 조언 금지 표현 감지: {', '.join(risky_advice)}")
        score -= 30
        suggestions.append("'알부엉은 투자 상담은 하지 않아. 실제 투자는 전문가와 상담해봐' 추가")
    
    # 최종 점수 보정
    score = max(0, min(100, score))
    
    # 전체 검증 통과 여부
    valid = len(issues) == 0 and score >= 60
    
    return {
        "valid": valid,
        "score": round(score, 1),
        "issues": issues,
        "warnings": warnings,
        "suggestions": suggestions
    }


def get_quality_report(response: str) -> str:
    """
    응답 품질 검증 결과를 사람이 읽기 쉬운 리포트로 반환
    
    Args:
        response: 검증할 응답 텍스트
        
    Returns:
        포맷된 품질 리포트 문자열
    """
    result = validate_albwoong_response(response)
    
    report_lines = []
    report_lines.append("=" * 50)
    report_lines.append("🦉 알부엉 응답 품질 검증 리포트")
    report_lines.append("=" * 50)
    report_lines.append(f"📊 품질 점수: {result['score']}/100")
    report_lines.append(f"✅ 검증 통과: {'통과' if result['valid'] else '실패'}")
    report_lines.append("")
    
    if result['issues']:
        report_lines.append("❌ 심각한 문제:")
        for issue in result['issues']:
            report_lines.append(f"  - {issue}")
        report_lines.append("")
    
    if result['warnings']:
        report_lines.append("⚠️ 경고 사항:")
        for warning in result['warnings']:
            report_lines.append(f"  - {warning}")
        report_lines.append("")
    
    if result['suggestions']:
        report_lines.append("💡 개선 제안:")
        for suggestion in result['suggestions']:
            report_lines.append(f"  - {suggestion}")
        report_lines.append("")
    
    if result['valid']:
        report_lines.append("🎉 이 응답은 알부엉 페르소나 규칙을 잘 따르고 있어요!")
    else:
        report_lines.append("🔧 위 사항들을 개선하면 더 좋은 응답이 될 거예요!")
    
    report_lines.append("=" * 50)
    
    return "\n".join(report_lines)
