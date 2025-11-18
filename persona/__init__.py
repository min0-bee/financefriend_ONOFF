# Persona package

# 최적화 버전을 기본으로 사용하도록 설정
try:
    from persona.persona_optimized import generate_structured_persona_reply_optimized
    
    # 기존 코드와 호환성을 위해 래퍼 함수 제공
    def generate_structured_persona_reply(*args, **kwargs):
        """
        최적화된 버전을 사용하는 래퍼 함수.
        기존 코드와 호환성을 위해 문자열만 반환합니다.
        """
        response, _ = generate_structured_persona_reply_optimized(*args, **kwargs)
        return response
    
    # 최적화 버전도 직접 사용할 수 있도록 export
    __all__ = ['generate_structured_persona_reply', 'generate_structured_persona_reply_optimized']
    
except ImportError:
    # 최적화 버전이 없으면 원본 사용
    from persona.persona import generate_structured_persona_reply
    __all__ = ['generate_structured_persona_reply']

# 다른 함수들도 export
from persona.persona import (
    albwoong_persona_reply,
    albwoong_persona_rewrite,
    albwoong_persona_rewrite_section,
)
