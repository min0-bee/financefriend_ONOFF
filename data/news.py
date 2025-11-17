from typing import List, Dict, Optional
from datetime import datetime
import streamlit as st
import requests
import re
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from core.logger import get_supabase_client
from core.config import SUPABASE_ENABLE

# Fallback용 샘플 데이터 (Supabase 연결 실패 시 사용)
FALLBACK_NEWS = [
    {
        "id": 1,
        "title": "한국은행, 기준금리 동결 결정",
        "summary": "한국은행이 물가 안정을 위해 기준금리를 현 수준으로 유지하기로 했습니다.",
        "content": (
            "한국은행 금융통화위원회는 21일 회의를 열고 기준금리를 연 3.50%로 동결했습니다. "
            "이는 최근 물가 상승세가 진정되고 있으나 여전히 불확실성이 크다는 판단에 따른 것입니다. "
            "시장에서는 양적완화 정책 전환 가능성도 제기되고 있습니다."
        ),
        "date": "2025-10-21",
        "url": "https://www.bok.or.kr/portal/main/sch/schDetail.do?schAlterKey=BOKNEWS&schKey=180409"
    },
    {
        "id": 2,
        "title": "삼성전자, 분기 배당 20% 증액 발표",
        "summary": "삼성전자가 주주환원 정책 강화 일환으로 배당금을 대폭 늘렸습니다.",
        "content": (
            "삼성전자는 이번 분기 배당을 주당 500원으로 결정하며 전년 동기 대비 20% 증액했습니다. "
            "PER이 하락하며 주가가 저평가됐다는 시장 분석에 따라 주주환원을 강화하겠다는 의지를 보였습니다."
        ),
        "date": "2025-10-20",
        "url": "https://news.samsung.com/kr/%EC%82%BC%EC%84%B1%EC%A0%84%EC%9E%90-2025%EB%85%84-3%EB%B6%84%EA%B8%B0-%EB%B0%B0%EB%8B%B9-%EC%A6%9D%EC%95%A1"
    },
    {
        "id": 3,
        "title": "원달러 환율, 1,300원 돌파",
        "summary": "미국 금리 인상 영향으로 원화 가치가 약세를 보이고 있습니다.",
        "content": (
            "21일 서울 외환시장에서 원달러 환율이 1,300원을 넘어섰습니다. "
            "미국의 기준금리 인상 기조가 지속되면서 달러 강세가 이어지고 있습니다. "
            "수출 기업들에게는 호재이지만 수입 물가 상승 우려도 커지고 있습니다."
        ),
        "date": "2025-10-21",
        "url": "https://www.koreaexim.go.kr/site/program/financial/marketView"
    },
]


def search_news_from_supabase(keyword: str, limit: int = 5) -> List[Dict]:
    """
    Supabase DB에서 키워드로 관련 뉴스를 검색합니다.
    
    Args:
        keyword: 검색 키워드
        limit: 가져올 뉴스 개수 (기본값: 5)
        
    Returns:
        검색된 뉴스 리스트 (실패 시 빈 리스트)
    """
    if not SUPABASE_ENABLE:
        return []
    
    supabase = get_supabase_client()
    if not supabase:
        return []
    
    try:
        # news 테이블에서 키워드로 검색
        # title, summary, content에서 키워드 포함 여부 확인
        # deleted_at이 NULL인 것만 (삭제되지 않은 뉴스)
        # published_at 기준 내림차순 정렬 (최신순)
        
        keyword_lower = keyword.lower()
        
        # Supabase의 ilike (대소문자 무시) 사용하여 검색
        # OR 조건: title, summary, content 중 하나라도 키워드를 포함하면 매칭
        try:
            # 방법 1: or_ 메서드 사용 (Supabase Python 클라이언트 문법)
            response = (
                supabase.table("news")
                .select("*")
                .is_("deleted_at", "null")
                .or_(f"title.ilike.%{keyword}%,summary.ilike.%{keyword}%,content.ilike.%{keyword}%")
                .order("published_at", desc=True)
                .limit(limit)
                .execute()
            )
        except Exception:
            # 방법 2: 여러 필터를 각각 시도하고 결과 합치기 (fallback)
            all_results = []
            seen_ids = set()
            
            for field in ["title", "summary", "content"]:
                try:
                    field_response = (
                        supabase.table("news")
                        .select("*")
                        .is_("deleted_at", "null")
                        .ilike(field, f"%{keyword}%")
                        .order("published_at", desc=True)
                        .limit(limit)
                        .execute()
                    )
                    
                    if field_response.data:
                        for item in field_response.data:
                            item_id = item.get("news_id")
                            if item_id and item_id not in seen_ids:
                                all_results.append(item)
                                seen_ids.add(item_id)
                except Exception:
                    continue
            
            # 날짜순 정렬 및 limit 적용
            all_results.sort(key=lambda x: x.get("published_at") or x.get("created_at", ""), reverse=True)
            response = type('obj', (object,), {'data': all_results[:limit]})()
        
        if not response.data:
            return []
        
        # Supabase 응답을 기존 형식으로 변환
        formatted_news = []
        for news in response.data:
            # published_at 또는 created_at을 날짜로 변환
            date_str = news.get("published_at") or news.get("created_at")
            if date_str:
                try:
                    # ISO 형식을 날짜만 추출 (YYYY-MM-DD)
                    date_obj = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    date = date_obj.strftime("%Y-%m-%d")
                except Exception:
                    date = date_str[:10] if len(date_str) >= 10 else "2025-01-01"
            else:
                date = "2025-01-01"
            
            formatted_news.append({
                "id": news.get("news_id"),
                "title": news.get("title", "제목 없음"),
                "summary": news.get("summary") or (
                    news.get("content", "")[:100] + "..."
                    if news.get("content") else "요약 없음"
                ),
                "content": news.get("content", "내용 없음"),
                "date": date,
                "url": news.get("url") or news.get("link") or ""
            })
        
        return formatted_news
        
    except Exception as e:
        # Supabase 오류 - 조용히 실패
        print(f"Supabase 뉴스 검색 실패: {e}")
        return []


def _fetch_news_from_supabase(limit: int = 3) -> List[Dict]:
    """
    Supabase DB에서 최신 뉴스를 직접 가져옵니다.

    Args:
        limit: 가져올 뉴스 개수 (기본값: 3)

    Returns:
        뉴스 리스트 (실패 시 빈 리스트)
    """
    if not SUPABASE_ENABLE:
        return []

    supabase = get_supabase_client()
    if not supabase:
        return []

    try:
        # news 테이블에서 최신 뉴스 가져오기
        # deleted_at이 NULL인 것만 (삭제되지 않은 뉴스)
        # published_at 기준 내림차순 정렬 (최신순)
        response = (
            supabase.table("news")
            .select("*")
            .is_("deleted_at", "null")
            .order("published_at", desc=True)
            .limit(limit)
            .execute()
        )

        if not response.data:
            return []

        # Supabase 응답을 기존 형식으로 변환
        formatted_news = []
        for news in response.data:
            # published_at 또는 created_at을 날짜로 변환
            date_str = news.get("published_at") or news.get("created_at")
            if date_str:
                try:
                    # ISO 형식을 날짜만 추출 (YYYY-MM-DD)
                    date_obj = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    date = date_obj.strftime("%Y-%m-%d")
                except Exception:
                    date = date_str[:10] if len(date_str) >= 10 else "2025-01-01"
            else:
                date = "2025-01-01"

            formatted_news.append({
                "id": news.get("news_id"),
                "title": news.get("title", "제목 없음"),
                "summary": news.get("summary") or (
                    news.get("content", "")[:100] + "..."
                    if news.get("content") else "요약 없음"
                ),
                "content": news.get("content", "내용 없음"),
                "date": date,
                "url": news.get("url") or news.get("link") or ""
            })

        return formatted_news

    except Exception as e:
        # Supabase 오류 - 조용히 실패
        print(f"Supabase 뉴스 조회 실패: {e}")
        return []


def collect_news(use_fallback_on_empty: bool = False) -> List[Dict]:
    """
    Supabase DB에서 최신 뉴스 3개를 가져옵니다.
    
    Args:
        use_fallback_on_empty: True면 Supabase에서 뉴스가 없거나 연결 실패 시 Fallback 사용
    
    Returns:
        Supabase에서 가져온 뉴스 리스트, 또는 Fallback 데이터 (use_fallback_on_empty=True일 때)
    """
    # Supabase에서 뉴스 가져오기 시도
    news_list = _fetch_news_from_supabase(limit=3)

    # 실제 뉴스가 있으면 반환
    if news_list:
        return news_list
    
    # 뉴스가 없거나 연결 실패한 경우
    if use_fallback_on_empty:
        # Fallback 데이터 사용 (연결 실패 시에만)
        return FALLBACK_NEWS
    
    # 뉴스가 없는 경우 빈 리스트 반환
    return []


@st.cache_data(ttl=300)  # 5분 캐시 (뉴스는 자주 변경되지 않음)
def load_news_cached(use_fallback: bool = False) -> List[Dict]:
    """
    뉴스 데이터를 캐싱하여 로드 (서버 전체 기준 5분 동안 재사용)
    ✅ 최적화: st.cache_data로 서버 기준 5분 안에 들어온 모든 세션이 같은 뉴스 결과 공유
    
    Args:
        use_fallback: True면 Supabase 연결 실패 시 Fallback 데이터 사용 (기본값: False, 실제 뉴스만)
    """
    return collect_news(use_fallback_on_empty=use_fallback)


def _clean_article_content(content: str, title: str = None) -> str:
    """
    기사 본문에서 불필요한 텍스트를 제거합니다.
    
    Args:
        content: 원본 본문 텍스트
        title: 기사 제목 (본문에서 제목 중복 제거용)
        
    Returns:
        정제된 본문 텍스트
    """
    if not content:
        return content
    
    # 제목이 본문 앞부분에 반복되는 경우 제거
    if title:
        title_clean = title.strip()
        if title_clean:
            # 본문의 앞부분(첫 200자)에서 제목과 유사한 텍스트 제거
            lines = content.split('\n')
            cleaned_lines = []
            title_removed = False
            
            for i, line in enumerate(lines):
                line_clean = line.strip()
                if not line_clean:
                    cleaned_lines.append(line)
                    continue
                
                # 제목과 정확히 일치하거나 매우 유사한 경우 제거
                if not title_removed and i < 5:  # 앞부분 5줄까지만 체크
                    # 제목과 정확히 일치
                    if line_clean == title_clean:
                        title_removed = True
                        continue
                    
                    # 제목이 줄에 포함되어 있고, 줄이 제목보다 길지 않은 경우
                    if title_clean in line_clean and len(line_clean) <= len(title_clean) * 1.5:
                        title_removed = True
                        continue
                    
                    # 제목의 주요 단어들이 모두 포함된 경우 (80% 이상 일치)
                    title_words = set(re.findall(r'[가-힣a-zA-Z0-9]+', title_clean.lower()))
                    line_words = set(re.findall(r'[가-힣a-zA-Z0-9]+', line_clean.lower()))
                    if title_words and len(line_words) > 0:
                        match_ratio = len(title_words & line_words) / len(title_words)
                        if match_ratio >= 0.8 and len(line_clean) <= len(title_clean) * 2:
                            title_removed = True
                            continue
                
                cleaned_lines.append(line)
            
            content = '\n'.join(cleaned_lines)
    
    # 불필요한 패턴들 제거
    patterns_to_remove = [
        # 오디오 관련 텍스트
        r'\d+\s*기사를\s*읽어드립니다',
        r'Your browser does not support the audio element\.',
        r'기사를\s*읽어드립니다',
        r'읽어드립니다',
        r'음성으로\s*듣기',
        r'음성재생\s*설정',
        r'음성\s*재생하기',
        r'음성\s*재생\s*중지',
        r'남성\s*여성',
        r'느림\s*보통\s*빠름',
        
        # 요약/자동요약 관련
        r'요약보기',
        r'자동요약',
        r'기사\s*제목과\s*주요\s*문장을\s*기반으로',
        r'전체\s*맥락을\s*이해하기\s*위해서는',
        r'본문\s*보기를\s*권장합니다',
        r'닫기',
        
        # 번역 관련
        r'번역\s*설정',
        r'번역\s*beta',
        r'Translated\s*by',
        r'번역중',
        r'Now\s*in\s*translation',
        r'한국어|English|日本語|简体中文|Nederlands|Deutsch|Русский|Malaysia|বাঙ্গোল|tiếng Việt|Español|اللغة العربية|Italiano|bahasa Indonesia|ภาษาไทย|Türkçe|Português|Français|हिन्दी',
        
        # 글씨크기 관련
        r'글씨크기\s*조절하기',
        r'글자크기\s*설정',
        r'파란원을\s*좌우로',
        r'글자크기가\s*변경\s*됩니다',
        r'매우\s*작은\s*폰트',
        r'작은\s*폰트',
        r'보통\s*폰트',
        r'큰\s*폰트',
        r'매우\s*큰\s*폰트',
        r'이\s*글자크기로\s*변경됩니다',
        r'\(예시\)',
        
        # 기자 정보 및 날짜/시간
        r'^[가-힣]+\s*기자\s*\([^)]+\)',
        r'^\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.\s*\d{1,2}:\d{2}',
        r'^자\s*수정\s*\d{4}-\d{2}-\d{2}\s*\d{2}:\d{2}',
        r'^등록\s*\d{4}-\d{2}-\d{2}\s*\d{2}:\d{2}',
        r'^수정\s*\d{4}-\d{2}-\d{2}\s*\d{2}:\d{2}',
        r'^작성\s*\d{4}-\d{2}-\d{2}\s*\d{2}:\d{2}',
        r'^\d{4}-\d{2}-\d{2}\s*\d{2}:\d{2}',
        r'^\d{1,2}:\d{2}$',
        
        # 인쇄/공유 관련
        r'인쇄하기',
        r'공유하기',
        r'페이스북',
        r'트위터',
        r'카카오톡',
        
        # Copyright 및 저작권
        r'Copyright\s*©',
        r'무단\s*전재',
        r'재배포',
        r'AI학습\s*이용\s*금지',
        r'해당\s*언론사로\s*이동합니다',
        r'에서\s*직접\s*확인하세요',
        
        # 관련 기사/추천 기사
        r'관련\s*기사',
        r'추천\s*기사',
        r'인기\s*기사',
        r'광고',
        r'\[속보\]',
        r'\[단독\]',
        r'\[뉴스\d+\]',
        
        # 기타 UI 요소
        r'가장\s*빠른\s*뉴스가\s*있고',
        r'다양한\s*정보',
        r'쌍방향\s*소통',
        r'다음뉴스를\s*만나보세요',
        r'다음뉴스는',
        r'국내외\s*주요이슈',
        r'실시간\s*속보',
        r'문화생활',
        r'입체적으로\s*전달',
        
        # 공통 불필요한 텍스트
        r'^\d+\s*$',
        r'^\s*0\s*$',
        r'^\s*$',
        r'댓글\s*\d*',
        r'좋아요\s*\d*',
        r'조회수\s*\d*',
        r'^\d+개社',
        r'^\d+%',
    ]
    
    lines = content.split('\n')
    cleaned_lines = []
    skip_until_empty = False  # 관련 기사 섹션 건너뛰기 플래그
    
    for line in lines:
        line = line.strip()
        if not line:
            if skip_until_empty:
                skip_until_empty = False
            continue
        
        # 관련 기사 섹션 시작 감지
        if re.search(r'관련\s*기사|추천\s*기사|인기\s*기사|다음\s*기사', line, re.IGNORECASE):
            skip_until_empty = True
            continue
        
        if skip_until_empty:
            # 관련 기사 섹션은 건너뛰기
            continue
        
        # 패턴 매칭하여 제거
        should_remove = False
        
        # 부분 매칭도 체크 (줄에 불필요한 텍스트가 포함되어 있는지)
        for pattern in patterns_to_remove:
            if re.search(pattern, line, re.IGNORECASE):
                should_remove = True
                break
        
        # 추가 체크: 언어 목록이 포함된 줄 제거
        if re.search(r'(영어|일본어|중국어|네델란드어|독일어|러시아어|말레이시아어|벵골어|베트남어|스페인어|아랍어|이탈리아어|인도네시아어|태국어|튀르키에어|포르투갈어|프랑스어|힌디어).*?(영어|일본어|중국어)', line, re.IGNORECASE):
            should_remove = True
        
        # 음성/번역 관련 텍스트가 포함된 줄 제거
        if re.search(r'(남성|여성|느림|보통|빠름|음성|재생|번역|beta|kaka)', line, re.IGNORECASE):
            should_remove = True
        
        # 기사 제목처럼 보이지만 실제로는 관련 기사 링크인 경우 제거
        if re.search(r'^[가-힣].*?-\s*(매일경제|연합뉴스|조선일보|중앙일보|동아일보|한겨레|경향신문)', line):
            should_remove = True
        
        # 짧은 줄 중 불필요한 것들 제거 (20자 이하이고 특정 패턴 포함)
        if len(line) <= 20:
            if re.search(r'(보기|이동|확인|닫기|설정|변경|재생|중지)', line, re.IGNORECASE):
                should_remove = True
        
        if not should_remove:
            cleaned_lines.append(line)
    
    # 정제된 텍스트 합치기
    cleaned_content = '\n'.join(cleaned_lines)
    
    # 연속된 빈 줄 제거 (최대 2개 연속만 허용)
    cleaned_content = re.sub(r'\n{3,}', '\n\n', cleaned_content)
    
    # 앞뒤 공백 제거
    cleaned_content = cleaned_content.strip()
    
    return cleaned_content


def parse_news_from_url(url: str) -> Optional[Dict]:
    """
    URL에서 뉴스 기사를 파싱하여 기존 형식으로 변환합니다.
    
    Args:
        url: 뉴스 기사 URL
        
    Returns:
        파싱된 뉴스 기사 딕셔너리 (실패 시 None)
        형식: {
            "id": int (임시 ID, 음수로 설정하여 구분),
            "title": str,
            "summary": str,
            "content": str,
            "date": str (YYYY-MM-DD),
            "url": str
        }
    """
    if not url or not url.strip():
        return None
    
    url = url.strip()
    
    # URL 유효성 검사
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return None
    except Exception:
        return None
    
    try:
        # User-Agent 설정 (일부 사이트에서 차단 방지)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        # URL에서 HTML 가져오기
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        response.encoding = response.apparent_encoding or 'utf-8'
        
        # BeautifulSoup으로 파싱
        soup = BeautifulSoup(response.text, 'lxml')
        
        # 제목 추출 (여러 선택자 시도)
        title = None
        title_selectors = [
            'meta[property="og:title"]',
            'meta[name="twitter:title"]',
            'h1.article-title',
            'h1.headline',
            'h1',
            '.article-title',
            '.headline',
            'title'
        ]
        
        for selector in title_selectors:
            element = soup.select_one(selector)
            if element:
                title = element.get('content') or element.get_text(strip=True)
                if title:
                    break
        
        if not title:
            title = soup.find('title')
            title = title.get_text(strip=True) if title else "제목 없음"
        
        # 본문 추출 (여러 선택자 시도)
        content = None
        content_selectors = [
            'article',
            '.article-body',
            '.article-content',
            '.news-content',
            '.content',
            '[role="article"]',
            '.article_text',
            '#articleBody'
        ]
        
        for selector in content_selectors:
            element = soup.select_one(selector)
            if element:
                # 스크립트와 스타일 태그 제거
                for script in element(['script', 'style', 'nav', 'footer', 'aside']):
                    script.decompose()
                content = element.get_text(separator='\n', strip=True)
                if content and len(content) > 100:  # 최소 길이 체크
                    break
        
        # 본문을 찾지 못한 경우 body에서 추출
        if not content or len(content) < 100:
            body = soup.find('body')
            if body:
                for script in body(['script', 'style', 'nav', 'footer', 'aside', 'header']):
                    script.decompose()
                paragraphs = body.find_all(['p', 'div'])
                content_parts = [p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)]
                content = '\n'.join(content_parts)
        
        if not content or len(content) < 50:
            content = "본문을 추출할 수 없습니다."
        
        # 본문 정제: 불필요한 텍스트 제거 (제목도 함께 전달하여 중복 제거)
        content = _clean_article_content(content, title)
        
        # 날짜 추출
        date_str = None
        date_selectors = [
            'meta[property="article:published_time"]',
            'meta[name="publishdate"]',
            'meta[name="date"]',
            'time[datetime]',
            '.date',
            '.published-date'
        ]
        
        for selector in date_selectors:
            element = soup.select_one(selector)
            if element:
                date_str = element.get('content') or element.get('datetime') or element.get_text(strip=True)
                if date_str:
                    break
        
        # 날짜 파싱
        date = datetime.now().strftime("%Y-%m-%d")  # 기본값: 오늘
        if date_str:
            try:
                # ISO 형식 파싱 시도
                if 'T' in date_str:
                    date_obj = datetime.fromisoformat(date_str.replace('Z', '+00:00').split('T')[0])
                else:
                    # 다른 형식 시도
                    date_obj = datetime.strptime(date_str[:10], "%Y-%m-%d")
                date = date_obj.strftime("%Y-%m-%d")
            except Exception:
                pass
        
        # 요약 생성 (본문 앞부분 150자)
        summary = content[:150].strip()
        if len(content) > 150:
            summary += "..."
        
        # 임시 ID 생성 (음수로 설정하여 Supabase 뉴스와 구분)
        import hashlib
        url_hash = int(hashlib.md5(url.encode()).hexdigest()[:8], 16)
        temp_id = -(url_hash % 1000000)  # 음수 ID
        
        article = {
            "id": temp_id,
            "title": title,
            "summary": summary,
            "content": content,
            "date": date,
            "url": url
        }
        
        return article
        
    except requests.RequestException as e:
        print(f"URL 요청 실패: {e}")
        return None
    except Exception as e:
        print(f"뉴스 파싱 실패: {e}")
        return None
