# URL/기사 기능 보호 가이드

## 문제

URL/기사 기능이 코드 수정할 때마다 사라지는 문제가 발생했습니다.

## 원인

1. **코드 수정 시 실수로 삭제**: 실수로 URL/기사 처리 코드 블록이 삭제됨
2. **조건문 변경**: 조건문 수정 시 URL/기사 처리 로직이 건너뛰어짐
3. **return 문 누락**: URL/기사 처리 후 return 문이 없어서 다음 로직이 실행됨

## 보호 조치

### 1. 명확한 주석 추가

```python
# ⚠️ 중요: URL/기사 기능 - 절대 삭제하지 말 것!
# 0) URL 감지 및 처리 (최우선)
urls = extract_urls_from_text(user_input)
if urls:
    # ... URL 처리 로직 ...
    return  # ⚠️ 반드시 return 필요

# ⚠️ 중요: 기사 찾기 기능 - 절대 삭제하지 말 것!
# 0-1) 기사 찾기 요청 감지 및 처리
is_search_request, keyword = detect_article_search_request(user_input)
if is_search_request and keyword:
    # ... 기사 검색 로직 ...
    return  # ⚠️ 반드시 return 필요
```

### 2. 함수 분리 (권장)

URL/기사 처리 로직을 별도 함수로 분리하여 보호:

```python
def handle_url_and_article_requests(user_input: str, profile, tracker) -> bool:
    """
    URL/기사 요청 처리
    
    Returns:
        True: URL/기사 요청이 처리되었음 (다음 로직 건너뛰기)
        False: URL/기사 요청이 아님 (다음 로직 계속)
    """
    # URL 처리
    urls = extract_urls_from_text(user_input)
    if urls:
        # ... URL 처리 로직 ...
        return True
    
    # 기사 검색 처리
    is_search_request, keyword = detect_article_search_request(user_input)
    if is_search_request and keyword:
        # ... 기사 검색 로직 ...
        return True
    
    return False
```

### 3. 테스트 코드 추가

URL/기사 기능이 작동하는지 확인하는 테스트 코드 추가:

```python
def test_url_article_features():
    """URL/기사 기능 테스트"""
    # URL 테스트
    assert extract_urls_from_text("https://example.com/news") == ["https://example.com/news"]
    
    # 기사 검색 테스트
    is_request, keyword = detect_article_search_request("금리에 대해 기사 보여줘")
    assert is_request == True
    assert keyword == "금리"
```

## 현재 구현 위치

- **URL 처리**: `ui/components/chat_panel.py` 447-505줄
- **기사 검색**: `ui/components/chat_panel.py` 507-570줄

## 주의사항

1. **절대 삭제하지 말 것**: URL/기사 처리 코드는 절대 삭제하지 마세요
2. **return 문 필수**: URL/기사 처리 후 반드시 `return` 문이 있어야 합니다
3. **성능 측정 종료**: URL/기사 처리 후 `profile.finish()`와 `tracker.finish_current_profile()` 호출 필수




