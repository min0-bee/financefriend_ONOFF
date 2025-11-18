import streamlit as st

# ─────────────────────────────────────────────────────────────
# 🎨 (1) CSS 스타일 정의
# ─────────────────────────────────────────────────────────────
# HTML처럼 Streamlit의 구성요소(뉴스 카드, 요약 박스, 챗봇 메시지 등)에
# 디자인 효과를 입히기 위한 CSS 코드입니다.
# Streamlit은 기본적으로 HTML/CSS를 직접 지원하지 않지만,
# `st.markdown(..., unsafe_allow_html=True)`을 통해 삽입할 수 있습니다.
# ─────────────────────────────────────────────────────────────

CSS = """
/* 📰 뉴스 카드 (뉴스 리스트에서 각각의 기사 박스 스타일) */
.news-card {
    padding: 15px;                /* 내부 여백 */
    border-radius: 10px;          /* 모서리 둥글게 */
    border: 1px solid #ddd;       /* 테두리 색 */
    margin: 10px 0;               /* 위아래 간격 */
    cursor: pointer;              /* 마우스 올리면 손가락 커서 표시 */
    transition: all 0.3s;         /* hover 시 부드럽게 전환 */
}

/* 뉴스 카드에 마우스를 올렸을 때 */
.news-card:hover {
    box-shadow: 0 4px 8px rgba(0,0,0,0.1);  /* 그림자 효과 */
    border-color: #1f77b4;                  /* 테두리 강조 색 */
}

/* 📦 뉴스 요약 박스 (상단 요약 섹션 스타일) */
.summary-box {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); /* 그라데이션 배경 */
    color: white;                  /* 글자색 흰색 */
    padding: 20px;                 /* 내부 여백 */
    border-radius: 15px;           /* 둥근 모서리 */
    margin-bottom: 20px;           /* 아래쪽 간격 */
}

/* 📰 기사 본문 영역 스타일 */
.article-content {
    background: #f9f9f9;           /* 연한 회색 배경 */
    padding: 20px;                 /* 내부 여백 */
    border-radius: 10px;           /* 둥근 모서리 */
    line-height: 1.8;              /* 줄 간격 넉넉하게 */
}

<<<<<<< HEAD
/* 💬 챗봇 메시지 공통 스타일 */
.chat-message {
    padding: 10px;
    border-radius: 10px;
    margin: 5px 0;                 /* 메시지 간격 */
=======
/* 💬 챗봇 메시지 컨테이너 */
.chat-message-container {
    padding-right: 4px;
    min-height: 300px;
    display: flex;
    flex-direction: column;
}

/* 화면을 꽉 채우기 위한 전체 레이아웃 조정 */
.main .block-container {
    padding-top: 1rem;
    padding-bottom: 1rem;
    max-width: 100%;
}

/* Streamlit 컬럼이 화면 높이를 최대한 활용하도록 */
[data-testid="column"] {
    display: flex;
    flex-direction: column;
}

/* 챗봇 컨테이너 - 우측 하단 플로팅 형태 (화면에 고정) */
[data-testid="column"]:has(#chat-scroll-box),
[data-testid="column"]:has(.chat-message-container) {
    position: fixed !important; /* 요소를 뷰포트에 고정 */
    bottom: 20px !important;    /* 화면 하단에서 20px 위로 */
    right: 20px !important;     /* 화면 오른쪽에서 20px 왼쪽으로 */
    z-index: 1000 !important;  /* 다른 요소들 위에 표시되도록 설정 */
    width: 400px !important;
    height: 600px !important;
    background: #ffffff !important;
    border-radius: 10px !important;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15) !important;
    display: flex !important;
    flex-direction: column !important;
    padding: 0 !important;
    box-sizing: border-box !important;
    overflow: hidden !important;
}

/* 메인 컨텐츠 영역 - 플로팅 챗봇이므로 여백 불필요 */
.main .block-container {
    padding-right: 0 !important;
    max-width: 100% !important;
}

/* 메인 컬럼 (뉴스 영역) - 전체 너비 사용 */
[data-testid="column"]:not(:has(#chat-scroll-box)):not(:has(.chat-message-container)) {
    width: 100% !important;
    max-width: 100% !important;
}

/* Streamlit 기본 사이드바와 챗봇 사이드바가 겹치지 않도록 */
[data-testid="stSidebar"] {
    z-index: 101 !important; /* Streamlit 사이드바가 챗봇 사이드바 위에 */
}

/* 챗 패널 영역 (chatbox) - 플로팅 챗봇 내부 스크롤 영역 */
#chat-scroll-box {
    flex: 1 !important;
    display: flex !important;
    flex-direction: column !important;
    padding: 10px !important;
    overflow-y: auto !important;
    min-height: 0 !important;
    max-height: calc(600px - 120px) !important; /* 전체 높이에서 제목/입력창 제외 */
}

/* 챗봇 제목 영역 */
[data-testid="column"]:has(#chat-scroll-box) h3,
[data-testid="column"]:has(.chat-message-container) h3 {
    margin: 0 !important;
    padding: 15px 15px 10px 15px !important;
    border-bottom: 1px solid #eee !important;
    font-size: 1rem !important;
}

/* 챗봇 구분선 */
[data-testid="column"]:has(#chat-scroll-box) hr,
[data-testid="column"]:has(.chat-message-container) hr {
    margin: 0 !important;
    padding: 0 !important;
    border: none !important;
    border-bottom: 1px solid #eee !important;
}

/* 챗봇 입력 영역 */
[data-testid="column"]:has(#chat-scroll-box) [data-testid="stChatInput"],
[data-testid="column"]:has(.chat-message-container) [data-testid="stChatInput"] {
    border-top: 1px solid #ccc !important;
    padding: 12px !important;
    margin: 0 !important;
}

/* 챗봇 초기화 버튼 */
[data-testid="column"]:has(#chat-scroll-box) button,
[data-testid="column"]:has(.chat-message-container) button {
    margin: 5px 15px 10px 15px !important;
    padding: 8px 12px !important;
>>>>>>> 181a128 (fix: 梨쀫큸 ?ш린 怨좎젙 諛??대? ?ㅽ겕濡?湲곕뒫 援ы쁽)
}

/* 👤 유저 메시지 (오른쪽 정렬 + 파란색 톤) */
.user-message {
    background: #e3f2fd;           /* 밝은 파란색 배경 */
    text-align: right;             /* 오른쪽 정렬 */
}

/* 🦉 챗봇 메시지 (왼쪽 정렬 + 회색 톤) */
.bot-message {
    background: #f5f5f5;           /* 밝은 회색 배경 */
}

/* 🟨 금융 용어 하이라이트 (기사 본문에서 하이라이트되는 단어) */
.financial-term {
    transition: all 0.2s;          /* hover 시 부드럽게 변화 */
    font-weight: 500;              /* 약간 굵게 */
}

/* 용어에 마우스를 올리면 강조 */
.financial-term:hover {
    background-color: #FDD835 !important;  /* 노란색 강조 */
    transform: scale(1.02);                /* 약간 커지게 */
    box-shadow: 0 2px 4px rgba(0,0,0,0.1); /* 그림자 효과 */
}

/* 하위 호환성: 이전 클래스명도 지원 */
.clickable-term {
    transition: all 0.2s;
    font-weight: 500;
}

.clickable-term:hover {
    background-color: #FDD835 !important;
    transform: scale(1.02);
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}
"""

# ─────────────────────────────────────────────────────────────
# 🧩 (2) CSS를 Streamlit에 주입하는 함수
# ─────────────────────────────────────────────────────────────
# Streamlit은 기본적으로 CSS 파일을 직접 import할 수 없기 때문에
# markdown을 통해 HTML <style> 태그 형태로 삽입합니다.
# unsafe_allow_html=True 옵션을 반드시 줘야 HTML/CSS가 적용됩니다.
# ─────────────────────────────────────────────────────────────
def inject_styles():
    st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)

