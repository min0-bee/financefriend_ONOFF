"""실제 질의와 답변을 가져오는 스크립트"""
import sys
from pathlib import Path

script_dir = Path(__file__).parent.parent
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))

from persona.persona import generate_structured_persona_reply
from persona.persona_optimized import generate_structured_persona_reply_optimized
import time
import json

prompt = "인플레이션이 뭐야?"

# 원본 버전
start = time.perf_counter()
resp1 = generate_structured_persona_reply(prompt)
t1 = time.perf_counter() - start

# 최적화 버전
start = time.perf_counter()
resp2, meta = generate_structured_persona_reply_optimized(prompt)
t2 = time.perf_counter() - start

# JSON으로 저장
with open("sample_responses.json", "w", encoding="utf-8") as f:
    json.dump({
        "prompt": prompt,
        "original": {
            "response": resp1,
            "time_seconds": t1
        },
        "optimized": {
            "response": resp2,
            "time_seconds": t2,
            "metadata": meta
        }
    }, f, indent=2, ensure_ascii=False)

print("완료: sample_responses.json에 저장되었습니다.")

