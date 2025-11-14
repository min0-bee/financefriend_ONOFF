import time
from datetime import datetime
import streamlit as st
from core.logger import log_event, start_view_timer, end_view_timer, is_page_hidden_eval
from rag.glossary import highlight_terms, explain_term

def render():
    article = st.session_state.selected_article
    if not article:
        st.warning("선택된 기사가 없습니다.")
        return

    # ✅ 최초 진입 시에만 기사 렌더 latency 측정
    if not st.session_state.get("detail_enter_logged"):
        t0 = time.time()
        perf_steps = {}  # 성능 측정 단계별 시간

        # 상세 진입 타이머 시작
        start_view_timer(article.get("id"))

        # 실제 렌더링
        st.markdown("---")
        st.header(article['title'])
        st.caption(f"📅 {article['date']}")
        st.markdown('<div class="article-content">', unsafe_allow_html=True)
        
        # ✅ 성능 측정: 하이라이트 처리 시간
        article_id = article.get("id")
        content = article['content']
        highlight_start = time.time()
        # ✅ 성능 개선: 하이라이트 처리에서 발견된 용어도 함께 받아서 재사용
        result = highlight_terms(content, article_id=str(article_id) if article_id else None, return_matched_terms=True)
        if isinstance(result, tuple):
            highlighted_content, matched_terms_from_highlight = result
        else:
            highlighted_content = result
            matched_terms_from_highlight = set()
        highlight_elapsed_ms = int((time.time() - highlight_start) * 1000)
        perf_steps["highlight_ms"] = highlight_elapsed_ms
        # ✅ 하이라이트 캐시 히트 추정: 처리 시간이 5ms 이하면 캐시 히트로 간주
        highlight_cache_hit = highlight_elapsed_ms <= 5
        
        st.markdown(highlighted_content, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
        if article.get("url"):
            st.markdown(f"[🔗 기사 원문 보기]({article['url']})")

        # ✅ 성능 측정: 용어 목록 필터링 시간
        terms_filter_start = time.time()
        # ✅ 성능 개선: 하이라이트 처리에서 이미 발견된 용어 재사용 (O(1) 복잡도)
        terms_to_show = []
        cache_key = f"terms_to_show_cache_{article_id}"
        cached_terms = st.session_state.get(cache_key)
        if cached_terms is not None:
            terms_to_show = cached_terms
            perf_steps["terms_filter_ms"] = 0  # 캐시 히트
        elif matched_terms_from_highlight:
            # ✅ 성능 개선: 하이라이트 처리에서 이미 발견된 용어 사용 (추가 필터링 불필요)
            terms_to_show = list(matched_terms_from_highlight)
            if article_id:
                st.session_state[cache_key] = terms_to_show
            perf_steps["terms_filter_ms"] = int((time.time() - terms_filter_start) * 1000)
        else:
            # Fallback: 하이라이트에서 용어를 찾지 못한 경우 (드문 경우)
            content_lower = content.lower()
            highlight_terms_set = st.session_state.get("rag_terms_for_highlight")
            if highlight_terms_set:
                terms_set = set()
                for term in highlight_terms_set:
                    if term and term.lower() in content_lower:
                        terms_set.add(term)
                terms_to_show = list(terms_set)
            elif st.session_state.get("rag_initialized", False):
                try:
                    metadata_map = st.session_state.get("rag_metadata_by_term")
                    if metadata_map:
                        terms_set = set()
                        seen_terms = set()
                        for term_key, metadata in metadata_map.items():
                            original_term = metadata.get('term', '').strip()
                            if original_term and original_term not in seen_terms:
                                seen_terms.add(original_term)
                                if original_term.lower() in content_lower:
                                    terms_set.add(original_term)
                        terms_to_show = list(terms_set)
                    else:
                        collection = st.session_state.rag_collection
                        all_data = collection.get()
                        if all_data and all_data['metadatas']:
                            terms_set = set()
                            for metadata in all_data['metadatas']:
                                term = metadata.get('term', '').strip()
                                if term and term.lower() in content_lower:
                                    terms_set.add(term)
                            terms_to_show = list(terms_set)
                except Exception as e:
                    terms_to_show = [t for t in st.session_state.financial_terms.keys() if t.lower() in content_lower]
            else:
                terms_to_show = [t for t in st.session_state.financial_terms.keys() if t.lower() in content_lower]
            
            if article_id:
                st.session_state[cache_key] = terms_to_show
            perf_steps["terms_filter_ms"] = int((time.time() - terms_filter_start) * 1000)
        
        perf_steps["terms_count"] = len(terms_to_show)

        # ✅ 성능 측정: 전체 렌더링 시간
        total_latency_ms = int((time.time() - t0) * 1000)
        perf_steps["total_ms"] = total_latency_ms
        perf_steps["content_length"] = len(content)
        perf_steps["highlighted_length"] = len(highlighted_content)
        
        # 렌더 완료 → 상세 성능 정보와 함께 로그 기록
        log_event(
            "news_detail_open",
            news_id=article_id,
            surface="detail",
            title=article.get("title"),
            latency_ms=total_latency_ms,
            note="기사 렌더링 완료",
            payload={
                "article_id": article_id,
                "perf_steps": perf_steps,  # 단계별 성능 정보
                "cache_hit": cached_terms is not None or highlight_cache_hit,  # ✅ 용어 목록 캐시 또는 하이라이트 캐시 히트
                "highlight_cache_hit": highlight_cache_hit,  # 하이라이트 캐시 히트 여부
                "terms_cache_hit": cached_terms is not None,  # 용어 목록 캐시 히트 여부
            }
        )

        # 플래그 설정(중복 기록 방지)
        st.session_state.detail_enter_logged = True
        st.session_state.page_enter_time = datetime.now()

    else:
        # 재렌더 시에는 단순 표시만 (latency 미측정)
        st.markdown("---")
        st.header(article['title'])
        st.caption(f"📅 {article['date']}")
        st.markdown('<div class="article-content">', unsafe_allow_html=True)
        # ✅ 성능 개선: article_id를 전달하여 캐싱 활용 (캐시 히트 시 거의 즉시)
        article_id = article.get("id")
        content = article['content']
        highlighted_content = highlight_terms(content, article_id=str(article_id) if article_id else None)
        st.markdown(highlighted_content, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
        if article.get("url"):
            st.markdown(f"[🔗 기사 원문 보기]({article['url']})")

    # ✅ 성능 개선: is_page_hidden_eval() 호출 최소화 (뒤로가기 버튼 클릭 시에만 체크)
    # 탭 전환 등으로 페이지가 숨겨지면 종료하는 로직은 제거 (필요시에만 활성화)


    # ← 뒤로가기 버튼 : 목록으로
    if st.button("← 뉴스 목록으로 돌아가기"):
        # ✅ 성능 측정: 뒤로가기 처리 시간
        back_start = time.time()
        
        if st.session_state.get("detail_enter_logged"):
            end_view_timer()
            st.session_state.detail_enter_logged = False
        
        log_event(
            "news_detail_back", 
            news_id=article.get("id"), 
            surface="detail",
            payload={
                "back_process_ms": int((time.time() - back_start) * 1000)
            }
        )
        
        st.session_state.selected_article = None
        st.session_state.detail_enter_logged = False
        st.rerun()

    # 용어 설명 UI
    st.info("💡 아래 버튼에서 용어를 선택하면 챗봇이 쉽게 설명해드립니다!")
    st.subheader("🔍 용어 설명 요청")

    # ✅ 성능 개선: 용어 목록은 이미 위에서 계산됨 (재렌더 시에는 캐시에서 가져오기)
    if not st.session_state.get("detail_enter_logged"):
        # 첫 렌더링 시에는 이미 terms_to_show가 계산됨
        pass
    else:
        # 재렌더 시에는 캐시에서 가져오기
        article_id = article.get("id")
        cache_key = f"terms_to_show_cache_{article_id}"
        cached_terms = st.session_state.get(cache_key)
        if cached_terms is not None:
            terms_to_show = cached_terms
        else:
            # 캐시가 없으면 다시 계산 (드문 경우)
            content_lower = article['content'].lower()
            if st.session_state.get("rag_initialized", False):
                try:
                    metadata_map = st.session_state.get("rag_metadata_by_term")
                    if metadata_map:
                        terms_set = set()
                        for term_key, metadata in metadata_map.items():
                            original_term = metadata.get('term', '').strip()
                            if original_term and original_term.lower() in content_lower:
                                terms_set.add(original_term)
                        terms_to_show = list(terms_set)
                    else:
                        collection = st.session_state.rag_collection
                        all_data = collection.get()
                        if all_data and all_data['metadatas']:
                            terms_set = set()
                            for metadata in all_data['metadatas']:
                                term = metadata.get('term', '').strip()
                                if term and term.lower() in content_lower:
                                    terms_set.add(term)
                            terms_to_show = list(terms_set)
                except Exception as e:
                    terms_to_show = [t for t in st.session_state.financial_terms.keys() if t.lower() in content_lower]
            else:
                terms_to_show = [t for t in st.session_state.financial_terms.keys() if t.lower() in content_lower]
            
            if article_id:
                st.session_state[cache_key] = terms_to_show

    # 버튼 렌더링 (3열 그리드)
    for i in range(0, len(terms_to_show), 3):
        cols = st.columns(3)
        for j, col in enumerate(cols):
            if i + j < len(terms_to_show):
                term = terms_to_show[i + j]
                with col:
                    if st.button(f"📌 {term}", key=f"term_btn_{term}", use_container_width=True):
                        # ✅ 성능 측정: 용어 클릭 전체 처리 시간
                        term_click_start = time.time()
                        st.session_state.term_click_count += 1

                        user_question = f"'{term}' 용어를 설명해주세요"
                        # 대화 히스토리 (사용자 발화 1회만 기록)
                        st.session_state.chat_history.append({"role": "user", "content": user_question})

                        # ✅ 성능 측정: 설명 생성 시간
                        explanation_start = time.time()
                        explanation, rag_info = explain_term(term, st.session_state.chat_history, return_rag_info=True)
                        explanation_latency_ms = int((time.time() - explanation_start) * 1000)
                        
                        # ✅ 성능 측정: 전체 처리 시간
                        total_latency_ms = int((time.time() - term_click_start) * 1000)

                        # 클릭(자동 질문 포함) 이벤트 로그 (상세 성능 정보 포함)
                        log_event(
                            "glossary_click",
                            term=term,
                            news_id=article.get("id"),
                            source="news_highlight",
                            surface="detail",
                            message=user_question,
                            click_count=st.session_state.term_click_count,
                            latency_ms=total_latency_ms,  # 전체 처리 시간
                            payload={
                                "term": term,
                                "news_id": article.get("id"),
                                "perf_steps": {
                                    "explanation_ms": explanation_latency_ms,  # 설명 생성 시간
                                    "total_ms": total_latency_ms,  # 전체 처리 시간
                                    "answer_length": len(explanation),  # 답변 길이
                                },
                                "rag_info": rag_info,  # RAG 정보
                            }
                        )

                        # 답변 히스토리 + 답변 이벤트 로그
                        st.session_state.chat_history.append({"role": "assistant", "content": explanation})
                        log_event(
                            "glossary_answer",
                            term=term,
                            source="news_highlight",
                            surface="detail",
                            message=user_question,
                            answer_len=len(explanation),
                            latency_ms=explanation_latency_ms,  # 설명 생성 시간
                            via="rag",
                            rag_info=rag_info,
                            response=explanation,
                            payload={
                                "term": term,
                                "news_id": article.get("id"),
                                "perf_steps": {
                                    "explanation_ms": explanation_latency_ms,
                                    "total_ms": total_latency_ms,
                                    "answer_length": len(explanation),
                                },
                                "rag_info": rag_info,
                            }
                        )

                        st.rerun()

    st.caption("💡 Tip: 버튼을 누르면 오른쪽 챗봇에서 상세 설명을 볼 수 있어요!")
