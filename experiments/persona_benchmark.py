from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from statistics import mean
from typing import Dict, List, Optional, Tuple

# 현재 스크립트의 부모 디렉터리를 Python 경로에 추가
script_dir = Path(__file__).parent.parent
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))

from persona.persona import generate_structured_persona_reply
from persona.persona_optimized import (
    PERSONA_LOGGER,
    generate_structured_persona_reply_optimized,
)


def _time_call_original(prompt: str, term: Optional[str]) -> Tuple[str, float]:
    start = time.perf_counter()
    response = generate_structured_persona_reply(prompt, term=term)
    latency = time.perf_counter() - start
    return response, latency


def _time_call_optimized(prompt: str, term: Optional[str]) -> Tuple[str, Dict[str, float]]:
    formatted, metadata = generate_structured_persona_reply_optimized(prompt, term=term)
    latency = metadata.get("latency_seconds", 0.0)
    tokens = metadata.get("tokens", {}) or {}
    return formatted, {
        "latency": latency,
        "input_tokens": tokens.get("input"),
        "output_tokens": tokens.get("output"),
        "total_tokens": tokens.get("total"),
    }


def benchmark(
    prompt: str,
    term: Optional[str],
    runs: int = 10,
) -> Dict[str, Dict[str, float]]:
    original_latencies: List[float] = []
    optimized_latencies: List[float] = []
    optimized_input_tokens: List[float] = []
    optimized_output_tokens: List[float] = []
    optimized_total_tokens: List[float] = []

    print(f"\n🔄 벤치마크 시작: {runs}회 실행 (원본 {runs}회 + 최적화 {runs}회 = 총 {runs * 2}회 API 호출)\n")

    for idx in range(runs):
        print(f"[{idx + 1}/{runs}] 원본 버전 실행 중...", end=" ", flush=True)
        _, latency_orig = _time_call_original(prompt, term)
        original_latencies.append(latency_orig)
        print(f"완료 ({latency_orig:.2f}초)")

        print(f"[{idx + 1}/{runs}] 최적화 버전 실행 중...", end=" ", flush=True)
        _, meta_opt = _time_call_optimized(prompt, term)
        optimized_latencies.append(meta_opt["latency"])
        print(f"완료 ({meta_opt['latency']:.2f}초)")

        for collector, key in [
            (optimized_input_tokens, "input_tokens"),
            (optimized_output_tokens, "output_tokens"),
            (optimized_total_tokens, "total_tokens"),
        ]:
            value = meta_opt.get(key)
            if value is not None:
                collector.append(value)

        PERSONA_LOGGER.info("benchmark_run=%s | original=%.3fs | optimized=%.3fs", idx, latency_orig, meta_opt["latency"])
        print()  # 빈 줄 추가

    return {
        "original": {
            "average_latency": mean(original_latencies),
            "min_latency": min(original_latencies),
            "max_latency": max(original_latencies),
        },
        "optimized": {
            "average_latency": mean(optimized_latencies),
            "min_latency": min(optimized_latencies),
            "max_latency": max(optimized_latencies),
            "average_input_tokens": mean(optimized_input_tokens) if optimized_input_tokens else 0.0,
            "average_output_tokens": mean(optimized_output_tokens) if optimized_output_tokens else 0.0,
            "average_total_tokens": mean(optimized_total_tokens) if optimized_total_tokens else 0.0,
        },
    }


def cli() -> None:
    parser = argparse.ArgumentParser(description="Compare original vs optimized persona latency.")
    parser.add_argument("--prompt", required=True, help="User question to send.")
    parser.add_argument("--term", default=None, help="Optional focus term.")
    parser.add_argument("--runs", type=int, default=10, help="Number of repeats per persona.")
    parser.add_argument("--output", default=None, help="Optional path to save JSON results.")
    args = parser.parse_args()

    results = benchmark(args.prompt, args.term, args.runs)
    
    print("\n" + "=" * 60)
    print("📊 벤치마크 결과 요약")
    print("=" * 60)
    orig = results["original"]
    opt = results["optimized"]
    print(f"\n원본 버전:")
    print(f"  평균 응답 시간: {orig['average_latency']:.2f}초")
    print(f"  최소: {orig['min_latency']:.2f}초 | 최대: {orig['max_latency']:.2f}초")
    print(f"\n최적화 버전:")
    print(f"  평균 응답 시간: {opt['average_latency']:.2f}초")
    print(f"  최소: {opt['min_latency']:.2f}초 | 최대: {opt['max_latency']:.2f}초")
    if opt.get("average_input_tokens"):
        print(f"  평균 입력 토큰: {opt['average_input_tokens']:.0f}")
        print(f"  평균 출력 토큰: {opt['average_output_tokens']:.0f}")
        print(f"  평균 총 토큰: {opt['average_total_tokens']:.0f}")
    
    improvement = ((orig['average_latency'] - opt['average_latency']) / orig['average_latency']) * 100
    print(f"\n⚡ 성능 개선: {improvement:+.1f}% ({orig['average_latency']:.2f}초 → {opt['average_latency']:.2f}초)")
    print("=" * 60 + "\n")
    
    print("전체 결과 (JSON):")
    print(json.dumps(results, indent=2, ensure_ascii=False))

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fp:
            json.dump(results, fp, indent=2, ensure_ascii=False)
        print(f"\n✅ 결과가 {args.output}에 저장되었습니다.")


if __name__ == "__main__":
    cli()


