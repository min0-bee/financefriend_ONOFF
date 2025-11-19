# URL/기사 기능 하이라이트 확인

## 현재 상태

### 1. URL로 가져온 기사 처리 흐름

```
1. 사용자가 URL 입력
   ↓
2. parse_news_from_url(url) 호출
   ↓
3. article 객체 생성 및 st.session_state.selected_article에 저장
   ↓
4. article_detail.py의 render() 함수 호출
   ↓
5. highlight_terms() 호출 (문맥 인식 활성화)
   ↓
6. 하이라이트된 기사 내용 표시
```

### 2. 하이라이트 적용 확인

**article_detail.py (32줄):**
```python
result = highlight_terms(
    content, 
    article_id=str(article_id) if article_id else None, 
    return_matched_terms=True,
    use_context_filter=True  # ⚡ 문맥 인식 활성화
)
```

**확인 사항:**
- ✅ `highlight_terms()` 함수 호출됨
- ✅ `use_context_filter=True` 명시적으로 설정
- ✅ 문맥 인식 함수 `is_financial_context()` 호출됨

### 3. 문제 가능성

#### 문제 1: article_id가 None인 경우
- URL로 가져온 기사는 `id`가 없을 수 있음
- 캐싱이 제대로 작동하지 않을 수 있음
- 하지만 하이라이트 자체는 작동해야 함

#### 문제 2: 문맥 인식이 작동하지 않는 경우
- `_build_term_context_keywords()` 함수가 호출되지 않음
- CSV 로드 실패
- 키워드 추출 실패

#### 문제 3: 캐시 문제
- 이전에 캐시된 결과가 사용됨 (문맥 인식 적용 전)
- 캐시를 초기화해야 할 수 있음

## 해결 방법

### 1. 명시적으로 use_context_filter=True 설정
- ✅ 완료: `article_detail.py`에 명시적으로 추가

### 2. 디버깅 로그 추가
```python
# highlight_terms 함수에 추가
if use_context_filter:
    st.info(f"🔍 문맥 인식 활성화: 용어 '{term}' 확인 중...")
```

### 3. 캐시 초기화
- Streamlit 앱 재시작
- 또는 캐시 키 변경

### 4. 테스트
- URL로 기사 가져오기
- 경제 용어가 아닌 의미로 사용된 단어 확인
- 하이라이트 여부 확인

## 확인 체크리스트

- [ ] URL로 기사를 가져왔는가?
- [ ] article_detail.py의 render() 함수가 호출되는가?
- [ ] highlight_terms() 함수가 호출되는가?
- [ ] use_context_filter=True로 설정되어 있는가?
- [ ] is_financial_context() 함수가 호출되는가?
- [ ] CSV에서 키워드가 제대로 로드되는가?
- [ ] 문맥 판단이 제대로 작동하는가?

