import streamlit as st
from openai import OpenAI
import json
from datetime import datetime, timezone   # [ADD] timezone
import re
import os                                  # [ADD]
import uuid                                # [ADD]
import csv                                  # [ADD]
import time

LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "events.csv")

# [ADD] ─────────────────────────────────────────────────────────
# 간단한 세션/유저 식별자 (로그인 전 MVP)
if "session_id" not in st.session_state:
    st.session_state.session_id = f"sess_{uuid.uuid4().hex[:12]}"


# ===== 익명 user_id 생성/유지 (MVP: URL uid + 로컬 파일 캐시) =====
USER_FILE = os.path.join(LOG_DIR, "user_info.json")

def _read_local_user_id():
    try:
        if os.path.exists(USER_FILE):
            with open(USER_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("user_id")
    except Exception:
        pass
    return None

def _write_local_user_id(uid: str):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(USER_FILE, "w", encoding="utf-8") as f:
            json.dump({"user_id": uid, "created_at": now_utc_iso(), "user_type": "anonymous"}, f, ensure_ascii=False)
    except Exception:
        pass

def get_or_create_user_id() -> str:
    # 1) URL 쿼리파라미터 우선 (Streamlit 1.30+)
    try:
        uid_from_qs = st.query_params.get("uid", None)
    except Exception:
        uid_from_qs = None
        try:
            qs = st.experimental_get_query_params()
            if "uid" in qs:
                uid_from_qs = qs["uid"][0]
        except Exception:
            pass

    if uid_from_qs:
        return uid_from_qs

    # 2) 로컬 파일 캐시 (개발/MVP 환경에서 유효)
    uid_local = _read_local_user_id()
    if uid_local:
        # URL에 uid가 없으면 달아줌(새로고침 없이 URL만 정리)
        try:
            st.query_params["uid"] = uid_local
        except Exception:
            try:
                st.experimental_set_query_params(uid=uid_local)
            except Exception:
                pass
        return uid_local

    # 3) 신규 생성
    new_uid = f"user_{uuid.uuid4().hex[:8]}"
    _write_local_user_id(new_uid)
    # URL에도 반영
    try:
        st.query_params["uid"] = new_uid
    except Exception:
        try:
            st.experimental_set_query_params(uid=new_uid)
        except Exception:
            pass
    return new_uid

# 세션 스테이트 바인딩
if "user_id" not in st.session_state:
    st.session_state.user_id = get_or_create_user_id()

# =============================================================

# ✅ [추가 1] 페이지 체류시간 기록용 시작점 저장
if "page_enter_time" not in st.session_state:
    st.session_state.page_enter_time = datetime.now()

# ✅ [추가 2] 용어 클릭 누적 카운터
if "term_click_count" not in st.session_state:
    st.session_state.term_click_count = 0    

def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_log_file():
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "event_time","event_name","user_id","session_id",
                    "news_id","term","source","surface",
                    "message","payload_json"
                ]
            )
            writer.writeheader()

def log_event(event_name: str, **kwargs):
    """
    CSV 기반 MVP 로깅.
    표준 컬럼 + 유연한 payload_json에 기타 정보를 넣는다.
    """
    ensure_log_file()
    row = {
        "event_time": now_utc_iso(),
        "event_name": event_name,
        "user_id": st.session_state.get("user_id","anon"),
        "session_id": st.session_state.get("session_id"),
        # 선택적 컨텍스트 (없으면 빈 값)
        "news_id": kwargs.get("news_id",""),
        "term": kwargs.get("term",""),
        "source": kwargs.get("source",""),
        "surface": kwargs.get("surface",""),
        "message": kwargs.get("message",""),
        # 나머지는 payload_json으로 직렬화
        "payload_json": json.dumps(kwargs.get("payload",{}), ensure_ascii=False),
    }
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=row.keys()).writerow(row)
# [ADD] ─────────────────────────────────────────────────────────



# 페이지 설정
st.set_page_config(layout="wide", page_title="금융 뉴스 도우미")

# [ADD] 세션 시작 로그 (최초 1회)
# 참고: ua는 Streamlit에서 직접 못 뽑으니, MVP에선 빈 dict로 남아도 무방. (GA4 붙일 때 개선)
if "session_logged" not in st.session_state:
    log_event(
        "session_start",
        surface="home",
        payload={"ua": st.session_state.get("_browser",{}), "note":"MVP session start"}
    )
    st.session_state.session_logged = True

# OpenAI 클라이언트 초기화 (MVP 단계: Mock 모드)
USE_OPENAI = False  # API 연결 시 True로 변경

@st.cache_resource
def get_openai_client():
    if USE_OPENAI:
        api_key = st.secrets.get("OPENAI_API_KEY", "your-api-key-here")
        return OpenAI(api_key=api_key)
    return None

client = get_openai_client()

# 세션 스테이트 초기화
if 'news_articles' not in st.session_state:
    st.session_state.news_articles = []
if 'selected_article' not in st.session_state:
    st.session_state.selected_article = None
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []
if 'financial_terms' not in st.session_state:
    # RAG를 위한 금융 용어 사전 (예시)
    st.session_state.financial_terms = {
        "양적완화": {
            "정의": "중앙은행이 시중에 통화를 공급하기 위해 국채 등을 매입하는 정책",
            "설명": "경기 부양을 위해 중앙은행이 돈을 풀어 시장 유동성을 높이는 방법입니다.",
            "비유": "마른 땅에 물을 뿌려주는 것처럼, 경제에 돈이라는 물을 공급하는 것입니다."
        },
        "기준금리": {
            "정의": "중앙은행이 시중은행에 돈을 빌려줄 때 적용하는 기준이 되는 금리",
            "설명": "모든 금리의 기준이 되며, 기준금리가 오르면 대출이자도 함께 오릅니다.",
            "비유": "물가의 온도조절기와 같습니다. 경제가 과열되면 올리고, 침체되면 내립니다."
        },
        "배당": {
            "정의": "기업이 벌어들인 이익 중 일부를 주주들에게 나눠주는 것",
            "설명": "주식을 보유한 주주에게 기업의 이익을 분배하는 방식입니다.",
            "비유": "함께 식당을 운영하는 동업자들이 매출 중 일부를 나눠갖는 것과 같습니다."
        },
        "PER": {
            "정의": "주가수익비율. 주가를 주당순이익으로 나눈 값",
            "설명": "주식이 1년 치 이익의 몇 배에 거래되는지를 나타냅니다. 낮을수록 저평가된 것으로 볼 수 있습니다.",
            "비유": "1년에 100만원 버는 가게를 몇 년 치 수익을 주고 사는지를 나타냅니다."
        },
        "환율": {
            "정의": "서로 다른 두 나라 화폐의 교환 비율",
            "설명": "원화를 달러로, 달러를 원화로 바꿀 때 적용되는 비율입니다.",
            "비유": "해외 쇼핑몰에서 물건을 살 때 적용되는 환전 비율입니다."
        }
    }

# 뉴스 수집 Agent (시뮬레이션)
def collect_news():
    """실제로는 OpenAI API로 뉴스를 수집하지만, 여기서는 예시 데이터 사용"""
    sample_news = [
        {
            "id": 1,
            "title": "한국은행, 기준금리 동결 결정",
            "summary": "한국은행이 물가 안정을 위해 기준금리를 현 수준으로 유지하기로 했습니다.",
            "content": "한국은행 금융통화위원회는 21일 회의를 열고 기준금리를 연 3.50%로 동결했습니다. 이는 최근 물가 상승세가 진정되고 있으나 여전히 불확실성이 크다는 판단에 따른 것입니다. 시장에서는 양적완화 정책 전환 가능성도 제기되고 있습니다.",
            "date": "2025-10-21"
        },
        {
            "id": 2,
            "title": "삼성전자, 분기 배당 20% 증액 발표",
            "summary": "삼성전자가 주주환원 정책 강화 일환으로 배당금을 대폭 늘렸습니다.",
            "content": "삼성전자는 이번 분기 배당을 주당 500원으로 결정하며 전년 동기 대비 20% 증액했습니다. PER이 하락하며 주가가 저평가됐다는 시장 분석에 따라 주주환원을 강화하겠다는 의지를 보였습니다.",
            "date": "2025-10-20"
        },
        {
            "id": 3,
            "title": "원달러 환율, 1,300원 돌파",
            "summary": "미국 금리 인상 영향으로 원화 가치가 약세를 보이고 있습니다.",
            "content": "21일 서울 외환시장에서 원달러 환율이 1,300원을 넘어섰습니다. 미국의 기준금리 인상 기조가 지속되면서 달러 강세가 이어지고 있습니다. 수출 기업들에게는 호재이지만 수입 물가 상승 우려도 커지고 있습니다.",
            "date": "2025-10-21"
        }
    ]
    return sample_news

# 뉴스 요약 생성 (GPT-4o-mini 사용)
def generate_summary(articles):
    """여러 뉴스를 종합한 요약 생성"""
    if USE_OPENAI and client:
        try:
            news_texts = "\n\n".join([f"제목: {a['title']}\n내용: {a['content']}" for a in articles])
            
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "당신은 금융 뉴스를 간결하게 요약하는 전문가입니다."},
                    {"role": "user", "content": f"다음 금융 뉴스들을 3-4문장으로 종합 요약해주세요:\n\n{news_texts}"}
                ],
                max_tokens=200
            )
            return response.choices[0].message.content
        except:
            pass
    
    # Mock 응답 (API 미연결 시)
    return "오늘 금융 시장은 한국은행의 기준금리 동결 결정과 삼성전자의 배당 증액 발표가 주목받았습니다. 원달러 환율이 1,300원을 돌파하며 외환시장의 변동성도 커지고 있습니다. 전문가들은 향후 통화정책 방향과 환율 추이를 주시할 필요가 있다고 조언합니다."

# 용어 하이라이트 처리
def highlight_terms(text, terms_dict):
    """텍스트에서 금융 용어를 하이라이트"""
    highlighted = text
    for term in terms_dict.keys():
        # HTML로 하이라이트 처리 - 클릭 가능하도록
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        highlighted = pattern.sub(
            f'<mark class="clickable-term" data-term="{term}" style="background-color: #FFEB3B; cursor: pointer; padding: 2px 4px; border-radius: 3px;">{term}</mark>',
            highlighted
        )
    return highlighted

# RAG 기반 용어 설명
def explain_term(term, chat_history):
    """RAG를 사용하여 용어 설명"""
    if term in st.session_state.financial_terms:
        term_info = st.session_state.financial_terms[term]
        context = f"""
        용어: {term}
        정의: {term_info['정의']}
        설명: {term_info['설명']}
        비유: {term_info['비유']}
        """
        
        if USE_OPENAI and client:
            try:
                messages = [
                    {"role": "system", "content": "당신은 금융 용어를 쉽게 설명하는 친절한 도우미입니다. 주어진 정보를 바탕으로 초보자도 이해할 수 있게 설명해주세요."}
                ]
                
                # 채팅 히스토리 추가
                for msg in chat_history[-4:]:  # 최근 4개만
                    messages.append(msg)
                
                messages.append({
                    "role": "user", 
                    "content": f"다음 금융 용어를 설명해주세요:\n{context}"
                })
                
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    max_tokens=300
                )
                return response.choices[0].message.content
            except:
                pass
        
        # Mock 응답 (API 미연결 시)
        return f"""**{term}** 에 대해 설명해드릴게요! 🎯

📖 **정의**
{term_info['정의']}

💡 **쉬운 설명**
{term_info['설명']}

🌟 **비유로 이해하기**
{term_info['비유']}

더 궁금한 점이 있으시면 언제든지 물어보세요!"""
    else:
        return f"'{term}'에 대한 정보가 금융 사전에 없습니다. 다른 용어를 선택해주세요."

# CSS 스타일
st.markdown("""
<style>
    .news-card {
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #ddd;
        margin: 10px 0;
        cursor: pointer;
        transition: all 0.3s;
    }
    .news-card:hover {
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        border-color: #1f77b4;
    }
    .summary-box {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 20px;
        border-radius: 15px;
        margin-bottom: 20px;
    }
    .article-content {
        background: #f9f9f9;
        padding: 20px;
        border-radius: 10px;
        line-height: 1.8;
    }
    .chat-message {
        padding: 10px;
        border-radius: 10px;
        margin: 5px 0;
    }
    .user-message {
        background: #e3f2fd;
        text-align: right;
    }
    .bot-message {
        background: #f5f5f5;
    }
    .clickable-term {
        transition: all 0.2s;
    }
    .clickable-term:hover {
        background-color: #FDD835 !important;
        transform: scale(1.05);
    }
</style>
""", unsafe_allow_html=True)

# 메인 레이아웃
col1, col2 = st.columns([2, 1])

# 왼쪽: 컨텐츠 영역
with col1:
    st.title("📰 금융 뉴스 도우미")
    
    # 뉴스 수집
    if not st.session_state.news_articles:
        with st.spinner("최신 뉴스를 수집하는 중..."):
            st.session_state.news_articles = collect_news()
    
    # 선택된 기사가 없을 때: 요약 + 뉴스 리스트
    if st.session_state.selected_article is None:
        # 종합 요약
        st.markdown('<div class="summary-box">', unsafe_allow_html=True)
        st.subheader("📊 오늘의 금융 뉴스 요약")
        summary = generate_summary(st.session_state.news_articles)
        st.write(summary)
        st.markdown('</div>', unsafe_allow_html=True)
        
        # 뉴스 목록
        st.subheader("📋 최신 뉴스")
        for article in st.session_state.news_articles:
            if st.button(
                f"**{article['title']}**\n{article['summary']}", 
                key=f"news_{article['id']}",
                use_container_width=True
            ):
                # 뉴스 클릭 로그
                log_event(
                    "news_click",
                    news_id=article.get("id"),
                    source="list",
                    surface="home",
                    payload={"title": article.get("title")}
                )
                st.session_state.selected_article = article
                st.rerun()
    
        # -----------------------------------------
        # 뉴스 상세 페이지 진입 
        # -----------------------------------------

    else:
        article = st.session_state.selected_article

        # [ADD] 상세 화면 진입 로그 (중복 방지)
        if not st.session_state.get("detail_enter_logged"):
            log_event(
                "news_detail_open",
                news_id=article.get("id"),
                surface="detail",
                payload={"title": article.get("title")}
            )
            st.session_state.detail_enter_logged = True
            st.session_state.page_enter_time = datetime.now()

    if st.button("← 뉴스 목록으로 돌아가기"):
        # [ADD] 상세 화면 이탈 로그
        log_event(
            "news_detail_back",
            news_id=article.get("id"),
            surface="detail"
        )
        st.session_state.selected_article = None
        st.session_state.detail_enter_logged = False
        st.rerun()
        
    st.markdown("---")
    st.header(article['title'])
    st.caption(f"📅 {article['date']}")
    
    # 용어 하이라이트 처리된 본문
    st.markdown('<div class="article-content">', unsafe_allow_html=True)
    highlighted_content = highlight_terms(article['content'], st.session_state.financial_terms)
    st.markdown(highlighted_content, unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)
    
    st.info("💡 아래 버튼에서 용어를 선택하면 챗봇이 쉽게 설명해드립니다!")
    
    # 용어 선택 버튼 - 큰 버튼으로 개선
    st.subheader("🔍 용어 설명 요청")
    terms_in_article = [term for term in st.session_state.financial_terms.keys() if term in article['content']]
    
    # 한 줄에 3개씩 배치
    for i in range(0, len(terms_in_article), 3):
        cols = st.columns(3)
        for j, col in enumerate(cols):
            if i + j < len(terms_in_article):
                term = terms_in_article[i + j]
                with col:
                    if st.button(
                        f"📌 {term}", 
                        key=f"term_btn_{term}",
                        use_container_width=True,
                        type="secondary"
                    ):
                        # ✅ 용어 클릭 카운트 누적 로그
                        st.session_state.term_click_count += 1
                        # [ADD] Glossary 조회 로그
                        log_event(
                            "glossary_click",
                            term=term,
                            news_id=article.get("id"),
                            source="news_highlight",
                            surface="detail",
                            payload={"click_count": st.session_state.term_click_count}
                        )

                        # 채팅에 용어 설명 추가
                        user_msg = {"role": "user", "content": f"'{term}' 용어를 설명해주세요"}
                        st.session_state.chat_history.append(user_msg)

                        # 챗봇 응답 생성
                        explanation = explain_term(term, st.session_state.chat_history)
                        bot_msg = {"role": "assistant", "content": explanation}
                        st.session_state.chat_history.append(bot_msg)

                        # Glossary 응답 로그
                        log_event(
                            "glossary_answer",
                            term=term,
                            source="news_highlight",
                            surface="detail",
                            payload={"answer_len": len(explanation)}
                        )

                        st.rerun()
    
    # 하이라이트 클릭 감지 제거 (Streamlit 한계)
    st.caption("💡 Tip: 위 버튼을 클릭하면 오른쪽 챗봇에서 상세한 설명을 확인할 수 있습니다!")

# 오른쪽: 챗봇 영역
with col2:
    st.markdown("### 💬 금융 용어 도우미")
    st.markdown("---")
    
    # 채팅 히스토리 표시
    chat_container = st.container(height=400)
    with chat_container:
        for message in st.session_state.chat_history:
            if message["role"] == "user":
                st.markdown(f'<div class="chat-message user-message">👤 {message["content"]}</div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="chat-message bot-message">🤖 {message["content"]}</div>', unsafe_allow_html=True)
    
    # 사용자 입력
    # -----------------------------------------
    # 기존 챗봇 입력 부분에 latency 로그 추가
    # -----------------------------------------
    user_input = st.chat_input("궁금한 금융 용어를 입력하세요...")
    
    if user_input:
        start_time = time.time() # 챗봇 응답시간 기록
        # [ADD] 채팅 질의 로그
        log_event(
            "chat_question",
            message=user_input,
            source="chat",
            surface="sidebar"
        )
        # 사용자 메시지 추가
        st.session_state.chat_history.append({"role": "user", "content": user_input})
        
        # 용어 추출 (간단한 키워드 매칭)
        found_term = None
        for term in st.session_state.financial_terms.keys():
            if term in user_input:
                found_term = term
                break
        
        if found_term:
            explanation = explain_term(found_term, st.session_state.chat_history)
        
            # [ADD] 용어 질의인 경우 glossary_answer로도 남김
            log_event(
                "glossary_answer",
                term=found_term,
                source="chat",
                surface="sidebar",
                payload={"answer_len": len(explanation)}
            )

        else:
            # 일반 대화
            if USE_OPENAI and client:
                try:
                    response = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": "당신은 금융 용어를 쉽게 설명하는 도우미입니다."}
                        ] + st.session_state.chat_history,
                        max_tokens=300
                    )
                    explanation = response.choices[0].message.content
                except:
                    explanation = "죄송합니다. 응답을 생성하는 중 오류가 발생했습니다."
            else:
                # Mock 응답
                explanation = f"'{user_input}'에 대해 궁금하시군요! MVP 개발 단계에서는 금융 사전에 등록된 용어({', '.join(st.session_state.financial_terms.keys())})만 설명이 가능합니다. 해당 용어를 입력하시거나 기사에서 하이라이트된 용어를 선택해주세요! 😊"

            latency = int((time.time() - start_time) * 1000)
            # ✅ 응답 시간 기록
            log_event(
                "chat_response",
                source="chat",
                surface="sidebar",
                payload={
                    "answer_len": len(explanation),
                    "latency_ms": latency
                }
            )
        
        st.session_state.chat_history.append({"role": "assistant", "content": explanation})
        # [ADD] 챗봇 응답 로그
        log_event(
            "chat_response",
            source="chat",
            surface="sidebar",
            payload={"answer_len": len(explanation)}
        )
        
        st.rerun()
    
    # 채팅 초기화 버튼
    if st.button("🔄 대화 초기화"):
        log_event("chat_reset", surface="sidebar")
        st.session_state.chat_history = []
        st.rerun()

# 사이드바: 설정
with st.sidebar:
    st.header("⚙️ 설정")
    st.markdown("---")
    
    st.subheader("📚 금융 용어 사전")
    st.write(f"등록된 용어: {len(st.session_state.financial_terms)}개")
    
    with st.expander("용어 목록 보기"):
        for term in st.session_state.financial_terms.keys():
            st.write(f"• {term}")
    
    st.markdown("---")
    st.info("""
    **사용 방법:**
    1. 최신 뉴스 목록에서 관심있는 기사를 선택하세요
    2. 기사 내 노란색 용어를 클릭하거나 챗봇에 질문하세요
    3. RAG 기반으로 쉬운 설명을 받아보세요
    """)
    
    st.markdown("---")
    st.caption("💡 OpenAI GPT-4o-mini 사용")


# =========================================================
# 📦 로그 로더 + 뷰어 (MVP) — CSV를 보기 좋게 정리/요약
# =========================================================
import pandas as pd

def load_logs_as_df(log_file: str) -> pd.DataFrame:
    """CSV(events.csv)를 DataFrame으로 로드하고 payload_json을 펼친다."""
    if not os.path.exists(log_file):
        st.info("아직 로그 파일이 없습니다. (logs/events.csv)")
        return pd.DataFrame()

    # 1) CSV 로드 + 시간 파싱
    df = pd.read_csv(log_file)
    # 결측 대비(누락된 컬럼이 있으면 빈 컬럼 추가)
    base_cols = ["event_time","event_name","user_id","session_id","news_id","term","source","surface","message","payload_json"]
    for col in base_cols:
        if col not in df.columns:
            df[col] = ""

    df["event_time"] = pd.to_datetime(df["event_time"], errors="coerce", utc=True)

    # 2) payload_json 파싱/펼치기
    def _safe_json_loads(x):
        try:
            return json.loads(x) if isinstance(x, str) and x.strip() else {}
        except Exception:
            return {}
    payloads = df["payload_json"].apply(_safe_json_loads)
    payload_df = pd.json_normalize(payloads)

    # 중복 컬럼명 충돌 방지
    for c in list(payload_df.columns):
        new_c, i = c, 1
        while new_c in df.columns:
            i += 1
            new_c = f"{c}__{i}"
        if new_c != c:
            payload_df = payload_df.rename(columns={c: new_c})

    df = pd.concat([df.drop(columns=["payload_json"]), payload_df], axis=1)

    # 3) 보기 좋은 정렬
    order_cols = ["event_time","event_name","user_id","session_id","surface","source","news_id","term","message"]
    other_cols = [c for c in df.columns if c not in order_cols]
    df = df[order_cols + other_cols]
    df = df.sort_values("event_time").reset_index(drop=True)
    return df


def show_log_viewer():
    st.markdown("## 🧪 로그 뷰어 (MVP)")
    df = load_logs_as_df(LOG_FILE)
    if df.empty:
        return

    # ===== 상단 요약 (세션 기준 기본 뷰) =====
    colA, colB, colC, colD = st.columns(4)
    with colA:
        st.metric("총 이벤트", f"{len(df):,}")
    with colB:
        st.metric("세션 수", df["session_id"].nunique())
    with colC:
        st.metric("유저 수", df["user_id"].nunique())
    with colD:
        st.metric("이벤트 종류", df["event_name"].nunique())

    # ===== [추가] 유저 기준 요약 스위치 & 요약 카드 =====
    st.markdown("---")
    agg_by_user = st.toggle(
        "👤 유저(user_id) 기준으로 요약 보기",
        value=False,
        help="세션이 여러 개여도 같은 유저로 묶어서 봅니다."
    )

    if agg_by_user:
        # 유저 단위 집계
        g = (
            df.groupby("user_id", dropna=False)
              .agg(
                  events=("event_name", "count"),
                  sessions=("session_id", "nunique"),
                  first_seen=("event_time", "min"),
                  last_seen=("event_time", "max")
              )
              .reset_index()
              .sort_values(["events","sessions"], ascending=False)
        )

        # 유저 기준 메트릭
        colU1, colU2, colU3, colU4 = st.columns(4)
        with colU1:
            st.metric("고유 유저 수", f"{len(g):,}")
        with colU2:
            st.metric("유저당 평균 세션", f"{(g['sessions'].mean() if len(g) else 0):.2f}")
        with colU3:
            st.metric("유저당 평균 이벤트", f"{(g['events'].mean() if len(g) else 0):.1f}")
        with colU4:
            st.metric("총 이벤트(유저 합계)", f"{int(g['events'].sum()):,}")

        # 상위 유저 표
        st.caption("유저별 활동 요약 (이벤트/세션 많은 순)")
        st.dataframe(g.head(50), use_container_width=True, height=320)

        # 특정 유저 타임라인
        st.markdown("### 🔎 특정 유저 타임라인")
        target_user = st.selectbox("유저 선택", options=g["user_id"].tolist() if len(g) else [])
        if target_user:
            udf = df[df["user_id"] == target_user].copy().sort_values("event_time")

            st.write(f"세션 수: {udf['session_id'].nunique()}개")
            sess_sum = (
                udf.groupby("session_id", dropna=False)
                   .agg(
                       events=("event_name","count"),
                       start=("event_time","min"),
                       end=("event_time","max")
                   )
                   .assign(dwell_sec=lambda x: (x["end"] - x["start"]).dt.total_seconds())
                   .sort_values("start", ascending=False)
            )
            st.dataframe(sess_sum, use_container_width=True, height=260)

            sel_sess = st.selectbox("세션 선택", options=sess_sum.index.tolist() if len(sess_sum) else [])
            if sel_sess:
                sdf = udf[udf["session_id"] == sel_sess].copy()
                sdf["next_time"] = sdf["event_time"].shift(-1)
                sdf["gap_sec"] = (sdf["next_time"] - sdf["event_time"]).dt.total_seconds()
                st.dataframe(
                    sdf[["event_time","event_name","surface","source","news_id","term","message","gap_sec"]],
                    use_container_width=True, height=320
                )

        # 유저 기준 보기에서는 기본 탭 숨김
        return

    # ===== 기본 탭: 전체표 / 이벤트요약 / 세션타임라인 / 용어통계 =====
    tab1, tab2, tab3, tab4 = st.tabs(["📄 전체 로그", "📊 이벤트 요약", "🧵 세션 타임라인", "🏷️ 용어 통계"])

    with tab1:
        st.caption("CSV를 테이블로 보기")
        st.dataframe(df, use_container_width=True, height=420)

    with tab2:
        st.caption("이벤트별 건수/최근 10건")
        counts = df["event_name"].value_counts().rename_axis("event_name").reset_index(name="count")
        st.dataframe(counts, use_container_width=True, height=250)
        try:
            st.bar_chart(data=counts.set_index("event_name"))
        except Exception:
            pass

        nc = (df["event_name"] == "news_click").sum()
        ndo = (df["event_name"] == "news_detail_open").sum()
        conv = (ndo / nc * 100) if nc else 0
        st.write(f"**클릭→진입 전환율(rough)**: {conv:.1f}%  (clicks={nc}, opens={ndo})")

    with tab3:
        st.caption("세션을 선택해 타임라인 확인")
        session_ids = df["session_id"].dropna().unique().tolist()
        sess = st.selectbox("세션 선택", options=session_ids, index=0 if session_ids else None)
        if sess:
            sdf = df[df["session_id"] == sess].copy().sort_values("event_time")
            sdf["next_time"] = sdf["event_time"].shift(-1)
            sdf["gap_sec"] = (sdf["next_time"] - sdf["event_time"]).dt.total_seconds()
            st.dataframe(
                sdf[["event_time","event_name","surface","source","news_id","term","message","gap_sec"]],
                use_container_width=True, height=420
            )

    with tab4:
        st.caption("용어 클릭/응답 길이 통계")
        gclick = df[df["event_name"] == "glossary_click"]
        gans = df[df["event_name"] == "glossary_answer"]

        col1, col2 = st.columns(2)
        with col1:
            st.write("용어 클릭 Top N")
            top_terms = gclick["term"].value_counts().head(10).rename_axis("term").reset_index(name="clicks")
            st.dataframe(top_terms, use_container_width=True, height=300)

        with col2:
            if "answer_len" in gans.columns:
                tmp = gans.copy()
                tmp["answer_len"] = pd.to_numeric(tmp["answer_len"], errors="coerce")
                agg = (
                    tmp.groupby("term", dropna=True)["answer_len"]
                       .agg(["count","mean","max"])
                       .sort_values("count", ascending=False)
                       .head(10)
                )
                st.write("응답 길이 요약(Top10)")
                st.dataframe(agg, use_container_width=True, height=300)
            else:
                st.info("`glossary_answer`에 answer_len이 아직 없어요.")

# 👇 원하는 위치에서 호출 (예: 페이지 맨 아래)
st.markdown("---")
show_log_viewer()
