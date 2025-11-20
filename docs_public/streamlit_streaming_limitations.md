# Streamlit에서 실시간 스트리밍이 작동하지 않는 이유 분석

## 핵심 문제

Streamlit은 **정적 페이지 렌더링**에 최적화된 프레임워크이며, 실시간 스트리밍과 같은 **동적 콘텐츠 업데이트**에 근본적인 제약이 있습니다.

## 주요 제약사항

### 1. Streamlit의 실행 모델

**문제:**
- Streamlit은 스크립트를 **위에서 아래로 한 번에 실행**합니다
- 스크립트가 완전히 실행될 때까지 **UI 업데이트가 보이지 않습니다**
- `st.empty().markdown()`을 여러 번 호출해도, 스크립트가 끝나기 전까지는 **마지막 상태만 표시**됩니다

**예시:**
```python
placeholder = st.empty()
for chunk in stream_gen:
    placeholder.markdown(chunk)  # ❌ 실시간으로 보이지 않음
    # 스크립트가 끝나야 UI가 업데이트됨
```

### 2. `st.write_stream()`의 한계

**문제:**
- `st.write_stream()`은 제너레이터를 **모두 소비한 후에만 반환**합니다
- 스트리밍 중에는 **실제로 보이지 않을 수 있습니다**
- HTML 기반 렌더링과 **충돌**할 수 있습니다

**현재 구현:**
```python
with st.chat_message("assistant"):
    full_response = st.write_stream(stream_gen)  # ❌ 완료 후에만 표시
```

### 3. HTML 기반 렌더링과의 충돌

**문제:**
- 현재 채팅 히스토리는 **HTML로 렌더링**됩니다
- `st.chat_message()`는 **Streamlit 네이티브 컴포넌트**입니다
- 두 방식이 **혼재**되어 있어 스트리밍이 제대로 작동하지 않습니다

**현재 구조:**
```python
# HTML 기반 렌더링
chat_html = "<div>...</div>"
st.markdown(chat_html, unsafe_allow_html=True)

# Streamlit 네이티브 컴포넌트 (충돌)
with st.chat_message("assistant"):
    st.write_stream(stream_gen)  # ❌ HTML과 충돌
```

### 4. `st.empty()`의 제약

**문제:**
- `st.empty().markdown()`을 반복 호출해도, **스크립트 실행 중에는 업데이트가 보이지 않습니다**
- Streamlit은 **스크립트 완료 후에만 UI를 업데이트**합니다
- 실시간 업데이트를 위해서는 **`st.rerun()`이 필요**하지만, 이는 성능 문제를 일으킵니다

**현재 구현:**
```python
placeholder = st.empty()
for chunk in stream_gen:
    placeholder.markdown(chunk)  # ❌ 실시간으로 보이지 않음
    # 스크립트가 끝나야 마지막 상태만 표시됨
```

## 왜 작동하지 않는가?

### 기술적 이유

1. **단일 스레드 실행 모델**
   - Streamlit은 Python 스크립트를 **단일 스레드**로 실행
   - 스크립트 실행 중에는 **UI 업데이트가 불가능**
   - 스크립트 완료 후에만 **DOM 업데이트**가 발생

2. **렌더링 타이밍**
   - Streamlit은 **전체 스크립트 실행 후**에만 브라우저에 전송
   - 중간 상태는 **무시**되고 마지막 상태만 표시
   - 실시간 업데이트를 위해서는 **여러 번의 스크립트 실행**이 필요

3. **상태 관리**
   - `st.session_state`는 **스크립트 실행 사이**에만 유지
   - 스크립트 실행 중에는 **상태 변경이 반영되지 않음**

### 아키텍처적 이유

1. **정적 페이지 설계**
   - Streamlit은 **정적 페이지 렌더링**에 최적화
   - 동적 콘텐츠 업데이트는 **부차적 기능**
   - 실시간 스트리밍은 **설계 목적과 다름**

2. **서버-클라이언트 통신**
   - Streamlit은 **요청-응답 모델**을 사용
   - 실시간 스트리밍은 **서버 푸시 모델**이 필요
   - 기본 아키텍처가 **호환되지 않음**

## 해결 방법

### 방법 1: `st.rerun()` 사용 (비권장)

**장점:**
- 실시간 업데이트 가능

**단점:**
- **매우 느림** (스크립트 전체 재실행)
- **성능 문제** 심각
- **사용자 경험 저하**

```python
for chunk in stream_gen:
    placeholder.markdown(chunk)
    st.rerun()  # ❌ 매우 느림, 비권장
```

### 방법 2: Streamlit 네이티브 컴포넌트로 전환 (권장)

**장점:**
- `st.write_stream()`이 제대로 작동
- 실시간 스트리밍 자동 지원

**단점:**
- 기존 HTML 기반 렌더링 구조 **대규모 변경 필요**
- 큰 리팩토링 필요

```python
# HTML 기반 렌더링 제거
# Streamlit 네이티브 컴포넌트 사용
for message in st.session_state.chat_history:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 스트리밍 응답
with st.chat_message("assistant"):
    st.write_stream(stream_gen)  # ✅ 작동함
```

### 방법 3: JavaScript를 사용한 실시간 업데이트

**장점:**
- 완전한 실시간 스트리밍 가능
- 기존 구조 유지

**단점:**
- **복잡한 구현** 필요
- JavaScript와 Python 간 **동기화** 필요

```python
# JavaScript를 사용하여 실시간 업데이트
st_html("""
<script>
// WebSocket 또는 Server-Sent Events 사용
// 실시간으로 DOM 업데이트
</script>
""")
```

### 방법 4: 다른 프레임워크 사용 (근본적 해결)

**권장 프레임워크:**
- **FastAPI + WebSocket**: 완전한 실시간 스트리밍
- **Flask + Socket.IO**: 실시간 양방향 통신
- **Gradio**: 스트리밍에 최적화된 UI

## 결론

### 핵심 문제

**Streamlit은 실시간 스트리밍에 적합하지 않습니다.**

이유:
1. **정적 페이지 렌더링**에 최적화
2. **단일 스레드 실행 모델**
3. **스크립트 완료 후에만 UI 업데이트**
4. **서버 푸시 모델 미지원**

### 권장 해결책

1. **단기**: `st.write_stream()` 사용 (네이티브 컴포넌트로 전환)
2. **중기**: JavaScript를 사용한 실시간 업데이트
3. **장기**: FastAPI + WebSocket으로 마이그레이션

### 현실적인 대안

**체감 시간 개선을 위한 대안:**
1. **스트리밍 수집 후 표시**: 현재 방식 유지, 응답 시간 단축에 집중
2. **로딩 인디케이터**: 스트리밍 중 로딩 표시로 체감 시간 개선
3. **응답 캐싱**: 반복 질문에 대해 즉시 응답

## 참고 자료

- [Streamlit 공식 문서 - 스트리밍](https://docs.streamlit.io/)
- [Streamlit GitHub Issues - 스트리밍 관련 이슈](https://github.com/streamlit/streamlit/issues)




