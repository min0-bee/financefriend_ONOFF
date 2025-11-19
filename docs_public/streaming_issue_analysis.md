# 실시간 스트리밍 문제 분석 및 해결 방안

## 문제 분석

### 1. RAG 검색은 빠른데 답변이 5초 이상 걸리는 이유

**현재 상황:**
- RAG 검색: 0.06ms (매우 빠름)
- LLM 응답 생성: 8초 (병목 지점)
- 체감 시간: 5초 이상

**원인:**
1. **스트리밍이 작동하지 않음**: `st.write_stream()`이 제대로 작동하지 않아 전체 응답이 완료될 때까지 기다려야 함
2. **HTML 기반 렌더링과 충돌**: `st.chat_message()`는 Streamlit 네이티브 컴포넌트인데, 현재 채팅 히스토리는 HTML로 렌더링됨
3. **스트리밍 완료 후에만 표시**: 스트리밍이 완료된 후에만 `chat_history`에 추가되므로, 스트리밍 중에는 보이지 않음

### 2. 실시간 스트리밍이 작동하지 않는 이유

**현재 구현:**
```python
with st.chat_message("assistant"):
    full_response = st.write_stream(stream_gen)
```

**문제점:**
1. **`st.write_stream()`의 동작 방식**: 제너레이터를 모두 소비한 후에만 반환하므로, 실시간으로 보이지 않을 수 있음
2. **HTML 렌더링과 충돌**: `st.chat_message()`는 Streamlit 네이티브 컴포넌트인데, 현재 채팅 히스토리는 HTML로 렌더링됨
3. **스트리밍 완료 후에만 추가**: 스트리밍이 완료된 후에만 `chat_history`에 추가되므로, 스트리밍 중에는 보이지 않음

## 해결 방안

### 방법 1: `st.empty()`를 사용한 실시간 업데이트 (권장)

**장점:**
- HTML 기반 렌더링과 호환
- 실시간으로 업데이트 가능
- 기존 구조 유지

**구현:**
```python
# 스트리밍 중 실시간 표시
streaming_placeholder = st.empty()
full_response = ""

for chunk in stream_gen:
    if isinstance(chunk, tuple) and chunk[0] == "__METADATA__":
        continue
    if chunk:
        full_response += str(chunk)
        # 실시간으로 HTML 업데이트
        streaming_placeholder.markdown(streaming_html, unsafe_allow_html=True)
```

### 방법 2: Streamlit 네이티브 컴포넌트로 전환

**장점:**
- `st.write_stream()`이 제대로 작동
- 실시간 스트리밍 자동 지원

**단점:**
- 기존 HTML 기반 렌더링 구조 변경 필요
- 큰 리팩토링 필요

### 방법 3: 하이브리드 접근

**구현:**
- 스트리밍 중: `st.empty()`로 실시간 표시
- 완료 후: `chat_history`에 추가하고 HTML로 렌더링

## 권장 해결 방법

**방법 1을 권장합니다:**
1. `st.empty()`를 사용하여 스트리밍 중 실시간 업데이트
2. HTML 기반 렌더링과 호환
3. 기존 구조 유지하면서 실시간 스트리밍 구현

