
import re
import time
import textwrap
import os
import base64
import streamlit as st
from streamlit.components.v1 import html as st_html
from concurrent.futures import ThreadPoolExecutor, as_completed
from core.logger import log_event
from core.performance import get_performance_tracker
from rag.glossary import explain_term, search_terms_by_rag
from core.utils import llm_chat, extract_urls_from_text, detect_article_search_request, search_related_article
from data.news import parse_news_from_url, search_news_from_supabase
from persona.persona import albwoong_persona_reply, generate_structured_persona_reply


def get_albwoong_avatar_base64():
    """알부엉 이미지를 Base64로 인코딩하여 반환"""
    possible_paths = [
        "assets/albwoong.png",
        "assets/albueong.png",
        "assets/albuong.png",
        "assets/albwoong.jpg",
        "assets/albwoong.svg",
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            try:
                with open(path, "rb") as img_file:
                    encoded = base64.b64encode(img_file.read()).decode()
                    ext = path.split(".")[-1].lower()
                    if ext == "svg":
                        mime_type = "image/svg+xml"
                    elif ext == "png":
                        mime_type = "image/png"
                    elif ext == "jpg" or ext == "jpeg":
                        mime_type = "image/jpeg"
                    else:
                        mime_type = "image/png"
                    return f"data:{mime_type};base64,{encoded}"
            except Exception:
                continue
    
    return ""


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

def render(terms: dict[str, dict], use_openai: bool = False, enable_optimization: bool = True):
    """
    챗봇 패널 렌더링
    
    Args:
        terms: 금융 용어 사전 (dict[str, dict])
        use_openai: OpenAI 사용 여부 (기본값: False)
        enable_optimization: 최적화 기능 활성화 (스트리밍, 캐싱, 병렬 처리 등)
    
    Features:
        - 플로팅 챗봇 UI (우측 하단 고정, 400px × 600px)
        - 자동 스크롤 기능
        - RAG 기반 응답 생성
        - 질문 유형 자동 판단
        - 구조화된 답변 형식
        - 성능 측정 및 분석
        - 스트리밍 응답 수집 (최적화 활성화 시, 수집 후 표시)
    """
    st.markdown("### 💬 금융 용어 도우미")
    
    # 입력창 크기 조정을 위한 CSS
    st.markdown("""
    <style>
    /* 입력창 크기 확대 */
    div[data-testid="stChatInputContainer"] {
        min-height: 60px !important;
    }
    div[data-testid="stChatInputContainer"] textarea {
        font-size: 16px !important;
        padding: 12px 16px !important;
        min-height: 60px !important;
        line-height: 1.5 !important;
    }
    div[data-testid="stChatInputContainer"] button {
        height: 60px !important;
        min-width: 60px !important;
    }
    
    </style>
    """, unsafe_allow_html=True)
    
    # 성능 리포트 표시 (최적화 활성화 시)
    if enable_optimization:
        with st.expander("📊 성능 분석", expanded=False):
            from core.performance import render_performance_report
            render_performance_report()
    
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
    article_buttons = []  # 기사 버튼을 별도로 저장
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
            avatar_img_src = get_albwoong_avatar_base64()
            if avatar_img_src:
                avatar_html = f'''<div class="chat-avatar chat-avatar--assistant"><img src="{avatar_img_src}" alt="알부엉" style="width: 100%; height: 100%; object-fit: cover; border-radius: 50%;"></div>'''
            else:
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
        "style='overflow-y:auto; padding-right:8px; flex: 1; min-height: 0;'>"
        + "".join(messages_html)
        + "<div id='chat-scroll-anchor'></div></div>"
    )
    st.markdown(chat_html, unsafe_allow_html=True)
    
    # 기사 버튼 표시 (가장 최근 검색 결과만 표시)
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
                key=f"article_btn_{article_id}_{msg_idx}",
                use_container_width=True
            ):
                st.session_state.selected_article = article
                st.rerun()
    
    st_html(
        """
        <script>
        (function() {
            // 챗봇 컨테이너 높이를 사이드바에 맞게 조정
            function adjustChatHeight() {
                const chatBox = window.parent.document.getElementById('chat-scroll-box');
                if (!chatBox) return;
                
                // 뷰포트 높이 계산
                const vh = window.parent.innerHeight;
                
                // 제목 영역 높이 측정 (실제 DOM에서)
                let titleHeight = 0;
                const chatPanel = chatBox.closest('[data-testid="column"]') || chatBox.parentElement;
                if (chatPanel) {
                    // 제목과 구분선 찾기
                    const titleElements = chatPanel.querySelectorAll('h3, hr');
                    titleElements.forEach(el => {
                        if (el !== chatBox && !chatBox.contains(el)) {
                            const rect = el.getBoundingClientRect();
                            if (rect.height > 0) {
                                titleHeight += rect.height + 10; // 마진 포함
                            }
                        }
                    });
                }
                if (titleHeight === 0) titleHeight = 100; // 기본값
                
                // 입력창 영역 높이 측정 (실제 DOM에서)
                let inputHeight = 120; // 기본값
                const chatInput = window.parent.document.querySelector('[data-testid="stChatInput"]');
                if (chatInput) {
                    const inputRect = chatInput.getBoundingClientRect();
                    inputHeight = inputRect.height + 40; // 입력창 높이 + 여유공간
                }
                
                // 초기화 버튼 높이 고려
                const resetButton = window.parent.document.querySelector('button');
                if (resetButton && resetButton.textContent.includes('초기화')) {
                    const buttonRect = resetButton.getBoundingClientRect();
                    inputHeight += buttonRect.height + 10;
                }
                
                // 플로팅 챗봇 높이에 맞게 계산 (600px 전체 높이에서 제목과 입력창 높이를 뺀 값)
                const totalHeight = 600; // 플로팅 챗봇 전체 높이
                const calculatedHeight = totalHeight - titleHeight - inputHeight - 20; // 20px 여유공간
                
                // 최소 높이 보장
                const finalHeight = Math.max(300, calculatedHeight);
                chatBox.style.height = finalHeight + 'px';
                chatBox.style.maxHeight = finalHeight + 'px';
                chatBox.style.overflowY = 'auto';
                chatBox.style.padding = '10px';
            }
            
            // 자동 스크롤을 맨 아래로 (챗봇 내부 스크롤만, 페이지 스크롤은 영향 없음)
            function scrollToBottom(smooth = true) {
                const chatBox = window.parent.document.getElementById('chat-scroll-box');
                if (chatBox) {
                    // 부드러운 스크롤 애니메이션 사용 (느린 속도)
                    if (smooth) {
                        const targetScroll = chatBox.scrollHeight;
                        const startScroll = chatBox.scrollTop;
                        const distance = targetScroll - startScroll;
                        const duration = 400; // 애니메이션 지속 시간 (ms) - 더 느리게
                        const startTime = performance.now();
                        
                        function animateScroll(currentTime) {
                            const elapsed = currentTime - startTime;
                            const progress = Math.min(elapsed / duration, 1);
                            
                            // easeOutCubic 함수로 부드러운 감속
                            const easeOutCubic = 1 - Math.pow(1 - progress, 3);
                            const currentScroll = startScroll + (distance * easeOutCubic);
                            
                            chatBox.scrollTop = currentScroll;
                            
                            if (progress < 1) {
                                requestAnimationFrame(animateScroll);
                            } else {
                                // 애니메이션 완료 후 정확한 위치로 이동
                                chatBox.scrollTop = targetScroll;
                            }
                        }
                        
                        requestAnimationFrame(animateScroll);
                    } else {
                        // 즉시 스크롤 (초기 로드 시)
                        chatBox.scrollTop = chatBox.scrollHeight;
                    }
                }
            }
            
            // 챗봇 패널 컬럼 설정 (오른쪽 사이드바 형태로 고정)
            function setupChatPanelLayout() {
                const chatBox = window.parent.document.getElementById('chat-scroll-box');
                if (!chatBox) return;
                
                // 챗봇 패널의 컬럼 찾기
                let chatColumn = chatBox.closest('[data-testid="column"]');
                
                // Streamlit 구조에 따라 여러 단계로 찾기
                if (!chatColumn) {
                    let parent = chatBox.parentElement;
                    let depth = 0;
                    while (parent && depth < 10) {
                        if (parent.hasAttribute && parent.hasAttribute('data-testid')) {
                            const testId = parent.getAttribute('data-testid');
                            if (testId === 'column') {
                                chatColumn = parent;
                                break;
                            }
                        }
                        parent = parent.parentElement;
                        depth++;
                    }
                }
                
                if (chatColumn) {
                    // 우측 하단 플로팅 챗봇 형태로 고정 (position: fixed 사용)
                    chatColumn.style.position = 'fixed'; // 요소를 뷰포트에 고정
                    chatColumn.style.bottom = '20px';     // 화면 하단에서 20px 위로
                    chatColumn.style.right = '20px';      // 화면 오른쪽에서 20px 왼쪽으로
                    chatColumn.style.zIndex = '1000';     // 다른 요소들 위에 표시되도록 설정
                    chatColumn.style.width = '400px';
                    chatColumn.style.height = '600px';
                    chatColumn.style.background = '#ffffff';
                    chatColumn.style.borderRadius = '10px';
                    chatColumn.style.boxShadow = '0 4px 12px rgba(0, 0, 0, 0.15)';
                    chatColumn.style.display = 'flex';
                    chatColumn.style.flexDirection = 'column';
                    chatColumn.style.padding = '0';
                    chatColumn.style.boxSizing = 'border-box';
                    chatColumn.style.overflow = 'hidden';
                }
            }
            
            // 초기 조정 및 스크롤
            setTimeout(() => {
                setupChatPanelLayout();
                adjustChatHeight();
                scrollToBottom();
            }, 100);
            
            // 윈도우 리사이즈 시 재조정
            window.parent.addEventListener('resize', () => {
                setTimeout(() => {
                    setupChatPanelLayout();
                    adjustChatHeight();
                }, 100);
            });
            
            // 사이드바는 고정이므로 스크롤 이벤트는 필요 없음
            
            // 새 메시지가 추가되거나 텍스트가 변경될 때마다 자동 스크롤 (MutationObserver 사용)
            const chatBox = window.parent.document.getElementById('chat-scroll-box');
            if (chatBox) {
                let scrollTimeout = null;
                const observer = new MutationObserver((mutations) => {
                    // 내용이 변경되었을 때만 스크롤
                    let shouldScroll = false;
                    mutations.forEach(mutation => {
                        // 새 노드가 추가되거나 텍스트 내용이 변경된 경우
                        if (mutation.type === 'childList' && mutation.addedNodes.length > 0) {
                            shouldScroll = true;
                        } else if (mutation.type === 'characterData') {
                            // 텍스트가 실시간으로 추가되는 경우 (스트리밍 응답)
                            shouldScroll = true;
                        }
                    });
                    if (shouldScroll) {
                        // 디바운싱: 연속된 변경을 하나로 묶어서 스크롤 (성능 최적화)
                        if (scrollTimeout) {
                            clearTimeout(scrollTimeout);
                        }
                        scrollTimeout = setTimeout(() => {
                            scrollToBottom(true); // 부드러운 스크롤 애니메이션 (느린 속도)
                        }, 50); // 50ms 지연으로 더 부드러운 스크롤
                    }
                });
                
                observer.observe(chatBox, {
                    childList: true,
                    subtree: true,
                    characterData: true,
                    characterDataOldValue: true // 텍스트 변경 추적
                });
            }
            
            // 페이지 로드 후 주기적으로 스크롤 확인 (새 메시지 추가 대응)
            // 스트리밍 응답 시 실시간 스크롤을 위해 간격을 더 짧게 설정
            let lastScrollHeight = 0;
            function checkAndScroll() {
                const chatBox = window.parent.document.getElementById('chat-scroll-box');
                if (chatBox) {
                    const currentScrollHeight = chatBox.scrollHeight;
                    if (currentScrollHeight !== lastScrollHeight) {
                        lastScrollHeight = currentScrollHeight;
                        scrollToBottom(true); // 부드러운 스크롤 애니메이션
                    }
                }
            }
            
            // 주기적으로 확인 (스트리밍 응답 대응을 위해 간격을 150ms로 설정)
            setInterval(checkAndScroll, 150);
            
            // 초기 스크롤 (즉시 스크롤, 애니메이션 없음)
            setTimeout(() => scrollToBottom(false), 200);
        })();
        </script>
        """,
        height=0,
    )

    # ⚠️ 중요: 입력창 플레이스홀더에 URL/기사 기능 안내 포함 - 절대 삭제하지 말 것!
    # 입력창 (URL/기사 검색 기능 포함)
    user_input = st.chat_input("궁금한 금융 용어, URL, 또는 '~에 대해 기사 보여줘'를 입력하세요...")
    if user_input:
        # 성능 측정 시작
        tracker = get_performance_tracker()
        profile = tracker.start_profile(user_input, optimization_enabled=enable_optimization)
        
        t0 = time.time()
        log_event("chat_question", message=user_input, source="chat", surface="sidebar")
        st.session_state.chat_history.append({"role": "user", "content": user_input})

        explanation = None
        matched_term = None
        is_financial_question = False  # 금융 용어 질문인지 판단
        api_info = None  # OpenAI API 정보 (초기화)

        # ⚠️ 중요: URL/기사 기능 - 절대 삭제하지 말 것!
        # 0) URL 감지 및 처리 (최우선)
        urls = extract_urls_from_text(user_input)
        if urls:
            # 첫 번째 URL 사용
            url = urls[0]
            with st.spinner("오늘의 경제 뉴스를 가져오는 중..."):
                try:
                    article = parse_news_from_url(url)
                    
                    if article:
                        # 성공 메시지와 함께 버튼 표시
                        explanation = "✅ 요청한 기사를 불러왔어. 아래 버튼을 클릭해줘! 📰"
                        
                        # 채팅 메시지에 기사 저장 (버튼 표시용)
                        st.session_state.chat_history.append({
                            "role": "assistant",
                            "content": explanation,
                            "articles": [article]  # 단일 기사를 리스트로 저장
                        })
                        
                        # 로그 기록
                        log_event(
                            "news_url_added_from_chat",
                            news_id=article.get("id"),
                            source="chat",
                            surface="sidebar",
                            message=user_input,
                            url=url
                        )
                        
                        # 세션 상태에 선택된 기사 저장
                        st.session_state.selected_article = article
                        st.rerun()
                    else:
                        error_msg = "기사를 가져올 수 없었어. URL을 다시 확인해줘!"
                        st.warning(error_msg)
                        st.session_state.chat_history.append({
                            "role": "assistant",
                            "content": error_msg
                        })
                        st.rerun()
                except Exception as e:
                    error_msg = f"기사 파싱 중 오류 발생: {e}"
                    st.error(error_msg)
                    st.session_state.chat_history.append({
                        "role": "assistant",
                        "content": f"죄송해! 기사를 불러오는 중 문제가 생겼어. URL을 다시 확인해줘! (오류: {str(e)})"
                    })
                    log_event(
                        "news_parse_error",
                        source="chat",
                        surface="sidebar",
                        message=user_input,
                        url=url,
                        error=str(e)
                    )
                    st.rerun()
            
            # URL 처리 완료 후 함수 종료
            profile.finish()
            tracker.finish_current_profile()
            return

        # ⚠️ 중요: 기사 찾기 기능 - 절대 삭제하지 말 것!
        # 0-1) 기사 찾기 요청 감지 및 처리
        is_search_request, keyword = detect_article_search_request(user_input)
        if is_search_request and keyword:
            with st.spinner(f"오늘 '{keyword}' 관련 기사를 찾는 중..."):
                # 1단계: Supabase에서 관련 기사 검색
                supabase_articles = search_news_from_supabase(keyword, limit=5)
                
                # 2단계: 현재 기사 리스트에서도 검색 (오늘 로드된 기사 중)
                articles = st.session_state.get("news_articles", [])
                matched_article = search_related_article(articles, keyword)
                
                # 3단계: 모든 결과 병합 (Supabase 결과 + 현재 리스트 결과)
                all_found_articles = []
                seen_ids = set()
                
                # 현재 리스트에서 찾은 기사 추가
                if matched_article:
                    article_id = matched_article.get("id")
                    if article_id and article_id not in seen_ids:
                        all_found_articles.append(matched_article)
                        seen_ids.add(article_id)
                
                # Supabase 결과 추가 (중복 제거)
                for article in supabase_articles:
                    article_id = article.get("id")
                    if article_id and article_id not in seen_ids:
                        all_found_articles.append(article)
                        seen_ids.add(article_id)
                
                if all_found_articles:
                    article_count = len(all_found_articles)
                    explanation = f"✅ '{keyword}' 관련 기사를 {article_count}개 찾았어! 아래에서 선택해줘."
                    st.session_state.chat_history.append({
                        "role": "assistant",
                        "content": explanation,
                        "articles": all_found_articles  # 여러 기사를 리스트로 저장
                    })
                    
                    # 로그 기록
                    log_event(
                        "news_search_from_chat",
                        source="chat",
                        surface="sidebar",
                        message=user_input,
                        payload={
                            "keyword": keyword,
                            "found_count": article_count,
                            "supabase_results": len(supabase_articles)
                        }
                    )
                    
                    st.rerun()
                else:
                    explanation = f"'{keyword}' 관련 기사를 찾지 못했어. 다른 키워드로 검색해볼까?"
                    st.session_state.chat_history.append({
                        "role": "assistant",
                        "content": explanation
                    })
                    st.rerun()
            
            # 기사 검색 처리 완료 후 함수 종료
            profile.finish()
            tracker.finish_current_profile()
            return

        # 1) RAG 정확 매칭 우선 (완전 일치 검색)
        step_rag = profile.add_step("rag_exact_match")
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

                        # ✅ 최적화: 금융 키워드가 없으면 벡터 검색 생략 (조기 종료)
                        if has_financial_keyword:
                            RAG_SIM_THRESHOLD = 0.38  # 코사인 거리(0~2, 낮을수록 유사)
                            rag_results = search_terms_by_rag(user_input, top_k=1, include_distances=True)
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
                        step_rag.finish()
                        step_explanation = profile.add_step("rag_explanation_generation")
                        explanation, rag_info = explain_term(
                            matched_term,
                            st.session_state.chat_history,
                            return_rag_info=True,
                        )
                        step_explanation.finish()
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
        step_rag.finish()

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

        # 3) 금융 용어가 아닌 일반 질문: 질문 패턴에 따라 답변 형식 결정
        if explanation is None and not is_financial_question:
            # 조사 제거 함수
            def remove_particles(term: str) -> str:
                """
                용어에서 조사(가, 이, 을, 를, 은, 는, 와, 과, 로, 의 등) 제거
                
                Args:
                    term: 조사가 포함된 용어 (예: "융자가")
                
                Returns:
                    조사가 제거된 용어 (예: "융자")
                """
                particles = ['가', '이', '을', '를', '은', '는', '와', '과', '로', '의', '에', '에서', '부터', '까지', '서', '으로', '도', '만']
                for particle in particles:
                    if term.endswith(particle):
                        term = term[:-len(particle)]
                        break
                return term
            
            # 사용자 입력에서 용어 추출 시도 (예: "융자가 뭐야?" -> "융자", "융자" -> "융자")
            extracted_term = None
            # 질문 패턴에서 용어 추출 (예: "~가 뭐야?", "~이 뭐야?", "~는?", "~이란?", "~란?")
            patterns = [
                r"([가-힣a-zA-Z0-9]+)(?:가|이|은|는|을|를)?\s*(?:뭐야|무엇|무엇인지|무엇인가|무엇이야|무엇입니까|이야|인가|이란|란|이냐|냐|에 대해|에 대해서)",
                r"(?:뭐야|무엇|무엇인지|무엇인가|무엇이야|무엇입니까|이야|인가|이란|란|이냐|냐|에 대해|에 대해서)\s*([가-힣a-zA-Z0-9]+)",
                r"([가-힣a-zA-Z0-9]+)\s*(?:이란|란|이야|인가|에 대해|에 대해서)",
            ]
            for pattern in patterns:
                match = re.search(pattern, user_input, re.IGNORECASE)
                if match:
                    extracted_term = match.group(1).strip()
                    # 조사 제거
                    extracted_term = remove_particles(extracted_term)
                    # 너무 짧거나 길면 용어로 간주하지 않음 (1~10자)
                    if 1 <= len(extracted_term) <= 10:
                        break
                    else:
                        extracted_term = None
            
            # 질문 패턴으로 추출 실패 시 입력이 짧은 용어 하나인지 확인 (예: "융자", "융자가")
            if not extracted_term:
                # 공백 없이 1~15자의 용어인지 확인 (조사 포함 고려)
                cleaned_input = user_input.strip()
                if re.match(r'^[가-힣a-zA-Z0-9]{1,15}$', cleaned_input):
                    extracted_term = remove_particles(cleaned_input)
                    # 조사 제거 후 너무 짧으면 용어로 간주하지 않음
                    if len(extracted_term) < 1:
                        extracted_term = None
            
            # 질문 패턴 판단: 금융 용어 질문인지 일반 질문인지
            # ⚡ 일관성: 금융 용어 질문만 구조화된 형식, 일반 질문은 자연스러운 대화 형식
            is_term_question = False
            if extracted_term:
                # 금융 관련 키워드 체크
                financial_keywords = [
                    '금융', '투자', '주식', '금리', '환율', '배당', '채권', '은행', '예금', '적금',
                    '대출', '이자', '경제', '시장', '주가', '코스피', '원화', '달러', '부동산',
                    '세금', '보험', '펀드', '자산', '재무', '통화', '정책', '용어', '융자', '관세', '인플레이션',
                    '디플레이션', 'GDP', 'CPI', 'PER', 'PBR', 'ROE', 'ROA', '유동성', '이익률', '수익률', '인수', '합병'
                ]
                # 추출된 용어가 금융 키워드를 포함하는지 또는 질문이 금융 키워드를 포함하는지 확인
                has_financial_keyword = any(kw in user_input for kw in financial_keywords) or any(kw in extracted_term for kw in financial_keywords)
                # 용어 정의 질문 패턴 체크
                is_definition_question = bool(re.search(r'(?:뭐야|무엇|무엇인지|무엇인가|무엇이야|무엇입니까|이야|인가|이란|란|이냐|냐|정의|설명해줘|에 대해|에 대해서)', user_input, re.IGNORECASE))
                
                # 금융 용어 질문 판단: 금융 키워드가 있거나 RAG에서 금융 용어를 찾은 경우만 구조화된 형식
                if has_financial_keyword:
                    # 금융 키워드가 있으면 구조화된 형식
                    is_term_question = True
                elif is_definition_question and st.session_state.get("rag_initialized", False):
                    # 정의 질문 패턴이 있고 RAG에서 금융 용어를 찾은 경우만 구조화된 형식
                    try:
                        rag_results = search_terms_by_rag(extracted_term, top_k=1, include_distances=True)
                        if rag_results:
                            distance = rag_results[0].get('_distance')
                            SIMILARITY_THRESHOLD = 0.5
                            if distance is not None and distance <= SIMILARITY_THRESHOLD:
                                # RAG에서 금융 용어를 찾았으면 구조화된 형식
                                is_term_question = True
                            # RAG에 없거나 거리가 멀면 일반 질문으로 처리 (자연스러운 대화 형식)
                        # RAG 검색 결과가 없으면 일반 질문으로 처리 (자연스러운 대화 형식)
                    except Exception as e:
                        # RAG 검색 실패 시 일반 질문으로 처리 (자연스러운 대화 형식)
                        pass
                # 그 외의 경우는 일반 질문으로 처리 (자연스러운 대화 형식)
            
            # 금융 용어 질문이면 구조화된 형식, 일반 질문이면 자연스러운 대화 형식
            step_llm = profile.add_step("llm_response_generation")
            try:
                if is_term_question:
                    # 금융 용어 질문: 구조화된 형식 (📘 정의, 💡 영향, 🌟 비유)
                    if enable_optimization:
                        # ✅ 최적화: 스트리밍 응답 수집 (수집 후 표시)
                        try:
                            stream_gen = generate_structured_persona_reply(
                                user_input=user_input,
                                term=extracted_term,
                                context=None,
                                temperature=0.2,  # ⚡ 최적화: 0.3 → 0.2 (더 빠른 응답)
                                stream=True
                            )
                            
                            # 스트리밍 응답 수집 (수집 후 표시 방식)
                            # Streamlit의 특성상 실시간 스트리밍은 어려우므로, 수집 후 한 번에 표시
                            full_response = ""
                            for chunk in stream_gen:
                                if isinstance(chunk, tuple) and chunk[0] == "__METADATA__":
                                    # 메타데이터는 무시
                                    continue
                                if chunk:
                                    full_response += str(chunk)
                            
                            explanation = full_response.strip() if full_response else None
                            api_info = {"via": "structured_persona_stream"}
                            
                            # 스트리밍 응답이 비어있으면 일반 모드로 fallback
                            if not explanation or len(full_response) == 0:
                                explanation = generate_structured_persona_reply(
                                    user_input=user_input,
                                    term=extracted_term,
                                    context=None,
                                    temperature=0.2,  # ⚡ 최적화: 0.3 → 0.2
                                    stream=False
                                )
                                api_info = {"via": "structured_persona_fallback"}
                        except Exception as stream_error:
                            # 스트리밍 실패 시 일반 모드로 fallback
                            explanation = generate_structured_persona_reply(
                                user_input=user_input,
                                term=extracted_term,
                                context=None,
                                temperature=0.2,  # ⚡ 최적화: 0.3 → 0.2
                                stream=False
                            )
                            api_info = {"via": "structured_persona_fallback", "stream_error": str(stream_error)}
                    else:
                        explanation = generate_structured_persona_reply(
                            user_input=user_input,
                            term=extracted_term,
                            context=None,
                            temperature=0.2  # ⚡ 최적화: 0.3 → 0.2
                        )
                        api_info = {"via": "structured_persona"}
                else:
                    # 일반 질문: 자연스러운 대화 형식 (자유로운 답변)
                    if enable_optimization:
                        # ✅ 최적화: 스트리밍 응답 수집 (수집 후 표시)
                        try:
                            stream_gen = albwoong_persona_reply(
                                user_input=user_input,
                                term=None,
                                context=None,
                                temperature=0.2,  # ⚡ 최적화: 0.3 → 0.2 (더 빠른 응답)
                                stream=True
                            )
                            
                            # 스트리밍 응답 수집 (수집 후 표시 방식)
                            # Streamlit의 특성상 실시간 스트리밍은 어려우므로, 수집 후 한 번에 표시
                            full_response = ""
                            for chunk in stream_gen:
                                if isinstance(chunk, tuple) and chunk[0] == "__METADATA__":
                                    # 메타데이터는 무시
                                    continue
                                if chunk:
                                    full_response += str(chunk)
                            
                            explanation = full_response.strip() if full_response else None
                            api_info = {"via": "persona_natural_stream"}
                            
                            # 스트리밍 응답이 비어있으면 일반 모드로 fallback
                            if not explanation or len(full_response) == 0:
                                explanation = albwoong_persona_reply(
                                    user_input=user_input,
                                    term=None,
                                    context=None,
                                    temperature=0.2,  # ⚡ 최적화: 0.3 → 0.2
                                    stream=False
                                )
                                api_info = {"via": "persona_natural_fallback"}
                        except Exception as stream_error:
                            # 스트리밍 실패 시 일반 모드로 fallback
                            explanation = albwoong_persona_reply(
                                user_input=user_input,
                                term=None,
                                context=None,
                                temperature=0.2,  # ⚡ 최적화: 0.3 → 0.2
                                stream=False
                            )
                            api_info = {"via": "persona_natural_fallback", "stream_error": str(stream_error)}
                    else:
                        explanation = albwoong_persona_reply(
                            user_input=user_input,
                            term=None,
                            context=None,
                            temperature=0.2  # ⚡ 최적화: 0.3 → 0.2
                        )
                        api_info = {"via": "persona_natural"}
            except Exception as e:
                # LLM 연결 실패 시 fallback
                try:
                    explanation = albwoong_persona_reply(user_input)
                    api_info = {"via": "persona_fallback", "error": str(e)}
                except Exception as e2:
                    explanation = (
                        f"죄송해! 지금은 답변을 생성하기 어려워. "
                        f"다시 시도하거나 다른 질문을 해줘! (오류: {str(e2)})"
                    )
                    api_info = {"error": {"type": type(e2).__name__, "message": str(e2)}}
            
            step_llm.finish()

        # 성능 측정 완료
        profile.finish()
        tracker.finish_current_profile()
        
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
                "answer_len": len(explanation) if explanation else 0,  # ✅ 응답 길이 (None 체크)
                "latency_ms": latency,            # ✅ 응답 지연(ms)
                "response": explanation or ""     # ✅ 시스템 응답 (None 체크)
            }
            
            # OpenAI API 정보 추가 (있는 경우)
            if api_info:
                log_kwargs["api_info"] = api_info
                log_kwargs["via"] = "openai"
            
            log_event("chat_response", **log_kwargs)
        
        # 응답이 있는 경우에만 chat_history에 추가
        if explanation and explanation.strip():
            st.session_state.chat_history.append({"role": "assistant", "content": explanation})
        else:
            # 응답이 없는 경우 오류 메시지 추가
            error_msg = "죄송해! 지금은 답변을 생성하기 어려워. 다시 시도해줘!"
            st.session_state.chat_history.append({"role": "assistant", "content": error_msg})
            explanation = error_msg
        # 메시지 추가 후 자동 스크롤을 위한 JavaScript 실행 (챗봇 내부 스크롤만)
        st_html(
            """
            <script>
            setTimeout(() => {
                const chatBox = window.parent.document.getElementById('chat-scroll-box');
                if (chatBox) {
                    // 느린 속도의 부드러운 스크롤 애니메이션으로 최신 메시지로 이동
                    const targetScroll = chatBox.scrollHeight;
                    const startScroll = chatBox.scrollTop;
                    const distance = targetScroll - startScroll;
                    const duration = 400; // 애니메이션 지속 시간 (ms) - 느린 속도
                    const startTime = performance.now();
                    
                    function animateScroll(currentTime) {
                        const elapsed = currentTime - startTime;
                        const progress = Math.min(elapsed / duration, 1);
                        
                        // easeOutCubic 함수로 부드러운 감속
                        const easeOutCubic = 1 - Math.pow(1 - progress, 3);
                        const currentScroll = startScroll + (distance * easeOutCubic);
                        
                        chatBox.scrollTop = currentScroll;
                        
                        if (progress < 1) {
                            requestAnimationFrame(animateScroll);
                        } else {
                            // 애니메이션 완료 후 정확한 위치로 이동
                            chatBox.scrollTop = targetScroll;
                        }
                    }
                    
                    requestAnimationFrame(animateScroll);
                }
            }, 150);
            </script>
            """,
            height=0,
        )
        st.rerun()

    # 대화 초기화(변경)
    if st.button("🔄 대화 초기화"):
        log_event("chat_reset", surface="sidebar")
        st.session_state.chat_history = []
        # ── NEW: 다음 렌더에서 다시 인사말 나오도록 ──
        st.session_state.intro_shown = False
        st.rerun()
