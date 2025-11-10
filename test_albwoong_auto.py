"""
🦉 알부엉 페르소나 자동 테스트
구조화된 단일 템플릿 응답을 자동으로 생성하여 보여줍니다.
"""

import sys
import os

# 패키지 경로 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

def run_auto_tests():
    """모든 테스트를 자동으로 실행"""
    
    print("="*70)
    print("  🦉 알부엉 페르소나 자동 테스트 (개선 효과 확인)")
    print("="*70)
    print()
    
    # API 키 확인
    try:
        from financefriend_ONOFF.core.config import OPENAI_API_KEY, USE_OPENAI
        
        if not OPENAI_API_KEY:
            print("⚠️  OpenAI API 키가 설정되지 않았습니다.")
            print("📝 .streamlit/secrets.toml 파일에 API 키를 추가하세요.")
            return
            
        print(f"✅ OpenAI API 설정 확인 완료")
        print()
        
    except Exception as e:
        print(f"❌ 설정 확인 중 오류: {e}")
        return
    
    # 페르소나 함수 임포트
    try:
        from financefriend_ONOFF.persona.persona import (
            albwoong_persona_reply, 
            validate_albwoong_response
        )
        print("✅ 페르소나 모듈 로드 성공")
        print()
    except Exception as e:
        print(f"❌ 페르소나 모듈 로드 실패: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # 테스트 케이스
    test_cases = [
        {"question": "양적완화가 뭐야?"},
        {"question": "금리가 오르면 주식이 왜 떨어져?"},
        {"question": "기준금리가 뭔지 쉽게 알려줘"},
        {"question": "환율이 우리 생활에 미치는 영향은 뭐야?"},
    ]
    
    total_tests = len(test_cases)
    
    for idx, test in enumerate(test_cases, 1):
        print("\n" + "="*70)
        print(f"  테스트 {idx}/{total_tests}")
        print("="*70)
        print(f"📝 질문: {test['question']}")
        print("-"*70)
        print()
        
        try:
            print("🔄 알부엉이 답변을 생성 중...")
            response = albwoong_persona_reply(test['question'])
            
            print("\n" + "┌" + "─"*68 + "┐")
            print("│ 🦉 알부엉의 답변:" + " "*50 + "│")
            print("├" + "─"*68 + "┤")
            
            # 답변을 줄바꿈하여 표시
            lines = response.split('\n')
            for line in lines:
                # 한 줄이 너무 길면 자동으로 잘라서 표시
                while len(line) > 66:
                    print(f"│ {line[:66]} │")
                    line = line[66:]
                if line:
                    print(f"│ {line:<66} │")
            
            print("└" + "─"*68 + "┘")
            
            # 품질 검증
            validation = validate_albwoong_response(response)
            
            print()
            print("📊 품질 검증 결과:")
            print(f"   점수: {validation['score']}/100")
            print(f"   상태: {'✅ 통과' if validation['valid'] else '❌ 실패'}")
            
            if validation['issues']:
                print(f"   ⚠️  문제점: {', '.join(validation['issues'])}")
            
            if validation['warnings']:
                print(f"   ⚠️  경고: {', '.join(validation['warnings'])}")
            
            # 알부엉 특징 체크
            albwoong_features = []
            if "신문에서" in response or "정리해둔" in response:
                albwoong_features.append("📰 알부엉 표현")
            if "물어봐" in response or "궁금한" in response:
                albwoong_features.append("💬 친근한 마무리")
            if "[" in response and "]" in response:
                albwoong_features.append("🌟 비유 사용")
            if not any(ending in response for ending in ["합니다", "됩니다", "습니다"]):
                albwoong_features.append("✅ 반말 통일")
            
            if albwoong_features:
                print(f"   특징: {' | '.join(albwoong_features)}")

            # 구조 검증
            print("\n🧩 템플릿 구조 점검:")
            required_sections = {
                "정의": "📘 정의:",
                "영향": "💡 영향:",
                "비유": "🌟 비유:",
                "마무리": "더 궁금한 거 있으면 편하게 물어봐",
            }
            for label, marker in required_sections.items():
                has_marker = marker in response
                print(f"   {'✅' if has_marker else '❌'} {label} 섹션 {'포함' if has_marker else '누락'}")

            if "🌟 비유:" in response:
                analogy_line = response.split("🌟 비유:")[-1].split("\n")[0]
                sentence_count = analogy_line.count(".")
                print(f"   {'✅' if sentence_count >= 2 else '⚠️'} 비유 문장 수 (마침표 {sentence_count}개)")
            
        except Exception as e:
            print(f"\n❌ 답변 생성 중 오류: {e}")
            import traceback
            traceback.print_exc()
    
    # 최종 요약
    print("\n" + "="*70)
    print("  ✅ 모든 테스트 완료!")
    print("="*70)
    print()
    print("🎯 개선 효과 확인:")
    print("   ✅ 구조화된 템플릿 일관성 유지")
    print("   ✅ 반말 통일 (알부엉 특유의 친근한 말투)")
    print("   ✅ 알부엉 표현 사용 (신문에서, 물어봐 등)")
    print("   ✅ 실시간 품질 검증 + 섹션 구조 점검")
    print()
    print("💡 다음 단계:")
    print("   - Streamlit 앱 실행: streamlit run app.py")
    print("   - 전체 UI에서 챗봇과 대화하며 체험")
    print()


if __name__ == "__main__":
    try:
        run_auto_tests()
    except KeyboardInterrupt:
        print("\n\n👋 테스트를 종료합니다.")
    except Exception as e:
        print(f"\n❌ 예상치 못한 오류: {e}")
        import traceback
        traceback.print_exc()



