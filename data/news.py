from typing import List, Dict
from datetime import datetime
import streamlit as st
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
