
import re
import time
import textwrap
import streamlit as st
from streamlit.components.v1 import html as st_html
from core.logger import log_event
from rag.glossary import explain_term, search_terms_by_rag
from core.utils import llm_chat, extract_urls_from_text, detect_article_search_request, search_related_article
from data.news import parse_news_from_url, search_news_from_supabase
from persona.persona import albwoong_persona_reply


# 일반 질문에 대한 LLM 응답
# ─────────────────────────────────────────────────────────────
# 🎭 Persona: 알부엉
# 특징: 신문을 품에 안고 다니는 금융 전문가 부엉이
# 성격: 차분·분석적 + 초보자 친화 설명, 어려운 용어를 쉽게
# 키워드: #지혜의상징 #뉴스요약러 #금융멘토
# 말투 가이드: 친근한 튜터형, 과장 금지, 핵심→예시→주의 순
# 오프닝 멘트(랜덤 1줄 사용)
# ─────────────────────────────────────────────────────────────

# ── NEW: 알부엉 인사말 후보 리스트 ─────────────────────────
ALBWOONG_OPENERS = [
    "안녕! 난 알부엉. '알다'와 '부엉이'가 만나 태어난, 너의 금융 친구야!",
    "오늘도 신문을 품에 안고 왔어. 궁금한 경제 이야기를 함께 알아보자!",
    "안녕! 뉴스 속 어려운 말, 내가 쉽게 풀어줄게.",
    "나는 알부엉! 숫자보다 사람을 먼저 생각하는 금융멘토야.",
    "좋은 아침이야! 오늘도 이자보다 이로운 지식을 전하러 왔어.",
    "매일 쏟아지는 뉴스, 핵심만 쏙 정리해줄게.",
    "오늘의 경제 뉴스 요약, 알부엉이 빠르게 브리핑해줄게!",
    "신문에서 본 어려운 단어? 같이 풀어보자!",
    "기사 속 단어가 낯설었지? 내가 쉽게 설명해줄게!",
    "오늘도 신문 한 장 품에 안고, 세상의 돈 이야기를 전하러 왔어.",
    "처음 듣는 말이라도 걱정 마! 내가 쉽게 알려줄게.",
    "복잡한 경제 얘기? 한 번에 정리해줄게!",
    "경제가 어렵게 느껴진다고? 알부엉이랑 함께면 괜찮아!",
    "나는 어려운 말을 일상으로 바꾸는 걸 좋아해.",
    "이게 무슨 뜻이지? 싶을 때, 바로 나를 불러!",
    "커피 한 잔 하면서 천천히 들어볼래?",
    "요즘 뉴스에 자주 나오던 이 단어어, 궁금했지? 내가 알려줄게!",
    "오늘도 지식 한 스푼, 알부엉과 함께 채워보자!",
    "모르는 걸 물어보는 게 진짜 지혜야. 시작해볼까?"
]

def render(terms: dict[str, dict], use_openai: bool=False):
    st.markdown("### 💬 금융 용어 도우미")
    st.markdown("---")

    # ── NEW: 세션 상태 초기화 ─────────────────────────
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "intro_shown" not in st.session_state:
        st.session_state.intro_shown = False

    # ── NEW: 첫 진입 시(또는 리셋 후) 알부엉 인사말 1회 자동 출력 ──
    if not st.session_state.intro_shown and len(st.session_state.chat_history) == 0:
        import random
        opener = random.choice(ALBWOONG_OPENERS)
        # 이모지는 한 번만, 톤은 짧고 친근하게
        st.session_state.chat_history.append({
            "role": "assistant",
            "content": f"🦉 {opener}"
        })
        st.session_state.intro_shown = True

    # 대화 히스토리 렌더(기존 그대로)
    messages_html = []
    article_buttons = []  # 기사 버튼들을 별도로 저장
    
    for idx, message in enumerate(st.session_state.chat_history):
        role = message["role"]
        role_class = "user" if role == "user" else "assistant"
        content_html = (
            message["content"]
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br>")
        )
        avatar_html = ""
        if role_class == "assistant":
            avatar_html = '<div class="chat-avatar chat-avatar--assistant"></div>'

        messages_html.append(
            textwrap.dedent(
                f"""
                <div class="chat-row chat-row--{role_class}">
                  {avatar_html}
                  <div class="chat-bubble chat-bubble--{role_class}">
                    {content_html}
                  </div>
                </div>
                """
            ).strip()
        )
        
        # 기사 목록이 있는 메시지인 경우 버튼 생성
        if role == "assistant" and "articles" in message and message["articles"]:
            article_buttons.append((idx, message["articles"]))

    chat_html = (
        "<div id='chat-scroll-box' class='chat-message-container' "
        "style='max-height:400px; overflow-y:auto; padding-right:8px;'>"
        + "".join(messages_html)
        + "<div id='chat-scroll-anchor'></div></div>"
    )
    st.markdown(chat_html, unsafe_allow_html=True)
    
    # 기사 버튼들 표시 (가장 최근 검색 결과만 표시)
    if article_buttons:
        # 가장 최근 메시지의 기사 버튼만 표시
        msg_idx, articles = article_buttons[-1]
        
        st.markdown("---")
        st.caption("📰 찾은 기사:")
        for article in articles[:5]:  # 최대 5개만 표시
            article_title = article.get("title", "제목 없음")
            article_id = article.get("id")
            
            if st.button(
                f"📄 {article_title[:50]}{'...' if len(article_title) > 50 else ''}",
                key=f"article_btn_{msg_idx}_{article_id}",
                use_container_width=True
            ):
                # 기사 선택 및 상세 화면으로 이동
                st.session_state.selected_article = article
                st.session_state.detail_enter_logged = False
                
                # 검색 키워드 정보 추출 (해당 메시지에서)
                search_keyword = None
                if msg_idx < len(st.session_state.chat_history):
                    message = st.session_state.chat_history[msg_idx]
                    search_keyword = message.get("search_keyword")
                
                # 로그 기록
                log_event(
                    "news_selected_from_chat",
                    news_id=article_id,
                    surface="sidebar",
                    payload={
                        "title": article_title,
                        "source": "chat_button",
                        "search_keyword": search_keyword,  # 검색 키워드 정보
                        "url": article.get("url"),  # 기사 URL
                        "article_date": article.get("date")  # 기사 날짜
                    }
                )
                
                st.rerun()
    st_html(
        """
        <script>
        const anchor = window.parent.document.getElementById('chat-scroll-anchor');
        if (anchor) {
            setTimeout(() => {
                anchor.scrollIntoView({behavior: "smooth", block: "end"});
            }, 50);
        }
        </script>
        """,
        height=0,
    )

    # 입력창
    user_input = st.chat_input("궁금한 금융 용어를 입력하세요...")
    if user_input:

        t0 = time.time()
        log_event("chat_question", message=user_input, source="chat", surface="sidebar")
        st.session_state.chat_history.append({"role": "user", "content": user_input})

        # 🔗 URL 감지 및 처리 (최우선)
        urls = extract_urls_from_text(user_input)
        if urls:
            # 첫 번째 URL 사용
            url = urls[0]
            with st.spinner("🔄 뉴스 기사를 가져오는 중..."):
                try:
                    article = parse_news_from_url(url)
                    
                    if article:
                        # 성공 메시지와 함께 버튼 표시
                        explanation = f"✅ 요청한 뉴스를 불러왔어. 아래 버튼을 클릭해줘! 🦉"
                        
                        # 챗 히스토리에 메시지와 기사 저장 (버튼 표시용)
                        st.session_state.chat_history.append({
                            "role": "assistant",
                            "content": explanation,
                            "articles": [article]  # 단일 기사를 리스트로 저장
                        })
                        
                        # 로그 기록
                        log_event(
                            "news_url_added_from_chat",
                            news_id=article.get("id"),
                            surface="sidebar",
                            message=user_input,  # 사용자 입력 메시지 (URL 포함)
                            payload={
                                "url": url,
                                "title": article.get("title"),
                                "source": "chat",
                                "url_parsed": True
                            }
                        )
                        
                        st.rerun()
                    else:
                        explanation = "❌ 기사를 가져올 수 없었어요. URL을 확인해주세요. 🦉"
                        st.session_state.chat_history.append({"role": "assistant", "content": explanation})
                        log_event(
                            "news_url_add_error",
                            surface="sidebar",
                            message=user_input,  # 사용자 입력 메시지
                            payload={
                                "url": url,
                                "error": "파싱 실패"
                            }
                        )
                        st.rerun()
                        
                except Exception as e:
                    explanation = f"❌ 오류가 발생했어요: {str(e)} 🦉"
                    st.session_state.chat_history.append({"role": "assistant", "content": explanation})
                    log_event(
                        "news_url_add_error",
                        surface="sidebar",
                        message=user_input,  # 사용자 입력 메시지
                        payload={
                            "url": url,
                            "error": str(e)
                        }
                    )
                    st.rerun()
            
            # URL 처리 완료 후 함수 종료
            return

        # 📰 기사 찾기 요청 감지 및 처리
        is_search_request, keyword = detect_article_search_request(user_input)
        if is_search_request and keyword:
            with st.spinner(f"🔍 '{keyword}' 관련 뉴스를 찾는 중..."):
                # 1단계: Supabase에서 관련 뉴스 검색
                supabase_articles = search_news_from_supabase(keyword, limit=5)
                
                # 2단계: 현재 뉴스 리스트에서도 검색 (이미 로드된 뉴스 중에서)
                articles = st.session_state.get("news_articles", [])
                matched_article = search_related_article(articles, keyword)
                
                # 3단계: 모든 결과 합치기 (Supabase 결과 + 현재 리스트 결과)
                all_found_articles = []
                seen_ids = set()
                
                # 현재 리스트에서 찾은 기사 추가
                if matched_article:
                    article_id = matched_article.get("id")
                    if article_id and article_id not in seen_ids:
                        all_found_articles.append(matched_article)
                        seen_ids.add(article_id)
                
                # Supabase에서 찾은 기사 추가
                for article in supabase_articles:
                    article_id = article.get("id")
                    if article_id and article_id not in seen_ids:
                        all_found_articles.append(article)
                        seen_ids.add(article_id)
                
                if all_found_articles:
                    # 찾은 기사들을 챗 히스토리에 특별한 형식으로 저장
                    article_count = len(all_found_articles)
                    explanation = f"✅ '{keyword}' 관련 최신 기사를 {article_count}개 찾았어! 아래 버튼에서 선택해줘!🦉"
                    
                    # 챗 히스토리에 메시지와 기사 목록 저장 (검색 키워드도 함께 저장)
                    st.session_state.chat_history.append({
                        "role": "assistant",
                        "content": explanation,
                        "articles": all_found_articles,  # 특별한 필드로 기사 목록 저장
                        "search_keyword": keyword  # 검색 키워드 저장 (기사 선택 시 추적용)
                    })
                    
                    # 검색된 기사 ID 목록 추출
                    found_article_ids = [article.get("id") for article in all_found_articles if article.get("id")]
                    
                    # 로그 기록
                    log_event(
                        "news_search_from_chat",
                        surface="sidebar",
                        message=user_input,  # 사용자 입력 메시지
                        payload={
                            "keyword": keyword,
                            "found_count": article_count,
                            "source": "chat",
                            "supabase_results": len(supabase_articles),
                            "local_results": 1 if matched_article else 0,
                            "article_ids": found_article_ids  # 검색된 기사 ID 목록
                        }
                    )
                    
                    st.rerun()
                else:
                    # 기사를 찾지 못함
                    explanation = f"❌ '{keyword}'와 관련된 기사를 찾지 못했어요. 다른 키워드로 시도해보세요. 🦉"
                    st.session_state.chat_history.append({"role": "assistant", "content": explanation})
                    log_event(
                        "news_search_failed",
                        surface="sidebar",
                        message=user_input,  # 사용자 입력 메시지
                        payload={
                            "keyword": keyword,
                            "source": "chat"
                        }
                    )
                    st.rerun()
            
            # 기사 찾기 처리 완료 후 함수 종료
            return

        explanation = None
        matched_term = None
        is_financial_question = False  # 금융 용어 질문인지 판단
        api_info = None  # OpenAI API 정보 (초기화)

        # 1) RAG 정확 매칭 우선 (완전 일치 검색)
        if st.session_state.get("rag_initialized", False):
            try:
                collection = st.session_state.get("rag_collection")
                if collection is None:
                    raise ValueError("RAG 컬렉션이 없습니다")
                
                all_data = collection.get()

                if all_data and all_data['metadatas']:
                    # 정확한 용어 매칭 시도 (조사/문장부호 포함)
                    def _term_exact_match(text: str, term: str) -> bool:
                        if not term:
                            return False
                        lookahead = r"(?=($|\s|[?!.,]|[은는이가을를과와로도의]))"
                        pattern = rf"(^|\s){re.escape(term)}{lookahead}"
                        return re.search(pattern, text, re.IGNORECASE) is not None

                    for metadata in all_data['metadatas']:
                        rag_term = metadata.get('term', '').strip()

                        if _term_exact_match(user_input, rag_term):
                            matched_term = rag_term
                            is_financial_question = True
                            break

                    # 정확 매칭 실패 시 벡터 검색으로 유사 용어 찾기 (단, 금융 관련 키워드가 있을 때만)
                    if not matched_term:
                        # 금융 관련 키워드 체크 (확장 가능)
                        financial_keywords = [
                            '금융', '투자', '주식', '금리', '환율', '배당', '채권', '은행', '예금', '적금',
                            '대출', '이자', '경제', '시장', '주가', '코스피', '원화', '달러', '부동산',
                            '세금', '보험', '펀드', '자산', '재무', '통화', '정책', '용어', '설명', '뭐야', '무엇'
                        ]

                        # 사용자 입력에 금융 키워드가 포함되어 있는지 확인
                        has_financial_keyword = any(kw in user_input for kw in financial_keywords)

                        if has_financial_keyword:
                            RAG_SIM_THRESHOLD = 0.38  # 코사인 거리(0~2, 낮을수록 유사)
                            rag_results = search_terms_by_rag(user_input, top_k=1)
                            if rag_results:
                                candidate = rag_results[0]
                                candidate_term = (candidate.get('term') or '').strip()
                                distance = candidate.get('_distance')

                                if candidate_term:
                                    # distance가 None이면 임시로 허용, 값이 있으면 임계값 비교
                                    if distance is None or distance <= RAG_SIM_THRESHOLD:
                                        matched_term = candidate_term
                                        is_financial_question = True
                                    else:
                                        # 거리가 높으면 금융 질문이 아니라고 판단
                                        matched_term = None
                                        is_financial_question = False

                    if matched_term:
                        # RAG에서 찾은 용어로 설명 생성 (RAG 정보 포함)
                        explanation, rag_info = explain_term(
                            matched_term,
                            st.session_state.chat_history,
                            return_rag_info=True,
                        )
                        log_event(
                            "glossary_answer",
                            term=matched_term,
                            source="chat_rag",
                            surface="sidebar",
                            message=user_input,  # ✅ 사용자 질문
                            answer_len=len(explanation),
                            via="rag",
                            rag_info=rag_info,  # RAG 정보 전달
                            response=explanation,  # 시스템 응답(설명)
                            payload={"query": user_input}
                        )
            except Exception as e:
                st.warning(f"⚠️ RAG 검색 중 오류 발생: {e}")

        # 2) RAG 실패 시: 하드코딩된 사전에서 정확한 매칭 시도
        if explanation is None and not is_financial_question:
            for term_key in terms.keys():
                lookahead = r"(?=($|\s|[?!.,]|[은는이가을를과와로도의]))"
                pattern = rf"(^|\s){re.escape(term_key)}{lookahead}"
                if re.search(pattern, user_input, re.IGNORECASE):
                    explanation, rag_info = explain_term(
                        term_key,
                        st.session_state.chat_history,
                        return_rag_info=True,
                    )
                    is_financial_question = True
                    log_event(
                        "glossary_answer",
                        term=term_key,
                        source="chat",
                        surface="sidebar",
                        message=user_input,  # ✅ 사용자 질문
                        answer_len=len(explanation),
                        via="rag",
                        rag_info=rag_info,  # RAG 정보 전달
                        response=explanation  # 시스템 응답(설명)
                    )
                    break

        # 3) 금융 용어가 아닌 일반 질문: LLM 백업 (use_openai=True일 때만)
        if explanation is None and not is_financial_question:
            if use_openai:
                sys = {
                    "role": "system",
                    "content": (
                        "너는 친근하고 박식한 AI 어시스턴트야. "
                        "사용자의 질문에 정확하고 도움이 되는 답변을 제공해줘. "
                        "금융 관련 질문이 아니어도 최선을 다해 답변하되, "
                        "확실하지 않은 내용은 정직하게 모른다고 말해줘."
                    )
                }
                usr = {
                    "role": "user",
                    "content": user_input
                }
                try:
                    explanation, api_info = llm_chat([sys, usr], temperature=0.7, max_tokens=500, return_metadata=True)
                except Exception as e:
                    explanation = albwoong_persona_reply(user_input, style_opt="짧게")
                    api_info = {
                        "error": {
                            "type": type(e).__name__,
                            "message": str(e)
                        }
                    }
            else:
                explanation = albwoong_persona_reply(user_input, style_opt="짧게")

        # 로깅 + 응답 축적
        latency = int((time.time() - t0) * 1000)
        
        # glossary_answer 이벤트가 발생한 경우 chat_response는 호출하지 않음 (중복 방지)
        # glossary_answer에서 이미 dialogue가 생성되었으므로 chat_response는 건너뜀
        # matched_term이 있으면 이미 glossary_answer가 호출되었음을 의미
        if not is_financial_question and not matched_term:
            # 일반 질문의 경우에만 chat_response 이벤트 발생
            log_kwargs = {
                "source": "chat",
                "surface": "sidebar",
                "message": user_input,            # ✅ 사용자 질문
                "answer_len": len(explanation),  # ✅ 응답 길이
                "latency_ms": latency,            # ✅ 응답 지연(ms)
                "response": explanation           # ✅ 시스템 응답
            }
            
            # OpenAI API 정보 추가 (있는 경우)
            if api_info:
                log_kwargs["api_info"] = api_info
                log_kwargs["via"] = "openai"
            
            log_event("chat_response", **log_kwargs)
        
        st.session_state.chat_history.append({"role": "assistant", "content": explanation})
        st.rerun()

    # 대화 초기화(변경)
    if st.button("🔄 대화 초기화"):
        log_event("chat_reset", surface="sidebar")
        st.session_state.chat_history = []
        # ── NEW: 다음 렌더에서 다시 인사말 나오도록 ──
        st.session_state.intro_shown = False
        st.rerun()
