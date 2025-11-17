# RAG 용어 응답 최적화 메모 (2025-11)

## 배경
- 용어 질문 처리 시 `explain_term()`이 **정의/비유/중요/오해/예시** 등 각 섹션마다 `albwoong_persona_rewrite_section()`을 호출했습니다.
- 해당 함수는 매번 OpenAI `llm_chat()`을 실행하므로, 용어 최초 요청 시 3~5회의 직렬 API 호출(약 7~10초 지연)이 발생했습니다.

## 변경 요약
| 항목 | 기존 | 변경 |
| --- | --- | --- |
| LLM 호출 횟수 | 섹션당 1회 (최소 3~5회) | 용어당 1회 |
| 설명 생성 방식 | 섹션별 재작성 후 수동 조합 | `generate_structured_persona_reply()`에 용어 메타데이터를 한 번에 전달 |
| 캐시 | 문자열 완성본 캐시 (용어별) | 동일하지만 최초 생성 시 1회 호출만 수행 |
| 실패 처리 | LLM 실패 시 빈 응답 | LLM 오류 시 원문 메타데이터를 간단히 포맷해 즉시 반환 |

## 동작 흐름 (요약)
1. RAG 또는 기본 사전에서 용어 메타데이터를 읽어와 사전 구조로 정리  
   - `_build_structured_context_from_metadata()`  
   - `_build_structured_context_from_default()`
2. `generate_structured_persona_reply()`에 `term`, `context`, `user_input`을 전달해 단일 JSON 구조 응답 생성
3. 결과를 캐시에 저장 → 동일 용어 재질의 시 실시간 호출 없음
4. 오류 발생 시 메타데이터를 간단한 텍스트로 포맷해 즉시 반환 (fallback)

## 기대 효과
- 새 용어 최초 질의에도 응답 지연이 약 1회 호출 수준(1~2초 내외)으로 단축
- OpenAI API 사용량 감소 (비용 절감)
- 구조화 응답 템플릿(`summary/detail/impact/analogy/reminder`) 유지 → 톤 관리 일관성 확보
- 캐시 전과 동일하게 사용 가능

## 참고
- 관련 코드: `rag/glossary.py` `explain_term()` / `persona/persona.py` `generate_structured_persona_reply()`
- 추가 최적화 아이디어: 프리컴파일된 용어 설명 저장, 백그라운드 캐시 리프레시 등 (필요 시 별도 논의)

