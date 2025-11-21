"""
?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧??
?뱴 湲덉쑖 ?⑹뼱 ?ъ쟾 紐⑤뱢 (RAG ?쒖뒪???듯빀)
?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧?먥븧??
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
from typing import Dict, List, Optional, Union
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

# ?????????????????????????????????????????????????????????????
# ?? ?꾩뿭 罹먯떆: ?꾨쿋??紐⑤뜽 (?몄뀡 媛??ъ궗??
# - SentenceTransformer 紐⑤뜽? 硫붾え由??ъ슜?됱씠 ?щ?濡??꾩뿭?쇰줈 罹먯떆
# - 紐⑤뱺 ?몄뀡?먯꽌 ?숈씪??紐⑤뜽 ?몄뒪?댁뒪 ?ъ궗??
# ??理쒖쟻?? st.cache_resource濡?罹먯떛?섎?濡??꾩뿭 蹂???쒓굅
# ?????????????????????????????????????????????????????????????
_RAG_AVAILABLE = chromadb is not None and SentenceTransformer is not None

# ?????????????????????????????????????????????????????????????
# ?뵇 臾몃㎘ ?몄떇: 寃쎌젣 愿???ㅼ썙??紐⑸줉 (?섎뱶肄붾뵫??湲곕낯 ?ㅼ썙??
# - CSV?먯꽌 異붿텧???⑹뼱蹂??ㅼ썙?쒖? 蹂묓빀?섏뿬 ?ъ슜
# ?????????????????????????????????????????????????????????????
BASE_FINANCIAL_KEYWORDS = [
    '湲덉쑖', '寃쎌젣', '?ъ옄', '二쇱떇', '?쒖옣', '???, '?異?, '?댁옄',
    '?섏쑉', '?듯솕', '?뺤콉', '以묒븰???, '湲덈━', '諛곕떦', '?섏씡',
    '?먯궛', '遺梨?, '?먮낯', '留ㅼ텧', '?댁씡', '?먯떎', '寃쎄린',
    '?명뵆?덉씠??, '?뷀뵆?덉씠??, 'GDP', 'CPI', 'PER', 'PBR',
    '肄붿뒪??, '肄붿뒪??, '二쇨?', '?곸듅', '?섎씫', '蹂??, '議곗젙',
    '?몄긽', '?명븯', '利앷?', '媛먯냼', '?덉젙', '遺덉븞??, '?좊룞??,
    '梨꾧텒', '???, '蹂댄뿕', '?멸툑', '愿??, '遺?숈궛', '?먰솕', '?щ윭'
]

# ?????????????????????????????????????????????????????????????
# ?슟 遺???ㅼ썙?? ???ㅼ썙?쒓? 臾몃㎘???덉쑝硫?寃쎌젣 ?⑹뼱媛 ?꾨떂
# - 釉뚮옖?쒕챸, ?뚯궗紐? ?몃챸 ?깆씠 ?ы븿??寃쎌슦
# ?????????????????????????????????????????????????????????????
NEGATIVE_KEYWORDS = [
    '釉뚮옖??, '?뚯궗', '湲곗뾽紐?, '?곹몴', '?쒗뭹紐?, '??, '??, '?ъ옣', '???,
    '源移?, '?섏텧', '?섏엯', '?쒖“', '?앹궛', '?먮ℓ', '留덉???, '愿묎퀬',
    '???, '醫낃?', '?쇱꽦', 'LG', '?꾨?', '湲곗븘', 'SK', '濡?뜲', '?좎꽭怨?
]

# ?????????????????????????????????????????????????????????????
# ?뵇 ?⑹뼱蹂?臾몃㎘ ?ㅼ썙??罹먯떆 (CSV?먯꽌 ?숈쟻?쇰줈 ?앹꽦)
# - 媛??⑹뼱???뺤쓽, 鍮꾩쑀, ?덉떆?먯꽌 ?ㅼ썙??異붿텧
# ?????????????????????????????????????????????????????????????
_TERM_CONTEXT_KEYWORDS_CACHE = None

def _extract_keywords_from_text(text: str) -> set:
    """
    ?띿뒪?몄뿉??寃쎌젣 愿???ㅼ썙??異붿텧
    - 紐낆궗, 寃쎌젣 ?⑹뼱, ?レ옄 ?깆쓣 異붿텧
    """
    if not text:
        return set()
    
    keywords = set()
    
    # 寃쎌젣 愿??紐낆궗 ?⑦꽩 (2-4???쒓?) - ???뺥솗??異붿텧
    # ?⑥뼱 寃쎄퀎瑜?怨좊젮?섏뿬 異붿텧
    noun_pattern = re.compile(r'[媛-??{2,4}')
    nouns = noun_pattern.findall(text)
    
    # 寃쎌젣 愿???ㅼ썙???꾪꽣留?(?덈Т ?쇰컲?곸씤 ?⑥뼱 ?쒖쇅)
    stopwords = {'洹멸쾬', '?닿쾬', '?寃?, '洹몃윴', '?대윴', '???, '洹몃븣', '?대븣', '???, '寃껋?', '寃껋씠', '寃껋쓣', '寃껋쓣', '寃껊룄', '寃껊쭔', '???, '?뚯궗', '湲곗뾽', '釉뚮옖??}
    # 寃쎌젣 愿???ㅼ썙?쒕쭔 異붿텧 (紐낇솗??寃쎌젣 ?⑹뼱)
    financial_nouns = {'??, '留덇컧', '嫄곕옒', '媛寃?, '二쇨?', '肄붿뒪??, '肄붿뒪??, '吏??, '?쒖옣', '?ъ옄', '湲덉쑖', '寃쎌젣', '???, '?異?, '?댁옄', '?섏쑉', '?듯솕', '?뺤콉', '以묒븰???, '湲덈━', '諛곕떦', '?섏씡', '?먯궛', '遺梨?, '?먮낯', '留ㅼ텧', '?댁씡', '?먯떎', '寃쎄린', '?명뵆?덉씠??, '?뷀뵆?덉씠??, 'GDP', 'CPI', 'PER', 'PBR', '二쇨?', '?곸듅', '?섎씫', '蹂??, '議곗젙', '?몄긽', '?명븯', '利앷?', '媛먯냼', '?덉젙', '遺덉븞??, '?좊룞??, '梨꾧텒', '???, '蹂댄뿕', '?멸툑', '愿??, '遺?숈궛', '?먰솕', '?щ윭', '湲곗?', '?뺤꽦', '理쒖쥌', '遺꾩꽍', '李⑦듃', '湲곗???, '?됯퇏媛'}
    
    for noun in nouns:
        if len(noun) >= 2 and noun not in stopwords:
            # 寃쎌젣 愿??紐낆궗?닿굅??3???댁긽??寃쎌슦 異붽?
            if noun in financial_nouns or len(noun) >= 3:  # 3???댁긽? ???좊ː?????덉쓬
                keywords.add(noun)
    
    # ?곷Ц ?쎌뼱 (?臾몄옄 2-5??
    acronym_pattern = re.compile(r'\b[A-Z]{2,5}\b')
    acronyms = acronym_pattern.findall(text)
    keywords.update(acronyms)
    
    return keywords

def _build_term_context_keywords() -> Dict[str, set]:
    """
    CSV?먯꽌 媛??⑹뼱蹂?臾몃㎘ ?ㅼ썙?쒕? ?숈쟻?쇰줈 ?앹꽦
    - ?뺤쓽, 鍮꾩쑀, ?덉떆?먯꽌 ?ㅼ썙??異붿텧
    - ?⑹뼱蹂꾨줈 愿???ㅼ썙???명듃 ?앹꽦
    """
    global _TERM_CONTEXT_KEYWORDS_CACHE
    
    if _TERM_CONTEXT_KEYWORDS_CACHE is not None:
        return _TERM_CONTEXT_KEYWORDS_CACHE
    
    term_keywords = {}
    
    try:
        # CSV?먯꽌 ?⑹뼱 ?곗씠??濡쒕뱶
        df = load_glossary_from_csv()
        if df.empty:
            # CSV媛 鍮꾩뼱?덉쑝硫?湲곕낯 ?ㅼ썙?쒕쭔 ?ъ슜
            st.warning("?좑툘 CSV ?뚯씪??鍮꾩뼱?덉뒿?덈떎. 湲곕낯 ?ㅼ썙?쒕쭔 ?ъ슜?⑸땲??")
            _TERM_CONTEXT_KEYWORDS_CACHE = {}
            return {}
        
        for _, row in df.iterrows():
            term = str(row.get("湲덉쑖?⑹뼱", "")).strip()
            if not term:
                continue
            
            # ?⑹뼱蹂??ㅼ썙???명듃 ?앹꽦
            keywords = set()
            
            # ?뺤쓽?먯꽌 ?ㅼ썙??異붿텧
            definition = str(row.get("?뺤쓽", "")).strip()
            if definition:
                keywords.update(_extract_keywords_from_text(definition))
            
            # 鍮꾩쑀?먯꽌 ?ㅼ썙??異붿텧
            analogy = str(row.get("鍮꾩쑀", "")).strip()
            if analogy:
                keywords.update(_extract_keywords_from_text(analogy))
            
            # ?덉떆?먯꽌 ?ㅼ썙??異붿텧 (媛??以묒슂 - ?ㅼ젣 ?ъ슜 臾몃㎘)
            example = str(row.get("?덉떆", "")).strip()
            if example:
                keywords.update(_extract_keywords_from_text(example))
            
            # ?⑹뼱 ?먯껜???ㅼ썙?쒖뿉 異붽?
            keywords.add(term)
            
            # 湲곕낯 寃쎌젣 ?ㅼ썙?쒕룄 異붽?
            keywords.update(BASE_FINANCIAL_KEYWORDS)
            
            term_keywords[term] = keywords
        
        # 湲곕낯 ?ъ쟾 ?⑹뼱??異붽?
        for term, info in DEFAULT_TERMS.items():
            if term not in term_keywords:
                keywords = set()
                if "?뺤쓽" in info:
                    keywords.update(_extract_keywords_from_text(info["?뺤쓽"]))
                if "鍮꾩쑀" in info:
                    keywords.update(_extract_keywords_from_text(info["鍮꾩쑀"]))
                keywords.add(term)
                keywords.update(BASE_FINANCIAL_KEYWORDS)
                term_keywords[term] = keywords
        
        _TERM_CONTEXT_KEYWORDS_CACHE = term_keywords
        
        # ?붾쾭源? ?앹꽦???ㅼ썙?????뺤씤
        total_terms = len(term_keywords)
        if total_terms > 0:
            sample_term = list(term_keywords.keys())[0]
            sample_keywords = term_keywords[sample_term]
            # st.info(f"??{total_terms}媛??⑹뼱???ㅼ썙???앹꽦 ?꾨즺 (?? '{sample_term}' ??{len(sample_keywords)}媛??ㅼ썙??")
        
    except Exception as e:
        # ?ㅻ쪟 諛쒖깮 ??湲곕낯 ?ㅼ썙?쒕쭔 ?ъ슜
        import traceback
        st.warning(f"?좑툘 ?⑹뼱蹂??ㅼ썙???앹꽦 以??ㅻ쪟: {e}\n{traceback.format_exc()}")
        term_keywords = {}
        for term in BASE_FINANCIAL_KEYWORDS:
            term_keywords[term] = set(BASE_FINANCIAL_KEYWORDS)
    
    return term_keywords

def get_financial_context_keywords(term: Optional[str] = None) -> set:
    """
    ?⑹뼱蹂??먮뒗 ?꾩껜 寃쎌젣 愿???ㅼ썙??諛섑솚
    
    Args:
        term: ?뱀젙 ?⑹뼱???ㅼ썙?쒕쭔 ?먰븯??寃쎌슦 ?⑹뼱紐? None?대㈃ ?꾩껜 湲곕낯 ?ㅼ썙??
    
    Returns:
        ?ㅼ썙???명듃
    """
    if term:
        term_keywords = _build_term_context_keywords()
        result = term_keywords.get(term, set(BASE_FINANCIAL_KEYWORDS))
        # ?붾쾭源? ?ㅼ썙?쒓? 鍮꾩뼱?덇굅???덈Т ?곸쑝硫?湲곕낯 ?ㅼ썙???ъ슜
        if not result or len(result) < 5:
            result = set(BASE_FINANCIAL_KEYWORDS)
        return result
    else:
        return set(BASE_FINANCIAL_KEYWORDS)

# ?????????????????????????????????????????????????????????????
# ??湲곕낯 湲덉쑖 ?⑹뼱 ?ъ쟾 (RAG/?ъ쟾 ?놁씠???숈옉?섎뒗 理쒖냼 ?명듃)
# - 媛??⑹뼱??'?뺤쓽', '?ㅻ챸', '鍮꾩쑀'濡?援ъ꽦
# - ?ㅼ젣 ?쒕퉬?ㅼ뿉?쒕뒗 DB/CSV/RAG濡??泥?媛??
# ?????????????????????????????????????????????????????????????
DEFAULT_TERMS = {
    "?묒쟻?꾪솕": {
        "?뺤쓽": "以묒븰??됱씠 ?쒖쨷???듯솕瑜?怨듦툒?섍린 ?꾪빐 援?콈 ?깆쓣 留ㅼ엯?섎뒗 ?뺤콉",
        "?ㅻ챸": "寃쎄린 遺?묒쓣 ?꾪빐 以묒븰??됱씠 ?덉쓣 ????쒖옣 ?좊룞?깆쓣 ?믪씠??諛⑸쾿?낅땲??",
        "鍮꾩쑀": "留덈Ⅸ ?낆뿉 臾쇱쓣 肉뚮젮二쇰뒗 寃껋쿂?? 寃쎌젣???덉씠?쇰뒗 臾쇱쓣 怨듦툒?섎뒗 寃껋엯?덈떎.",
    },
    "湲곗?湲덈━": {
        "?뺤쓽": "以묒븰??됱씠 ?쒖쨷??됱뿉 ?덉쓣 鍮뚮젮以????곸슜?섎뒗 湲곗????섎뒗 湲덈━",
        "?ㅻ챸": "紐⑤뱺 湲덈━??湲곗????섎ŉ, 湲곗?湲덈━媛 ?ㅻⅤ硫??異쒖씠?먮룄 ?④퍡 ?ㅻ쫭?덈떎.",
        "鍮꾩쑀": "臾쇨????⑤룄議곗젅湲곗? 媛숈뒿?덈떎. 寃쎌젣媛 怨쇱뿴?섎㈃ ?щ━怨? 移⑥껜?섎㈃ ?대┰?덈떎.",
    },
    "諛곕떦": {
        "?뺤쓽": "湲곗뾽??踰뚯뼱?ㅼ씤 ?댁씡 以??쇰?瑜?二쇱＜?ㅼ뿉寃??섎닠二쇰뒗 寃?,
        "?ㅻ챸": "二쇱떇??蹂댁쑀??二쇱＜?먭쾶 湲곗뾽???댁씡??遺꾨같?섎뒗 諛⑹떇?낅땲??",
        "鍮꾩쑀": "?④퍡 ?앸떦???댁쁺?섎뒗 ?숈뾽?먮뱾??留ㅼ텧 以??쇰?瑜??섎닠媛뽯뒗 寃껉낵 媛숈뒿?덈떎.",
    },
    "PER": {
        "?뺤쓽": "二쇨??섏씡鍮꾩쑉. 二쇨?瑜?二쇰떦?쒖씠?듭쑝濡??섎늿 媛?,
        "?ㅻ챸": "二쇱떇??1??移??댁씡??紐?諛곗뿉 嫄곕옒?섎뒗吏瑜??섑??낅땲?? ??쓣?섎줉 ??됯???寃껋쑝濡?蹂????덉뒿?덈떎.",
        "鍮꾩쑀": "1?꾩뿉 100留뚯썝 踰꾨뒗 媛寃뚮? 紐???移??섏씡??二쇨퀬 ?щ뒗吏瑜??섑??낅땲??",
    },
    "?섏쑉": {
        "?뺤쓽": "?쒕줈 ?ㅻⅨ ???섎씪 ?뷀룓??援먰솚 鍮꾩쑉",
        "?ㅻ챸": "?먰솕瑜??щ윭濡? ?щ윭瑜??먰솕濡?諛붽? ???곸슜?섎뒗 鍮꾩쑉?낅땲??",
        "鍮꾩쑀": "?댁쇅 ?쇳븨紐곗뿉??臾쇨굔???????곸슜?섎뒗 ?섏쟾 鍮꾩쑉?낅땲??",
    },
}


def _cache_rag_metadata(metadatas: List[Dict]):
    """
    RAG 硫뷀??곗씠?곕? ?몄뀡??罹먯떛?섏뿬 諛섎났?곸씤 collection.get() ?몄텧??以꾩엯?덈떎.
    term / synonym 紐⑤몢 ?뚮Ц?먮줈 ?ㅻ? 留뚮뱾??lookup ?띾룄瑜??믪씠怨?
    ?섏씠?쇱씠?몄슜 ?⑹뼱 ?명듃???④퍡 ??ν빀?덈떎.
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

# ?????????????????????????????????????????????????????????????
# ?㎞ ?몄뀡??湲덉쑖 ?⑹뼱 ?ъ쟾 蹂댁옣 (RAG ?듯빀 踰꾩쟾)
#   - 蹂寃??ы빆:
#   1. 湲곗〈: DEFAULT_TERMS留?蹂듭궗
#   2. ?좉퇋: RAG ?쒖뒪???먮룞 珥덇린??異붽?
#   3. Fallback: RAG ?ㅽ뙣 ??湲곗〈 DEFAULT_TERMS ?ъ슜
# - Streamlit? ?ъ슜?먮퀎 ?몄뀡 ?곹깭(st.session_state)瑜??쒓났
# - 理쒖큹 1?뚮쭔 DEFAULT_TERMS瑜?蹂듭궗???ｌ뼱 以묎컙 蹂寃쎌뿉???먮낯 蹂댁〈
# ?????????????????????????????????????????????????????????????
# ?????????????????????????????????????????????????????????????
# ??鍮좊Ⅸ ?띿뒪???ъ쟾 濡쒕뱶 (CSV?먯꽌 ?띿뒪?몃쭔 異붿텧)
# ?????????????????????????????????????????????????????????????
def load_text_glossary_fast() -> Dict[str, Dict[str, str]]:
    """
    CSV?먯꽌 ?띿뒪???ъ쟾留?鍮좊Ⅴ寃?濡쒕뱶 (?꾨쿋???놁씠)
    - ?섏씠?쇱씠?몄? 湲곕낯 ?ㅻ챸???ъ슜
    - 留ㅼ슦 鍮좊쫫 (~0.1珥?
    """
    terms_dict = {}
    
    try:
        csv_path = os.path.join(os.path.dirname(__file__), "glossary", "湲덉쑖?⑹뼱.csv")
        if not os.path.exists(csv_path):
            return DEFAULT_TERMS.copy()
        
        df = pd.read_csv(csv_path, encoding="utf-8")
        df = df.fillna("")
        
        for _, row in df.iterrows():
            term = str(row.get("湲덉쑖?⑹뼱", "")).strip()
            if not term:
                continue
            
            terms_dict[term] = {
                "?뺤쓽": str(row.get("?뺤쓽", "")).strip(),
                "鍮꾩쑀": str(row.get("鍮꾩쑀", "")).strip(),
                "?ㅻ챸": str(row.get("?뺤쓽", "")).strip(),  # 湲곕낯 ?ㅻ챸
                "?좎쓽??: str(row.get("?좎쓽??, "")).strip(),
                "??以묒슂?": str(row.get("??以묒슂?", "")).strip(),
                "?ㅽ빐 援먯젙": str(row.get("?ㅽ빐 援먯젙", "")).strip(),
                "?덉떆": str(row.get("?덉떆", "")).strip(),
            }
    except Exception as e:
        # CSV 濡쒕뱶 ?ㅽ뙣 ??湲곕낯 ?ъ쟾 ?ъ슜
        pass
    
    # 湲곕낯 ?ъ쟾怨?蹂묓빀 (湲곕낯 ?ъ쟾???곗꽑)
    result = DEFAULT_TERMS.copy()
    result.update(terms_dict)
    return result


# ?????????????????????????????????????????????????????????????
# ?봽 諛깃렇?쇱슫?쒖뿉??RAG ?쒖뒪??珥덇린??
# ?????????????????????????????????????????????????????????????
def initialize_rag_system_background():
    """
    諛깃렇?쇱슫???ㅻ젅?쒖뿉??RAG ?쒖뒪??珥덇린??
    - UI瑜?釉붾줈?뱁븯吏 ?딆쓬
    - 珥덇린???꾨즺 ???먮룞?쇰줈 ?쒖꽦??
    """
    if st.session_state.get("rag_initialized", False):
        return
    
    if st.session_state.get("rag_loading", False):
        return  # ?대? 濡쒕뵫 以?
    
    if not _RAG_AVAILABLE:
        st.session_state.rag_initialized = False
        return
    
    def _load_in_background():
        """諛깃렇?쇱슫?쒖뿉???ㅽ뻾?섎뒗 ?ㅼ젣 濡쒕뵫 ?⑥닔"""
        try:
            st.session_state["rag_loading"] = True
            st.session_state["rag_error"] = None
            
            # RAG ?쒖뒪??珥덇린??(諛깃렇?쇱슫??紐⑤뱶濡??ㅽ뻾)
            initialize_rag_system(is_background=True)
            
            st.session_state["rag_loading"] = False
        except Exception as e:
            st.session_state["rag_loading"] = False
            st.session_state["rag_error"] = str(e)
    
    # 諛깃렇?쇱슫???ㅻ젅???쒖옉
    thread = threading.Thread(target=_load_in_background, daemon=True)
    thread.start()


def ensure_financial_terms():
    """
    湲덉쑖 ?⑹뼱 ?ъ쟾 珥덇린??(Lazy Loading + 諛깃렇?쇱슫??濡쒕뵫)
    
    ??理쒖쟻?? ?띿뒪???ъ쟾留?癒쇱? 濡쒕뱶 (0.1珥? ??利됱떆 UI ?쒖떆
    ??理쒖쟻?? RAG ?쒖뒪?쒖? 諛깃렇?쇱슫?쒖뿉??濡쒕뱶 ???ъ슜?먮뒗 湲곕떎由ъ? ?딆쓬
    
    - ?몄뀡 理쒖큹 ?ㅽ뻾 ???띿뒪???ъ쟾留?鍮좊Ⅴ寃?濡쒕뱶
    - RAG ?쒖뒪?쒖? 諛깃렇?쇱슫?쒖뿉??珥덇린??
    - Fallback?쇰줈 湲곕낯 ?⑹뼱 ?ъ쟾???좎?
    """
    # 1截뤴깵 ?띿뒪???ъ쟾 鍮좊Ⅴ寃?濡쒕뱶 (利됱떆 UI ?쒖떆 媛??
    if "financial_terms" not in st.session_state:
        st.session_state.financial_terms = load_text_glossary_fast()
        st.session_state["terms_text_ready"] = True

    # 2截뤴깵 RAG ?쒖뒪??諛깃렇?쇱슫??珥덇린??(UI 釉붾줈???놁쓬)
    if "rag_initialized" not in st.session_state and "rag_loading" not in st.session_state:
        if not _RAG_AVAILABLE:
            st.session_state.rag_initialized = False
        else:
            # 諛깃렇?쇱슫?쒖뿉??珥덇린???쒖옉
            initialize_rag_system_background()



# ?????????????????????????????????????????????????????????????
# ?뵶 湲곗〈 ?⑥닔 (二쇱꽍泥섎━): ?섎뱶肄붾뵫???ъ쟾 湲곕컲 ?섏씠?쇱씠??
# ?????????????????????????????????????????????????????????????
# def highlight_terms(text: str) -> str:
#     highlighted = text
#
#     # ?꾩옱 ?몄뀡???⑹뼱 ?ъ쟾?먯꽌 ???⑹뼱)留??쒗쉶
#     for term in st.session_state.financial_terms.keys():
#         # re.escape(term): ?뱀닔臾몄옄 ?ы븿 ?⑹뼱???덉쟾?섍쾶 留ㅼ묶
#         # re.IGNORECASE: ??뚮Ц??援щ텇 ?놁씠 寃??(?곷Ц ?⑹뼱 ?鍮?
#         pattern = re.compile(re.escape(term), re.IGNORECASE)
#
#         # ?좑툘 二쇱쓽: ?꾨옒 ?泥?臾몄옄?댁쓽 {term}? '?ъ쟾 ?? ?쒓린瑜?洹몃?濡??ъ슜
#         # - 留ㅼ묶???먮옒 ?쒓린(??뚮Ц??瑜??좎??섍퀬 ?띕떎硫?repl ?⑥닔 ?ъ슜 ?꾩슂
#         #   ?? pattern.sub(lambda m: f"...>{m.group(0)}</mark>", highlighted)
#         highlighted = pattern.sub(
#             f'<mark class="clickable-term" data-term="{term}" '
#             f'style="background-color: #FFEB3B; cursor: pointer; padding: 2px 4px; border-radius: 3px;">{term}</mark>',
#             highlighted,
#         )
#     return highlighted


# ?????????????????????????????????????????????????????????????
# ?뵇 臾몃㎘ ?몄떇 ?⑥닔: 臾몃㎘??寃쎌젣 ?⑹뼱?몄? ?먮떒
# ?????????????????????????????????????????????????????????????
def is_financial_context(text: str, term: str, match_start: int, match_end: int, window_size: int = 50) -> bool:
    """
    臾몃㎘ ?덈룄???댁뿉 寃쎌젣 愿???ㅼ썙?쒓? ?덈뒗吏 ?뺤씤?섏뿬 寃쎌젣 ?⑹뼱?몄? ?먮떒
    - CSV?먯꽌 異붿텧???⑹뼱蹂??ㅼ썙?쒕? ?쒖슜?섏뿬 ???뺥솗???먮떒
    
    Args:
        text: ?꾩껜 ?띿뒪??
        term: ?뺤씤???⑹뼱
        match_start: 留ㅼ묶???꾩튂 ?쒖옉
        match_end: 留ㅼ묶???꾩튂 ??
        window_size: 二쇰? 臾몃㎘ ?ш린 (臾몄옄 ??
    
    Returns:
        寃쎌젣 ?⑹뼱濡??ъ슜??寃쎌슦 True
    """
    # 二쇰? 臾몃㎘ 異붿텧
    context_start = max(0, match_start - window_size)
    context_end = min(len(text), match_end + window_size)
    context = text[context_start:context_end].lower()
    
    # ??媛쒖꽑: CSV?먯꽌 異붿텧???⑹뼱蹂??ㅼ썙???ъ슜
    term_keywords = get_financial_context_keywords(term)
    
    # ?붾쾭源? ?ㅼ썙?쒓? 鍮꾩뼱?덇굅???덈Т ?곸쑝硫?湲곕낯 ?ㅼ썙???ъ슜
    if not term_keywords or len(term_keywords) < 5:
        # 湲곕낯 ?ㅼ썙?쒕쭔 ?ъ슜 (CSV?먯꽌 ?ㅼ썙??異붿텧 ?ㅽ뙣??寃쎌슦)
        term_keywords = set(BASE_FINANCIAL_KEYWORDS)
    
    # ?슟 遺???ㅼ썙??泥댄겕: 臾몃㎘??遺???ㅼ썙?쒓? ?덉쑝硫?寃쎌젣 ?⑹뼱媛 ?꾨떂
    context_lower = context.lower()
    
    # ?좑툘 ?밸퀎 ?⑦꽩 泥댄겕: "???醫낃?" 媛숈? 釉뚮옖?쒕챸 ?⑦꽩
    # "??? 諛붾줈 ?욌뮘??"醫낃?"媛 ?덉쑝硫?臾댁“嫄?釉뚮옖?쒕챸
    if term.lower() == '醫낃?':
        # "???醫낃?" ?먮뒗 "醫낃?" ?욌뮘??"??????덈뒗吏 ?뺤씤
        target_pattern = r'\b???s*醫낃?\b|\b醫낃?\s*???b'
        if re.search(target_pattern, context_lower, re.IGNORECASE):
            return False  # 釉뚮옖?쒕챸?쇰줈 ?먮떒
    
    # 釉뚮옖???뚯궗紐?愿??遺???ㅼ썙?쒕쭔 泥댄겕 (???꾧꺽)
    brand_negative_keywords = ['???, '醫낃?', '?쇱꽦', 'LG', '?꾨?', '湲곗븘', 'SK', '濡?뜲', '?좎꽭怨?, '釉뚮옖??, '?뚯궗', '湲곗뾽紐?, '?곹몴', '?쒗뭹紐?, '源移?, '?섏텧', '?섏엯']
    
    # 遺???ㅼ썙?쒓? 臾몃㎘???덈뒗吏 ?뺤씤
    found_negative_keyword = None
    for neg_keyword in brand_negative_keywords:
        # ?⑥뼱 寃쎄퀎瑜?怨좊젮??留ㅼ묶 (???뺥솗??
        neg_pattern = r'\b' + re.escape(neg_keyword.lower()) + r'\b'
        if re.search(neg_pattern, context_lower):
            # ?⑹뼱 ?먯껜媛 遺???ㅼ썙?쒖씤 寃쎌슦???쒖쇅 (?? "愿????遺???ㅼ썙?쒖씠吏留?寃쎌젣 ?⑹뼱)
            if neg_keyword.lower() != term.lower():
                found_negative_keyword = neg_keyword
                break
    
    # 遺???ㅼ썙?쒓? 諛쒓껄??寃쎌슦
    if found_negative_keyword:
        # 媛뺥븳 寃쎌젣 ?ㅼ썙?쒓? ?덈뒗吏 ?뺤씤 (遺???ㅼ썙?쒕낫???곗꽑?쒖쐞媛 ?믪쓬)
        strong_financial_keywords = ['肄붿뒪??, '肄붿뒪??, '二쇨?', '??, '留덇컧', '嫄곕옒', '媛寃?, '吏??, '?쒖옣', '?ъ옄', '湲덉쑖', '寃쎌젣', '?곸듅', '?섎씫', '蹂??, '留ㅻℓ', '泥닿껐', '?멸?']
        has_financial_keyword = False
        for fin_keyword in strong_financial_keywords:
            fin_pattern = r'\b' + re.escape(fin_keyword.lower()) + r'\b'
            if re.search(fin_pattern, context_lower):
                has_financial_keyword = True
                break
        
        # 遺???ㅼ썙?쒓? ?덇퀬 紐낇솗??寃쎌젣 ?ㅼ썙?쒓? ?놁쑝硫?False
        # ?? "?섏텧", "援??" 媛숈? ?쇰컲 ?⑥뼱??寃쎌젣 ?ㅼ썙?쒕줈 ?몄젙?섏? ?딆쓬
        if not has_financial_keyword:
            return False
    
    # 二쇰? 臾몃㎘???⑹뼱蹂?愿???ㅼ썙?쒓? ?덈뒗吏 ?뺤씤
    # ?좑툘 以묒슂: ?⑹뼱 ?먯껜???쒖쇅 (?⑹뼱媛 臾몃㎘???덈떎怨??댁꽌 寃쎌젣 ?⑹뼱??寃껋? ?꾨떂)
    # ?? "???醫낃?"?먯꽌 "醫낃?"媛 ?덉?留? "??, "留덇컧", "嫄곕옒", "媛寃?, "二쇨?", "肄붿뒪?? 媛숈? ?ㅼ썙?쒓? ?놁쑝硫?寃쎌젣 ?⑹뼱媛 ?꾨떂
    
    # ?ㅼ썙??留ㅼ묶?????꾧꺽?섍쾶: ?⑥뼱 寃쎄퀎 怨좊젮
    found_financial_keywords = []
    for keyword in term_keywords:
        if keyword and len(keyword) > 0 and keyword.lower() != term.lower():
            # ?⑥뼱 寃쎄퀎瑜?怨좊젮??留ㅼ묶 (???뺥솗??
            keyword_pattern = r'\b' + re.escape(keyword.lower()) + r'\b'
            if re.search(keyword_pattern, context_lower):
                found_financial_keywords.append(keyword)
                return True  # 寃쎌젣 愿???ㅼ썙?쒓? 臾몃㎘???덉쑝硫?寃쎌젣 ?⑹뼱濡??먮떒
    
    # 湲곕낯 寃쎌젣 ?ㅼ썙?쒕룄 ?뺤씤 (?⑹뼱蹂??ㅼ썙?쒖뿉 ?놁쓣 寃쎌슦)
    for keyword in BASE_FINANCIAL_KEYWORDS:
        if keyword and len(keyword) > 0 and keyword.lower() != term.lower():
            # ?⑥뼱 寃쎄퀎瑜?怨좊젮??留ㅼ묶
            keyword_pattern = r'\b' + re.escape(keyword.lower()) + r'\b'
            if re.search(keyword_pattern, context_lower):
                return True
    
    # 臾몃㎘??寃쎌젣 愿???ㅼ썙?쒓? ?놁쑝硫?寃쎌젣 ?⑹뼱媛 ?꾨떂
    return False

# ??蹂몃Ц?먯꽌 湲덉쑖 ?⑹뼱 ?섏씠?쇱씠??(RAG ?듯빀 踰꾩쟾 + 臾몃㎘ ?몄떇)
# - 蹂寃??ы빆:
#   1. 湲곗〈: st.session_state.financial_terms ?ъ쟾?먯꽌留?寃??
#   2. ?좉퇋: RAG????λ맂 紐⑤뱺 ?⑹뼱瑜??섏씠?쇱씠????곸쑝濡??ъ슜
#   3. Fallback: RAG 誘몄큹湲고솕 ??湲곗〈 ?ъ쟾 ?ъ슜
#   4. ??臾몃㎘ ?몄떇: 臾몃㎘??寃쎌젣 ?⑹뼱媛 ?꾨땶 寃쎌슦 ?섏씠?쇱씠???쒖쇅
# - 湲곗궗 蹂몃Ц ?띿뒪?몄뿉???⑹뼱瑜?李얠븘 <mark> ?쒓렇濡?媛먯떥 媛뺤“
# - ??뚮Ц??臾댁떆(re.IGNORECASE) ???곷Ц ?쎌뼱 ?깆뿉?????
# - data-term ?띿꽦: 異뷀썑 JS/?대깽???곌껐 ???대뼡 ?⑹뼱?몄? ?앸퀎 ?⑹씠
# - Streamlit 異쒕젰 ??st.markdown(..., unsafe_allow_html=True) ?꾩슂
# ?????????????????????????????????????????????????????????????
<<<<<<< HEAD
def highlight_terms(text: str, article_id: Optional[str] = None, return_matched_terms: bool = False) -> Union[str, tuple[str, set[str]]]:
=======
def highlight_terms(text: str, article_id: Optional[str] = None, return_matched_terms: bool = False, use_context_filter: bool = True) -> Union[str, tuple[str, set[str]]]:
>>>>>>> origin/mjy
    """
    湲곗궗 蹂몃Ц?먯꽌 湲덉쑖 ?⑹뼱瑜?李얠븘 ?섏씠?쇱씠??泥섎━ (罹먯떛 吏??

    Args:
        text: ?먮낯 ?띿뒪??湲곗궗 蹂몃Ц ??
        article_id: 湲곗궗 ID (罹먯떛 ?ㅻ줈 ?ъ슜, None?대㈃ 罹먯떛 ????
        return_matched_terms: True??寃쎌슦 (?섏씠?쇱씠?몃맂 ?띿뒪?? 諛쒓껄???⑹뼱 ?명듃) ?쒗뵆 諛섑솚

    Returns:
        return_matched_terms=False: 湲덉쑖 ?⑹뼱媛 ?섏씠?쇱씠??泥섎━??HTML 臾몄옄??
        return_matched_terms=True: (?섏씠?쇱씠?몃맂 HTML 臾몄옄?? 諛쒓껄???⑹뼱 ?명듃) ?쒗뵆
    """
    # ???깅뒫 媛쒖꽑: 湲곗궗蹂??섏씠?쇱씠??寃곌낵 罹먯떛
    if article_id:
        cache_key = f"highlight_cache_{article_id}"
        text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
        cache_entry = st.session_state.get(cache_key)
        
        # 罹먯떆媛 ?덇퀬 ?띿뒪?멸? 蹂寃쎈릺吏 ?딆븯?쇰㈃ 罹먯떆??寃곌낵 諛섑솚
        if cache_entry and cache_entry.get("text_hash") == text_hash:
            cached_highlighted = cache_entry.get("highlighted", text)
            if return_matched_terms:
                cached_matched_terms = cache_entry.get("matched_terms", set())
                return cached_highlighted, cached_matched_terms
            return cached_highlighted
    
    highlighted = text
    terms_to_highlight = set()

    cached_terms = st.session_state.get("rag_terms_for_highlight")
    if cached_terms:
        terms_to_highlight = set(cached_terms)
    elif st.session_state.get("rag_initialized", False):
        try:
            collection = st.session_state.get("rag_collection")
            if collection is None:
                raise ValueError("RAG 而щ젆?섏씠 ?놁뒿?덈떎")
            all_data = collection.get()
            if all_data and all_data['metadatas']:
                _cache_rag_metadata(all_data['metadatas'])
                terms_to_highlight = set(st.session_state.get("rag_terms_for_highlight", []))
        except Exception as e:
            st.warning(f"?좑툘 RAG ?⑹뼱 濡쒕뱶 以??ㅻ쪟, 湲곕낯 ?ъ쟾???ъ슜?⑸땲?? {e}")
            terms_to_highlight = set(st.session_state.get("financial_terms", DEFAULT_TERMS).keys())
    else:
        terms_to_highlight = set(st.session_state.get("financial_terms", DEFAULT_TERMS).keys())

    # ???깅뒫 媛쒖꽑: ?뺣젹???⑹뼱 紐⑸줉???몄뀡??罹먯떛 (?⑹뼱 紐⑸줉??蹂寃쎈릺吏 ?딅뒗 ???ъ궗??
    sorted_terms_cache_key = "highlight_sorted_terms_cache"
    sorted_terms_hash_key = "highlight_sorted_terms_hash"
    
    current_terms_hash = hashlib.md5(str(sorted(terms_to_highlight)).encode('utf-8')).hexdigest()
    cached_sorted_terms = st.session_state.get(sorted_terms_cache_key)
    cached_terms_hash = st.session_state.get(sorted_terms_hash_key)
    
    if cached_sorted_terms and cached_terms_hash == current_terms_hash:
        sorted_terms = cached_sorted_terms
    else:
        # 湲??⑹뼱遺??泥섎━?섏뿬 遺遺?留ㅼ묶 諛⑹? (?? "遺媛媛移섏꽭"媛 "遺媛媛移?蹂대떎 癒쇱? 泥섎━)
        sorted_terms = sorted(terms_to_highlight, key=len, reverse=True)
        st.session_state[sorted_terms_cache_key] = sorted_terms
        st.session_state[sorted_terms_hash_key] = current_terms_hash

    # ???깅뒫 媛쒖꽑: ?뺢퇋???⑦꽩 而댄뙆??罹먯떛
    pattern_cache_key = "highlight_pattern_cache"
    if pattern_cache_key not in st.session_state:
        st.session_state[pattern_cache_key] = {}
    pattern_cache = st.session_state[pattern_cache_key]

    # ?대? ?섏씠?쇱씠?몃맂 遺遺꾩쓣 蹂댄샇?섍린 ?꾪븳 ?꾩떆 ?뚮젅?댁뒪???留?
    placeholders = {}
    placeholder_counter = 0

    # ???깅뒫 媛쒖꽑: 鍮좊Ⅸ ?ъ쟾 ?꾪꽣留?- ?띿뒪?몄뿉 ?ы븿???⑹뼱留?泥섎━
    text_lower = highlighted.lower()
    terms_in_text = [term for term in sorted_terms if term and term.lower() in text_lower]
    
    # ???깅뒫 媛쒖꽑: 諛쒓껄???⑹뼱 異붿쟻 (?⑹뼱 ?꾪꽣留??ъ궗?⑹쓣 ?꾪빐)
    matched_terms_set = set()

    for term in terms_in_text:
        # ?뚮젅?댁뒪??붽? ?꾨땶 ?ㅼ젣 ?띿뒪?몃쭔 留ㅼ묶?섎룄濡??⑦꽩 ?앹꽦
        # __PLACEHOLDER_濡??쒖옉?섎뒗 遺遺꾩? ?쒖쇅
        escaped_term = re.escape(term)

        # ???깅뒫 媛쒖꽑: ?뺢퇋???⑦꽩 罹먯떛
        if escaped_term not in pattern_cache:
            pattern_cache[escaped_term] = re.compile(escaped_term, re.IGNORECASE)
        pattern = pattern_cache[escaped_term]

        # 留ㅼ묶???먮옒 ?쒓린瑜??좎??섎㈃???섏씠?쇱씠??
<<<<<<< HEAD
        # ??媛쒖꽑: 媛숈? ?⑹뼱??泥?踰덉㎏ 留ㅼ묶留??섏씠?쇱씠??(媛?낆꽦 ?μ긽)
=======
>>>>>>> origin/mjy
        matches = []
        for match in pattern.finditer(highlighted):
            # 留ㅼ묶???꾩튂媛 ?뚮젅?댁뒪????덉뿉 ?덈뒗吏 ?뺤씤
            start_pos = match.start()
            # 留ㅼ묶 ?꾩튂 ?댁쟾???뚮젅?댁뒪??붽? ?덇퀬 ?꾩쭅 ?ロ엳吏 ?딆븯?붿? 泥댄겕
            # ???깅뒫 媛쒖꽑: ???⑥쑉?곸씤 ?뚮젅?댁뒪???泥댄겕
            if start_pos > 0 and '__PLACEHOLDER_' in highlighted[max(0, start_pos-30):start_pos]:
                continue
<<<<<<< HEAD
            matches.append(match)
            # ??媛쒖꽑: 泥?踰덉㎏ 留ㅼ묶留?泥섎━?섍퀬 以묐떒
            break
=======
            
            # ??臾몃㎘ ?몄떇: 臾몃㎘??寃쎌젣 ?⑹뼱媛 ?꾨땶 寃쎌슦 ?쒖쇅
            if use_context_filter:
                is_financial = is_financial_context(text, term, match.start(), match.end())
                if not is_financial:
                    # 臾몃㎘??寃쎌젣 ?⑹뼱媛 ?꾨땲誘濡??섏씠?쇱씠???쒖쇅
                    continue
            
            matches.append(match)
>>>>>>> origin/mjy

        # 泥?踰덉㎏ 留ㅼ묶留??섏씠?쇱씠??泥섎━
        if matches:
            match = matches[0]
            matched_text = match.group(0)
            # ???깅뒫 媛쒖꽑: 留ㅼ묶???⑹뼱 異붿쟻
            matched_terms_set.add(term)
            
            # HTML ?쒓렇 ?앹꽦 (Streamlit? ?대┃ ?대깽?몃? 吏?먰븯吏 ?딆쑝誘濡??쒓컖???쒖떆留?
            placeholder = f"__PLACEHOLDER_{placeholder_counter}__"
            mark_html = (
                f'<mark class="financial-term" '
                f'style="background-color: #FFEB3B; padding: 2px 4px; border-radius: 3px;">'
                f'{matched_text}</mark>'
            )
            placeholders[placeholder] = mark_html
            placeholder_counter += 1

            # ?띿뒪??移섑솚
            highlighted = highlighted[:match.start()] + placeholder + highlighted[match.end():]

    # 紐⑤뱺 ?뚮젅?댁뒪??붾? ?ㅼ젣 HTML濡?蹂듭썝
    for placeholder, mark_html in placeholders.items():
        highlighted = highlighted.replace(placeholder, mark_html)

    # ???깅뒫 媛쒖꽑: 寃곌낵瑜?罹먯떆?????
    if article_id:
        st.session_state[cache_key] = {
            "text_hash": text_hash,
            "highlighted": highlighted,
            "matched_terms": matched_terms_set  # 諛쒓껄???⑹뼱???④퍡 罹먯떛
        }

    # ???깅뒫 媛쒖꽑: 諛쒓껄???⑹뼱 諛섑솚 (?⑹뼱 ?꾪꽣留??ъ궗??
    if return_matched_terms:
        return highlighted, matched_terms_set
    
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
        "definition": info.get("?뺤쓽"),
        "detail": info.get("?ㅻ챸"),
        "analogy": info.get("鍮꾩쑀"),
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
    user_prompt = f"{question_text}媛 萸먯빞?"
    response = generate_structured_persona_reply(
        user_input=user_prompt,
        term=base_term,
        context=context,
        temperature=temperature,
    )
    if response and "(LLM ?곌껐 ?ㅻ쪟" not in response:
        return response

    # LLM ?몄텧 ?ㅽ뙣 ??媛꾨떒???뺣낫?쇰룄 ?쒓났
    parts: List[str] = [f"?쨼 **{base_term}** ??????ㅻ챸?댁쨪寃? ?렞"]
    if context.get("definition"):
        parts.append(f"?뱰 ?뺤쓽: {context['definition']}")
    if context.get("detail"):
        parts.append(f"?뮕 ?ㅻ챸: {context['detail']}")
    if context.get("importance"):
        parts.append(f"????以묒슂??: {context['importance']}")
    if context.get("analogy"):
        parts.append(f"?뙚 鍮꾩쑀: {context['analogy']}")
    if context.get("example"):
        parts.append(f"?벐 ?덉떆: {context['example']}")
    parts.append("??沅곴툑?????덉쑝硫??명븯寃?臾쇱뼱遊?")
    return "\n".join(parts)


# ?????????????????????????????????????????????????????????????
# ?뱚 CSV ?뚯씪?먯꽌 湲덉쑖?⑹뼱 濡쒕뱶
# - rag/glossary/湲덉쑖?⑹뼱.csv ?뚯씪??pandas濡??쎌뼱??
# - 而щ읆: 踰덊샇, 湲덉쑖?⑹뼱, ?뺤쓽, 鍮꾩쑀, ??以묒슂?, ?ㅽ빐 援먯젙, ?덉떆
# ?????????????????????????????????????????????????????????????
def load_glossary_from_csv() -> pd.DataFrame:
    """湲덉쑖?⑹뼱.csv ?뚯씪??濡쒕뱶?섏뿬 DataFrame?쇰줈 諛섑솚"""
    csv_path = os.path.join(os.path.dirname(__file__), "glossary", "湲덉쑖?⑹뼱.csv")

    if not os.path.exists(csv_path):
        st.warning(f"?좑툘 湲덉쑖?⑹뼱 ?뚯씪??李얠쓣 ???놁뒿?덈떎: {csv_path}")
        return pd.DataFrame()

    try:
        df = pd.read_csv(csv_path, encoding="utf-8")
        # 寃곗륫移섎? 鍮?臾몄옄?대줈 泥섎━
        df = df.fillna("")
        return df
    except Exception as e:
        st.error(f"??CSV 濡쒕뱶 以??ㅻ쪟 諛쒖깮: {e}")
        return pd.DataFrame()


# ?????????????????????????????????????????????????????????????
# ?뵍 CSV ?뚯씪 泥댄겕??怨꾩궛 (蹂寃?媛먯???
# ?????????????????????????????????????????????????????????????
def _calculate_csv_checksum(csv_path: str) -> str:
    """CSV ?뚯씪??泥댄겕?ъ쓣 怨꾩궛?섏뿬 蹂寃??щ? ?뺤씤"""
    try:
        with open(csv_path, 'rb') as f:
            file_hash = hashlib.md5(f.read()).hexdigest()
        return file_hash
    except Exception:
        return ""


# ?????????????????????????????????????????????????????????????
# ?? ?꾨쿋??紐⑤뜽 濡쒕뱶 (st.cache_resource濡?罹먯떛)
# ?????????????????????????????????????????????????????????????
@st.cache_resource
def _get_embedding_model():
    """
    ?꾨쿋??紐⑤뜽??濡쒕뱶 (st.cache_resource濡?罹먯떛)
    - ??踰?濡쒕뱶??紐⑤뜽? ?몄뀡 媛??ъ궗??
    - 由ъ냼??硫붾え由? 紐⑤뜽 ?뚯씪)瑜?怨듭쑀?섎?濡?cache_resource ?ъ슜
    """
    return SentenceTransformer('jhgan/ko-sroberta-multitask')


@st.cache_resource
def _get_chroma_client():
    """
    ChromaDB ?대씪?댁뼵???앹꽦 (st.cache_resource濡?罹먯떛)
    - ??踰??앹꽦???대씪?댁뼵?몃뒗 ?몄뀡 媛??ъ궗??
    - persistent 紐⑤뱶濡??붿뒪?ъ뿉 ???
    """
    chroma_db_path = os.path.join(_get_cache_dir(), "chroma_db")
    return chromadb.PersistentClient(
        path=chroma_db_path,
        settings=Settings(
            anonymized_telemetry=False
        )
    )


# ?????????????????????????????????????????????????????????????
# ?뮶 ?꾨쿋??踰≫꽣 罹먯떆 ?뚯씪 寃쎈줈
# ?????????????????????????????????????????????????????????????
def _get_cache_dir():
    """罹먯떆 ?붾젆?좊━ 寃쎈줈 諛섑솚"""
    cache_dir = os.path.join(os.path.dirname(__file__), "glossary", ".cache")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def _get_embeddings_cache_path():
    """?꾨쿋??踰≫꽣 罹먯떆 ?뚯씪 寃쎈줈"""

    return os.path.join(_get_cache_dir(), "embeddings.pkl")


def _get_metadata_cache_path():
    """硫뷀??곗씠??罹먯떆 ?뚯씪 寃쎈줈"""
    return os.path.join(_get_cache_dir(), "metadata.pkl")


def _get_checksum_cache_path():
    """泥댄겕??罹먯떆 ?뚯씪 寃쎈줈"""
    return os.path.join(_get_cache_dir(), "checksum.json")


# ?????????????????????????????????????????????????????????????
# ?뮶 ?꾨쿋??踰≫꽣 ???
# ?????????????????????????????????????????????????????????????
def _save_embeddings_cache(documents: List[str], embeddings, metadatas: List[Dict], ids: List[str], checksum: str):
    """?꾨쿋??踰≫꽣? 硫뷀??곗씠?곕? 罹먯떆 ?뚯씪濡????(濡쒖뺄? ?뺤텞 ?놁쓬, 鍮좊Ⅸ 濡쒕뱶)"""
    try:
        cache_dir = _get_cache_dir()
        
        # ?꾨쿋??踰≫꽣 ???(?뺤텞 ?놁쓬 - 鍮좊Ⅸ 濡쒕뱶)
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

        
        # 泥댄겕?????
        with open(_get_checksum_cache_path(), 'w', encoding='utf-8') as f:
            json.dump({'checksum': checksum}, f)
        
    except Exception as e:
        st.warning(f"?좑툘 ?꾨쿋??罹먯떆 ????ㅽ뙣: {e}")


# ?????????????????????????????????????????????????????????????
# ?뱛 ?꾨쿋??踰≫꽣 濡쒕뱶 (濡쒖뺄 罹먯떆)
# ?????????????????????????????????????????????????????????????
def _load_embeddings_cache(checksum: str) -> Optional[Dict]:
    """??λ맂 ?꾨쿋??踰≫꽣瑜?濡쒖뺄 罹먯떆 ?뚯씪?먯꽌 濡쒕뱶"""
    try:
        # 泥댄겕???뺤씤
        checksum_path = _get_checksum_cache_path()
        if not os.path.exists(checksum_path):
            return None
        
        with open(checksum_path, 'r', encoding='utf-8') as f:
            cached_data = json.load(f)
            if cached_data.get('checksum') != checksum:
                return None  # CSV ?뚯씪??蹂寃쎈맖
        
        # ?꾨쿋??踰≫꽣 濡쒕뱶

        embeddings_path = _get_embeddings_cache_path()
        if not os.path.exists(embeddings_path):
            return None
        
        with open(embeddings_path, 'rb') as f:
            return pickle.load(f)
    
    except Exception as e:
        st.warning(f"?좑툘 濡쒖뺄 ?꾨쿋??罹먯떆 濡쒕뱶 ?ㅽ뙣: {e}")
        return None


# ?????????????????????????????????????????????????????????????
# ?곻툘 Supabase Storage???꾨쿋?????
# ?????????????????????????????????????????????????????????????
def _save_embeddings_to_supabase(documents: List[str], embeddings, metadatas: List[Dict], ids: List[str], checksum: str) -> bool:
    """Supabase Storage???꾨쿋??踰≫꽣 ???""
    if not SUPABASE_ENABLE:
        return False
    
    supabase = get_supabase_client()
    if not supabase:
        return False
    
    try:
        # 1. ?꾨쿋???곗씠??以鍮?
        cache_data = {
            'documents': documents,
            'embeddings': embeddings.tolist() if hasattr(embeddings, 'tolist') else embeddings,
            'metadatas': metadatas,
            'ids': ids
        }
        
        pickled_data = pickle.dumps(cache_data)
        compressed_data = gzip.compress(pickled_data)
        
        # 3. Storage 踰꾪궥怨?寃쎈줈 ?ㅼ젙 (gzip ?뺤옣??
        bucket_name = "glossary-cache"
        storage_path = f"embeddings/{checksum}.pkl.gz"
        
        # 4. Storage???낅줈??(湲곗〈 ?뚯씪???덉쑝硫???뼱?곌린)
        try:
            # 湲곗〈 ?뚯씪 ??젣 ?쒕룄 (?덉쑝硫?
            supabase.storage.from_(bucket_name).remove([storage_path])
        except:
            pass  # ?뚯씪???놁쑝硫?臾댁떆
        
        # ???뚯씪 ?낅줈??(gzip ?뺤텞???곗씠??
        supabase.storage.from_(bucket_name).upload(
            storage_path,
            compressed_data,
            file_options={"content-type": "application/octet-stream", "upsert": "true"}
        )
        
        # 5. 硫뷀??곗씠?곕? ?뚯씠釉붿뿉 ???(glossary_embeddings ?뚯씠釉?
        try:
            supabase.table("glossary_embeddings").upsert({
                "checksum": checksum,
                "storage_path": storage_path,
                "term_count": len(documents),
                "updated_at": "now()"
            }).execute()
        except Exception as table_error:
            # ?뚯씠釉붿씠 ?놁쑝硫?寃쎄퀬留?(Storage???깃났?덉쑝誘濡?
            st.warning(f"?좑툘 glossary_embeddings ?뚯씠釉?????ㅽ뙣: {table_error}")
        
        return True
    
    except Exception as e:
        st.warning(f"?좑툘 Supabase Storage ????ㅽ뙣: {e}")
        return False


# ?????????????????????????????????????????????????????????????
# ?곻툘 Supabase Storage?먯꽌 ?꾨쿋??濡쒕뱶
# ?????????????????????????????????????????????????????????????
def _load_embeddings_from_supabase(checksum: str) -> Optional[Dict]:
    """Supabase Storage?먯꽌 ?꾨쿋??踰≫꽣 濡쒕뱶 (1?쒖쐞)"""
    if not SUPABASE_ENABLE:
        return None
    
    supabase = get_supabase_client()
    if not supabase:
        return None
    
    try:
        bucket_name = "glossary-cache"
        storage_path = None
        
        # 1. 硫뷀??곗씠???뚯씠釉붿뿉???뺤씤 (?좏깮?? ?놁뼱??吏꾪뻾)
        try:
            result = supabase.table("glossary_embeddings").select("*").eq("checksum", checksum).execute()
            if result.data and len(result.data) > 0:
                # 硫뷀??곗씠?곌? ?덉쑝硫??대떦 寃쎈줈 ?ъ슜
                metadata = result.data[0]
                storage_path = metadata.get("storage_path")
        except:
            # ?뚯씠釉붿씠 ?놁뼱??Storage?먯꽌 吏곸젒 ?뺤씤
            pass
        
        # 2. Storage?먯꽌 ?ㅼ슫濡쒕뱶 ?쒕룄 (.pkl.gz ?곗꽑, .pkl fallback)
        if not storage_path:
            # 硫뷀??곗씠?곌? ?놁쑝硫?吏곸젒 寃쎈줈 ?쒕룄
            storage_paths = [
                f"embeddings/{checksum}.pkl.gz",  # ?뺤텞???뚯씪 ?곗꽑
                f"embeddings/{checksum}.pkl"      # ?뺤텞 ?????뚯씪 fallback
            ]
        else:
            storage_paths = [storage_path]
        
        response = None
        is_gzipped = False
        
        for path in storage_paths:
            try:
                response = supabase.storage.from_(bucket_name).download(path)
                if response:
                    is_gzipped = path.endswith('.gz')
                    break
            except:
                continue
        
        if not response:
            return None
        
        # 3. gzip ?뺤텞 ?댁젣 (?꾩슂??寃쎌슦)
        if is_gzipped:
            decompressed_data = gzip.decompress(response)
            cache_data = pickle.loads(decompressed_data)
        else:
            cache_data = pickle.loads(response)
        
        return cache_data

    
    except Exception as e:
        # ?뚯씪???녾굅???먮윭 諛쒖깮 ??None 諛섑솚 (議곗슜???ㅽ뙣)
        return None


# ?????????????????????????????????????????????????????????????
# ?봽 ?섏씠釉뚮━??濡쒕뱶: Supabase ?곗꽑, 濡쒖뺄 Fallback
# ?????????????????????????????????????????????????????????????
def _load_embeddings_with_fallback(checksum: str) -> Optional[Dict]:
    """
    ?꾨쿋??踰≫꽣 濡쒕뱶 (?섏씠釉뚮━??諛⑹떇)
    
    ??理쒖쟻?? Supabase Storage瑜??곗꽑 ?뺤씤 (?대? ?щ씪媛 ?덉쑝硫?鍮좊Ⅴ寃?濡쒕뱶)
    
    ?곗꽑?쒖쐞:
    1. Supabase Storage (?먭꺽 ??μ냼, ?대? ?щ씪媛 ?덉쑝硫?利됱떆 ?ъ슜)
    2. 濡쒖뺄 罹먯떆 ?뚯씪 (鍮좊Ⅸ 濡쒖뺄 ?묎렐, Supabase ?ㅽ뙣 ??
    3. None (?덈줈 ?앹꽦 ?꾩슂)
    """
    # ??1?쒖쐞: Supabase Storage (?대? ?щ씪媛 ?덉쑝硫??곗꽑 ?ъ슜)
    cached_data = _load_embeddings_from_supabase(checksum)
    if cached_data:
        st.session_state["rag_cache_source"] = "supabase"
        # 濡쒖뺄 罹먯떆?먮룄 ??ν븯???ㅼ쓬?먮뒗 ??鍮좊Ⅴ寃??묎렐
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
    
    # ??2?쒖쐞: 濡쒖뺄 罹먯떆 ?뚯씪 (Supabase ?ㅽ뙣 ??
    cached_data = _load_embeddings_cache(checksum)
    if cached_data:
        st.session_state["rag_cache_source"] = "local"
        # 諛깃렇?쇱슫?쒖뿉??Supabase???숆린??(?ㅼ쓬?먮뒗 Supabase?먯꽌 鍮좊Ⅴ寃?濡쒕뱶)
        _sync_supabase_async(
            cached_data['documents'],
            cached_data['embeddings'],
            cached_data['metadatas'],
            cached_data['ids'],
            checksum
        )
        return cached_data

    # ??3?쒖쐞: ?놁쓬 (?덈줈 ?앹꽦 ?꾩슂)
    st.session_state["rag_cache_source"] = "none"
    return None


# ?????????????????????????????????????????????????????????????
# ?쭬 RAG ?쒖뒪??珥덇린??諛?踰≫꽣 DB 援ъ텞 (?섏씠釉뚮━??理쒖쟻??踰꾩쟾)
# - ?꾨쿋??紐⑤뜽: ?꾩뿭 罹먯떆濡??ъ궗??(?몄뀡留덈떎 ?щ줈??諛⑹?)
# - ?꾨쿋??踰≫꽣: Supabase Storage ?곗꽑, 濡쒖뺄 Fallback (?섏씠釉뚮━??
# - ChromaDB: persistent 紐⑤뱶濡??붿뒪?ъ뿉 ???(?몄뀡 媛??좎?)
# - CSV 泥댄겕?? ?뚯씪 蹂寃?媛먯??섏뿬 ?먮룞 ?ъ엫踰좊뵫
# ?????????????????????????????????????????????????????????????
def initialize_rag_system(is_background: bool = False):
    """
    RAG ?쒖뒪??珥덇린?? 踰≫꽣 DB ?앹꽦 諛?湲덉쑖?⑹뼱 ?꾨쿋??(?섏씠釉뚮━??罹먯떆)
    
    Args:
        is_background: 諛깃렇?쇱슫???ㅻ젅?쒖뿉???ㅽ뻾 以묒씠硫?True (st.spinner ?ъ슜 ????
    """

    # ?몄뀡???대? 珥덇린?붾릺???덉쑝硫??ㅽ궢
    if "rag_initialized" in st.session_state and st.session_state.rag_initialized:
        return

    # 諛깃렇?쇱슫???ㅻ젅??泥댄겕
    is_background_thread = is_background or (threading.current_thread().name != "MainThread")
    
    # ?ㅽ뵾??而⑦뀓?ㅽ듃 留ㅻ땲? (諛깃렇?쇱슫?쒖뿉?쒕뒗 no-op)
    class _noop_context:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    
    spinner_context = _noop_context if is_background_thread else st.spinner

    perf_enabled = _perf_enabled()
    perf_steps: List[Dict] = []
    total_start = time.perf_counter() if perf_enabled else 0.0
    step_start = total_start
    perf_logged = False

    try:
        # 1截뤴깵 CSV 濡쒕뱶 諛?泥댄겕??怨꾩궛
        with spinner_context("?뱞 湲덉쑖?⑹뼱 ?뚯씪 濡쒕뱶 以?.."):
            csv_path = os.path.join(os.path.dirname(__file__), "glossary", "湲덉쑖?⑹뼱.csv")
            if not os.path.exists(csv_path):
                if not is_background_thread:
                    st.warning(f"?좑툘 湲덉쑖?⑹뼱 ?뚯씪??李얠쓣 ???놁뒿?덈떎: {csv_path}")
                st.session_state.rag_initialized = False
                return

            df = pd.read_csv(csv_path, encoding="utf-8")
            df = df.fillna("")
            csv_checksum = _calculate_csv_checksum(csv_path)
        if perf_enabled:
            step_start = _perf_step(perf_enabled, perf_steps, "csv_load", step_start)

        # 2截뤴깵 ?꾨쿋??紐⑤뜽 濡쒕뱶 (st.cache_resource濡?罹먯떛)
        # 泥??ㅽ뻾 ??紐⑤뜽 濡쒕뱶媛 留ㅼ슦 ?먮━誘濡???긽 ?ㅽ뵾???쒖떆
        with spinner_context("?쨼 ?쒓뎅???꾨쿋??紐⑤뜽 濡쒕뱶 以?.. (泥??ㅽ뻾 ??10-20珥??뚯슂)"):
            embedding_model = _get_embedding_model()
        if perf_enabled:
            step_start = _perf_step(perf_enabled, perf_steps, "model_ready", step_start)

        # 3截뤴깵 ChromaDB ?대씪?댁뼵???앹꽦 (persistent 紐⑤뱶, st.cache_resource濡?罹먯떛)
        with spinner_context("?뮶 踰≫꽣 ?곗씠?곕쿋?댁뒪 珥덇린??以?.."):
            chroma_client = _get_chroma_client()
        if perf_enabled:
            step_start = _perf_step(perf_enabled, perf_steps, "chroma_client", step_start)

        # 4截뤴깵 ?섏씠釉뚮━??諛⑹떇?쇰줈 ?꾨쿋??濡쒕뱶 ?쒕룄 (Supabase ?곗꽑, 濡쒖뺄 Fallback)
        with spinner_context("?봽 ?꾨쿋??踰≫꽣 濡쒕뱶 以?.."):
            cached_data = _load_embeddings_with_fallback(csv_checksum)
        if perf_enabled:
            step_start = _perf_step(perf_enabled, perf_steps, "cache_lookup", step_start)

        # 5截뤴깵 而щ젆??媛?몄삤湲??먮뒗 ?앹꽦
        collection_name = "financial_terms"
        with spinner_context("?뵇 踰≫꽣 而щ젆???뺤씤 以?.."):
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

                    if not is_background_thread:
                        cache_source = "Supabase" if SUPABASE_ENABLE else "濡쒖뺄"
                        st.success(f"??RAG ?쒖뒪??珥덇린???꾨즺! ({cache_source} 罹먯떆 ?ъ슜, {len(documents)}媛??⑹뼱)")
                    return
                elif cached_data is None:
                    try:
                        chroma_client.delete_collection(name=collection_name)
                    except:
                        pass
                    collection = chroma_client.create_collection(
                        name=collection_name,
                        metadata={"description": "湲덉쑖 ?⑹뼱 ?ъ쟾 踰≫꽣 DB"}
                    )
            except:
                collection = chroma_client.create_collection(
                    name=collection_name,
                    metadata={"description": "湲덉쑖 ?⑹뼱 ?ъ쟾 踰≫꽣 DB"}
                )
        if perf_enabled:
            step_start = _perf_step(perf_enabled, perf_steps, "collection_ready", step_start)

        if cached_data is not None:
            with spinner_context("?벀 罹먯떆???곗씠??以鍮?以?.."):
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
            with spinner_context("?뱷 湲덉쑖?⑹뼱 ?곗씠??以鍮?以?.."):
                documents = []
                metadatas = []
                ids = []

                for idx, row in df.iterrows():
                    term = str(row.get("湲덉쑖?⑹뼱", "")).strip()
                    if not term:
                        continue

                    synonym = str(row.get("?좎쓽??, "")).strip()
                    definition = str(row.get("?뺤쓽", "")).strip()
                    analogy = str(row.get("鍮꾩쑀", "")).strip()

                    search_text = f"{term}"
                    if synonym:
                        search_text += f" ({synonym})"
                    search_text += f" - {definition}"
                    if analogy:
                        search_text += f" | 鍮꾩쑀: {analogy}"

                    documents.append(search_text)

                    metadatas.append({
                        "term": term,
                        "synonym": synonym,
                        "definition": definition,
                        "analogy": analogy,
                        "importance": str(row.get("??以묒슂?", "")).strip(),
                        "correction": str(row.get("?ㅽ빐 援먯젙", "")).strip(),
                        "example": str(row.get("?덉떆", "")).strip(),
                        "difficulty": str(row.get("?⑥뼱 ?쒖씠??, "")).strip(),
                    })

                    ids.append(f"term_{idx}")
            if perf_enabled:
                step_start = _perf_step(perf_enabled, perf_steps, "documents_prepared", step_start)

            with spinner_context(f"?봽 {len(documents)}媛?湲덉쑖?⑹뼱 踰≫꽣??以?.."):
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

            with spinner_context("?뮶 ?꾨쿋??踰≫꽣 ???以?.."):
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

        # 諛깃렇?쇱슫???ㅻ젅?쒖뿉?쒕뒗 UI 硫붿떆吏 ?쒖떆 ????
        if not is_background_thread:
            if cached_data is not None:
                cache_source = "Supabase" if SUPABASE_ENABLE else "濡쒖뺄"
                st.success(f"??RAG ?쒖뒪??珥덇린???꾨즺! ({cache_source} 罹먯떆 ?ъ슜, {len(documents)}媛??⑹뼱)")
            else:
                save_source = "Supabase + 濡쒖뺄" if SUPABASE_ENABLE else "濡쒖뺄"
                st.success(f"??RAG ?쒖뒪??珥덇린???꾨즺! ({len(documents)}媛??⑹뼱 濡쒕뱶, {save_source}????λ맖)")

    except Exception as e:
        if not is_background_thread:
            st.error(f"??RAG 珥덇린???ㅽ뙣: {e}")
        st.session_state.rag_initialized = False
    finally:
        if perf_enabled and not perf_logged:
            perf_steps.append({"step": "total", "ms": round((time.perf_counter() - total_start) * 1000, 2)})
            _record_perf("initialize", perf_steps)


# ?????????????????????????????????????????????????????????????
# ?뵇 RAG 湲곕컲 ?⑹뼱 寃??
# - ?ъ슜??吏덈Ц??踰≫꽣?뷀븯???좎궗???⑹뼱 寃??
# - ?곸쐞 k媛쒖쓽 愿???⑹뼱 諛섑솚
# ?????????????????????????????????????????????????????????????
def search_terms_by_rag(query: str, top_k: int = 1, include_distances: bool = False) -> List[Dict]:
    """RAG瑜??ъ슜?섏뿬 吏덈Ц怨?愿?⑤맂 湲덉쑖 ?⑹뼱 寃??
    
    Args:
        query: 寃?됲븷 吏덈Ц ?먮뒗 ?⑹뼱
        top_k: 諛섑솚???곸쐞 k媛?寃곌낵
        include_distances: True??寃쎌슦 嫄곕━ ?뺣낫???ы븿?섏뿬 諛섑솚
    
    Returns:
        寃?됰맂 ?⑹뼱 硫뷀??곗씠??由ъ뒪??(include_distances=True??寃쎌슦 嫄곕━ ?뺣낫 ?ы븿)
    """

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

        # ???깅뒫 媛쒖꽑: ?꾨쿋??寃곌낵 罹먯떛 (?숈씪 吏덈Ц??????ъ궗??
        query_hash = hashlib.md5(query.encode('utf-8')).hexdigest()
        embedding_cache_key = f"rag_embedding_cache_{query_hash}"
        
        cached_embedding = st.session_state.get(embedding_cache_key)
        if cached_embedding is not None:
            # 罹먯떆 ?덊듃: ?꾨쿋???몄퐫???앸왂 (嫄곗쓽 0ms)
            query_embedding = cached_embedding
            if perf_enabled:
                step_start = _perf_step(perf_enabled, perf_steps, "encode_cached", step_start)
        else:
            # 罹먯떆 誘몄뒪: ?꾨쿋???몄퐫???섑뻾
            query_embedding = embedding_model.encode([query])[0]
            # 罹먯떆?????(?ㅼ쓬 ?몄텧 ??利됱떆 ?ъ슜)
            st.session_state[embedding_cache_key] = query_embedding
            if perf_enabled:
                step_start = _perf_step(perf_enabled, perf_steps, "encode", step_start)
<<<<<<< HEAD
=======

        # 嫄곕━ ?뺣낫 ?ы븿 ?щ????곕씪 include ?뚮씪誘명꽣 ?ㅼ젙
        include = ["metadatas"]
        if include_distances:
            include.append("distances")
>>>>>>> origin/mjy

        results = collection.query(
            query_embeddings=[query_embedding.tolist()],
            n_results=top_k,
            include=include
        )
        if perf_enabled:
            step_start = _perf_step(perf_enabled, perf_steps, "query", step_start)

        matched_terms = []
        if results and results['metadatas']:
<<<<<<< HEAD
            for metadata in results['metadatas'][0]:
                matched_terms.append(metadata)
=======
            for i, metadata in enumerate(results['metadatas'][0]):
                term_data = metadata.copy()
                # 嫄곕━ ?뺣낫媛 ?덉쑝硫?異붽?
                if include_distances and results.get('distances') and results['distances'][0]:
                    term_data['_distance'] = results['distances'][0][i]
                matched_terms.append(term_data)
>>>>>>> origin/mjy
        if perf_enabled:
            step_start = _perf_step(perf_enabled, perf_steps, "format", step_start)
            perf_steps.append({"step": "total", "ms": round((time.perf_counter() - total_start) * 1000, 2), "info": {"top_k": top_k, "returned": len(matched_terms)}})
            _record_perf("query", perf_steps)
            perf_logged = True

        return matched_terms

    except Exception as e:
        st.error(f"??RAG 寃??以??ㅻ쪟: {e}")
        return []
    finally:
        if perf_enabled and not perf_logged:
            perf_steps.append({"step": "total", "ms": round((time.perf_counter() - total_start) * 1000, 2)})
            _record_perf("query", perf_steps)


# ?????????????????????????????????????????????????????????????
# ?쫱 梨쀫큸 ?묐떟?? RAG 湲곕컲 ?⑹뼱 ?ㅻ챸 ?앹꽦 (湲곗〈 ?⑥닔 ?泥?
# - 蹂寃??ы빆:
#   1. 湲곗〈: ?섎뱶肄붾뵫??DEFAULT_TERMS ?ъ쟾?먯꽌 寃??
#   2. ?좉퇋: RAG 踰≫꽣 寃?됱쑝濡??좎궗 ?⑹뼱 李얘린
#   3. Fallback: RAG ?ㅽ뙣 ??湲곗〈 諛⑹떇?쇰줈 ?숈옉
# ?????????????????????????????????????????????????????????????
def explain_term(term: str, chat_history=None, return_rag_info: bool = False):
    """
    ?⑹뼱 ?ㅻ챸 ?앹꽦 (RAG ?뺥솗 留ㅼ묶 ?곗꽑, ?ㅽ뙣 ??湲곗〈 ?ъ쟾 ?ъ슜)

    Args:
        term: ?ㅻ챸??湲덉쑖 ?⑹뼱
        chat_history: 梨꾪똿 ?대젰 (?ν썑 而⑦뀓?ㅽ듃 媛뺥솕??
        return_rag_info: True??寃쎌슦 (explanation, rag_info) ?쒗뵆 諛섑솚

    Returns:
        return_rag_info=False: 留덊겕?ㅼ슫 ?뺤떇???⑹뼱 ?ㅻ챸 臾몄옄??
        return_rag_info=True: (留덊겕?ㅼ슫 ?뺤떇???⑹뼱 ?ㅻ챸, RAG 硫뷀??곗씠???먮뒗 None) ?쒗뵆
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
                    raise ValueError("RAG 而щ젆?섏씠 ?놁뒿?덈떎")
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
            st.warning(f"?좑툘 RAG 寃??以??ㅻ쪟, 湲곕낯 ?ъ쟾???ъ슜?⑸땲?? {e}")

    terms = st.session_state.get("financial_terms", DEFAULT_TERMS)

    if term not in terms:
        message = f"'{term}'??????뺣낫媛 ?꾩쭅 ?놁뼱. ?ㅻⅨ ?⑹뼱瑜??좏깮?댁쨾."
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





