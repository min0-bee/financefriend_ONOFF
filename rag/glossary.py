"""
═══════════════════════════════════════════════════════════════════════
📚 금융 용어 사전 모듈 (RAG 시스템 통합)
═══════════════════════════════════════════════════════════════════════
"""

import re
import streamlit as st
import pickle
import hashlib
import json
import gzip
import os
import time
import threading
import pandas as pd
from typing import Dict, List, Optional
from persona.persona import (
    albwoong_persona_reply,
    generate_structured_persona_reply,
)
from core.logger import get_supabase_client
from core.config import SUPABASE_ENABLE
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
import pickle
import hashlib
import json
import gzip
from core.logger import get_supabase_client
from core.config import SUPABASE_ENABLE

# ─────────────────────────────────────────────────────────────
# 🚀 전역 캐시: 임베딩 모델 (세션 간 재사용)
# - SentenceTransformer 모델은 메모리 사용량이 크므로 전역으로 캐시
# - 모든 세션에서 동일한 모델 인스턴스 재사용
# ─────────────────────────────────────────────────────────────
_embedding_model_cache = None

# ─────────────────────────────────────────────────────────────
# 🚀 전역 캐시: 임베딩 모델 (세션 간 재사용)
# ─────────────────────────────────────────────────────────────
_embedding_model_cache = None
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


def _cache_rag_metadata(metadatas: List[Dict]):
    """
    RAG 메타데이터를 세션에 캐싱하여 반복적인 collection.get() 호출을 줄입니다.
    term / synonym 모두 소문자로 키를 만들어 lookup 속도를 높이고,
    하이라이트용 용어 세트도 함께 저장합니다.
    """
    metadata_map: Dict[str, Dict] = {}
    highlight_terms = set()

    for meta in metadatas:
        term = (meta.get("term") or "").strip()
        if term:
            metadata_map[term.lower()] = meta
            highlight_terms.add(term)

        synonym_field = (meta.get("synonym") or "").strip()
        if synonym_field:
            for raw in re.split(r"[,\n]", synonym_field):
                synonym = raw.strip()
                if synonym:
                    metadata_map[synonym.lower()] = meta
                    highlight_terms.add(synonym)

    st.session_state["rag_metadata_by_term"] = metadata_map
    st.session_state["rag_terms_for_highlight"] = highlight_terms


def _perf_enabled() -> bool:
    return st.session_state.get("rag_perf_enable", True)


def _perf_step(perf_enabled: bool, steps: List[Dict], label: str, start_time: float) -> float:
    if not perf_enabled:
        return time.perf_counter()
    elapsed_ms = (time.perf_counter() - start_time) * 1000
    steps.append({"step": label, "ms": round(elapsed_ms, 2)})
    return time.perf_counter()


def _record_perf(section: str, steps: List[Dict]):
    if not steps:
        return
    logs = st.session_state.setdefault("rag_perf_logs", {})
    history = logs.setdefault(section, [])
    history.append({
        "timestamp": time.strftime("%H:%M:%S", time.localtime()),
        "steps": steps,
    })
    logs[section] = history[-10:]
    st.session_state[f"rag_last_{section}_perf"] = steps


def _sync_supabase_async(documents, embeddings, metadatas, ids, checksum):
    if not SUPABASE_ENABLE:
        return
    if st.session_state.get("rag_cache_synced") or st.session_state.get("rag_cache_sync_in_progress"):
        return

    def _worker():
        try:
            if _save_embeddings_to_supabase(documents, embeddings, metadatas, ids, checksum):
                st.session_state["rag_cache_synced"] = True
        except Exception as e:
            st.session_state["rag_cache_sync_error"] = str(e)
        finally:
            st.session_state["rag_cache_sync_in_progress"] = False

    st.session_state["rag_cache_sync_in_progress"] = True
    threading.Thread(target=_worker, daemon=True).start()

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
        text: 원본 텍스트(기사 본문 등)

    Returns:
        금융 용어가 하이라이트 처리된 HTML 문자열
    """
    highlighted = text
    terms_to_highlight = set()

    cached_terms = st.session_state.get("rag_terms_for_highlight")
    if cached_terms:
        terms_to_highlight = set(cached_terms)
    elif st.session_state.get("rag_initialized", False):
        try:
            collection = st.session_state.get("rag_collection")
            if collection is None:
                raise ValueError("RAG 컬렉션이 없습니다")
            all_data = collection.get()
            if all_data and all_data['metadatas']:
                _cache_rag_metadata(all_data['metadatas'])
                terms_to_highlight = set(st.session_state.get("rag_terms_for_highlight", []))
        except Exception as e:
            st.warning(f"⚠️ RAG 용어 로드 중 오류, 기본 사전을 사용합니다: {e}")
            terms_to_highlight = set(st.session_state.get("financial_terms", DEFAULT_TERMS).keys())
    else:
        terms_to_highlight = set(st.session_state.get("financial_terms", DEFAULT_TERMS).keys())

    # 3️⃣ 용어별로 하이라이트 처리
    # 긴 용어부터 처리하여 부분 매칭 방지 (예: "부가가치세"가 "부가가치"보다 먼저 처리)
    sorted_terms = sorted(terms_to_highlight, key=len, reverse=True)

    # 이미 하이라이트된 부분을 보호하기 위한 임시 플레이스홀더 맵
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

def _build_structured_context_from_metadata(
    base_term: str,
    metadata: Dict[str, str],
    question_term: Optional[str] = None,
    synonym_matched: bool = False,
) -> Dict[str, str]:
    context: Dict[str, str] = {}

    def _add(key: str, value: Optional[str]):
        if value:
            value = str(value).strip()
            if value:
                context[key] = value

    _add("definition", metadata.get("definition"))
    _add("analogy", metadata.get("analogy"))
    _add("importance", metadata.get("importance"))
    _add("correction", metadata.get("correction"))
    _add("example", metadata.get("example"))
    _add("synonym", metadata.get("synonym"))

    if question_term and question_term.lower() != base_term.lower():
        label = "question_term_synonym" if synonym_matched else "question_term"
        _add(label, question_term)

    context["term"] = base_term
    context["source"] = "RAG"
    return context


def _build_structured_context_from_default(term: str, info: Dict[str, str]) -> Dict[str, str]:
    context: Dict[str, str] = {}

    mapping = {
        "definition": info.get("정의"),
        "detail": info.get("설명"),
        "analogy": info.get("비유"),
    }

    for key, value in mapping.items():
        if value:
            value = str(value).strip()
            if value:
                context[key] = value

    context["term"] = term
    context["source"] = "DEFAULT_DICTIONARY"
    return context


def _generate_structured_term_response(
    base_term: str,
    context: Dict[str, str],
    question_term: Optional[str] = None,
    temperature: float = 0.25,
) -> str:
    question_text = question_term or base_term
    user_prompt = f"{question_text}가 뭐야?"
    response = generate_structured_persona_reply(
        user_input=user_prompt,
        term=base_term,
        context=context,
        temperature=temperature,
    )
    if response and "(LLM 연결 오류" not in response:
        return response

    # LLM 호출 실패 시 간단한 정보라도 제공
    parts: List[str] = [f"🤖 **{base_term}** 에 대해 설명해줄게! 🎯"]
    if context.get("definition"):
        parts.append(f"📖 정의: {context['definition']}")
    if context.get("detail"):
        parts.append(f"💡 설명: {context['detail']}")
    if context.get("importance"):
        parts.append(f"❗ 왜 중요해?: {context['importance']}")
    if context.get("analogy"):
        parts.append(f"🌟 비유: {context['analogy']}")
    if context.get("example"):
        parts.append(f"📰 예시: {context['example']}")
    parts.append("더 궁금한 점 있으면 편하게 물어봐!")
    return "\n".join(parts)


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
# 🔐 CSV 파일 체크섬 계산 (변경 감지용)
# ─────────────────────────────────────────────────────────────
def _calculate_csv_checksum(csv_path: str) -> str:
    """CSV 파일의 체크섬을 계산하여 변경 여부 확인"""
    try:
        with open(csv_path, 'rb') as f:
            file_hash = hashlib.md5(f.read()).hexdigest()
        return file_hash
    except Exception:
        return ""


# ─────────────────────────────────────────────────────────────
# 🚀 임베딩 모델 로드 (전역 캐시 사용)
# ─────────────────────────────────────────────────────────────
def _get_embedding_model():
    """임베딩 모델을 전역 캐시에서 로드하거나 새로 로드"""
    global _embedding_model_cache
    
    if _embedding_model_cache is None:
        _embedding_model_cache = SentenceTransformer('jhgan/ko-sroberta-multitask')
    
    return _embedding_model_cache


# ─────────────────────────────────────────────────────────────
# 💾 임베딩 벡터 캐시 파일 경로
# ─────────────────────────────────────────────────────────────
def _get_cache_dir():
    """캐시 디렉토리 경로 반환"""
    cache_dir = os.path.join(os.path.dirname(__file__), "glossary", ".cache")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def _get_embeddings_cache_path():
    """임베딩 벡터 캐시 파일 경로"""

    return os.path.join(_get_cache_dir(), "embeddings.pkl")


def _get_metadata_cache_path():
    """메타데이터 캐시 파일 경로"""
    return os.path.join(_get_cache_dir(), "metadata.pkl")


def _get_checksum_cache_path():
    """체크섬 캐시 파일 경로"""
    return os.path.join(_get_cache_dir(), "checksum.json")


# ─────────────────────────────────────────────────────────────
# 💾 임베딩 벡터 저장
# ─────────────────────────────────────────────────────────────
def _save_embeddings_cache(documents: List[str], embeddings, metadatas: List[Dict], ids: List[str], checksum: str):
    """임베딩 벡터와 메타데이터를 캐시 파일로 저장 (로컬은 압축 없음, 빠른 로드)"""
    try:
        cache_dir = _get_cache_dir()
        
        # 임베딩 벡터 저장 (압축 없음 - 빠른 로드)
        cache_data = {
            'documents': documents,
            'embeddings': embeddings,
            'metadatas': metadatas,
            'ids': ids
        }
        
        with open(_get_embeddings_cache_path(), 'wb') as f:
            pickle.dump({
                'documents': documents,
                'embeddings': embeddings,
                'metadatas': metadatas,
                'ids': ids
            }, f)

        
        # 체크섬 저장
        with open(_get_checksum_cache_path(), 'w', encoding='utf-8') as f:
            json.dump({'checksum': checksum}, f)
        
    except Exception as e:
        st.warning(f"⚠️ 임베딩 캐시 저장 실패: {e}")


# ─────────────────────────────────────────────────────────────
# 📂 임베딩 벡터 로드 (로컬 캐시)
# ─────────────────────────────────────────────────────────────
def _load_embeddings_cache(checksum: str) -> Optional[Dict]:
    """저장된 임베딩 벡터를 로컬 캐시 파일에서 로드"""
    try:
        # 체크섬 확인
        checksum_path = _get_checksum_cache_path()
        if not os.path.exists(checksum_path):
            return None
        
        with open(checksum_path, 'r', encoding='utf-8') as f:
            cached_data = json.load(f)
            if cached_data.get('checksum') != checksum:
                return None  # CSV 파일이 변경됨
        
        # 임베딩 벡터 로드

        embeddings_path = _get_embeddings_cache_path()
        if not os.path.exists(embeddings_path):
            return None
        
        with open(embeddings_path, 'rb') as f:
            return pickle.load(f)
    
    except Exception as e:
        st.warning(f"⚠️ 로컬 임베딩 캐시 로드 실패: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# ☁️ Supabase Storage에 임베딩 저장
# ─────────────────────────────────────────────────────────────
def _save_embeddings_to_supabase(documents: List[str], embeddings, metadatas: List[Dict], ids: List[str], checksum: str) -> bool:
    """Supabase Storage에 임베딩 벡터 저장"""
    if not SUPABASE_ENABLE:
        return False
    
    supabase = get_supabase_client()
    if not supabase:
        return False
    
    try:
        # 1. 임베딩 데이터 준비
        cache_data = {
            'documents': documents,
            'embeddings': embeddings.tolist() if hasattr(embeddings, 'tolist') else embeddings,
            'metadatas': metadatas,
            'ids': ids
        }
        
        pickled_data = pickle.dumps(cache_data)
        compressed_data = gzip.compress(pickled_data)
        
        # 3. Storage 버킷과 경로 설정 (gzip 확장자)
        bucket_name = "glossary-cache"
        storage_path = f"embeddings/{checksum}.pkl.gz"
        
        # 4. Storage에 업로드 (기존 파일이 있으면 덮어쓰기)
        try:
            # 기존 파일 삭제 시도 (있으면)
            supabase.storage.from_(bucket_name).remove([storage_path])
        except:
            pass  # 파일이 없으면 무시
        
        # 새 파일 업로드 (gzip 압축된 데이터)
        supabase.storage.from_(bucket_name).upload(
            storage_path,
            compressed_data,
            file_options={"content-type": "application/octet-stream", "upsert": "true"}
        )
        
        # 5. 메타데이터를 테이블에 저장 (glossary_embeddings 테이블)
        try:
            supabase.table("glossary_embeddings").upsert({
                "checksum": checksum,
                "storage_path": storage_path,
                "term_count": len(documents),
                "updated_at": "now()"
            }).execute()
        except Exception as table_error:
            # 테이블이 없으면 경고만 (Storage는 성공했으므로)
            st.warning(f"⚠️ glossary_embeddings 테이블 저장 실패: {table_error}")
        
        return True
    
    except Exception as e:
        st.warning(f"⚠️ Supabase Storage 저장 실패: {e}")
        return False


# ─────────────────────────────────────────────────────────────
# ☁️ Supabase Storage에서 임베딩 로드
# ─────────────────────────────────────────────────────────────
def _load_embeddings_from_supabase(checksum: str) -> Optional[Dict]:
    """Supabase Storage에서 임베딩 벡터 로드 (1순위)"""
    if not SUPABASE_ENABLE:
        return None
    
    supabase = get_supabase_client()
    if not supabase:
        return None
    
    try:
        # 1. 메타데이터 테이블에서 확인 (선택적, 없어도 진행)
        bucket_name = "glossary-cache"
        storage_path = f"embeddings/{checksum}.pkl"

        
        try:
            # 메타데이터 확인 (있으면 체크섬 검증)
            result = supabase.table("glossary_embeddings").select("*").eq("checksum", checksum).execute()
            if result.data and len(result.data) > 0:
                # 메타데이터가 있으면 해당 경로 사용
                metadata = result.data[0]
                storage_path = metadata.get("storage_path", storage_path)

        except:
            # 테이블이 없어도 Storage에서 직접 확인
            pass
        

        # 2. Storage에서 다운로드
        response = supabase.storage.from_(bucket_name).download(storage_path)
        
        if not response:
            return None
        
        # 3. pickle로 역직렬화
        return pickle.loads(response)

    
    except Exception as e:
        # 파일이 없거나 에러 발생 시 None 반환 (조용히 실패)
        return None


# ─────────────────────────────────────────────────────────────
# 🔄 하이브리드 로드: Supabase 우선, 로컬 Fallback
# ─────────────────────────────────────────────────────────────
def _load_embeddings_with_fallback(checksum: str) -> Optional[Dict]:
    """
    임베딩 벡터 로드 (하이브리드 방식)

    우선순위:
    1. 로컬 캐시 파일 (빠른 로컬 접근)
    2. Supabase Storage (원격 저장소)
    3. None (새로 생성 필요)
    """
    cached_data = _load_embeddings_cache(checksum)
    if cached_data:
        st.session_state["rag_cache_source"] = "local"
        _sync_supabase_async(
            cached_data['documents'],
            cached_data['embeddings'],
            cached_data['metadatas'],
            cached_data['ids'],
            checksum
        )
        return cached_data

    cached_data = _load_embeddings_from_supabase(checksum)
    if cached_data:
        st.session_state["rag_cache_source"] = "supabase"
        try:
            _save_embeddings_cache(
                cached_data['documents'],
                cached_data['embeddings'],
                cached_data['metadatas'],
                cached_data['ids'],
                checksum
            )
            st.session_state["rag_cache_synced"] = True
        except:
            pass
        return cached_data

    st.session_state["rag_cache_source"] = "none"
    return None


# ─────────────────────────────────────────────────────────────
# 🧠 RAG 시스템 초기화 및 벡터 DB 구축 (하이브리드 최적화 버전)
# - 임베딩 모델: 전역 캐시로 재사용 (세션마다 재로드 방지)
# - 임베딩 벡터: Supabase Storage 우선, 로컬 Fallback (하이브리드)
# - ChromaDB: persistent 모드로 디스크에 저장 (세션 간 유지)
# - CSV 체크섬: 파일 변경 감지하여 자동 재임베딩
# ─────────────────────────────────────────────────────────────
def initialize_rag_system():
    """RAG 시스템 초기화: 벡터 DB 생성 및 금융용어 임베딩 (하이브리드 캐시)"""

    # 세션에 이미 초기화되어 있으면 스킵
    if "rag_initialized" in st.session_state and st.session_state.rag_initialized:
        return

    perf_enabled = _perf_enabled()
    perf_steps: List[Dict] = []
    total_start = time.perf_counter() if perf_enabled else 0.0
    step_start = total_start
    perf_logged = False

    try:
        # 1️⃣ CSV 로드 및 체크섬 계산
        with st.spinner("📄 금융용어 파일 로드 중..."):
            csv_path = os.path.join(os.path.dirname(__file__), "glossary", "금융용어.csv")
            if not os.path.exists(csv_path):
                st.warning(f"⚠️ 금융용어 파일을 찾을 수 없습니다: {csv_path}")
                st.session_state.rag_initialized = False
                return

            df = pd.read_csv(csv_path, encoding="utf-8")
            df = df.fillna("")
            csv_checksum = _calculate_csv_checksum(csv_path)
        if perf_enabled:
            step_start = _perf_step(perf_enabled, perf_steps, "csv_load", step_start)

        # 2️⃣ 임베딩 모델 로드 (전역 캐시 사용)
        # 첫 실행 시 모델 로드가 매우 느리므로 항상 스피너 표시
        embedding_model = _get_embedding_model()
        if embedding_model is None or _embedding_model_cache is None:
            with st.spinner("🤖 한국어 임베딩 모델 로드 중... (첫 실행 시 10-20초 소요)"):
                embedding_model = _get_embedding_model()
        if perf_enabled:
            step_start = _perf_step(perf_enabled, perf_steps, "model_ready", step_start)

        # 3️⃣ ChromaDB 클라이언트 생성 (persistent 모드)
        with st.spinner("💾 벡터 데이터베이스 초기화 중..."):
            chroma_db_path = os.path.join(_get_cache_dir(), "chroma_db")
            chroma_client = chromadb.PersistentClient(
                path=chroma_db_path,
                settings=Settings(
                    anonymized_telemetry=False
                )
            )
        if perf_enabled:
            step_start = _perf_step(perf_enabled, perf_steps, "chroma_client", step_start)

        # 4️⃣ 하이브리드 방식으로 임베딩 로드 시도 (Supabase 우선, 로컬 Fallback)
        with st.spinner("🔄 임베딩 벡터 로드 중..."):
            cached_data = _load_embeddings_with_fallback(csv_checksum)
        if perf_enabled:
            step_start = _perf_step(perf_enabled, perf_steps, "cache_lookup", step_start)

        # 5️⃣ 컬렉션 가져오기 또는 생성
        collection_name = "financial_terms"
        with st.spinner("🔍 벡터 컬렉션 확인 중..."):
            try:
                collection = chroma_client.get_collection(name=collection_name)
                if collection.count() > 0 and cached_data is not None:
                    documents = cached_data['documents']
                    metadatas = cached_data['metadatas']
                    ids = cached_data['ids']

                    st.session_state.rag_collection = collection
                    st.session_state.rag_embedding_model = embedding_model
                    st.session_state.rag_initialized = True
                    st.session_state.rag_term_count = len(documents)
                    _cache_rag_metadata(metadatas)
                    st.session_state["rag_explanation_cache"] = {}

                    if perf_enabled:
                        step_start = _perf_step(perf_enabled, perf_steps, "cache_ready", step_start)
                        perf_steps.append({"step": "total", "ms": round((time.perf_counter() - total_start) * 1000, 2)})
                        _record_perf("initialize", perf_steps)
                        perf_logged = True

                    cache_source = "Supabase" if SUPABASE_ENABLE else "로컬"
                    st.success(f"✅ RAG 시스템 초기화 완료! ({cache_source} 캐시 사용, {len(documents)}개 용어)")
                    return
                elif cached_data is None:
                    try:
                        chroma_client.delete_collection(name=collection_name)
                    except:
                        pass
                    collection = chroma_client.create_collection(
                        name=collection_name,
                        metadata={"description": "금융 용어 사전 벡터 DB"}
                    )
            except:
                collection = chroma_client.create_collection(
                    name=collection_name,
                    metadata={"description": "금융 용어 사전 벡터 DB"}
                )
        if perf_enabled:
            step_start = _perf_step(perf_enabled, perf_steps, "collection_ready", step_start)

        if cached_data is not None:
            with st.spinner("📦 캐시된 데이터 준비 중..."):
                documents = cached_data['documents']
                embeddings = cached_data['embeddings']
                metadatas = cached_data['metadatas']
                ids = cached_data['ids']

                if collection.count() == 0:
                    collection.add(
                        documents=documents,
                        metadatas=metadatas,
                        embeddings=embeddings.tolist() if hasattr(embeddings, 'tolist') else embeddings,
                        ids=ids
                    )
            if perf_enabled:
                step_start = _perf_step(perf_enabled, perf_steps, "cache_materialize", step_start)
            _cache_rag_metadata(metadatas)
        else:
            with st.spinner("📝 금융용어 데이터 준비 중..."):
                documents = []
                metadatas = []
                ids = []

                for idx, row in df.iterrows():
                    term = str(row.get("금융용어", "")).strip()
                    if not term:
                        continue

                    synonym = str(row.get("유의어", "")).strip()
                    definition = str(row.get("정의", "")).strip()
                    analogy = str(row.get("비유", "")).strip()

                    search_text = f"{term}"
                    if synonym:
                        search_text += f" ({synonym})"
                    search_text += f" - {definition}"
                    if analogy:
                        search_text += f" | 비유: {analogy}"

                    documents.append(search_text)

                    metadatas.append({
                        "term": term,
                        "synonym": synonym,
                        "definition": definition,
                        "analogy": analogy,
                        "importance": str(row.get("왜 중요?", "")).strip(),
                        "correction": str(row.get("오해 교정", "")).strip(),
                        "example": str(row.get("예시", "")).strip(),
                        "difficulty": str(row.get("단어 난이도", "")).strip(),
                    })

                    ids.append(f"term_{idx}")
            if perf_enabled:
                step_start = _perf_step(perf_enabled, perf_steps, "documents_prepared", step_start)

            with st.spinner(f"🔄 {len(documents)}개 금융용어 벡터화 중..."):
                embeddings = embedding_model.encode(documents, show_progress_bar=False)
            if perf_enabled:
                step_start = _perf_step(perf_enabled, perf_steps, "embedding_encode", step_start)

            collection.add(
                documents=documents,
                metadatas=metadatas,
                embeddings=embeddings.tolist(),
                ids=ids
            )
            if perf_enabled:
                step_start = _perf_step(perf_enabled, perf_steps, "collection_populate", step_start)

            with st.spinner("💾 임베딩 벡터 저장 중..."):
                _save_embeddings_cache(documents, embeddings, metadatas, ids, csv_checksum)
                st.session_state["rag_cache_synced"] = False
            if perf_enabled:
                step_start = _perf_step(perf_enabled, perf_steps, "cache_save", step_start)

            _sync_supabase_async(documents, embeddings, metadatas, ids, csv_checksum)

        st.session_state.rag_collection = collection
        st.session_state.rag_embedding_model = embedding_model
        st.session_state.rag_initialized = True
        st.session_state.rag_term_count = len(documents)
        _cache_rag_metadata(metadatas)
        st.session_state["rag_explanation_cache"] = {}

        if perf_enabled:
            step_start = _perf_step(perf_enabled, perf_steps, "session_update", step_start)
            perf_steps.append({"step": "total", "ms": round((time.perf_counter() - total_start) * 1000, 2)})
            _record_perf("initialize", perf_steps)
            perf_logged = True

        if cached_data is not None:
            cache_source = "Supabase" if SUPABASE_ENABLE else "로컬"
            st.success(f"✅ RAG 시스템 초기화 완료! ({cache_source} 캐시 사용, {len(documents)}개 용어)")
        else:
            save_source = "Supabase + 로컬" if SUPABASE_ENABLE else "로컬"
            st.success(f"✅ RAG 시스템 초기화 완료! ({len(documents)}개 용어 로드, {save_source}에 저장됨)")

    except Exception as e:
        st.error(f"❌ RAG 초기화 실패: {e}")
        st.session_state.rag_initialized = False
    finally:
        if perf_enabled and not perf_logged:
            perf_steps.append({"step": "total", "ms": round((time.perf_counter() - total_start) * 1000, 2)})
            _record_perf("initialize", perf_steps)


# ─────────────────────────────────────────────────────────────
# 🔍 RAG 기반 용어 검색
# - 사용자 질문을 벡터화하여 유사한 용어 검색
# - 상위 k개의 관련 용어 반환
# ─────────────────────────────────────────────────────────────
def search_terms_by_rag(query: str, top_k: int = 3) -> List[Dict]:
    """RAG를 사용하여 질문과 관련된 금융 용어 검색"""

    if not st.session_state.get("rag_initialized", False):
        return []

    perf_enabled = _perf_enabled()
    perf_steps: List[Dict] = []
    total_start = time.perf_counter() if perf_enabled else 0.0
    step_start = total_start
    perf_logged = False

    try:
        collection = st.session_state.rag_collection
        embedding_model = st.session_state.rag_embedding_model

        query_embedding = embedding_model.encode([query])[0]
        if perf_enabled:
            step_start = _perf_step(perf_enabled, perf_steps, "encode", step_start)

        results = collection.query(
            query_embeddings=[query_embedding.tolist()],
            n_results=top_k
        )
        if perf_enabled:
            step_start = _perf_step(perf_enabled, perf_steps, "query", step_start)

        matched_terms = []
        if results and results['metadatas']:
            for metadata in results['metadatas'][0]:
                matched_terms.append(metadata)
        if perf_enabled:
            step_start = _perf_step(perf_enabled, perf_steps, "format", step_start)
            perf_steps.append({"step": "total", "ms": round((time.perf_counter() - total_start) * 1000, 2), "info": {"top_k": top_k, "returned": len(matched_terms)}})
            _record_perf("query", perf_steps)
            perf_logged = True

        return matched_terms

    except Exception as e:
        st.error(f"❌ RAG 검색 중 오류: {e}")
        return []
    finally:
        if perf_enabled and not perf_logged:
            perf_steps.append({"step": "total", "ms": round((time.perf_counter() - total_start) * 1000, 2)})
            _record_perf("query", perf_steps)


# ─────────────────────────────────────────────────────────────
# 🦉 챗봇 응답용: RAG 기반 용어 설명 생성 (기존 함수 대체)
# - 변경 사항:
#   1. 기존: 하드코딩된 DEFAULT_TERMS 사전에서 검색
#   2. 신규: RAG 벡터 검색으로 유사 용어 찾기
#   3. Fallback: RAG 실패 시 기존 방식으로 동작
# ─────────────────────────────────────────────────────────────
def explain_term(term: str, chat_history=None, return_rag_info: bool = False):
    """
    용어 설명 생성 (RAG 정확 매칭 우선, 실패 시 기존 사전 사용)

    Args:
        term: 설명할 금융 용어
        chat_history: 채팅 이력 (향후 컨텍스트 강화용)
        return_rag_info: True일 경우 (explanation, rag_info) 튜플 반환

    Returns:
        return_rag_info=False: 마크다운 형식의 용어 설명 문자열
        return_rag_info=True: (마크다운 형식의 용어 설명, RAG 메타데이터 또는 None) 튜플
    """

    rag_info: Optional[Dict] = None
    metadata: Optional[Dict] = None
    synonym_matched = False

    if st.session_state.get("rag_initialized", False):
        try:
            metadata_map = st.session_state.get("rag_metadata_by_term")
            if not metadata_map:
                collection = st.session_state.get("rag_collection")
                if collection is None:
                    raise ValueError("RAG 컬렉션이 없습니다")
                all_data = collection.get()
                if all_data and all_data["metadatas"]:
                    _cache_rag_metadata(all_data["metadatas"])
                    metadata_map = st.session_state.get("rag_metadata_by_term", {})

            if metadata_map:
                metadata = metadata_map.get(term.lower())
                if metadata:
                    base_term = (metadata.get("term") or "").strip()
                    synonym_field = (metadata.get("synonym") or "").strip()
                    if synonym_field:
                        synonyms = [s.strip().lower() for s in re.split(r"[,\n]", synonym_field) if s.strip()]
                        synonym_matched = term.lower() in synonyms and term.lower() != base_term.lower()
                    else:
                        synonym_matched = False

                    definition = metadata.get("definition", "")
                    analogy = metadata.get("analogy", "")
                    importance = metadata.get("importance", "")
                    correction = metadata.get("correction", "")
                    example = metadata.get("example", "")

                    cache = st.session_state.setdefault("rag_explanation_cache", {})
                    cache_key = base_term.lower()
                    response = cache.get(cache_key)

                    if response is None:
                        structured_context = _build_structured_context_from_metadata(
                            base_term=base_term,
                            metadata=metadata,
                            question_term=term,
                            synonym_matched=synonym_matched,
                        )
                        response = _generate_structured_term_response(
                            base_term=base_term,
                            context=structured_context,
                            question_term=term,
                        )
                        cache[cache_key] = response

                    if return_rag_info:
                        rag_info = {
                            "search_method": "exact_match",
                            "matched_term": base_term,
                            "synonym_used": synonym_matched,
                            "source": "rag"
                        }

                    if return_rag_info:
                        return response, rag_info
                    return response
        except Exception as e:
            st.warning(f"⚠️ RAG 검색 중 오류, 기본 사전을 사용합니다: {e}")

    terms = st.session_state.get("financial_terms", DEFAULT_TERMS)

    if term not in terms:
        message = f"'{term}'에 대한 정보가 아직 없어. 다른 용어를 선택해줘."
        if return_rag_info:
            return message, None
        return message

    info = terms[term]
    structured_context = _build_structured_context_from_default(term, info)
    response = _generate_structured_term_response(
        base_term=term,
        context=structured_context,
        question_term=term,
    )

    if return_rag_info:
        return response, None
    return response
