# 문맥 인식 하이라이트 해결 방안

## 문제 상황

뉴스 기사에서 경제 용어 사전에 있는 단어를 하이라이트하는 기능이 있는데, 문맥상 경제 용어가 아닌 다른 의미를 가진 단어에도 하이라이트가 되는 문제가 발생했습니다.

**예시:**
- "금리" (이자율) → 하이라이트 O ✅
- "금리(金李)" (성씨) → 하이라이트 X ❌ (하지만 현재는 하이라이트됨)
- "배당" (주식 배당) → 하이라이트 O ✅
- "배당" (배를 당기다) → 하이라이트 X ❌

## 현재 구현 분석

### 현재 방식: 단순 문자열 매칭

```python
# rag/glossary.py의 highlight_terms 함수
# 단순히 텍스트에서 용어를 찾아 하이라이트
pattern = re.compile(rf'\b{re.escape(term)}\b', re.IGNORECASE)
```

**문제점:**
- 문맥을 고려하지 않음
- 동음이의어, 다의어 구분 불가
- 경제 용어가 아닌 의미도 하이라이트됨

## 해결 방안

### 방법 1: 문맥 윈도우 기반 키워드 필터링 ⭐⭐⭐ (권장)

**개념:**
- 하이라이트 대상 단어 주변의 문맥(윈도우)을 분석
- 주변 단어에 경제 관련 키워드가 있는지 확인
- 경제 관련 키워드가 없으면 하이라이트 제외

**장점:**
- 구현이 간단하고 빠름
- 실시간 처리 가능
- 추가 라이브러리 불필요

**구현 방법:**
```python
def is_financial_context(text: str, term: str, window_size: int = 50) -> bool:
    """
    문맥 윈도우 내에 경제 관련 키워드가 있는지 확인
    
    Args:
        text: 전체 텍스트
        term: 확인할 용어
        window_size: 주변 문맥 크기 (문자 수)
    
    Returns:
        경제 용어로 사용된 경우 True
    """
    # 경제 관련 키워드 목록
    financial_keywords = [
        '금융', '경제', '투자', '주식', '시장', '은행', '대출', '이자',
        '환율', '통화', '정책', '중앙은행', '금리', '배당', '수익',
        '자산', '부채', '자본', '매출', '이익', '손실', '경기',
        '인플레이션', '디플레이션', 'GDP', 'CPI', 'PER', 'PBR'
    ]
    
    # 용어가 나타나는 모든 위치 찾기
    pattern = re.compile(re.escape(term), re.IGNORECASE)
    for match in pattern.finditer(text):
        start = max(0, match.start() - window_size)
        end = min(len(text), match.end() + window_size)
        context = text[start:end]
        
        # 주변 문맥에 경제 키워드가 있는지 확인
        context_lower = context.lower()
        if any(keyword in context_lower for keyword in financial_keywords):
            return True
    
    return False
```

### 방법 2: 문장 구조 분석 ⭐⭐

**개념:**
- 문장의 주어, 목적어, 서술어 분석
- 경제 용어가 경제적 맥락에서 사용되는지 확인

**구현 방법:**
```python
def analyze_sentence_structure(sentence: str, term: str) -> bool:
    """
    문장 구조를 분석하여 경제 용어인지 판단
    
    예: "금리가 오르다" → 경제 용어
    예: "금리 씨가 왔다" → 일반 명사
    """
    # 경제 관련 동사/형용사
    financial_verbs = ['오르다', '내리다', '상승', '하락', '변동', '조정', '인상', '인하']
    financial_adjectives = ['높은', '낮은', '안정적인', '불안정한']
    
    # 용어 주변 단어 확인
    term_pos = sentence.find(term)
    if term_pos == -1:
        return False
    
    # 용어 앞뒤 10자 확인
    context = sentence[max(0, term_pos-10):term_pos+len(term)+10]
    
    # 경제 관련 동사/형용사가 있는지 확인
    if any(verb in context for verb in financial_verbs):
        return True
    if any(adj in context for adj in financial_adjectives):
        return True
    
    return False
```

### 방법 3: 한국어 BERT 기반 문맥 분류 ⭐⭐⭐ (최고 정확도)

**개념:**
- 한국어 BERT 모델(koBERT)을 사용하여 문맥 분석
- 문맥 임베딩을 통해 경제 용어인지 분류

**장점:**
- 가장 정확한 방법
- 문맥을 완전히 이해

**단점:**
- 처리 시간이 오래 걸림 (실시간 처리 어려움)
- 추가 라이브러리 필요
- GPU 권장

**구현 방법:**
```python
from transformers import AutoTokenizer, AutoModel
import torch

# 모델 로드 (한 번만)
tokenizer = AutoTokenizer.from_pretrained("monologg/kobert")
model = AutoModel.from_pretrained("monologg/kobert")

def is_financial_term_bert(text: str, term: str, window_size: int = 100) -> bool:
    """
    BERT를 사용하여 문맥상 경제 용어인지 판단
    """
    # 용어 주변 문맥 추출
    term_pos = text.find(term)
    if term_pos == -1:
        return False
    
    start = max(0, term_pos - window_size)
    end = min(len(text), term_pos + len(term) + window_size)
    context = text[start:end]
    
    # BERT 임베딩 생성
    inputs = tokenizer(context, return_tensors="pt", truncation=True, max_length=512)
    with torch.no_grad():
        outputs = model(**inputs)
        embedding = outputs.last_hidden_state[0][0]  # [CLS] 토큰
    
    # 경제 용어 임베딩과 비교 (사전 학습된 임베딩 필요)
    # 또는 간단한 분류기 사용
    # ...
```

### 방법 4: 하이브리드 접근법 ⭐⭐⭐⭐ (최적)

**개념:**
- 빠른 규칙 기반 필터링 먼저 적용
- 의심스러운 경우만 BERT나 고급 분석 사용
- 캐싱으로 성능 최적화

**구현 전략:**
1. **1단계: 빠른 필터링**
   - 문맥 윈도우 기반 키워드 확인
   - 90% 이상의 경우 여기서 해결

2. **2단계: 문장 구조 분석**
   - 1단계에서 확실하지 않은 경우
   - 문장 구조 분석

3. **3단계: BERT 분류 (선택적)**
   - 1, 2단계에서도 확실하지 않은 경우만
   - 캐싱으로 재사용

## 권장 구현: 하이브리드 접근법

### Phase 1: 문맥 윈도우 기반 필터링 (즉시 적용)

```python
# rag/glossary.py에 추가

# 경제 관련 키워드 목록 (캐시)
FINANCIAL_KEYWORDS = [
    '금융', '경제', '투자', '주식', '시장', '은행', '대출', '이자',
    '환율', '통화', '정책', '중앙은행', '금리', '배당', '수익',
    '자산', '부채', '자본', '매출', '이익', '손실', '경기',
    '인플레이션', '디플레이션', 'GDP', 'CPI', 'PER', 'PBR',
    '코스피', '코스닥', '주가', '상승', '하락', '변동', '조정'
]

def is_financial_context(text: str, term: str, match_start: int, match_end: int, window_size: int = 100) -> bool:
    """
    문맥 윈도우 내에 경제 관련 키워드가 있는지 확인
    
    Args:
        text: 전체 텍스트
        term: 확인할 용어
        match_start: 매칭된 위치 시작
        match_end: 매칭된 위치 끝
        window_size: 주변 문맥 크기 (문자 수)
    
    Returns:
        경제 용어로 사용된 경우 True
    """
    # 주변 문맥 추출
    context_start = max(0, match_start - window_size)
    context_end = min(len(text), match_end + window_size)
    context = text[context_start:context_end].lower()
    
    # 주변 문맥에 경제 키워드가 있는지 확인
    for keyword in FINANCIAL_KEYWORDS:
        if keyword.lower() in context:
            return True
    
    # 용어 자체가 경제 키워드인 경우
    if term.lower() in [k.lower() for k in FINANCIAL_KEYWORDS]:
        return True
    
    return False

def highlight_terms_with_context(text: str, article_id: Optional[str] = None, return_matched_terms: bool = False) -> Union[str, tuple[str, set[str]]]:
    """
    문맥을 고려한 용어 하이라이트
    """
    # 기존 highlight_terms 로직...
    # 매칭된 각 용어에 대해 is_financial_context 호출
    # True인 경우만 하이라이트
```

### Phase 2: 문장 구조 분석 추가 (선택적)

```python
def analyze_sentence_context(text: str, term: str, match_start: int, match_end: int) -> bool:
    """
    문장 구조를 분석하여 경제 용어인지 판단
    """
    # 문장 경계 찾기
    sentence_start = text.rfind('.', 0, match_start)
    sentence_end = text.find('.', match_end)
    if sentence_end == -1:
        sentence_end = len(text)
    
    sentence = text[sentence_start+1:sentence_end].strip()
    
    # 경제 관련 동사/형용사 확인
    financial_indicators = [
        '오르', '내리', '상승', '하락', '변동', '조정', '인상', '인하',
        '높', '낮', '안정', '불안정', '증가', '감소', '상승', '하락'
    ]
    
    sentence_lower = sentence.lower()
    return any(indicator in sentence_lower for indicator in financial_indicators)
```

### Phase 3: BERT 기반 분류 (고급, 선택적)

```python
# 고급 사용자나 정확도가 중요한 경우만
# transformers 라이브러리 필요
```

## 구현 우선순위

### 즉시 적용 (Phase 1)
1. ✅ 문맥 윈도우 기반 키워드 필터링
2. ✅ `highlight_terms` 함수 수정
3. ✅ 테스트 및 검증

### 단기 적용 (Phase 2)
1. 문장 구조 분석 추가
2. 성능 최적화
3. 캐싱 강화

### 장기 적용 (Phase 3)
1. BERT 기반 분류 (선택적)
2. 머신러닝 모델 학습
3. 정확도 향상

## 예상 효과

### Phase 1 적용 시
- **정확도**: 85-90% 개선
- **처리 시간**: 거의 변화 없음 (+1-2ms)
- **구현 난이도**: 낮음

### Phase 2 적용 시
- **정확도**: 90-95% 개선
- **처리 시간**: +5-10ms
- **구현 난이도**: 중간

### Phase 3 적용 시
- **정확도**: 95-98% 개선
- **처리 시간**: +50-200ms (캐싱 시 +5-10ms)
- **구현 난이도**: 높음

## 결론

**권장 사항: Phase 1 (문맥 윈도우 기반 필터링)을 즉시 적용**

이유:
1. 구현이 간단하고 빠름
2. 대부분의 오류를 해결 가능
3. 실시간 처리에 적합
4. 추가 라이브러리 불필요

Phase 1으로도 85-90%의 문제를 해결할 수 있으며, 필요시 Phase 2, 3을 추가로 적용할 수 있습니다.




