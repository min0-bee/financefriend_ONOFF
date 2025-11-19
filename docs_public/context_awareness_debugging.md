# 문맥 인식 기능 디버깅 가이드

## 확인 사항

### 1. CSV 파일 경로 확인
- 파일 위치: `rag/glossary/금융용어.csv`
- 함수: `load_glossary_from_csv()` (698줄)

### 2. 함수 호출 확인
- `_build_term_context_keywords()`: CSV에서 키워드 생성
- `get_financial_context_keywords(term)`: 용어별 키워드 조회
- `is_financial_context()`: 문맥 판단

### 3. 캐시 확인
- `_TERM_CONTEXT_KEYWORDS_CACHE`: 전역 캐시 변수
- 첫 호출 시에만 CSV 로드 및 키워드 생성

### 4. 파라미터 확인
- `highlight_terms()`의 `use_context_filter` 파라미터 (기본값: True)
- `article_detail.py`에서 호출 시 파라미터 전달 여부

## 디버깅 방법

### 1. 로그 추가
```python
# _build_term_context_keywords() 함수에 추가
st.info(f"📊 CSV에서 {len(df)}개 용어 로드")
st.info(f"📊 {len(term_keywords)}개 용어의 키워드 생성 완료")

# is_financial_context() 함수에 추가
st.info(f"🔍 용어 '{term}' 문맥 확인: {len(term_keywords)}개 키워드")
```

### 2. 테스트 코드
```python
# 테스트: 용어별 키워드 확인
keywords = get_financial_context_keywords("생산적금융")
st.write(f"생산적금융 키워드: {keywords}")

# 테스트: 문맥 판단
text = "정부는 생산적 금융을 확대하겠다고 밝혔다"
result = is_financial_context(text, "생산적금융", 5, 10)
st.write(f"문맥 판단 결과: {result}")
```

### 3. 캐시 초기화
```python
# 캐시 초기화 (디버깅용)
_TERM_CONTEXT_KEYWORDS_CACHE = None
```

## 일반적인 문제

### 1. CSV 파일을 찾을 수 없음
- 경로 확인: `rag/glossary/금융용어.csv`
- 파일 존재 여부 확인

### 2. 키워드 추출 실패
- `_extract_keywords_from_text()` 함수 확인
- 정규식 패턴 확인

### 3. 캐시 문제
- 전역 변수 `_TERM_CONTEXT_KEYWORDS_CACHE` 확인
- Streamlit 세션 간 공유 문제 가능

### 4. 함수 호출 안 됨
- `use_context_filter=True` 확인
- `is_financial_context()` 호출 여부 확인

