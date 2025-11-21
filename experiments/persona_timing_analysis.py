"""
상세한 응답시간 분석 스크립트

각 단계별 시간을 측정하여 병목 지점을 파악합니다:
- 프롬프트 빌드 시간
- API 호출 시간 (네트워크 + 모델 처리)
- 파싱 시간
- 포맷팅 시간
- 로깅 오버헤드
- 토큰 추정 오버헤드
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from statistics import mean, stdev
from typing import Dict, List, Optional, Tuple

# 현재 스크립트의 부모 디렉터리를 Python 경로에 추가
script_dir = Path(__file__).parent.parent
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))

import persona.persona as persona_module
import persona.persona_optimized as persona_optimized_module
from core.utils import llm_chat

# Private 함수들을 안전하게 가져오기
build_messages_original = persona_module._build_messages_for_structured_reply
parse_structured_response = persona_module._parse_structured_response
format_structured_output = persona_module._format_structured_output
generate_structured_persona_reply = persona_module.generate_structured_persona_reply

build_messages_optimized = persona_optimized_module._build_messages_for_structured_reply
_estimate_token_count = persona_optimized_module._estimate_token_count
_log_prompt_stats = persona_optimized_module._log_prompt_stats
optimized_llm_chat = persona_optimized_module.optimized_llm_chat
generate_structured_persona_reply_optimized = persona_optimized_module.generate_structured_persona_reply_optimized
PERSONA_LOGGER = persona_optimized_module.PERSONA_LOGGER


class TimingContext:
    """단계별 시간 측정을 위한 컨텍스트 매니저"""
    
    def __init__(self, timings: Dict[str, List[float]], step_name: str):
        self.timings = timings
        self.step_name = step_name
        self.start_time = None
        
    def __enter__(self):
        self.start_time = time.perf_counter()
        return self
        
    def __exit__(self, *args):
        elapsed = time.perf_counter() - self.start_time
        if self.step_name not in self.timings:
            self.timings[self.step_name] = []
        self.timings[self.step_name].append(elapsed)


def analyze_original_timing(
    user_input: str,
    term: Optional[str] = None,
    context: Optional[Dict[str, str]] = None,
) -> Tuple[str, Dict[str, float]]:
    """원본 버전의 단계별 시간 측정"""
    timings: Dict[str, List[float]] = {}
    
    # 1. 프롬프트 빌드
    with TimingContext(timings, "build_messages"):
        messages = build_messages_original(user_input, term, context)
    
    # 2. API 호출
    with TimingContext(timings, "api_call"):
        raw = llm_chat(messages, temperature=0.3, max_tokens=700)
    
    # 3. 파싱
    with TimingContext(timings, "parse_response"):
        structured = parse_structured_response(raw)
    
    # 4. 포맷팅
    with TimingContext(timings, "format_output"):
        formatted = format_structured_output(structured, term, user_input)
    
    # 전체 시간
    total_time = sum(sum(times) for times in timings.values())
    
    return formatted, {
        "total": total_time,
        **{k: sum(v) for k, v in timings.items()},
        "message_count": len(messages),
    }


def analyze_optimized_timing(
    user_input: str,
    term: Optional[str] = None,
    context: Optional[Dict[str, str]] = None,
) -> Tuple[str, Dict[str, float]]:
    """최적화 버전의 단계별 시간 측정"""
    timings: Dict[str, List[float]] = {}
    
    # 1. 프롬프트 빌드
    with TimingContext(timings, "build_messages"):
        messages = build_messages_optimized(user_input, term, context)
    
    # 2. 토큰 추정 (최적화 버전에만 있음)
    with TimingContext(timings, "token_estimation"):
        model = "gpt-4o-mini"
        token_count = _estimate_token_count(messages, model)
    
    # 3. 로깅 (최적화 버전에만 있음)
    with TimingContext(timings, "logging_overhead"):
        _log_prompt_stats(messages, model, None)  # logger=None이면 실제로는 스킵
    
    # 4. API 호출
    with TimingContext(timings, "api_call"):
        raw, metadata = optimized_llm_chat(
            messages,
            temperature=0.3,
            max_tokens=400,
            stream=False,
            logger=None,
        )
    
    # 5. 파싱
    with TimingContext(timings, "parse_response"):
        structured = parse_structured_response(raw)
    
    # 6. 포맷팅
    with TimingContext(timings, "format_output"):
        formatted = format_structured_output(structured, term, user_input)
    
    # 전체 시간
    total_time = sum(sum(times) for times in timings.values())
    
    return formatted, {
        "total": total_time,
        **{k: sum(v) for k, v in timings.items()},
        "message_count": len(messages),
        "token_estimate": token_count,
        "api_latency_from_metadata": metadata.get("latency_seconds", 0),
        "input_tokens": metadata.get("tokens", {}).get("input") if metadata.get("tokens") else None,
        "output_tokens": metadata.get("tokens", {}).get("output") if metadata.get("tokens") else None,
    }


def benchmark_detailed(
    prompt: str,
    term: Optional[str] = None,
    context: Optional[Dict[str, str]] = None,
    runs: int = 10,
) -> Dict:
    """상세한 벤치마크 실행"""
    
    original_results: List[Dict] = []
    optimized_results: List[Dict] = []
    
    print(f"\n[상세 응답시간 분석 시작] {runs}회 실행\n")
    print("=" * 80)
    
    for idx in range(runs):
        print(f"\n[{idx + 1}/{runs}] 실행 중...")
        
        # 원본 측정
        print("  원본 버전 측정 중...", end=" ", flush=True)
        _, orig_timing = analyze_original_timing(prompt, term, context)
        original_results.append(orig_timing)
        print(f"완료 (총 {orig_timing['total']:.3f}초)")
        
        # 최적화 측정
        print("  최적화 버전 측정 중...", end=" ", flush=True)
        _, opt_timing = analyze_optimized_timing(prompt, term, context)
        optimized_results.append(opt_timing)
        print(f"완료 (총 {opt_timing['total']:.3f}초)")
        
        # 간단한 비교
        diff = opt_timing['total'] - orig_timing['total']
        diff_pct = (diff / orig_timing['total']) * 100 if orig_timing['total'] > 0 else 0
        print(f"  차이: {diff:+.3f}초 ({diff_pct:+.1f}%)")
    
    print("\n" + "=" * 80)
    
    # 통계 계산
    def calc_stats(values: List[float]) -> Dict:
        if not values:
            return {}
        return {
            "mean": mean(values),
            "min": min(values),
            "max": max(values),
            "stdev": stdev(values) if len(values) > 1 else 0.0,
        }
    
    # 원본 통계
    orig_stats = {}
    for key in ["total", "build_messages", "api_call", "parse_response", "format_output"]:
        values = [r.get(key, 0) for r in original_results if key in r]
        if values:
            orig_stats[key] = calc_stats(values)
    
    # 최적화 통계
    opt_stats = {}
    for key in ["total", "build_messages", "api_call", "parse_response", "format_output", 
                "token_estimation", "logging_overhead"]:
        values = [r.get(key, 0) for r in optimized_results if key in r]
        if values:
            opt_stats[key] = calc_stats(values)
    
    # 메시지 수 통계
    orig_msg_counts = [r.get("message_count", 0) for r in original_results]
    opt_msg_counts = [r.get("message_count", 0) for r in optimized_results]
    
    # 토큰 통계
    opt_token_estimates = [r.get("token_estimate", 0) for r in optimized_results if r.get("token_estimate")]
    opt_input_tokens = [r.get("input_tokens") for r in optimized_results if r.get("input_tokens")]
    opt_output_tokens = [r.get("output_tokens") for r in optimized_results if r.get("output_tokens")]
    
    return {
        "prompt": prompt,
        "term": term,
        "runs": runs,
        "original": {
            "timings": orig_stats,
            "message_count": calc_stats(orig_msg_counts) if orig_msg_counts else {},
        },
        "optimized": {
            "timings": opt_stats,
            "message_count": calc_stats(opt_msg_counts) if opt_msg_counts else {},
            "token_estimate": calc_stats(opt_token_estimates) if opt_token_estimates else {},
            "input_tokens": calc_stats(opt_input_tokens) if opt_input_tokens else {},
            "output_tokens": calc_stats(opt_output_tokens) if opt_output_tokens else {},
        },
        "raw_original": original_results,
        "raw_optimized": optimized_results,
    }


def print_detailed_report(results: Dict) -> None:
    """상세 리포트 출력"""
    print("\n" + "=" * 80)
    print("[상세 응답시간 분석 결과]")
    print("=" * 80)
    
    print(f"\n질문: {results['prompt']}")
    if results.get('term'):
        print(f"용어: {results['term']}")
    print(f"실행 횟수: {results['runs']}회\n")
    
    orig = results["original"]
    opt = results["optimized"]
    
    # 전체 시간 비교
    print("=" * 80)
    print("[전체 응답 시간 비교]")
    print("=" * 80)
    orig_total = orig["timings"].get("total", {})
    opt_total = opt["timings"].get("total", {})
    
    if orig_total and opt_total:
        print(f"\n원본 버전:")
        print(f"  평균: {orig_total['mean']:.3f}초")
        print(f"  최소: {orig_total['min']:.3f}초 | 최대: {orig_total['max']:.3f}초")
        print(f"  표준편차: {orig_total['stdev']:.3f}초")
        
        print(f"\n최적화 버전:")
        print(f"  평균: {opt_total['mean']:.3f}초")
        print(f"  최소: {opt_total['min']:.3f}초 | 최대: {opt_total['max']:.3f}초")
        print(f"  표준편차: {opt_total['stdev']:.3f}초")
        
        improvement = ((orig_total['mean'] - opt_total['mean']) / orig_total['mean']) * 100
        print(f"\n[성능 변화] {improvement:+.1f}% ({orig_total['mean']:.3f}초 -> {opt_total['mean']:.3f}초)")
    
    # 단계별 비교
    print("\n" + "=" * 80)
    print("[단계별 시간 분석]")
    print("=" * 80)
    
    steps = [
        ("build_messages", "프롬프트 빌드"),
        ("api_call", "API 호출"),
        ("parse_response", "응답 파싱"),
        ("format_output", "출력 포맷팅"),
    ]
    
    print(f"\n{'단계':<20} {'원본 (평균)':<15} {'최적화 (평균)':<15} {'차이':<15}")
    print("-" * 80)
    
    for step_key, step_name in steps:
        orig_step = orig["timings"].get(step_key, {})
        opt_step = opt["timings"].get(step_key, {})
        
        orig_mean = orig_step.get("mean", 0)
        opt_mean = opt_step.get("mean", 0)
        diff = opt_mean - orig_mean
        diff_pct = (diff / orig_mean * 100) if orig_mean > 0 else 0
        
        print(f"{step_name:<20} {orig_mean:>8.3f}초     {opt_mean:>8.3f}초     {diff:>+8.3f}초 ({diff_pct:>+6.1f}%)")
    
    # 최적화 버전에만 있는 단계
    print("\n최적화 버전 전용 단계:")
    print("-" * 80)
    
    token_est = opt["timings"].get("token_estimation", {})
    if token_est:
        print(f"  토큰 추정: {token_est.get('mean', 0):.3f}초 (평균)")
    
    logging_overhead = opt["timings"].get("logging_overhead", {})
    if logging_overhead:
        print(f"  로깅 오버헤드: {logging_overhead.get('mean', 0):.3f}초 (평균)")
    
    # 메시지 수 비교
    print("\n" + "=" * 80)
    print("[메시지 구조 비교]")
    print("=" * 80)
    
    orig_msg = orig.get("message_count", {})
    opt_msg = opt.get("message_count", {})
    
    if orig_msg and opt_msg:
        print(f"\n원본: 평균 {orig_msg.get('mean', 0):.1f}개 메시지")
        print(f"최적화: 평균 {opt_msg.get('mean', 0):.1f}개 메시지")
        msg_diff = opt_msg.get('mean', 0) - orig_msg.get('mean', 0)
        print(f"차이: {msg_diff:+.1f}개")
    
    # 토큰 정보
    print("\n" + "=" * 80)
    print("[토큰 사용량] (최적화 버전)")
    print("=" * 80)
    
    token_est = opt.get("token_estimate", {})
    if token_est:
        print(f"\n추정 입력 토큰: 평균 {token_est.get('mean', 0):.0f}개")
    
    input_tokens = opt.get("input_tokens", {})
    output_tokens = opt.get("output_tokens", {})
    
    if input_tokens:
        print(f"실제 입력 토큰: 평균 {input_tokens.get('mean', 0):.0f}개")
    if output_tokens:
        print(f"실제 출력 토큰: 평균 {output_tokens.get('mean', 0):.0f}개")
        if input_tokens:
            total_avg = input_tokens.get('mean', 0) + output_tokens.get('mean', 0)
            print(f"총 토큰: 평균 {total_avg:.0f}개")
    
    print("\n" + "=" * 80)


def cli() -> None:
    parser = argparse.ArgumentParser(
        description="상세한 응답시간 분석: 각 단계별 시간을 측정하여 병목 지점 파악"
    )
    parser.add_argument("--prompt", required=True, help="사용자 질문")
    parser.add_argument("--term", default=None, help="선택적 용어")
    parser.add_argument("--runs", type=int, default=10, help="실행 횟수 (기본값: 10)")
    parser.add_argument("--output", default=None, help="결과를 저장할 JSON 파일 경로")
    parser.add_argument("--quiet", action="store_true", help="상세 리포트 출력 생략")
    
    args = parser.parse_args()
    
    results = benchmark_detailed(
        prompt=args.prompt,
        term=args.term,
        runs=args.runs,
    )
    
    if not args.quiet:
        print_detailed_report(results)
    
    # JSON 출력
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fp:
            json.dump(results, fp, indent=2, ensure_ascii=False)
        print(f"\n[완료] 상세 결과가 {args.output}에 저장되었습니다.")
    else:
        print("\n전체 결과 (JSON):")
        print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    cli()

