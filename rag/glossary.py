"""
═══════════════════════════════════════════════════════════════════════
📚 금융 용어 사전 모듈 (RAG 시스템 통합)
═══════════════════════════════════════════════════════════════════════

## 📌 주요 변경 사항

### 1️⃣ 기존 시스템 (주석처리됨)
   - DEFAULT_TERMS 하드코딩 사전 (5개 용어)
   - 정적 용어 검색만 가능

### 2️⃣ 신규 RAG 시스템
   - CSV 기반 240+ 금융용어 로드
   - 벡터 데이터베이스 (ChromaDB) 연동
   - 의미 기반 유사도 검색 지원
   - 한국어 임베딩 모델 (jhgan/ko-sroberta-multitask)

## 🔧 필수 라이브러리 설치
```bash
pip install chromadb sentence-transformers pandas
```

## 📂 파일 구조
```
rag/
├── glossary.py (현재 파일)
└── glossary/
    └── 금융용어사전.csv (240+ 용어)
```

## 🚀 사용 방법

### 초기화 (자동)
```python
from rag.glossary import ensure_financial_terms

# 앱 시작 시 자동으로 RAG 초기화
ensure_financial_terms()
```

### 용어 설명
```python
from rag.glossary import explain_term

# RAG 벡터 검색으로 유사 용어 자동 매칭
explanation = explain_term("양적완화")
print(explanation)
```

### 본문 하이라이트
```python
from rag.glossary import highlight_terms

text = "한국은행이 기준금리를 인상했다"
highlighted = highlight_terms(text)
# 결과: 한국은행이 <mark>기준금리</mark>를 인상했다
```

### 벡터 검색 (고급)
```python
from rag.glossary import search_terms_by_rag

# 자연어 질문으로 관련 용어 찾기
results = search_terms_by_rag("중앙은행이 돈을 푸는 정책", top_k=3)
# 결과: [{'term': '양적완화', ...}, {'term': '기준금리', ...}, ...]
```

## 🔄 Fallback 메커니즘
- RAG 초기화 실패 시 자동으로 DEFAULT_TERMS 사전 사용
- CSV 파일 없어도 기본 5개 용어로 동작 보장

## 📊 CSV 파일 형식
- 컬럼: 금융용어, 유의어, 정의, 비유, 왜 중요?, 오해 교정, 예시, 단어 난이도
- 인코딩: UTF-8
═══════════════════════════════════════════════════════════════════════
"""

import re
import streamlit as st

# ═════════════════════════════════════════════════════════════
# 🆕 RAG 시스템 추가: CSV 기반 금융용어 벡터 검색
# - ChromaDB: 벡터 데이터베이스로 유사도 검색 지원
# - SentenceTransformer: 한국어 임베딩 모델
# - pandas: CSV 파일 로드
# ═════════════════════════════════════════════════════════════
import os
import pandas as pd
from typing import Dict, List, Optional

try:
    import chromadb
    from chromadb.config import Settings
except Exception:
    chromadb = None
    Settings = None

try:
    from sentence_transformers import SentenceTransformer
except Exception:
    SentenceTransformer = None

from persona.persona import albwoong_persona_rewrite_section, albwoong_persona_reply

_RAG_AVAILABLE = chromadb is not None and SentenceTransformer is not None

# ─────────────────────────────────────────────────────────────
# ✅ 기본 금융 용어 사전 (RAG/사전 없이도 동작하는 최소 세트)
# - 각 용어는 '정의', '설명', '비유'로 구성
# - 실제 서비스에서는 DB/CSV/RAG로 대체 가능
# ─────────────────────────────────────────────────────────────
DEFAULT_TERMS = {
    "양적완화": {
        "정의": "중앙은행이 시중에 통화를 공급하기 위해 국채 등을 매입하는 정책",
        "설명": "경기 부양을 위해 중앙은행이 돈을 풀어 시장 유동성을 높이는 방법입니다.",
        "비유": "마른 땅에 물을 뿌려주는 것처럼, 경제에 돈이라는 물을 공급하는 것입니다.",
    },
    "기준금리": {
        "정의": "중앙은행이 시중은행에 돈을 빌려줄 때 적용하는 기준이 되는 금리",
        "설명": "모든 금리의 기준이 되며, 기준금리가 오르면 대출이자도 함께 오릅니다.",
        "비유": "물가의 온도조절기와 같습니다. 경제가 과열되면 올리고, 침체되면 내립니다.",
    },
    "배당": {
        "정의": "기업이 벌어들인 이익 중 일부를 주주들에게 나눠주는 것",
        "설명": "주식을 보유한 주주에게 기업의 이익을 분배하는 방식입니다.",
        "비유": "함께 식당을 운영하는 동업자들이 매출 중 일부를 나눠갖는 것과 같습니다.",
    },
    "PER": {
        "정의": "주가수익비율. 주가를 주당순이익으로 나눈 값",
        "설명": "주식이 1년 치 이익의 몇 배에 거래되는지를 나타냅니다. 낮을수록 저평가된 것으로 볼 수 있습니다.",
        "비유": "1년에 100만원 버는 가게를 몇 년 치 수익을 주고 사는지를 나타냅니다.",
    },
    "환율": {
        "정의": "서로 다른 두 나라 화폐의 교환 비율",
        "설명": "원화를 달러로, 달러를 원화로 바꿀 때 적용되는 비율입니다.",
        "비유": "해외 쇼핑몰에서 물건을 살 때 적용되는 환전 비율입니다.",
    },
}

# ─────────────────────────────────────────────────────────────
# 🧰 세션에 금융 용어 사전 보장 (RAG 통합 버전)
#   - 변경 사항:
#   1. 기존: DEFAULT_TERMS만 복사
#   2. 신규: RAG 시스템 자동 초기화 추가
#   3. Fallback: RAG 실패 시 기존 DEFAULT_TERMS 사용
# - Streamlit은 사용자별 세션 상태(st.session_state)를 제공
# - 최초 1회만 DEFAULT_TERMS를 복사해 넣어 중간 변경에도 원본 보존
# ─────────────────────────────────────────────────────────────
def ensure_financial_terms():
    """
    금융 용어 사전 초기화 및 RAG 시스템 자동 시작
    - 세션 최초 실행 시 RAG 시스템을 초기화
    - Fallback으로 기본 용어 사전도 유지
    """
    # 1️⃣ 기본 용어 사전 초기화 (Fallback용)
    if "financial_terms" not in st.session_state:
        st.session_state.financial_terms = DEFAULT_TERMS.copy()

    # 2️⃣ RAG 시스템 자동 초기화 (최초 1회만)
    if "rag_initialized" not in st.session_state:
        if not _RAG_AVAILABLE:
            st.session_state.rag_initialized = False
            st.warning("⚠️ 고급 용어 검색 모듈이 설치되지 않아 기본 사전을 사용합니다.")
        else:
            initialize_rag_system()

# ─────────────────────────────────────────────────────────────
# 🔴 기존 함수 (주석처리): 하드코딩된 사전 기반 하이라이트
# ─────────────────────────────────────────────────────────────
# def highlight_terms(text: str) -> str:
#     highlighted = text
#
#     # 현재 세션의 용어 사전에서 키(용어)만 순회
#     for term in st.session_state.financial_terms.keys():
#         # re.escape(term): 특수문자 포함 용어도 안전하게 매칭
#         # re.IGNORECASE: 대소문자 구분 없이 검색 (영문 용어 대비)
#         pattern = re.compile(re.escape(term), re.IGNORECASE)
#
#         # ⚠️ 주의: 아래 대체 문자열의 {term}은 '사전 키' 표기를 그대로 사용
#         # - 매칭된 원래 표기(대소문자)를 유지하고 싶다면 repl 함수 사용 필요
#         #   예) pattern.sub(lambda m: f"...>{m.group(0)}</mark>", highlighted)
#         highlighted = pattern.sub(
#             f'<mark class="clickable-term" data-term="{term}" '
#             f'style="background-color: #FFEB3B; cursor: pointer; padding: 2px 4px; border-radius: 3px;">{term}</mark>',
#             highlighted,
#         )
#     return highlighted


# ─────────────────────────────────────────────────────────────
# ✨ 본문에서 금융 용어 하이라이트 (RAG 통합 버전)
# - 변경 사항:
#   1. 기존: st.session_state.financial_terms 사전에서만 검색
#   2. 신규: RAG에 저장된 모든 용어를 하이라이트 대상으로 사용
#   3. Fallback: RAG 미초기화 시 기존 사전 사용
# - 기사 본문 텍스트에서 용어를 찾아 <mark> 태그로 감싸 강조
# - 대소문자 무시(re.IGNORECASE) → 영문 약어 등에도 대응
# - data-term 속성: 추후 JS/이벤트 연결 시 어떤 용어인지 식별 용이
# - Streamlit 출력 시 st.markdown(..., unsafe_allow_html=True) 필요
# ─────────────────────────────────────────────────────────────
def highlight_terms(text: str) -> str:
    """
    기사 본문에서 금융 용어를 찾아 하이라이트 처리

    Args:
        text: 원본 텍스트 (기사 본문 등)

    Returns:
        금융 용어가 하이라이트 처리된 HTML 문자열
    """
    highlighted = text
    terms_to_highlight = set()

    # 1️⃣ RAG가 초기화되어 있으면 RAG의 모든 용어 사용
    if st.session_state.get("rag_initialized", False):
        try:
            collection = st.session_state.get("rag_collection")
            if collection is None:
                raise ValueError("RAG 컬렉션이 없습니다")
            
            # 모든 문서의 메타데이터에서 용어 추출
            all_data = collection.get()
            if all_data and all_data['metadatas']:
                for metadata in all_data['metadatas']:
                    term = metadata.get('term', '').strip()
                    if term:
                        terms_to_highlight.add(term)
        except Exception as e:
            # RAG 오류 시 Fallback: 기본 사전 사용
            st.session_state.rag_initialized = False  # 실패 상태로 표시
            terms_to_highlight = set(st.session_state.get("financial_terms", DEFAULT_TERMS).keys())
    else:
        # 2️⃣ RAG 미초기화 시 기존 사전 사용
        terms_to_highlight = set(st.session_state.get("financial_terms", DEFAULT_TERMS).keys())

    # 3️⃣ 용어별로 하이라이트 처리
    # 긴 용어부터 처리하여 부분 매칭 방지 (예: "부가가치세"가 "부가가치"보다 먼저 처리)
    sorted_terms = sorted(terms_to_highlight, key=len, reverse=True)

    # 이미 하이라이트된 부분을 보호하기 위한 임시 플레이스홀더 사용
    placeholders = {}
    placeholder_counter = 0

    for term in sorted_terms:
        if not term:  # 빈 문자열 스킵
            continue

        # 플레이스홀더가 아닌 실제 텍스트만 매칭하도록 패턴 생성
        # __PLACEHOLDER_로 시작하는 부분은 제외
        escaped_term = re.escape(term)

        # 매칭된 원래 표기를 유지하면서 하이라이트
        matches = []
        pattern = re.compile(escaped_term, re.IGNORECASE)

        for match in pattern.finditer(highlighted):
            # 매칭된 위치가 플레이스홀더 안에 있는지 확인
            start_pos = match.start()
            # 매칭 위치 이전에 플레이스홀더가 있고 아직 닫히지 않았는지 체크
            prefix = highlighted[:start_pos]
            # 플레이스홀더 안에 있지 않은 경우만 저장
            if '__PLACEHOLDER_' not in highlighted[max(0, start_pos-20):start_pos]:
                matches.append(match)

        # 뒤에서부터 치환 (인덱스 변경 방지)
        for match in reversed(matches):
            matched_text = match.group(0)
            # HTML 태그 생성 (Streamlit은 클릭 이벤트를 지원하지 않으므로 시각적 표시만)
            placeholder = f"__PLACEHOLDER_{placeholder_counter}__"
            mark_html = (
                f'<mark class="financial-term" '
                f'style="background-color: #FFEB3B; padding: 2px 4px; border-radius: 3px;">'
                f'{matched_text}</mark>'
            )
            placeholders[placeholder] = mark_html
            placeholder_counter += 1

            # 텍스트 치환
            highlighted = highlighted[:match.start()] + placeholder + highlighted[match.end():]

    # 모든 플레이스홀더를 실제 HTML로 복원
    for placeholder, mark_html in placeholders.items():
        highlighted = highlighted.replace(placeholder, mark_html)

    return highlighted

def _fmt(header_icon: str, header_text: str, body_md: str) -> str:
    if not body_md or not body_md.strip():
        return ""
    return f"{header_icon} **{header_text}**\n\n{body_md}\n"


def explain_term(term: str, chat_history=None, return_rag_info: bool = False):
    """용어 설명 생성 (RAG 정확 매칭 우선, 실패 시 기본 사전 사용)"""
    rag_info: Optional[Dict] = None

    if st.session_state.get("rag_initialized", False):
        try:
            collection = st.session_state.get("rag_collection")
            if collection is None:
                raise ValueError("RAG 컬렉션이 없습니다")

            all_data = collection.get()
            if all_data and all_data["metadatas"]:
                for metadata in all_data["metadatas"]:
                    rag_term = (metadata.get("term") or "").strip()
                    synonym = (metadata.get("synonym") or "").strip()

                    if rag_term.lower() != term.lower() and (not synonym or synonym.lower() != term.lower()):
                        continue

                    definition = metadata.get("definition", "")
                    analogy = metadata.get("analogy", "")
                    importance = metadata.get("importance", "")
                    correction = metadata.get("correction", "")
                    example = metadata.get("example", "")

                    if return_rag_info:
                        rag_info = {
                            "search_method": "exact_match",
                            "matched_term": rag_term,
                            "synonym_used": synonym.lower() == term.lower() if synonym else False,
                            "source": "rag"
                        }

                    parts: List[str] = []
                    parts.append(f"🤖 **{rag_term}** 에 대해 설명해줄게! 🎯\n")

                    if definition:
                        out = albwoong_persona_rewrite_section(definition, "정의", term=rag_term, max_sentences=2)
                        parts.append(_fmt("📖", "정의", out))

                    if analogy:
                        out = albwoong_persona_rewrite_section(analogy, "비유로 이해하기", term=rag_term, max_sentences=2)
                        parts.append(_fmt("🌟", "비유로 이해하기", out))

                    if importance:
                        out = albwoong_persona_rewrite_section(importance, "왜 중요할까?", term=rag_term, max_sentences=2)
                        parts.append(_fmt("❗", "왜 중요할까?", out))

                    if correction:
                        out = albwoong_persona_rewrite_section(correction, "흔한 오해", term=rag_term, max_sentences=2)
                        parts.append(_fmt("⚠️", "흔한 오해", out))

                    if example:
                        out = albwoong_persona_rewrite_section(example, "예시", term=rag_term, max_sentences=2)
                        parts.append(_fmt("📰", "예시", out))

                    parts.append("더 궁금한 점 있으면 편하게 물어봐!")
                    response = "\n".join([p for p in parts if p])

                    if return_rag_info:
                        return response, rag_info
                    return response
        except Exception as e:
            st.warning(f"⚠️ RAG 검색 중 오류, 기본 사전 사용: {e}")

    terms = st.session_state.get("financial_terms", DEFAULT_TERMS)

    if term not in terms:
        message = f"'{term}'에 대한 정보가 아직 없어. 다른 용어를 선택해줘."
        if return_rag_info:
            return message, None
        return message

    info = terms[term]
    parts: List[str] = []
    parts.append(f"🤖 **{term}** 에 대해 설명해줄게! 🎯\n")

    if info.get("정의"):
        out = albwoong_persona_rewrite_section(info["정의"], "정의", term=term, max_sentences=2)
        parts.append(_fmt("📖", "정의", out))

    if info.get("비유"):
        out = albwoong_persona_rewrite_section(info["비유"], "비유로 이해하기", term=term, max_sentences=2)
        parts.append(_fmt("🌟", "비유로 이해하기", out))

    if info.get("설명"):
        out = albwoong_persona_rewrite_section(info["설명"], "쉬운 설명", term=term, max_sentences=2)
        parts.append(_fmt("💡", "쉬운 설명", out))

    parts.append("더 궁금한 점 있으면 편하게 물어봐!")
    response = "\n".join([p for p in parts if p])

    if return_rag_info:
        return response, None
    return response
