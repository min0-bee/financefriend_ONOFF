import os
import csv
import json
import uuid
import re
import pandas as pd
import streamlit as st
from datetime import datetime, timezone
from core.config import LOG_DIR, LOG_FILE
from openai import OpenAI
from core.logger import CSV_HEADER

# ─────────────────────────────────────────────────────────────
# 🕓 (1) 현재 UTC 시각을 ISO 형식 문자열로 반환
# ─────────────────────────────────────────────────────────────
def now_utc_iso() -> str:
    """
    🌍 현재 시각을 UTC 기준으로 ISO 8601 문자열로 반환합니다.
    예: "2025-10-22T08:30:25.123456+00:00"
    """
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────
# 📁 (2) 로그 파일(events.csv) 존재 확인 및 생성
# ─────────────────────────────────────────────────────────────
def ensure_log_file():
    """
    📋 logs/events.csv 파일이 없으면 자동으로 생성합니다.
    - 디렉토리(LOG_DIR)가 없으면 만들어줍니다.
    - 헤더(컬럼명)는 core.logger의 CSV_HEADER를 그대로 사용합니다.
    """
    os.makedirs(LOG_DIR, exist_ok=True)

    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
            writer.writeheader()


# ─────────────────────────────────────────────────────────────
# 🧾 (3) 로그 CSV 파일을 DataFrame으로 로드
# ─────────────────────────────────────────────────────────────
def load_logs_as_df(log_file: str) -> pd.DataFrame:
    """
    🧮 logs/events.csv → pandas DataFrame으로 로드합니다.
    주요 기능:
      - payload를 JSON 확장하지 않고 문자열 그대로 유지합니다.
      - event_time을 datetime 타입으로 변환
      - 누락된 컬럼은 빈 문자열로 채웁니다.
    """
    if not os.path.exists(log_file):
        # 파일이 없으면 빈 DataFrame 반환
        return pd.DataFrame(columns=CSV_HEADER)

    # 1️⃣ CSV 읽기
    df = pd.read_csv(
        log_file,
        dtype=str,
        engine="python",
        on_bad_lines="skip",
        encoding="utf-8-sig",
    )

    # 2️⃣ 표준 컬럼 보장 (없는 경우 빈 컬럼으로 채움)
    for col in CSV_HEADER:
        if col not in df.columns:
            df[col] = ""

    # 3️⃣ event_time 문자열 → datetime 변환 (UTC 기준)
    df["event_time"] = pd.to_datetime(df["event_time"], errors="coerce", utc=True)

    # # 4️⃣ payload_json 컬럼을 안전하게 JSON → dict로 변환
    # def _safe_json_loads(x):
    #     try:
    #         return json.loads(x) if isinstance(x, str) and x.strip() else {}
    #     except Exception:
    #         return {}

    # payloads = df["payload_json"].apply(_safe_json_loads)

    # 5️⃣ payload 내용을 별도의 컬럼으로 확장 (json_normalize)
    # payload_df = pd.json_normalize(payloads)

    # 4️⃣ 숫자형 컬럼 자동 변환
    for col in ["click_count", "answer_len", "latency_ms"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")


    # 컬럼 순서 재정렬 (보기 쉽게)
    order_cols = [
        "event_id",
        "event_time",
        "event_name",
        "user_id",
        "session_id",
        "surface",
        "source",
        "news_id",
        "term",
        "message",
        "note",
        "title",
        "click_count",
        "answer_len",
        "via",
        "latency_ms",
        "payload",  # ✅ 그대로 유지
    ]
    order_cols = [c for c in order_cols if c in df.columns]
    df = df[order_cols].sort_values("event_time").reset_index(drop=True)
    return df


# ─────────────────────────────────────────────────────────────
#   (4)  --- OpenAI: 클라이언트 & 호출 헬퍼 ---
# ─────────────────────────────────────────────────────────────

@st.cache_resource
def get_openai_client(api_key: str = None):
    """
    OpenAI Python SDK v1.x 클라이언트 생성 (st.cache_resource로 캐싱)
    - 한 번 생성된 클라이언트는 세션 간 재사용
    - 환경변수/Streamlit secrets에서 키를 찾고, 없으면 None 반환
    """
    # 1) 우선순위: 전달 인자 → 환경변수 → st.secrets
    key = api_key or os.getenv("OPENAI_API_KEY")
    try:
        if not key and "OPENAI_API_KEY" in st.secrets:
            key = st.secrets["OPENAI_API_KEY"]
    except Exception:
        pass

    # 2) 키가 없으면 연결 건너뛰기
    if not key:
        return None

    # 3) 정상 생성
    return OpenAI(api_key=key)


def llm_chat(messages, model: str = None, temperature: float = 0.3, max_tokens: int = 512, return_metadata: bool = False, stream: bool = False):
    """
    💬 ChatGPT (Chat Completions API) 호출 헬퍼 함수
    --------------------------------------------------
    ✅ 기능:
        - OpenAI의 ChatCompletions API를 호출해 LLM 응답을 받아옴.
        - messages 형식의 대화 이력을 입력받아 모델의 답변을 반환함.
          (Streamlit 등에서 챗봇 기능 구현 시 자주 사용)

    ✅ 매개변수:
        messages : list[dict]
            [{"role": "system"|"user"|"assistant", "content": "..."}] 형식의 메시지 배열
            예시:
                [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "오늘의 금융 뉴스 요약해줘"}
                ]
        model : str, optional
            사용할 OpenAI 모델 이름 (기본값은 core.config의 DEFAULT_OPENAI_MODEL)
        temperature : float, optional
            생성 텍스트의 창의성 조절 (0~1, 낮을수록 일관성↑, 높을수록 다양성↑)
        max_tokens : int, optional
            모델이 생성할 최대 토큰 수 (응답 길이 제한)
        return_metadata : bool, optional
            True면 응답과 함께 메타데이터(토큰 사용량, 모델명 등)도 반환
        stream : bool, optional
            True면 스트리밍 응답을 반환 (제너레이터)

    ✅ 반환값:
        str 또는 tuple 또는 generator : 
            - stream=False, return_metadata=False: 모델이 생성한 텍스트 응답 (문자열)
            - stream=False, return_metadata=True: (응답 텍스트, 메타데이터 딕셔너리)
            - stream=True: 제너레이터 (각 델타를 yield)
              메타데이터 예시: {
                  "model": "gpt-4o-mini",
                  "tokens": {"input": 150, "output": 200, "total": 350},
                  "api_params": {"temperature": 0.3, "max_tokens": 512}
              }
    """

    try:
        # ✅ 1. 설정값 가져오기
        #   - 기본 모델명 (예: "gpt-4o-mini")
        #   - OpenAI API 키
        from core.config import DEFAULT_OPENAI_MODEL, OPENAI_API_KEY

    except Exception as e:
        st.error(f"❌ config import 실패: {e}")
        problems.append("config import 실패")

    # ✅ 2. OpenAI 클라이언트 초기화
    client = get_openai_client(OPENAI_API_KEY)

    # ✅ 3. 모델 지정 (직접 전달 없으면 기본값 사용)
    model = model or DEFAULT_OPENAI_MODEL

    # ✅ 4. 스트리밍 모드 처리
    if stream:
        def stream_generator():
            response_text = ""
            usage = None
            with client.chat.completions.stream(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            ) as stream_resp:
                for event in stream_resp:
                    if event.type == "message.delta":
                        delta = event.delta.content or ""
                        if delta:
                            response_text += delta
                            yield delta
                    elif event.type == "message.completed":
                        usage = event.response.usage  # type: ignore[attr-defined]
            
            # 스트리밍 완료 후 메타데이터 반환 (return_metadata=True인 경우)
            if return_metadata:
                metadata = {
                    "model": model,
                    "tokens": {
                        "input": usage.prompt_tokens if usage else 0,
                        "output": usage.completion_tokens if usage else 0,
                        "total": usage.total_tokens if usage else 0
                    },
                    "api_params": {
                        "temperature": temperature,
                        "max_tokens": max_tokens
                    }
                }
                yield ("__METADATA__", metadata)
        
        return stream_generator()

    # ✅ 5. 일반 모드: ChatCompletions API 호출
    #   - messages: 대화 이력
    #   - temperature: 창의성 조절
    #   - max_tokens: 응답 길이 제한
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    # ✅ 6. 응답에서 모델의 텍스트 추출
    response_text = resp.choices[0].message.content.strip()
    
    # ✅ 7. 메타데이터 수집 (에이전트 수집용)
    if return_metadata:
        usage = resp.usage
        metadata = {
            "model": model,
            "tokens": {
                "input": usage.prompt_tokens if usage else 0,
                "output": usage.completion_tokens if usage else 0,
                "total": usage.total_tokens if usage else 0
            },
            "api_params": {
                "temperature": temperature,
                "max_tokens": max_tokens
            }
        }
        return response_text, metadata
    
    return response_text


# === LLM 연결 진단 패널 ===
def render_llm_diagnostics():
    import os, importlib, sys
    import streamlit as st

    st.markdown("### 🧪 LLM 연결 진단")
    problems = []

    # 1) openai 패키지 제대로 import 되는지
    try:
        import openai  # 패키지 모듈 (v1에서도 모듈명은 openai)
        st.write("✅ `import openai` OK", getattr(openai, "__version__", "unknown"))
    except Exception as e:
        st.error(f"❌ `import openai` 실패: {e}")
        problems.append("openai import 실패")

    # 2) 프로젝트에 openai.py / openai 폴더로 **이름충돌** 있는지
    import glob, os
    here = os.path.abspath(os.getcwd())
    shadow = []
    for pattern in ["openai.py", "openai/__init__.py"]:
        for p in glob.glob(os.path.join(here, "**", pattern), recursive=True):
            shadow.append(p)
    if shadow:
        st.error("❌ 프로젝트 안에 `openai` 이름 충돌 가능성:", icon="🚫")
        for p in shadow:
            st.code(p)
        problems.append("로컬 파일/폴더 이름충돌(openai)")
    else:
        st.write("✅ 프로젝트 내 이름충돌 없음")

    # 3) config 값 확인
    try:
        from core import config
        st.write("✅ `from core import config` OK")
        st.write({
            "DEFAULT_OPENAI_MODEL": getattr(config, "DEFAULT_OPENAI_MODEL", None),
            "USE_OPENAI": getattr(config, "USE_OPENAI", None),
            "OPENAI_API_KEY in config (bool)": bool(getattr(config, "OPENAI_API_KEY", None)),
        })
    except Exception as e:
        st.error(f"❌ config import 실패: {e}")
        problems.append("config import 실패")

    # 4) 환경변수 확인 (현재 프로세스)
    st.write({
        "env.OPENAI_API_KEY": bool(os.getenv("OPENAI_API_KEY")),
    })

    # 5) .streamlit/secrets.toml 읽히는지
    try:
        import streamlit as st
        st.write({
            "secrets.has_OPENAI_API_KEY": ("OPENAI_API_KEY" in st.secrets),
            "secrets.has_OPENAI_MODEL": ("OPENAI_MODEL" in st.secrets),
        })
    except Exception as e:
        st.warning(f"secrets 접근 경고: {e}")

    # 6) OpenAI v1 클라이언트 생성 & 간이 호출
    try:
        from openai import OpenAI
        api_key = getattr(config, "OPENAI_API_KEY", None) or os.getenv("OPENAI_API_KEY")
        if not api_key:
            st.error("❌ API 키 없음: config.OPENAI_API_KEY 또는 env.OPENAI_API_KEY가 비어있음")
            problems.append("API 키 없음")
        else:
            client = OpenAI(api_key=api_key)
            st.write("✅ OpenAI 클라이언트 생성 OK")
            # 모델 핑(가벼운 호출): 모델 리스트 혹은 최소 chat 호출 시그니처 확인
            try:
                # 가장 가벼운 확인: 모델 리스트
                _ = client.models.list()
                st.write("✅ `client.models.list()` OK")
            except Exception as e:
                st.warning(f"⚠️ models.list 경고: {e}")
            # 짧은 채팅 호출 시도 (모델명은 config 사용)
            try:
                mdl = getattr(config, "DEFAULT_OPENAI_MODEL", "gpt-4o-mini")
                resp = client.chat.completions.create(
                    model=mdl,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=5,
                )
                txt = resp.choices[0].message.content.strip()
                st.success(f"✅ chat.completions 응답 OK: {txt!r}")
            except Exception as e:
                st.error(f"❌ chat.completions 실패: {e}")
                problems.append("chat.completions 실패")
    except Exception as e:
        st.error(f"❌ OpenAI 클라이언트 생성 실패: {e}")
        problems.append("OpenAI 클라이언트 생성 실패")

    if problems:
        st.markdown("**요약 (의심 포인트)**: " + ", ".join(problems))
    else:
        st.success("🎉 진단상 문제 없음")

# 👉 호출 위치 예시
# with st.sidebar:
#     render_llm_diagnostics()


# ─────────────────────────────────────────────────────────────
# 🔗 (5) URL 감지 및 추출 유틸리티
# ─────────────────────────────────────────────────────────────

def extract_urls_from_text(text: str) -> list[str]:
    """
    텍스트에서 URL을 추출합니다.
    
    Args:
        text: URL이 포함될 수 있는 텍스트
        
    Returns:
        발견된 URL 리스트
    """
    if not text:
        return []
    
    # URL 패턴 (http/https로 시작하는 URL)
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+[^\s<>"{}|\\^`\[\].,;!?]'
    urls = re.findall(url_pattern, text)
    
    return urls


def is_url(text: str) -> bool:
    """
    텍스트가 URL인지 확인합니다.
    
    Args:
        text: 확인할 텍스트
        
    Returns:
        URL이면 True, 아니면 False
    """
    if not text or not text.strip():
        return False
    
    text = text.strip()
    urls = extract_urls_from_text(text)
    
    # 텍스트 전체가 URL인지 확인 (앞뒤 공백 제거 후 비교)
    return len(urls) == 1 and text.strip() == urls[0]


# ─────────────────────────────────────────────────────────────
# 📰 (6) 기사 찾기 요청 감지 및 키워드 추출
# ─────────────────────────────────────────────────────────────

def detect_article_search_request(text: str) -> tuple[bool, str]:
    """
    사용자 입력이 기사 찾기 요청인지 감지하고 키워드를 추출합니다.
    
    Args:
        text: 사용자 입력 텍스트
        
    Returns:
        (is_request, keyword) 튜플
        - is_request: 기사 찾기 요청이면 True
        - keyword: 추출된 키워드 (없으면 빈 문자열)
    """
    if not text or not text.strip():
        return False, ""
    
    text = text.strip()
    
    # 기사 찾기 패턴들 (확장)
    search_patterns = [
        # "~에 대해 기사 보여줘" 패턴
        r'(.+?)(?:에\s*대해|에\s*관해|에\s*대한|에\s*관한).*?기사.*?(?:보여|찾아|알려|알고싶|보고싶)',
        r'(.+?)(?:에\s*대해|에\s*관해|에\s*대한|에\s*관한).*?(?:기사|뉴스|기사.*?보여|뉴스.*?보여)',
        r'(.+?)(?:기사|뉴스).*?(?:보여|찾아|알려|보고싶|알고싶)',
        r'(.+?)(?:에\s*대해|에\s*관해).*?(?:더\s*알고싶|더\s*보고싶|더\s*알려)',
        r'(.+?)(?:에\s*대한|에\s*관한).*?(?:기사|뉴스)',
        # "~에 대해 알고싶어" 패턴 (기사/뉴스 없이도 매칭)
        r'(.+?)(?:에\s*대해|에\s*관해).*?알고싶',
        r'(.+?)(?:에\s*대해|에\s*관해).*?보고싶',
        # "~가 더 필요해", "~관련 뉴스" 패턴 추가
        r'(.+?)(?:에?\s*관련|에?\s*관한|에?\s*대한).*?(?:뉴스|기사).*?(?:더\s*필요|더\s*보고싶|더\s*알고싶|가져와|찾아)',
        r'(.+?)(?:에?\s*관련|에?\s*관한|에?\s*대한).*?(?:뉴스|기사).*?필요',
        r'(.+?)(?:에?\s*관련|에?\s*관한|에?\s*대한).*?뉴스',
        r'(.+?)(?:에?\s*관련|에?\s*관한|에?\s*대한).*?기사',
        r'(.+?)(?:가|이|을|를).*?(?:더\s*필요|더\s*보고싶|더\s*알고싶)',
        r'(.+?)(?:에?\s*대해|에?\s*관해).*?(?:뉴스|기사).*?(?:더\s*필요|더\s*보고싶|더\s*알고싶)',
    ]
    
    for pattern in search_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            keyword = match.group(1).strip()
            # 조사 제거 (은/는/이/가/을/를/에/의 등)
            keyword = re.sub(r'\s*(은|는|이|가|을|를|에|의|와|과|로|으로)\s*$', '', keyword)
            # "관련", "관한", "대한" 같은 단어 제거 (검색 키워드에서)
            keyword = re.sub(r'\s*(관련|관한|대한|대해|관해)\s*$', '', keyword)
            keyword = re.sub(r'^\s*(관련|관한|대한|대해|관해)\s*', '', keyword)
            if keyword and len(keyword) > 1:  # 최소 2글자 이상
                return True, keyword
    
    return False, ""


def detect_inappropriate_question(text: str) -> bool:
    """
    투자 조언, 로또 번호 등 부적절한 질문인지 감지합니다.
    
    Args:
        text: 사용자 입력 텍스트
        
    Returns:
        부적절한 질문이면 True
    """
    if not text or not text.strip():
        return False
    
    text_lower = text.lower()
    
    # 투자 조언 요청 패턴
    investment_patterns = [
        r'어디에.*투자|어디.*투자|투자.*어디|어떤.*투자|무엇.*투자',
        r'투자.*추천|추천.*투자|투자.*어때|어떻게.*투자',
        r'주식.*살까|살까.*주식|어떤.*주식|무엇.*주식',
        r'어디.*살까|무엇.*살까|어떤.*살까',
        r'로또.*번호|번호.*로또|로또.*뽑|뽑.*로또',
        r'복권.*번호|번호.*복권',
        r'당첨.*번호|당첨.*예측',
        r'투자.*조언|조언.*투자|투자.*상담',
        r'어떤.*좋아|무엇.*좋아|어떤게.*좋아',
        r'어떤.*사|무엇.*사|어떤거.*사',
        r'.*에.*투자할까|.*에.*투자할까해|.*에.*투자할까요|.*에.*투자할까요\?',
        r'.*에.*투자.*할까|.*에.*투자.*할까해|.*에.*투자.*할까요',
    ]
    
    for pattern in investment_patterns:
        if re.search(pattern, text_lower):
            return True
    
    return False


def search_related_article(articles: list[dict], keyword: str) -> dict | None:
    """
    뉴스 리스트에서 키워드와 관련된 기사를 찾습니다.
    
    Args:
        articles: 뉴스 기사 리스트
        keyword: 검색 키워드
        
    Returns:
        가장 관련성 높은 기사 (없으면 None)
    """
    if not articles or not keyword:
        return None
    
    keyword_lower = keyword.lower()
    best_match = None
    best_score = 0
    
    for article in articles:
        score = 0
        
        # 제목에서 매칭 (가장 높은 점수)
        title = article.get("title", "").lower()
        if keyword_lower in title:
            score += 10
            # 정확히 일치하면 추가 점수
            if keyword_lower == title:
                score += 5
        
        # 요약에서 매칭
        summary = article.get("summary", "").lower()
        if keyword_lower in summary:
            score += 5
        
        # 본문에서 매칭
        content = article.get("content", "").lower()
        if keyword_lower in content:
            score += 2
            # 본문에서 여러 번 나오면 추가 점수
            count = content.count(keyword_lower)
            if count > 1:
                score += min(count - 1, 3)  # 최대 3점 추가
        
        # 키워드의 단어들이 각각 매칭되는지 확인
        keyword_words = keyword_lower.split()
        if len(keyword_words) > 1:
            matched_words = sum(1 for word in keyword_words if word in title or word in summary)
            if matched_words > 0:
                score += matched_words * 2
        
        if score > best_score:
            best_score = score
            best_match = article
    
    # 최소 점수 이상이어야 매칭으로 인정
    if best_score >= 2:
        return best_match
    
    return None