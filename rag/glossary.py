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
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

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
# - 변경 사항:
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

# ─────────────────────────────────────────────────────────────
# 🦉 챗봇 응답용: 용어 설명 생성
# - 사전에 없으면 안내 문구 반환
# - 있으면 '정의/설명/비유'를 포맷팅하여 마크다운으로 반환
# - chat_history는 맥락 강화용 파라미터(현재는 미사용)
# ─────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────
# 🔴 기존 함수 (주석처리): 하드코딩된 사전 기반 설명
# - RAG 시스템 도입 전 최소 세트 기반 동작 방식
# ─────────────────────────────────────────────────────────────
# def explain_term(term: str, chat_history):
#     terms = st.session_state.financial_terms
#
#     # 존재하지 않는 용어 처리
#     if term not in terms:
#         return f"'{term}'에 대한 정보가 금융 사전에 없습니다. 다른 용어를 선택해주세요."
#
#     info = terms[term]
#
#     # 마크다운 포맷으로 친절한 설명 구성
#     return (
#         f"**{term}** 에 대해 설명해드릴게요! 🎯\n\n"
#         f"📖 **정의**\n{info['정의']}\n\n"
#         f"💡 **쉬운 설명**\n{info['설명']}\n\n"
#         f"🌟 **비유로 이해하기**\n{info['비유']}\n\n"
#         f"더 궁금한 점이 있으시면 언제든지 물어보세요!"
#     )


# ═════════════════════════════════════════════════════════════
# 🆕 RAG 시스템 핵심 기능
# ═════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────
# 📁 CSV 파일에서 금융용어 로드
# - rag/glossary/금융용어.csv 파일을 pandas로 읽어옴
# - 컬럼: 번호, 금융용어, 정의, 비유, 왜 중요?, 오해 교정, 예시
# ─────────────────────────────────────────────────────────────
def load_glossary_from_csv() -> pd.DataFrame:
    """금융용어.csv 파일을 로드하여 DataFrame으로 반환"""
    csv_path = os.path.join(os.path.dirname(__file__), "glossary", "금융용어.csv")

    if not os.path.exists(csv_path):
        st.warning(f"⚠️ 금융용어 파일을 찾을 수 없습니다: {csv_path}")
        return pd.DataFrame()

    try:
        df = pd.read_csv(csv_path, encoding="utf-8")
        # 결측치를 빈 문자열로 처리
        df = df.fillna("")
        return df
    except Exception as e:
        st.error(f"❌ CSV 로드 중 오류 발생: {e}")
        return pd.DataFrame()


# ─────────────────────────────────────────────────────────────
# 🧠 RAG 시스템 초기화 및 벡터 DB 구축
# - ChromaDB를 사용하여 벡터 데이터베이스 생성
# - 한국어 임베딩 모델 (jhgan/ko-sroberta-multitask) 사용
# - 금융용어 + 정의 + 비유를 결합하여 벡터화
# ─────────────────────────────────────────────────────────────
def initialize_rag_system():
    """RAG 시스템 초기화: 벡터 DB 생성 및 금융용어 임베딩"""

    # 세션에 이미 초기화되어 있으면 스킵
    if "rag_initialized" in st.session_state and st.session_state.rag_initialized:
        return

    try:
        # 1️⃣ CSV 로드
        df = load_glossary_from_csv()
        if df.empty:
            st.warning("⚠️ CSV 파일이 비어있어 기본 용어 사전을 사용합니다.")
            st.session_state.rag_initialized = False
            return

        # 2️⃣ 한국어 임베딩 모델 로드 (최초 실행시 자동 다운로드)
        with st.spinner("🔄 한국어 임베딩 모델 로딩 중..."):
            embedding_model = SentenceTransformer('jhgan/ko-sroberta-multitask')

        # 3️⃣ ChromaDB 클라이언트 생성 (인메모리 방식)
        chroma_client = chromadb.Client(Settings(
            anonymized_telemetry=False,
            is_persistent=False  # 메모리 방식 (빠른 실행)
        ))

        # 4️⃣ 컬렉션 생성 또는 기존 컬렉션 삭제 후 재생성
        try:
            chroma_client.delete_collection(name="financial_terms")
        except:
            pass  # 컬렉션이 없으면 무시

        collection = chroma_client.create_collection(
            name="financial_terms",
            metadata={"description": "금융 용어 사전 벡터 DB"}
        )

        # 5️⃣ 각 용어를 벡터화하여 DB에 저장
        documents = []
        metadatas = []
        ids = []

        for idx, row in df.iterrows():
            term = str(row.get("금융용어", "")).strip()
            if not term:  # 빈 용어는 스킵
                continue

            # 검색 문서: 용어 + 정의 + 비유를 결합
            definition = str(row.get("정의", "")).strip()
            analogy = str(row.get("비유", "")).strip()

            # 벡터화할 텍스트 생성
            search_text = f"{term} - {definition}"
            if analogy:
                search_text += f" | 비유: {analogy}"

            documents.append(search_text)

            # 메타데이터: 전체 정보 저장
            metadatas.append({
                "term": term,
                "definition": definition,
                "analogy": analogy,
                "importance": str(row.get("왜 중요?", "")).strip(),
                "correction": str(row.get("오해 교정", "")).strip(),
                "example": str(row.get("예시", "")).strip(),
            })

            ids.append(f"term_{idx}")

        # 6️⃣ 임베딩 생성 및 DB에 추가
        with st.spinner(f"🔄 {len(documents)}개 금융용어 벡터화 중..."):
            embeddings = embedding_model.encode(documents, show_progress_bar=False)

            collection.add(
                documents=documents,
                metadatas=metadatas,
                embeddings=embeddings.tolist(),
                ids=ids
            )

        # 7️⃣ 세션 상태에 저장
        st.session_state.rag_collection = collection
        st.session_state.rag_embedding_model = embedding_model
        st.session_state.rag_initialized = True
        st.session_state.rag_term_count = len(documents)

        st.success(f"✅ RAG 시스템 초기화 완료! ({len(documents)}개 용어 로드)")

    except Exception as e:
        st.error(f"❌ RAG 초기화 실패: {e}")
        st.session_state.rag_initialized = False


# ─────────────────────────────────────────────────────────────
# 🔍 RAG 기반 용어 검색
# - 사용자 질문을 벡터화하여 유사한 용어 검색
# - 상위 k개의 관련 용어 반환
# ─────────────────────────────────────────────────────────────
def search_terms_by_rag(query: str, top_k: int = 3) -> List[Dict]:
    """RAG를 사용하여 질문과 관련된 금융 용어 검색"""

    if not st.session_state.get("rag_initialized", False):
        return []

    try:
        collection = st.session_state.get("rag_collection")
        embedding_model = st.session_state.get("rag_embedding_model")
        
        if collection is None or embedding_model is None:
            raise ValueError("RAG 시스템이 제대로 초기화되지 않았습니다")

        # 쿼리 임베딩
        query_embedding = embedding_model.encode([query])[0]

        # 유사도 검색
        results = collection.query(
            query_embeddings=[query_embedding.tolist()],
            n_results=top_k
        )

        # 결과 포맷팅
        matched_terms = []
        if results and results['metadatas']:
            for metadata in results['metadatas'][0]:
                matched_terms.append(metadata)

        return matched_terms

    except Exception as e:
        st.error(f"❌ RAG 검색 중 오류: {e}")
        return []


# ─────────────────────────────────────────────────────────────
# 🦉 챗봇 응답용: RAG 기반 용어 설명 생성 (기존 함수 대체)
# - 변경 사항:
#   1. 기존: 하드코딩된 DEFAULT_TERMS 사전에서 검색
#   2. 신규: RAG 벡터 검색으로 유사 용어 찾기
#   3. Fallback: RAG 실패 시 기존 방식으로 동작
# ─────────────────────────────────────────────────────────────
def explain_term(term: str, chat_history=None, return_rag_info: bool = False) -> str:
    """
    용어 설명 생성 (RAG 정확 매칭 우선, 실패 시 기존 사전 사용)

    Args:
        term: 설명할 금융 용어
        chat_history: 채팅 이력 (향후 컨텍스트 강화용)
        return_rag_info: True면 응답과 함께 RAG 정보도 반환

    Returns:
        return_rag_info=False: 마크다운 형식의 용어 설명 (str)
        return_rag_info=True: (용어 설명, RAG 정보 딕셔너리)
          RAG 정보 예시: {
              "search_method": "exact_match",
              "matched_term": "기준금리",
              "source": "rag" 또는 "default_terms"
          }
    """
    rag_info = {
        "search_method": None,
        "matched_term": None,
        "source": None
    }

    # 1️⃣ RAG 시스템이 초기화되어 있으면 정확한 용어 매칭 시도
    if st.session_state.get("rag_initialized", False):
        try:
            collection = st.session_state.get("rag_collection")
            if collection is None:
                raise ValueError("RAG 컬렉션이 없습니다")
            
            all_data = collection.get()

            if all_data and all_data['metadatas']:
                # 정확한 용어 매칭 (대소문자 무시, 완전 일치)
                for metadata in all_data['metadatas']:
                    rag_term = metadata.get('term', '').strip()

                    # 용어가 정확히 일치하는지 확인
                    if rag_term.lower() == term.lower():

                        # RAG 정보 수집
                        rag_info = {
                            "search_method": "exact_match",
                            "matched_term": rag_term,
                            "source": "rag",
                            "synonym_used": synonym.lower() == term.lower() if synonym else False
                        }

                        # 매칭된 용어 정보로 설명 생성
                        term_name = rag_term
                        definition = metadata.get("definition", "")
                        analogy = metadata.get("analogy", "")
                        importance = metadata.get("importance", "")
                        correction = metadata.get("correction", "")
                        example = metadata.get("example", "")

                        # 마크다운 포맷으로 친절한 설명 구성
                        response = f"**{term_name}** 에 대해 설명해드릴게요! 🎯\n\n"

                        if definition:
                            response += f"📖 **정의**\n{definition}\n\n"

                        if analogy:
                            response += f"🌟 **비유로 이해하기**\n{analogy}\n\n"

                        if importance:
                            response += f"❗ **왜 중요할까요?**\n{importance}\n\n"

                        if correction:
                            response += f"⚠️ **흔한 오해**\n{correction}\n\n"

                        if example:
                            response += f"📰 **예시**\n{example}\n\n"

                        response += "더 궁금한 점이 있으시면 언제든지 물어보세요!"

                        if return_rag_info:
                            return response, rag_info
                        return response

        except Exception as e:
            st.warning(f"⚠️ RAG 검색 중 오류 발생, 기본 사전을 사용합니다: {e}")
            rag_info["source"] = "fallback"  # 예외 발생 시에도 rag_info 기본값 유지

    # 2️⃣ Fallback: 기존 하드코딩된 사전 사용
    terms = st.session_state.get("financial_terms", DEFAULT_TERMS)

    if term not in terms:
        error_msg = f"'{term}'에 대한 정보가 금융 사전에 없습니다. 다른 용어를 선택해주세요."
        if return_rag_info:
            rag_info["error"] = "term_not_found"
            rag_info["source"] = "default_terms"
            return error_msg, rag_info
        return error_msg

    info = terms[term]
    
    # 기본 사전 사용 정보 업데이트
    rag_info["source"] = "default_terms"

    # 마크다운 포맷으로 친절한 설명 구성
    response = (
        f"**{term}** 에 대해 설명해드릴게요! 🎯\n\n"
        f"📖 **정의**\n{info['정의']}\n\n"
        f"💡 **쉬운 설명**\n{info['설명']}\n\n"
        f"🌟 **비유로 이해하기**\n{info['비유']}\n\n"
        f"더 궁금한 점이 있으시면 언제든지 물어보세요!"
    )
    
    if return_rag_info:
        return response, rag_info
    return response