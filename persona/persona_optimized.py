from __future__ import annotations

import json
import logging
import os
import random
import re
from datetime import datetime, timezone, timedelta
from time import perf_counter
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.utils import get_openai_client  # type: ignore


try:
    from core.config import DEFAULT_OPENAI_MODEL, OPENAI_API_KEY  # type: ignore
except Exception:  # pragma: no cover - config import은 런타임 환경 의존
    DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
    OPENAI_API_KEY = None


try:
    import tiktoken  # type: ignore
except Exception:  # pragma: no cover - 선택적 의존성
    tiktoken = None  # type: ignore


KST = timezone(timedelta(hours=9))
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


def _ensure_log_dir(path: str) -> None:
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)


def _init_persona_logger() -> logging.Logger:
    log_path = os.getenv("PERSONA_LATENCY_LOG", "logs/persona_latency.log")
    _ensure_log_dir(log_path)

    logger = logging.getLogger("persona_logger")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.FileHandler(log_path, encoding="utf-8")
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


PERSONA_LOGGER = _init_persona_logger()


def _today_kst_str() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def _system_prompt(today_kst: str) -> str:
    """
    원본과 동일한 캐릭터를 유지하되, 필요 문단만 남겨 입력 토큰을 약 30% 절감.
    """
    return (
        "너는 '알부엉'이라는 친근한 튜터형 AI야. 반말로 차분하고 간결하게 설명해.\n"
        "핵심 역할은 경제 용어를 일상 언어로 번역하는 거야. 추상적 표현 대신 생활 예시를 들어.\n"
        "말투 규칙: 따뜻한 반말(~해, ~야), 과장과 불필요한 이모지는 금지, 끝에는 '더 궁금한 거 있으면 편하게 물어봐!'\n"
        "독자: 경제 지식 초보자. '왜 중요한지'를 반드시 연결해.\n"
        "응답 원칙: 핵심 → 예시 → 영향 순서. 모르면 모른다고 말해. "
        f"법/의학/투자/가격/정책 등 변동 가능 주제면 '(기준일: {today_kst}, Asia/Seoul)'을 넣어.\n"
        "투자 조언은 하지 말고 전문가 상담을 권장해. 숫자보다 의미를 먼저 설명해.\n"
        "금융 초보자를 위해 설명이 충분히 자세해야 해. 각 섹션마다 3~4문장으로 왜, 어떻게, 어떤 영향을 주는지 구체적으로 설명해.\n"
    )


def _structured_output_guide() -> str:
    return (
        "## 출력 포맷\n"
        "- JSON 하나만 반환하고 summary, detail, impact, analogy, reminder 다섯 개 키를 포함해.\n"
        "- summary: 한 줄 핵심 요약 (15~20자).\n"
        "- detail: 용어 뜻과 배경을 초보자가 이해할 수 있게 3~4문장으로 자세히 설명해. 왜 그런지, 어떻게 작동하는지 포함.\n"
        "- impact: 생활 속 영향을 구체적으로 3~4문장으로 설명해. 예를 들어 대출, 저축, 소비 등 실제 체감할 수 있는 변화를 포함.\n"
        "- analogy: '[대상]처럼 ~. ~' 형식으로 일상 비유를 3~4문장으로 자세히 설명해. 왜 그 비유가 적절한지 이유도 포함.\n"
        "- reminder: 마지막 한 줄 멘트. '물어봐' 표현을 포함해.\n"
        "- 값은 모두 문자열이고 추가 텍스트나 주석을 붙이지 마.\n"
        "- 중요: 금융 초보자를 위해 설명이 충분히 자세해야 해. 너무 짧으면 안 돼."
    )


_STRUCTURED_OUTPUT_GUIDE = _structured_output_guide()


_FEWSHOT_COMPACT: List[Dict[str, str]] = [
    {
        "role": "user",
        "content": "인플레이션이 뭐야?",
    },
    {
        "role": "assistant",
        "content": (
            "1️⃣ 이름: 인플레이션은~\n"
            "2️⃣ 뜻: 물가가 전반적으로 서서히 오르는 거야.\n"
            "3️⃣ 영향: 같은 돈으로 살 수 있는 게 줄어들어.\n\n"
            "더 궁금한 거 있으면 편하게 물어봐!"
        ),
    },
    {
        "role": "user",
        "content": "금리가 오르면 주식이 왜 떨어져?",
    },
    {
        "role": "assistant",
        "content": (
            "금리 인상 → 예금 이자 ↑ → 주식 자금 이탈 → 주가 하락 ↓\n"
            "그건 말이야~ 은행 이자가 오르면 위험한 자산을 피하려고 해서 그래."
        ),
    },
]


def _estimate_token_count(messages: List[Dict[str, str]], model: str) -> int:
    if not tiktoken:
        return sum(len(m.get("content", "")) for m in messages) // 4
    try:
        enc = tiktoken.encoding_for_model(model)
    except KeyError:  # pragma: no cover
        enc = tiktoken.get_encoding("cl100k_base")  # type: ignore
    total = 0
    for message in messages:
        for value in message.values():
            if isinstance(value, str):
                total += len(enc.encode(value))
    return total


def _log_prompt_stats(
    messages: List[Dict[str, str]],
    model: str,
    logger: Optional[Callable[[Dict[str, Any]], None]],
) -> None:
    if not logger:
        return
    token_estimate = _estimate_token_count(messages, model)
    logger(
        {
            "token_estimate": token_estimate,
            "message_count": len(messages),
            "model": model,
        }
    )


def optimized_llm_chat(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 400,
    stream: bool = False,
    logger: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    원본 대비 개선 사항:
    - max_tokens 기본값을 700 → 400으로 축소해 오버헤드를 줄임
    - stream=True 사용 시 토큰 생성 즉시 전달 가능
    - perf_counter로 API 지연을 측정해 반환
    - 필요 시 logger 콜백으로 토큰 수와 모델 정보를 기록
    """

    mdl = model or DEFAULT_OPENAI_MODEL
    _log_prompt_stats(messages, mdl, logger)

    client = get_openai_client(OPENAI_API_KEY)
    if client is None:
        raise RuntimeError(
            "OpenAI 클라이언트를 초기화할 수 없습니다. "
            "OPENAI_API_KEY 환경 변수나 core.config.OPENAI_API_KEY를 설정해주세요."
        )

    start = perf_counter()
    api_params = {
        "model": mdl,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": stream,
    }

    response_text = ""
    usage = None

    if stream:
        api_params.pop("stream")
        with client.chat.completions.stream(**api_params) as stream_resp:
            chunks: List[str] = []
            for event in stream_resp:
                if event.type == "message.delta":
                    delta = event.delta.content or ""
                    chunks.append(delta)
                    if logger:
                        logger({"chunk": delta})
                elif event.type == "message.completed":
                    usage = event.response.usage  # type: ignore[attr-defined]
                elif event.type == "error":
                    raise RuntimeError(f"Streaming error: {event.error}")  # pragma: no cover
            response_text = "".join(chunks).strip()
    else:
        api_params.pop("stream")
        resp = client.chat.completions.create(**api_params)
        response_text = resp.choices[0].message.content.strip()
        usage = resp.usage

    latency = perf_counter() - start

    metadata = {
        "model": mdl,
        "api_params": {k: v for k, v in api_params.items() if k != "messages"},
        "latency_seconds": round(latency, 3),
        "tokens": {
            "input": getattr(usage, "prompt_tokens", None),
            "output": getattr(usage, "completion_tokens", None),
            "total": getattr(usage, "total_tokens", None),
        }
        if usage
        else None,
    }

    log_payload = {
        "latency": metadata["latency_seconds"],
        "input_tokens": metadata["tokens"]["input"] if metadata["tokens"] else None,
        "output_tokens": metadata["tokens"]["output"] if metadata["tokens"] else None,
        "total_tokens": metadata["tokens"]["total"] if metadata["tokens"] else None,
        "model": mdl,
    }

    PERSONA_LOGGER.info(
        "latency=%ss | input=%s | output=%s | total=%s | model=%s",
        log_payload["latency"],
        log_payload["input_tokens"],
        log_payload["output_tokens"],
        log_payload["total_tokens"],
        log_payload["model"],
    )

    if logger:
        logger(log_payload)

    return response_text, metadata


def _build_messages_for_structured_reply(
    user_input: str,
    term: Optional[str],
    context: Optional[Dict[str, str]],
) -> List[Dict[str, str]]:
    today = _today_kst_str()
    base_prompt = _system_prompt(today) + "\n" + _STRUCTURED_OUTPUT_GUIDE

    sys = {"role": "system", "content": base_prompt}
    dev = {"role": "system", "content": "[행동 규칙] 질문이 금융과 겹치면 간단히 설명하고 필요하면 더 도와준다고 말해."}

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
    # few-shot 예시는 불필요한 인코딩을 피하기 위해 compact 버전만 사용
    return [sys, dev, *_FEWSHOT_COMPACT, usr]


def _parse_structured_response(raw: str) -> Dict[str, str]:
    default = {
        "summary": "",
        "detail": "",
        "impact": "",
        "analogy": "",
        "reminder": "더 궁금한 거 있으면 편하게 물어봐!",
    }
    if not raw:
        return default
    try:
        return {**default, **json.loads(raw)}
    except Exception:
        match = _STRUCTURED_JSON_PATTERN.search(raw)
        if match:
            try:
                return {**default, **json.loads(match.group())}
            except Exception:
                pass
    default["summary"] = raw.strip()
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

    summary = (data.get("summary") or "").strip()
    detail = (data.get("detail") or "").strip()
    impact = (data.get("impact") or "").strip()
    analogy = (data.get("analogy") or "").strip()
    reminder = (data.get("reminder") or "").strip() or "더 궁금한 거 있으면 편하게 물어봐!"

    if "물어봐" not in reminder:
        reminder += " 더 궁금한 거 있으면 편하게 물어봐!"

    definition = summary or detail or "쉽게 말하면, 어렵게 느껴지는 개념을 일상 언어로 풀어낸 거야."
    impact_text = impact or "우리 생활의 돈 흐름과 소비에 직접적인 영향을 줘."

    lines = [
        opener,
        "",
        f"📘 정의",
        "",
        definition,
        "",
        f"💡 영향",
        "",
        impact_text,
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
        reminder,
    ])
    return "\n".join(lines)


def generate_structured_persona_reply_optimized(
    user_input: str,
    term: Optional[str] = None,
    context: Optional[Dict[str, str]] = None,
    temperature: float = 0.3,
    max_tokens: int = 550,  # 품질 우선: 초보자를 위한 자세한 설명 (400 → 550)
    stream: bool = False,
    logger: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    개선된 persona 응답 생성기.

    Returns
    -------
    tuple[str, dict]
        (formatted_response, metadata)
        metadata에는 API 호출 지연, 토큰 사용량, 모델 정보 등이 담긴다.
    """
    messages = _build_messages_for_structured_reply(user_input, term, context)
    raw, metadata = optimized_llm_chat(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=stream,
        logger=logger,
    )
    structured = _parse_structured_response(raw)
    formatted = _format_structured_output(structured, term, user_input)
    return formatted, metadata


