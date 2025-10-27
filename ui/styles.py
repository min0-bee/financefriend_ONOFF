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

/* 💬 챗봇 메시지 공통 스타일 */
.chat-message {
    padding: 10px;
    border-radius: 10px;
    margin: 5px 0;                 /* 메시지 간격 */
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

