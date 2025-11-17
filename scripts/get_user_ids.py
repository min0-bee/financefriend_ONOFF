"""
UUID 확인 스크립트

사용 방법:
  python scripts/get_user_ids.py

기능:
  1. 현재 사용자의 UUID 확인 (logs/user_info.json)
  2. Supabase event_logs에서 모든 사용자 UUID 조회
  3. 관리자 설정에 사용할 UUID 목록 출력
"""

import sys
import os
import json
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logger import get_supabase_client
from core.config import SUPABASE_ENABLE, USER_FILE

def get_my_user_id() -> str:
    """현재 사용자의 UUID 확인"""
    try:
        if os.path.exists(USER_FILE):
            with open(USER_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("user_id", "")
    except Exception:
        pass
    return ""

def get_all_user_ids_from_supabase() -> list:
    """Supabase event_logs에서 모든 사용자 UUID 조회"""
    if not SUPABASE_ENABLE:
        print("⚠️ Supabase가 비활성화되어 있습니다.")
        return []
    
    supabase = get_supabase_client()
    if not supabase:
        print("⚠️ Supabase 클라이언트를 생성할 수 없습니다.")
        return []
    
    try:
        # event_logs 테이블에서 고유한 user_id 조회
        response = (
            supabase.table("event_logs")
            .select("user_id")
            .not_.is_("user_id", "null")
            .execute()
        )
        
        if not response.data:
            return []
        
        # 고유한 user_id만 추출
        unique_user_ids = set()
        for row in response.data:
            user_id = row.get("user_id")
            if user_id:
                unique_user_ids.add(user_id)
        
        return sorted(list(unique_user_ids))
    
    except Exception as e:
        print(f"❌ Supabase에서 사용자 조회 실패: {e}")
        return []

def main():
    print("=" * 60)
    print("📋 UUID 확인")
    print("=" * 60)
    
    # 1. 현재 사용자 UUID
    my_user_id = get_my_user_id()
    if my_user_id:
        print(f"\n👤 내 UUID:")
        print(f"   {my_user_id}")
    else:
        print("\n⚠️ 현재 사용자 UUID를 찾을 수 없습니다.")
    
    # 2. Supabase에서 모든 사용자 UUID 조회
    print(f"\n🔍 Supabase에서 모든 사용자 UUID 조회 중...")
    all_user_ids = get_all_user_ids_from_supabase()
    
    if all_user_ids:
        print(f"\n👥 전체 사용자 UUID 목록 ({len(all_user_ids)}명):")
        print("-" * 60)
        for idx, user_id in enumerate(all_user_ids, 1):
            marker = " ← 내 UUID" if user_id == my_user_id else ""
            print(f"{idx:2d}. {user_id}{marker}")
        
        print("\n" + "=" * 60)
        print("📝 관리자 설정용 UUID 목록:")
        print("=" * 60)
        print("\n# .streamlit/secrets.toml 또는 core/config.py에 추가:")
        print("\nADMIN_USER_IDS = [")
        for user_id in all_user_ids:
            comment = "  # 내 UUID" if user_id == my_user_id else ""
            print(f'    "{user_id}",{comment}')
        print("]")
        
        # 쉼표로 구분된 문자열 형식
        print("\n# 또는 쉼표로 구분된 문자열 형식:")
        user_ids_str = ", ".join([f'"{uid}"' for uid in all_user_ids])
        print(f'ADMIN_USER_IDS = [{user_ids_str}]')
    else:
        print("⚠️ Supabase에서 사용자 UUID를 찾을 수 없습니다.")
        print("   (event_logs 테이블에 데이터가 없거나 접근 권한이 없을 수 있습니다)")
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    main()

