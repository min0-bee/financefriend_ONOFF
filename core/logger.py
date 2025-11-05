# core/logger.py
import os
import csv
import uuid
import json
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple
import streamlit as st
from streamlit_js_eval import streamlit_js_eval
from core.config import (
    LOG_DIR, LOG_FILE,
    API_BASE_URL, API_ENABLE, API_RETRY_COUNT, API_RETRY_DELAY, API_SHOW_ERRORS,
    CSV_ENABLE, ANONYMOUS_USER_ID, AGENT_ID_MAPPING, EVENT_TO_INTERACTION_TYPE,
    SUPABASE_ENABLE, SUPABASE_URL, SUPABASE_KEY
)

# requests 라이브러리 (API 호출용)
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    if API_ENABLE:
        st.warning("⚠️ requests 라이브러리가 없습니다. pip install requests를 실행해주세요.")

# Supabase 클라이언트 (event_log 중심 로깅용)
_supabase_client = None
try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False
    if SUPABASE_ENABLE:
        try:
            st.warning("⚠️ supabase 라이브러리가 없습니다. pip install supabase를 실행해주세요.")
        except:
            pass

# 1) 실제 사용하는 모든 칼럼을 헤더에 “고정”
CSV_HEADER = [
    "event_id", "event_time", "event_name",
    "user_id", "session_id",
    "surface", "source",
    "news_id", "term",
    "message", "note", "title", "click_count",
    "answer_len", "via", "latency_ms",
    "payload"
]

def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def get_supabase_client() -> Optional[Any]:
    """Supabase 클라이언트를 싱글톤으로 반환 (없으면 None)"""
    global _supabase_client
    
    if _supabase_client is not None:
        return _supabase_client
    
    if not SUPABASE_AVAILABLE or not SUPABASE_ENABLE:
        return None
    
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    
    try:
        from supabase import create_client
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        return _supabase_client
    except Exception as e:
        if API_SHOW_ERRORS:
            try:
                st.warning(f"⚠️ Supabase 클라이언트 생성 실패: {str(e)}")
            except:
                pass
        return None

def ensure_log_file():
    """logs 폴더를 만들고, CSV가 없으면 헤더를 생성합니다."""
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
            writer.writerow(CSV_HEADER)

def _nz(v):
    """None → '' (CSV에 'None' 문자열 안 남게)"""
    return "" if v is None else v

def _as_json_text(x) -> str:
    """
    임의의 값(문자열/숫자/딕트/리스트)을 JSON 문자열로 직렬화.
    - 문자열도 JSON으로 감싸 쉼표/개행 안전 확보
    """
    try:
        return json.dumps(x if x is not None else "", ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return json.dumps(str(x), ensure_ascii=False, separators=(",", ":"))


# ─────────────────────────────────────────────────────────────
# API 클라이언트 함수들
# ─────────────────────────────────────────────────────────────

def _get_backend_session_id() -> Optional[int]:
    """백엔드 세션 ID를 가져옵니다 (없으면 None)"""
    return st.session_state.get("backend_session_id")


def _get_user_id() -> str:
    """사용자 ID를 가져옵니다 (서버 UUID 우선 사용)"""
    # 서버 UUID가 있으면 우선 사용 (서버와 항상 동일)
    server_user_id = st.session_state.get("backend_user_id")
    if server_user_id:
        return server_user_id
    
    # 없으면 session_state의 user_id 사용
    user_id = st.session_state.get("user_id")
    if user_id:
        return user_id
    
    # 없으면 로컬에서 가져오기 (임시, 서버 연결 후 서버 UUID로 교체됨)
    from core.user import get_or_create_user_id
    return get_or_create_user_id()


def _save_server_user_id(server_user_id: str) -> None:
    """서버에서 받은 user_id를 저장 (세션 상태, 로컬 파일, URL 파라미터)"""
    st.session_state["backend_user_id"] = server_user_id
    st.session_state["user_id"] = server_user_id
    
    # 서버 UUID를 로컬에 저장
    from core.user import _write_local_user_id
    _write_local_user_id(server_user_id)
    
    # URL 파라미터도 업데이트
    try:
        st.query_params["uid"] = server_user_id
    except:
        try:
            st.experimental_set_query_params(uid=server_user_id)
        except:
            pass


def _extract_user_id_from_response(users: Any) -> Optional[str]:
    """서버 응답에서 user_id 추출 (list 또는 dict 형태 지원)"""
    if isinstance(users, list) and len(users) > 0:
        return users[0].get("user_id")
    elif isinstance(users, dict):
        return users.get("user_id")
    return None


def _fetch_user_by_username(username: str) -> Optional[str]:
    """username으로 사용자를 조회하고 서버의 user_id를 반환"""
    try:
        get_url = f"{API_BASE_URL}/api/v1/users/"
        get_params = {"username": username}
        get_response = _api_request_with_retry("GET", get_url, params=get_params)
        
        if get_response and get_response.status_code == 200:
            users = get_response.json()
            return _extract_user_id_from_response(users)
    except Exception:
        pass
    return None


def _generate_email_from_user_id(user_id: str, is_legacy_format: bool) -> str:
    """user_id를 기반으로 이메일 주소 생성"""
    # UUID 형식: 하이픈 제거하고 사용
    if len(user_id) == 36 and user_id.count("-") == 4:
        email_local_part = user_id.replace("-", "")[:32]
        return f"{email_local_part}@example.com"
    
    # Legacy 형식 (user_xxx)
    if is_legacy_format:
        email_local_part = user_id.replace("user_", "")[:32] if len(user_id) > 32 else user_id
        return f"{email_local_part}@example.com"
    
    # 기타 형식
    email_local_part = user_id[:32] if len(user_id) > 32 else user_id
    return f"{email_local_part}@example.com"


def _log_api_error(operation: str, response: Optional[requests.Response], 
                   error_msg: Optional[str] = None, extra_info: Optional[str] = None,
                   silent: bool = False) -> None:
    """API 에러 로깅 공통 함수
    
    Args:
        operation: 작업 이름 (예: "사용자 생성 실패")
        response: HTTP 응답 객체 (None이면 연결 실패)
        error_msg: 직접 제공된 에러 메시지
        extra_info: 추가 정보 (caption으로 표시)
        silent: True면 에러 메시지를 표시하지 않음 (재시도 중에 사용)
    """
    if not API_SHOW_ERRORS or silent:
        return
    
    try:
        if response:
            try:
                error_detail = response.json().get("detail", response.text[:200]) if response.text else "알 수 없는 오류"
                if isinstance(error_detail, list):
                    error_detail = "; ".join(str(e) for e in error_detail)
                error_msg = f"{operation} ({response.status_code}): {error_detail}"
            except:
                error_msg = f"{operation} ({response.status_code}): {response.text[:200] if response.text else '알 수 없는 오류'}"
        elif error_msg:
            error_msg = f"{operation}: {error_msg}"
        else:
            error_msg = f"{operation}: 서버 연결 실패"
        
        st.warning(f"⚠️ {error_msg}")
        if extra_info:
            st.caption(extra_info)
    except:
        pass  # Streamlit 컨텍스트 외부에서는 무시


def _diagnose_connection_error(url: str, error: Exception) -> str:
    """연결 에러의 상세 원인 진단"""
    import socket
    from urllib.parse import urlparse
    
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        port = parsed.port or (80 if parsed.scheme == 'http' else 443)
        
        diagnosis = []
        
        # 1. DNS 확인
        try:
            ip = socket.gethostbyname(host)
            diagnosis.append(f"✅ DNS 확인: {host} → {ip}")
        except socket.gaierror:
            diagnosis.append(f"❌ DNS 확인 실패: {host}를 찾을 수 없습니다")
            return "\n".join(diagnosis)
        
        # 2. 포트 연결 테스트
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            result = sock.connect_ex((ip, port))
            sock.close()
            
            if result == 0:
                diagnosis.append(f"✅ 포트 연결: {ip}:{port} 접근 가능")
            else:
                diagnosis.append(f"❌ 포트 연결 실패: {ip}:{port}에 연결할 수 없습니다 (포트가 닫혀있거나 방화벽 차단)")
        except Exception as e:
            diagnosis.append(f"⚠️ 포트 테스트 실패: {str(e)}")
        
        # 3. HTTP 연결 테스트
        error_str = str(error)
        if "Connection refused" in error_str or "ConnectionResetError" in error_str:
            diagnosis.append(f"❌ HTTP 연결: 서버가 해당 포트에서 리스닝하지 않거나 연결을 거부했습니다")
        elif "Timeout" in error_str or "timed out" in error_str.lower():
            diagnosis.append(f"❌ 타임아웃: 서버 응답이 없습니다 (방화벽 또는 네트워크 문제 가능)")
        elif "Name or service not known" in error_str:
            diagnosis.append(f"❌ 호스트명 확인 실패: {host}를 찾을 수 없습니다")
        else:
            diagnosis.append(f"⚠️ 기타 에러: {error_str}")
        
        return "\n".join(diagnosis)
    except Exception as e:
        return f"진단 중 에러: {str(e)}"


def _api_request_with_retry(method: str, url: str, silent: bool = False, **kwargs) -> Optional[requests.Response]:
    """API 요청을 재시도 로직과 함께 실행합니다
    
    Args:
        method: HTTP 메서드 (GET, POST, PUT, DELETE 등)
        url: 요청 URL
        silent: True면 에러 메시지를 표시하지 않음 (재시도 중에 사용)
        **kwargs: requests.request에 전달할 추가 파라미터
    """
    if not REQUESTS_AVAILABLE or not API_ENABLE:
        return None
    
    last_error = None
    last_exception = None
    for attempt in range(API_RETRY_COUNT):
        try:
            response = requests.request(method, url, timeout=5, **kwargs)
            # 2xx 성공 또는 4xx 클라이언트 에러는 재시도하지 않음
            if 200 <= response.status_code < 500:
                return response
            # 5xx 서버 에러는 재시도
            if response.status_code >= 500 and attempt < API_RETRY_COUNT - 1:
                time.sleep(API_RETRY_DELAY * (2 ** attempt))  # exponential backoff
                continue
            return response
        except requests.ConnectionError as e:
            last_exception = e
            last_error = f"연결 실패: 백엔드 서버({API_BASE_URL})가 실행 중인지 확인하세요"
            # ConnectionError의 상세 정보 포함
            error_str = str(e)
            if "Connection refused" in error_str:
                last_error = f"연결 거부: 서버가 요청을 거부했습니다 ({API_BASE_URL})"
            elif "Connection reset" in error_str:
                last_error = f"연결 리셋: 서버가 연결을 끊었습니다 ({API_BASE_URL})"
            elif "NewConnectionError" in error_str or "Failed to establish" in error_str:
                last_error = f"연결 실패: 서버에 연결할 수 없습니다 ({API_BASE_URL})"
            
            # 디버깅: 첫 번째 시도에서 ConnectionError 발생 시 로깅 (silent이 False일 때만)
            if attempt == 0 and not silent and API_SHOW_ERRORS:
                try:
                    # 직접 요청을 시도해서 진짜 문제인지 확인
                    test_response = requests.request(method, url, timeout=5, **kwargs)
                    # 직접 요청이 성공했다면 재시도 로직 문제
                    if 200 <= test_response.status_code < 500:
                        # 재시도 없이 바로 성공한 응답 반환
                        return test_response
                except:
                    pass  # 직접 요청도 실패하면 원래 로직대로 진행
            
            if attempt < API_RETRY_COUNT - 1:
                time.sleep(API_RETRY_DELAY * (2 ** attempt))
                continue
        except requests.Timeout as e:
            last_exception = e
            last_error = f"타임아웃: 서버 응답이 너무 느립니다 (5초)"
            if attempt < API_RETRY_COUNT - 1:
                time.sleep(API_RETRY_DELAY * (2 ** attempt))
                continue
        except (requests.RequestException, Exception) as e:
            last_exception = e
            last_error = f"API 요청 실패: {str(e)}"
            if attempt < API_RETRY_COUNT - 1:
                time.sleep(API_RETRY_DELAY * (2 ** attempt))
                continue
    
    # 마지막 시도 실패 시 에러 메시지 표시 (설정에 따라, silent이 False일 때만)
    if last_error and API_SHOW_ERRORS and not silent:
        try:
            # 상세 진단 정보 포함
            diagnosis = ""
            if last_exception and isinstance(last_exception, (requests.ConnectionError, requests.Timeout)):
                diagnosis = _diagnose_connection_error(url, last_exception)
            
            if diagnosis:
                st.warning(f"⚠️ API 연결 실패: {last_error}")
                with st.expander("🔍 상세 진단 정보", expanded=False):
                    st.code(diagnosis, language=None)
                st.caption("💡 CSV 파일에만 저장됩니다.")
            else:
                st.warning(f"⚠️ API 연결 실패: {last_error}. CSV 파일에만 저장됩니다.")
        except:
            pass  # Streamlit 컨텍스트 외부에서는 무시
    
    return None


def _ensure_backend_user(user_id: str, silent: bool = False) -> bool:
    """백엔드에 사용자가 없으면 생성 시도
    
    Args:
        user_id: 사용자 ID (UUID 또는 legacy 형식)
        silent: True면 에러 메시지를 표시하지 않음 (재시도 중에 사용)
    """
    if not REQUESTS_AVAILABLE or not API_ENABLE:
        return False
    
    # 이미 생성 시도했고 backend_user_id가 있으면 성공으로 간주
    if st.session_state.get("backend_user_created", False) and st.session_state.get("backend_user_id"):
        return True
    
    # backend_user_id가 없으면 조회 시도 (이미 존재하는 사용자일 수 있음)
    # _api_request_with_retry가 실패할 수 있으므로 직접 요청으로 조회
    if st.session_state.get("backend_user_created", False) and not st.session_state.get("backend_user_id"):
        # 직접 요청으로 조회 시도
        try:
            import requests
            get_url = f"{API_BASE_URL}/api/v1/users/"
            get_params = {"username": user_id}
            get_response = requests.get(get_url, params=get_params, timeout=5)
            
            if get_response.status_code == 200:
                users = get_response.json()
                server_user_id = _extract_user_id_from_response(users)
                if server_user_id:
                    _save_server_user_id(server_user_id)
                    return True
        except:
            pass  # 조회 실패해도 계속 진행
        
        # 직접 조회도 실패하면 기존 함수 시도
        server_user_id = _fetch_user_by_username(user_id)
        if server_user_id:
            _save_server_user_id(server_user_id)
            return True
    
    # 사용자 생성 API 호출
    url = f"{API_BASE_URL}/api/v1/users/"
    
    # 서버에 사용자 생성 요청
    # 필수 필드만 보내기 (서버 스키마에 많은 컬럼이 있어도 필수만 전송)
    # username만 필수로 보내고, 나머지는 서버 기본값 사용
    payload = {
        "username": user_id  # UUID 형식 또는 legacy 형식 (식별자로 사용)
    }
    
    # 선택적 필드: 서버가 요구하는 경우에만 추가
    # (400 validation 오류가 발생하면 이 필드들을 추가로 시도)
    is_legacy_format = user_id.startswith("user_")
    email = _generate_email_from_user_id(user_id, is_legacy_format)
    user_type = "guest" if user_id == ANONYMOUS_USER_ID or is_legacy_format else "user"
    
    # 비밀번호는 서버가 자동 생성할 수도 있으므로 일단 제외
    # import secrets
    # password = secrets.token_urlsafe(16)
    
    # 테스트 코드에서는 직접 requests.post()를 사용하여 성공했으므로,
    # 복잡한 재시도 로직을 우회하고 직접 요청을 먼저 시도
    # (테스트 코드와 동일한 방식으로 동작)
    import requests
    response = None
    try:
        # 직접 POST 요청 시도 (테스트 코드와 동일)
        if not silent and API_SHOW_ERRORS:
            st.info("🔄 서버에 사용자 생성 요청 중...")
        
        response = requests.post(url, json=payload, timeout=5)
        
        if not silent and API_SHOW_ERRORS:
            st.info(f"📋 응답 코드: {response.status_code}")
        
        # 성공 또는 클라이언트 에러(4xx)는 재시도 불필요
        # 422는 아래에서 처리하므로 여기서는 그냥 통과
        if response.status_code in [200, 201, 400]:
            pass  # 아래에서 처리
        elif response.status_code == 422:
            # 422는 직접 요청 블록에서 처리하도록 함
            pass
        else:
            # 5xx 서버 에러는 재시도 로직 사용
            response = _api_request_with_retry("POST", url, json=payload, silent=silent)
    except requests.ConnectionError as e:
        # 연결 실패 시 재시도 로직 사용
        if not silent and API_SHOW_ERRORS:
            st.warning(f"⚠️ 직접 연결 실패: {str(e)}. 재시도 로직을 사용합니다...")
        response = _api_request_with_retry("POST", url, json=payload, silent=silent)
    except requests.Timeout as e:
        # 타임아웃 시 재시도 로직 사용
        if not silent and API_SHOW_ERRORS:
            st.warning(f"⚠️ 직접 요청 타임아웃: {str(e)}. 재시도 로직을 사용합니다...")
        response = _api_request_with_retry("POST", url, json=payload, silent=silent)
    except Exception as e:
        # 기타 예외 시 재시도 로직 사용
        if not silent and API_SHOW_ERRORS:
            st.warning(f"⚠️ 직접 요청 실패: {str(e)}. 재시도 로직을 사용합니다...")
        response = _api_request_with_retry("POST", url, json=payload, silent=silent)
    
    # response가 None이거나 실패한 경우 직접 요청 재시도
    if response is None or (response and response.status_code not in [200, 201]):
        # 직접 요청 시도 (테스트 코드에서는 성공했으므로)
        try:
            if not silent and API_SHOW_ERRORS:
                if response is None:
                    st.info("🔄 재시도 로직이 실패했습니다. 직접 요청을 재시도합니다...")
                elif response:
                    st.info(f"🔄 재시도 로직이 {response.status_code} 응답을 반환했습니다. 직접 요청을 재시도합니다...")
            
            # 직접 POST 요청 시도 (테스트 코드와 동일)
            test_response = requests.post(url, json=payload, timeout=5)
            
            if not silent and API_SHOW_ERRORS:
                st.info(f"📋 직접 요청 재시도 응답 코드: {test_response.status_code}")
            
            if test_response.status_code == 201:
                # 성공했으므로 실제로 처리
                data = test_response.json()
                server_user_id = data.get("user_id")
                if server_user_id:
                    _save_server_user_id(server_user_id)
                st.session_state["backend_user_created"] = True
                if not silent and API_SHOW_ERRORS:
                    st.success("✅ 직접 요청으로 사용자 생성 성공!")
                return True
            elif test_response.status_code == 400:
                # 400 응답 처리 (이미 존재하거나 validation 오류)
                try:
                    error_data = test_response.json()
                    error_detail = str(error_data).lower()
                    
                    # validation 오류인 경우 (필수 필드 누락)
                    if "required" in error_detail or "missing" in error_detail or "field" in error_detail:
                        if not silent and API_SHOW_ERRORS:
                            st.warning(f"⚠️ 필수 필드 누락. 추가 필드를 포함하여 재시도...")
                        
                        # 필수 필드 추가하여 재시도
                        enhanced_payload = {
                            "username": user_id,
                            "email": email,
                            "user_type": user_type,
                            "password": secrets.token_urlsafe(16)  # 필수일 수 있으므로 추가
                        }
                        
                        retry_response = requests.post(url, json=enhanced_payload, timeout=5)
                        if retry_response.status_code == 201:
                            data = retry_response.json()
                            server_user_id = data.get("user_id")
                            if server_user_id:
                                _save_server_user_id(server_user_id)
                            st.session_state["backend_user_created"] = True
                            if not silent and API_SHOW_ERRORS:
                                st.success("✅ 필수 필드 추가 후 사용자 생성 성공!")
                            return True
                    
                    # 이미 존재하는 경우 - username으로 조회 시도
                    if not silent and API_SHOW_ERRORS:
                        st.info(f"🔍 사용자 생성 400 응답. 이미 존재하는지 확인 중...")
                    
                    # username으로 조회 시도 (직접 요청으로)
                    try:
                        import requests
                        get_url = f"{API_BASE_URL}/api/v1/users/"
                        get_params = {"username": user_id}
                        get_response = requests.get(get_url, params=get_params, timeout=5)
                        
                        if get_response.status_code == 200:
                            users = get_response.json()
                            server_user_id = _extract_user_id_from_response(users)
                            if server_user_id:
                                _save_server_user_id(server_user_id)
                                st.session_state["backend_user_created"] = True
                                if not silent and API_SHOW_ERRORS:
                                    st.success("✅ 사용자가 이미 존재합니다. 서버 user_id를 가져왔습니다.")
                                return True
                        
                        # 조회 실패
                        if not silent and API_SHOW_ERRORS:
                            st.warning(f"⚠️ username={user_id}로 조회했지만 사용자를 찾을 수 없습니다. (응답 코드: {get_response.status_code})")
                            st.json(error_data)  # 서버 에러 상세 정보 표시
                    except Exception as e:
                        if not silent and API_SHOW_ERRORS:
                            st.warning(f"⚠️ username={user_id}로 조회 중 에러 발생: {str(e)}")
                    
                    return False
                except:
                    if not silent and API_SHOW_ERRORS:
                        st.error(f"❌ 직접 요청 응답 (400): {test_response.text[:200]}")
                    return False
            else:
                if not silent and API_SHOW_ERRORS:
                    try:
                        error_data = test_response.json()
                        st.error(f"❌ 직접 요청 응답 에러: {test_response.status_code}")
                        st.json(error_data)
                    except:
                        st.error(f"❌ 직접 요청 응답 에러: {test_response.status_code} - {test_response.text[:200]}")
                return False
        except requests.ConnectionError as e:
            if not silent and API_SHOW_ERRORS:
                st.error(f"❌ 직접 요청도 ConnectionError 발생: {str(e)}")
                # 진단 정보 표시 (직접 요청 블록에서 실패했으므로)
                try:
                    diagnosis = _diagnose_connection_error(url, e)
                    if diagnosis:
                        with st.expander("🔍 상세 진단 정보", expanded=False):
                            st.code(diagnosis, language=None)
                except:
                    pass
            # 직접 요청도 실패하면 실패로 처리
            st.session_state["backend_user_created"] = False
            return False
        except requests.Timeout as e:
            if not silent and API_SHOW_ERRORS:
                st.error(f"❌ 직접 요청도 Timeout 발생: {str(e)}")
            st.session_state["backend_user_created"] = False
            return False
        except Exception as e:
            if not silent and API_SHOW_ERRORS:
                st.error(f"❌ 직접 요청 실패: {str(e)}")
            st.session_state["backend_user_created"] = False
            return False
    
    if response:
        # 201 Created: 성공적으로 생성됨
        if response.status_code == 201:
            data = response.json()
            server_user_id = data.get("user_id")
            if server_user_id:
                _save_server_user_id(server_user_id)
            st.session_state["backend_user_created"] = True
            return True
        # 400 Bad Request: 이미 존재하는 사용자 또는 validation 오류
        elif response.status_code == 400:
            # 서버 응답의 상세 정보 확인
            try:
                error_data = response.json()
                error_detail = str(error_data.get("detail", error_data))
                
                # username으로 조회 시도 (직접 요청으로, _api_request_with_retry 사용하지 않음)
                try:
                    import requests
                    get_url = f"{API_BASE_URL}/api/v1/users/"
                    get_params = {"username": user_id}
                    get_response = requests.get(get_url, params=get_params, timeout=5)
                    
                    if get_response.status_code == 200:
                        users = get_response.json()
                        server_user_id = _extract_user_id_from_response(users)
                        if server_user_id:
                            _save_server_user_id(server_user_id)
                            st.session_state["backend_user_created"] = True
                            if not silent and API_SHOW_ERRORS:
                                st.success("✅ 사용자가 이미 존재합니다. 서버 user_id를 가져왔습니다.")
                            return True
                    
                    # 조회 실패: 400의 상세 정보를 로깅
                    if not silent and API_SHOW_ERRORS:
                        try:
                            st.error(f"❌ 사용자 생성 실패 (400 Bad Request)")
                            st.json(error_data)  # 전체 에러 응답 표시
                            st.info(f"💡 username={user_id}로 조회했지만 사용자를 찾을 수 없습니다. (응답 코드: {get_response.status_code})")
                            st.info(f"💡 서버 로그를 확인하거나 Swagger UI에서 직접 테스트해보세요.")
                        except:
                            pass
                    # 조회 실패해도 계속 진행 (서버가 다른 이유로 400을 반환할 수 있음)
                    st.session_state["backend_user_created"] = False
                    return False
                except Exception as e:
                    # 조회 중 에러 발생
                    if not silent and API_SHOW_ERRORS:
                        try:
                            st.error(f"❌ 사용자 생성 실패 (400 Bad Request)")
                            st.json(error_data)
                            st.warning(f"⚠️ username={user_id}로 조회 중 에러 발생: {str(e)}")
                        except:
                            pass
                    st.session_state["backend_user_created"] = False
                    return False
            except:
                # JSON 파싱 실패 시 텍스트로 확인
                error_text = response.text[:200] if response.text else "알 수 없는 오류"
                if not silent and API_SHOW_ERRORS:
                    try:
                        st.warning(f"⚠️ 사용자 생성 실패 (400): {error_text}")
                    except:
                        pass
                return False
        # 422 Validation Error: 필드 검증 실패
        elif response.status_code == 422:
            _log_api_error("사용자 생성 실패", response, 
                          extra_info=f"email={email}, username={user_id}, user_type={user_type}",
                          silent=silent)
            return False
        # 기타 에러 (401, 403, 500 등)
        else:
            _log_api_error(f"사용자 생성 실패 ({response.status_code})", response, silent=silent)
            return False
    
    # response가 None인 경우 (연결 실패)
    # 직접 요청 블록이 실행되지 않았거나 실패한 경우에만 진단 정보 표시
    # 주의: 직접 요청 블록에서 return False를 하면 여기까지 오지 않으므로,
    # 직접 요청 블록 내부에서도 진단 정보를 표시해야 함
    # 하지만 직접 요청 블록이 실행되지 않은 경우(예: 코드 경로 문제)를 대비해 여기서도 확인
    if response is None and not silent and API_SHOW_ERRORS:
        try:
            # 상세 진단 정보 포함
            diagnosis = ""
            st.warning(f"⚠️ 사용자 생성 실패: 서버 연결 실패 ({API_BASE_URL})")
            
            # 연결 테스트를 다시 시도해서 진단 정보 생성
            try:
                import socket
                from urllib.parse import urlparse
                parsed = urlparse(url)
                host = parsed.hostname
                port = parsed.port or (80 if parsed.scheme == 'http' else 443)
                
                # DNS 확인
                try:
                    ip = socket.gethostbyname(host)
                    diagnosis = f"✅ DNS 확인: {host} → {ip}\n"
                except socket.gaierror:
                    diagnosis = f"❌ DNS 확인 실패: {host}를 찾을 수 없습니다\n"
                    with st.expander("🔍 상세 진단 정보", expanded=True):
                        st.code(diagnosis, language=None)
                    st.caption("💡 서버 IP 주소가 올바른지 확인하세요.")
                    return False
                
                # 포트 연결 테스트
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(3)
                    result = sock.connect_ex((ip, port))
                    sock.close()
                    
                    if result == 0:
                        diagnosis += f"✅ 포트 연결: {ip}:{port} 접근 가능\n"
                        
                        # HTTP 연결 테스트
                        try:
                            import requests
                            # Health check 엔드포인트 먼저 시도
                            health_url = f"{API_BASE_URL}/health"
                            try:
                                health_response = requests.get(health_url, timeout=3)
                                if health_response.status_code == 200:
                                    diagnosis += f"✅ Health Check 성공: /health 엔드포인트 응답 정상\n"
                                    diagnosis += f"   응답: {health_response.text[:100]}\n"
                                else:
                                    diagnosis += f"⚠️ Health Check 실패: /health 엔드포인트가 {health_response.status_code} 응답\n"
                            except Exception as health_e:
                                diagnosis += f"⚠️ Health Check 실패: {str(health_e)}\n"
                            
                            # 실제 API 엔드포인트 테스트 (GET)
                            api_url = f"{API_BASE_URL}/api/v1/users/"
                            try:
                                api_response = requests.get(api_url, timeout=3)
                                diagnosis += f"📡 API 엔드포인트 테스트 (GET): {api_url}\n"
                                diagnosis += f"   응답 코드: {api_response.status_code}\n"
                                if api_response.status_code == 401 or api_response.status_code == 403:
                                    diagnosis += "   💡 인증이 필요할 수 있습니다.\n"
                                elif api_response.status_code == 405:
                                    diagnosis += "   💡 GET 메서드가 허용되지 않습니다 (POST만 허용 가능).\n"
                            except requests.ConnectionError:
                                diagnosis += f"❌ API 엔드포인트 연결 실패: {api_url}\n"
                                diagnosis += "   💡 서버가 HTTP 요청을 거부하거나 다른 포트/경로를 사용 중일 수 있습니다.\n"
                            except Exception as api_e:
                                diagnosis += f"⚠️ API 엔드포인트 테스트 실패: {str(api_e)}\n"
                            
                            # POST 요청 테스트 (실제 사용자 생성 시도)
                            try:
                                import secrets
                                test_payload = {
                                    "email": f"test_{secrets.token_hex(8)}@example.com",
                                    "username": f"test_user_{secrets.token_hex(8)}",
                                    "user_type": "guest",
                                    "password": secrets.token_urlsafe(16)
                                }
                                post_response = requests.post(api_url, json=test_payload, timeout=5)
                                diagnosis += f"\n📤 POST 요청 테스트: {api_url}\n"
                                diagnosis += f"   응답 코드: {post_response.status_code}\n"
                                
                                if post_response.status_code == 201:
                                    diagnosis += "   ✅ POST 요청 성공! (사용자 생성 가능)\n"
                                elif post_response.status_code == 400:
                                    try:
                                        error_data = post_response.json()
                                        diagnosis += f"   ⚠️ 400 Bad Request: {str(error_data)[:200]}\n"
                                    except:
                                        diagnosis += f"   ⚠️ 400 Bad Request: {post_response.text[:200]}\n"
                                elif post_response.status_code == 422:
                                    try:
                                        error_data = post_response.json()
                                        diagnosis += f"   ❌ 422 Validation Error: {str(error_data)[:200]}\n"
                                        diagnosis += "   💡 요청 본문의 필드가 서버 스키마와 맞지 않을 수 있습니다.\n"
                                    except:
                                        diagnosis += f"   ❌ 422 Validation Error: {post_response.text[:200]}\n"
                                elif post_response.status_code == 401 or post_response.status_code == 403:
                                    diagnosis += "   ❌ 인증/권한 오류: 서버가 인증을 요구합니다.\n"
                                else:
                                    try:
                                        error_data = post_response.json()
                                        diagnosis += f"   ⚠️ 응답 코드 {post_response.status_code}: {str(error_data)[:200]}\n"
                                    except:
                                        diagnosis += f"   ⚠️ 응답 코드 {post_response.status_code}: {post_response.text[:200]}\n"
                            except requests.ConnectionError:
                                diagnosis += f"\n❌ POST 요청 연결 실패\n"
                                diagnosis += "   💡 GET은 성공하지만 POST가 실패합니다. 서버 설정 문제일 수 있습니다.\n"
                            except Exception as post_e:
                                diagnosis += f"\n⚠️ POST 요청 테스트 실패: {str(post_e)}\n"
                        except ImportError:
                            diagnosis += "⚠️ requests 모듈을 사용할 수 없어 HTTP 테스트를 건너뜁니다.\n"
                        
                        diagnosis += "\n💡 가능한 해결 방법:\n"
                        diagnosis += "   1. 서버가 실행 중인지 확인 (팀원에게 확인)\n"
                        diagnosis += "   2. 서버 로그 확인 (서버 측 에러 로그 확인)\n"
                        diagnosis += "   3. API_BASE_URL이 올바른지 확인 (http://192.168.80.78:8000)\n"
                        diagnosis += "   4. 서버가 CORS 설정으로 인해 요청을 차단할 수 있음\n"
                    else:
                        diagnosis += f"❌ 포트 연결 실패: {ip}:{port}에 연결할 수 없습니다\n"
                        diagnosis += "💡 가능한 원인:\n"
                        diagnosis += "   - 서버가 해당 포트에서 리스닝하지 않음\n"
                        diagnosis += "   - 방화벽이 포트를 차단함\n"
                        diagnosis += "   - 서버가 127.0.0.1에서만 리스닝 중일 수 있음 (0.0.0.0으로 변경 필요)"
                except Exception as e:
                    diagnosis += f"⚠️ 포트 테스트 실패: {str(e)}"
            except Exception as e:
                diagnosis = f"⚠️ 진단 중 에러: {str(e)}"
            
            if diagnosis:
                with st.expander("🔍 상세 진단 정보", expanded=True):
                    st.code(diagnosis, language=None)
            
            st.caption("💡 서버 연결 확인: 서버가 실행 중인지, 같은 네트워크에 연결되어 있는지 확인하세요.")
        except:
            pass  # Streamlit 컨텍스트 외부에서는 무시
    
    return False


def _ensure_backend_session() -> Optional[int]:
    """백엔드 세션이 없으면 생성하고, 있으면 반환합니다"""
    backend_session_id = _get_backend_session_id()
    if backend_session_id:
        return backend_session_id
    
    # 세션 생성
    # 익명 사용자도 식별만 되면 되므로, 사용자 생성 실패해도 로컬 user_id로 세션 생성 시도
    user_id = _get_user_id()  # 로컬 user_id 또는 서버 UUID
    
    # 서버 UUID가 있으면 우선 사용, 없으면 로컬 user_id 사용
    backend_user_id = st.session_state.get("backend_user_id")
    if backend_user_id:
        user_id = backend_user_id
    else:
        # 서버 UUID가 없으면 사용자 생성을 시도 (세션 생성 전 필수)
        # silent=False로 설정하여 422 등 에러를 확인할 수 있도록 함
        user_created = _ensure_backend_user(user_id, silent=False)
        
        if user_created:
            # 사용자 생성 성공 → 서버 UUID 사용
            backend_user_id = st.session_state.get("backend_user_id")
            if backend_user_id:
                user_id = backend_user_id
        else:
            # 사용자 생성 실패 → username으로 조회 시도
            if API_SHOW_ERRORS:
                try:
                    st.warning(f"⚠️ 사용자 생성 실패. username으로 조회 시도...")
                except:
                    pass
            
            try:
                import requests
                get_url = f"{API_BASE_URL}/api/v1/users/"
                get_params = {"username": user_id}
                get_response = requests.get(get_url, params=get_params, timeout=5)
                
                if get_response.status_code == 200:
                    users = get_response.json()
                    server_user_id = _extract_user_id_from_response(users)
                    if server_user_id:
                        _save_server_user_id(server_user_id)
                        user_id = server_user_id
                        if API_SHOW_ERRORS:
                            try:
                                st.success(f"✅ username으로 조회 성공! 서버 user_id 사용")
                            except:
                                pass
            except:
                pass  # 조회 실패해도 계속 진행 (세션 생성 시도)
    
    url = f"{API_BASE_URL}/api/v1/sessions/"
    
    context = {}
    if "surface" in st.session_state:
        context["surface"] = st.session_state.get("surface", "")
    if "source" in st.session_state:
        context["source"] = st.session_state.get("source", "")
    
    # 세션 생성 요청 (테스트 코드와 동일하게 직접 요청 먼저 시도)
    import requests
    response = None
    
    # 디버깅: 요청 정보 표시
    if API_SHOW_ERRORS:
        try:
            st.info("🔄 서버에 세션 생성 요청 중...")
            st.json({
                "요청 URL": url,
                "요청 본문": {
                    "user_id": user_id,
                    "user_id_타입": type(user_id).__name__,
                    "user_id_길이": len(user_id) if user_id else 0,
                    "context": context
                }
            })
        except:
            pass
    
    try:
        # 직접 POST 요청 시도 (테스트 코드와 동일)
        response = requests.post(url, json={"user_id": user_id, "context": context}, timeout=5)
        
        if API_SHOW_ERRORS:
            try:
                st.info(f"📋 세션 생성 응답 코드: {response.status_code}")
                # 응답 본문 확인 (디버깅용)
                try:
                    response_data = response.json()
                    st.json({"응답 코드": response.status_code, "응답 본문": response_data})
                except:
                    st.text(f"응답 본문 (텍스트): {response.text[:500]}")
            except:
                pass
        
        # 성공 또는 클라이언트 에러(4xx)는 재시도 불필요
        if response.status_code in [200, 201, 400, 404, 422]:
            pass  # 아래에서 처리
        else:
            # 5xx 서버 에러는 재시도 로직 사용
            if API_SHOW_ERRORS:
                try:
                    st.warning(f"⚠️ 5xx 서버 에러 ({response.status_code}). 재시도 로직 사용...")
                except:
                    pass
            response = _api_request_with_retry(
                "POST", url,
                json={"user_id": user_id, "context": context}
            )
    except requests.ConnectionError as e:
        # 연결 실패 시 재시도 로직 사용
        if API_SHOW_ERRORS:
            try:
                st.warning(f"⚠️ 직접 연결 실패: {str(e)}. 재시도 로직을 사용합니다...")
            except:
                pass
        response = _api_request_with_retry(
            "POST", url,
            json={"user_id": user_id, "context": context}
        )
    except requests.Timeout as e:
        # 타임아웃 시 재시도 로직 사용
        if API_SHOW_ERRORS:
            try:
                st.warning(f"⚠️ 직접 요청 타임아웃: {str(e)}. 재시도 로직을 사용합니다...")
            except:
                pass
        response = _api_request_with_retry(
            "POST", url,
            json={"user_id": user_id, "context": context}
        )
    except Exception as e:
        # 기타 예외 시 재시도 로직 사용
        if API_SHOW_ERRORS:
            try:
                st.warning(f"⚠️ 직접 요청 실패: {str(e)}. 재시도 로직을 사용합니다...")
            except:
                pass
        response = _api_request_with_retry(
            "POST", url,
            json={"user_id": user_id, "context": context}
        )
    
    # 404 에러면 사용자가 없다는 의미 (익명 사용자도 식별만 되면 되므로 재시도)
    # 디버깅: response 상태 확인
    if API_SHOW_ERRORS:
        try:
            if response is None:
                st.error("❌ response가 None입니다!")
            elif response:
                st.info(f"🔍 response 상태 확인: status_code={response.status_code}")
            else:
                st.error("❌ response가 False입니다!")
        except:
            pass
    
    if response and response.status_code == 404:
        if API_SHOW_ERRORS:
            try:
                st.warning(f"⚠️ 세션 생성 404 응답. 현재 user_id: {user_id[:20]}...")
                st.info("🔍 사용자 확인 중...")
            except:
                pass
        
        # 원본 user_id 저장 (username 조회용)
        # 세션 생성 시 user_id로 "user_xxx"를 보냈지만 서버는 UUID를 기대함
        # 따라서 username으로 조회해서 서버 UUID를 가져와야 함
        original_user_id = user_id
        
        # user_id가 UUID 형식이면 로컬 user_id를 username으로 사용
        if not user_id.startswith("user_") and len(user_id) == 36:
            # UUID 형식이면 로컬 user_id를 가져와서 username으로 사용
            from core.user import get_or_create_user_id
            local_user_id = get_or_create_user_id()
            if local_user_id and local_user_id.startswith("user_"):
                original_user_id = local_user_id
        elif not user_id.startswith("user_"):
            # 이상한 형식이면 로컬 user_id 확인
            from core.user import get_or_create_user_id
            local_user_id = get_or_create_user_id()
            if local_user_id:
                original_user_id = local_user_id
        
        # 사용자 생성/조회 다시 시도 (최종 시도)
        # username으로 조회 시도 (이미 존재할 수 있음)
        try:
            import requests
            get_url = f"{API_BASE_URL}/api/v1/users/"
            get_params = {"username": original_user_id}
            
            if API_SHOW_ERRORS:
                try:
                    st.info(f"🔍 username='{original_user_id[:20]}...'로 사용자 조회 중...")
                except:
                    pass
            
            get_response = requests.get(get_url, params=get_params, timeout=5)
            
            if API_SHOW_ERRORS:
                try:
                    st.info(f"📋 사용자 조회 응답 코드: {get_response.status_code}")
                except:
                    pass
            
            if get_response.status_code == 200:
                users = get_response.json()
                if API_SHOW_ERRORS:
                    try:
                        st.json(users)  # 디버깅: 서버 응답 확인
                    except:
                        pass
                
                server_user_id = _extract_user_id_from_response(users)
                if server_user_id:
                    _save_server_user_id(server_user_id)
                    user_id = server_user_id
                    if API_SHOW_ERRORS:
                        try:
                            st.success(f"✅ 사용자 조회 성공! 서버 user_id: {server_user_id[:20]}...")
                            st.info(f"🔄 서버 user_id로 세션 생성 재시도...")
                        except:
                            pass
                else:
                    if API_SHOW_ERRORS:
                        try:
                            st.error(f"❌ 사용자 조회는 성공했지만 user_id를 찾을 수 없습니다.")
                            st.json(users)  # 디버깅: 서버 응답 확인
                        except:
                            pass
            else:
                # 사용자 조회 실패 - 사용자 생성 시도
                if API_SHOW_ERRORS:
                    try:
                        st.warning(f"⚠️ 사용자 조회 실패 (응답 코드: {get_response.status_code}). 사용자 생성 시도...")
                        try:
                            error_data = get_response.json()
                            st.json(error_data)
                        except:
                            st.text(get_response.text[:200])
                    except:
                        pass
                
                # 사용자 생성 시도
                if _ensure_backend_user(original_user_id, silent=False):  # silent=False로 변경하여 에러 표시
                    backend_user_id = st.session_state.get("backend_user_id")
                    if backend_user_id:
                        user_id = backend_user_id
                        if API_SHOW_ERRORS:
                            try:
                                st.success(f"✅ 사용자 생성 성공! 서버 user_id: {backend_user_id[:20]}...")
                            except:
                                pass
                    else:
                        if API_SHOW_ERRORS:
                            try:
                                st.warning("⚠️ 사용자 생성은 성공했지만 backend_user_id를 가져올 수 없습니다.")
                            except:
                                pass
        except Exception as e:
            if API_SHOW_ERRORS:
                try:
                    st.error(f"❌ 사용자 조회 실패: {str(e)}")
                    import traceback
                    st.code(traceback.format_exc())
                except:
                    pass
        
        # 세션 생성 재시도
        if API_SHOW_ERRORS:
            try:
                st.info(f"🔄 세션 생성 재시도 (user_id: {user_id[:20]}...)")
            except:
                pass
        
        try:
            response = requests.post(url, json={"user_id": user_id, "context": context}, timeout=5)
            if API_SHOW_ERRORS:
                try:
                    st.info(f"📋 세션 생성 재시도 응답 코드: {response.status_code}")
                    if response.status_code != 201:
                        try:
                            error_data = response.json()
                            st.json(error_data)
                        except:
                            st.text(response.text[:200])
                except:
                    pass
        except Exception as e:
            if API_SHOW_ERRORS:
                try:
                    st.error(f"❌ 세션 생성 재시도 실패: {str(e)}")
                    import traceback
                    st.code(traceback.format_exc())
                except:
                    pass
    
    if response:
        if response.status_code == 201:
            data = response.json()
            backend_session_id = data.get("session_id")
            if backend_session_id:
                st.session_state["backend_session_id"] = backend_session_id
                st.session_state["session_token"] = data.get("session_token")
                return backend_session_id
        else:
            # 에러 응답 파싱 및 로깅
            _log_api_error("세션 생성 실패", response)
    elif response is None:
        # 연결 실패
        _log_api_error("세션 생성 실패", None, 
                      error_msg=f"서버 연결 실패: {API_BASE_URL}에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요.")
    
    return None


def _log_news_interaction(news_id: str, interaction_type: str, original_event_name: str = None, **kwargs) -> Tuple[bool, Optional[str]]:
    """뉴스 상호작용을 API로 전송"""
    if not REQUESTS_AVAILABLE or not API_ENABLE:
        return False, "API 비활성화"
    
    # news_id를 정수로 변환 (정수, 문자열 모두 처리)
    news_id_int = None
    try:
        if news_id is None:
            return False, "news_id가 없습니다"
        
        # 이미 정수인 경우
        if isinstance(news_id, int):
            news_id_int = news_id
        # 문자열인 경우
        elif isinstance(news_id, str):
            # 빈 문자열 체크
            if not news_id.strip():
                return False, "news_id가 없습니다"
            # 숫자로 변환 시도
            news_id_int = int(news_id)
        else:
            # 다른 타입인 경우 문자열로 변환 후 시도
            news_id_str = str(news_id)
            if news_id_str.isdigit():
                news_id_int = int(news_id_str)
            else:
                return False, f"잘못된 news_id 형식: {news_id} (타입: {type(news_id)})"
    except (ValueError, TypeError, AttributeError) as e:
        return False, f"잘못된 news_id 형식: {news_id} (에러: {str(e)})"
    
    if news_id_int is None:
        return False, "news_id가 없습니다"
    
    user_id = _get_user_id()
    url = f"{API_BASE_URL}/api/v1/news/{news_id_int}/interactions"
    
    # payload에 원래 이벤트 이름 포함 (로그 뷰어에서 복원하기 위해)
    payload = kwargs.get("payload", {})
    if isinstance(payload, dict):
        payload = payload.copy()
    else:
        payload = {}
    
    if original_event_name:
        payload["original_event_name"] = original_event_name
    
    # 서버 스키마: body에 news_id와 interaction_type 포함
    request_body = {
        "news_id": news_id_int,
        "interaction_type": interaction_type
    }
    
    # payload가 있으면 함께 전송 (서버가 지원하는 경우)
    if payload:
        request_body["metadata"] = payload  # 또는 payload 필드가 있으면 그대로 사용
    
    response = _api_request_with_retry(
        "POST", url,
        params={"user_id": user_id},  # user_id는 query parameter로
        json=request_body
    )
    
    if response is None:
        return False, "서버 연결 실패"
    
    if response.status_code == 201:
        return True, None
    
    # 에러 응답 파싱 및 로깅
    try:
        error_detail = response.json().get("detail", response.text[:200])
    except:
        error_detail = response.text[:200] if response.text else "알 수 없는 오류"
    
    _log_api_error("뉴스 상호작용 로깅 실패", response)
    
    return False, f"HTTP {response.status_code}: {error_detail}"


def _log_dialogue(sender_type: str, content: str, intent: Optional[str] = None) -> Tuple[Optional[int], Optional[str]]:
    """대화를 Supabase 또는 API로 전송하고 dialogue_id를 반환"""
    
    # 🎯 event_log 중심 모드: Supabase에 직접 저장
    if SUPABASE_ENABLE:
        supabase = get_supabase_client()
        if supabase:
            try:
                # 로그 중심 모드: session_id는 선택적 (NULL 허용으로 변경됨)
                # 세션별 통계를 위해 있으면 사용하고, 없으면 NULL로 저장
                session_id = _get_backend_session_id()
                
                # session_id가 없으면 생성 시도 (선택적, 실패해도 OK)
                if session_id is None:
                    # API가 활성화되어 있으면 API로 세션 생성 시도
                    if API_ENABLE:
                        session_id = _ensure_backend_session()
                    
                    # API가 비활성화되어 있으면 Supabase에 간단하게 세션 생성 시도 (선택적)
                    # 실패해도 조용히 처리 (event_logs에는 기록되고, dialogues는 session_id NULL로 저장)
                    if session_id is None and not API_ENABLE:
                        try:
                            user_id = _get_user_id()
                            if user_id:
                                # 간단한 세션 생성 (필수 필드만)
                                # users 테이블에 사용자가 없으면 생성 시도 (FK 제약)
                                user_exists = False
                                try:
                                    user_response = supabase.table("users").select("user_id").eq("user_id", user_id).limit(1).execute()
                                    user_exists = user_response.data and len(user_response.data) > 0
                                except:
                                    user_exists = False
                                
                                # 사용자가 없으면 간단하게 생성 시도
                                if not user_exists:
                                    try:
                                        user_insert = {
                                            "user_id": user_id,
                                            "created_at": datetime.now(timezone.utc).isoformat()
                                        }
                                        supabase.table("users").insert(user_insert).execute()
                                        user_exists = True
                                        import time
                                        time.sleep(0.1)  # FK 제약 반영 대기
                                    except Exception:
                                        # 사용자 생성 실패해도 조용히 처리
                                        pass
                                
                                # 세션 생성 시도 (users 테이블에 사용자가 있어야 함)
                                if user_exists:
                                    try:
                                        session_token = str(uuid.uuid4())
                                        from datetime import timedelta
                                        expires_at = datetime.now(timezone.utc) + timedelta(days=30)
                                        session_insert = {
                                            "user_id": user_id,
                                            "session_token": session_token,
                                            "created_at": datetime.now(timezone.utc).isoformat(),
                                            "expires_at": expires_at.isoformat()
                                        }
                                        session_response = supabase.table("sessions").insert(session_insert).execute()
                                        if session_response.data:
                                            session_row = session_response.data[0] if session_response.data else {}
                                            session_id = session_row.get("session_id") or session_row.get("id")
                                            if session_id:
                                                st.session_state["backend_session_id"] = session_id
                                    except Exception:
                                        # 세션 생성 실패해도 조용히 처리 (dialogues는 session_id NULL로 저장)
                                        pass
                        except Exception:
                            # 세션 생성 실패해도 조용히 처리
                            pass
                
                # dialogues 테이블에 저장 시도 (session_id가 NULL이어도 저장 가능)
                insert_data = {
                    "sender_type": sender_type,
                    "content": content,
                    "created_at": datetime.now(timezone.utc).isoformat()
                }
                
                # session_id가 있으면 포함, 없으면 NULL로 저장 (NOT NULL 제약 해제됨)
                if session_id is not None:
                    insert_data["session_id"] = session_id
                
                if intent:
                    insert_data["intent"] = intent
                
                try:
                    response = supabase.table("dialogues").insert(insert_data).execute()
                    
                    if response.data:
                        # Supabase에서 생성된 dialogue_id 반환
                        row_data = response.data[0] if response.data else {}
                        # 가능한 모든 키 확인 (dialogue_id, id 등)
                        dialogue_id = (
                            row_data.get("dialogue_id") or 
                            row_data.get("id") or
                            (row_data.get("dialogue_id") if "dialogue_id" in row_data else None)
                        )
                        
                        # 숫자로 변환 시도 (BIGINT인 경우)
                        if dialogue_id is not None:
                            try:
                                dialogue_id = int(dialogue_id)
                            except (ValueError, TypeError):
                                pass
                        
                        if dialogue_id:
                            return dialogue_id, None
                        else:
                            # dialogue_id를 찾을 수 없어도 에러 아님 (event_logs에 기록됨)
                            # 디버깅: response.data 전체 확인
                            if API_SHOW_ERRORS:
                                try:
                                    st.warning(f"⚠️ dialogue_id를 찾을 수 없음. response.data: {response.data}")
                                except:
                                    pass
                            return None, None
                    else:
                        # dialogues 저장 실패해도 에러 아님 (event_logs에 기록됨)
                        if API_SHOW_ERRORS:
                            try:
                                st.warning(f"⚠️ dialogues 저장 실패: response.data가 비어있음")
                            except:
                                pass
                        return None, None
                except Exception as dialogue_error:
                    # dialogues 저장 실패해도 에러 아님 (event_logs에 기록됨)
                    # 로그 중심 모드에서는 dialogues는 선택적
                    if API_SHOW_ERRORS:
                        try:
                            st.warning(f"⚠️ dialogues 저장 예외: {str(dialogue_error)}")
                        except:
                            pass
                    return None, None
            except Exception as e:
                error_msg = str(e)
                # Supabase 에러는 항상 표시 (API_SHOW_ERRORS와 독립적)
                try:
                    st.error(f"⚠️ Supabase dialogue 삽입 실패: {error_msg}")
                    import traceback
                    st.error(f"상세 에러:\n{traceback.format_exc()}")
                except:
                    pass
                # Supabase 실패해도 API로 시도 (API 활성화 시)
                if API_ENABLE:
                    pass  # 아래 API 로직으로 진행
                else:
                    return None, error_msg
    
    # API 모드 (기존 로직)
    if not REQUESTS_AVAILABLE or not API_ENABLE:
        return None, "API 비활성화"
    
    # 세션 생성 시도 (최대 2회 재시도)
    backend_session_id = None
    for attempt in range(2):
        backend_session_id = _ensure_backend_session()
        if backend_session_id:
            break
        # 실패 시 잠시 대기 후 재시도
        if attempt < 1:
            time.sleep(0.5)
    
    if not backend_session_id:
        return None, "세션 생성 실패"
    
    url = f"{API_BASE_URL}/api/v1/dialogues/"
    
    # 서버 스키마에 맞게 구성
    payload = {
        "session_id": backend_session_id,
        "sender_type": sender_type,
        "content": content
    }
    # intent는 선택적 필드이지만 스키마에 있으면 포함
    if intent:
        payload["intent"] = intent
    else:
        # intent가 없으면 기본값 또는 빈 문자열
        payload["intent"] = ""
    
    response = _api_request_with_retry("POST", url, json=payload)
    
    if response is None:
        return None, "서버 연결 실패"
    
    if response.status_code == 201:
        data = response.json()
        return data.get("dialogue_id"), None
    
    # 에러 응답 파싱 및 로깅
    try:
        error_detail = response.json().get("detail", response.text[:200])
    except:
        error_detail = response.text[:200] if response.text else "알 수 없는 오류"
    
    _log_api_error("대화 생성 실패", response)
    
    return None, f"HTTP {response.status_code}: {error_detail}"


def _log_agent_task(agent_id: int, dialogue_id: Optional[int], 
                    input_data: Dict[str, Any], output_data: Optional[Dict[str, Any]] = None,
                    duration_ms: Optional[int] = None) -> Optional[int]:
    """에이전트 작업을 API로 전송"""
    if not REQUESTS_AVAILABLE or not API_ENABLE:
        return None
    
    backend_session_id = _ensure_backend_session()
    if not backend_session_id:
        return None
    
    url = f"{API_BASE_URL}/api/v1/agent-tasks/"
    
    payload = {
        "agent_id": agent_id,
        "session_id": backend_session_id,
        "input_data": input_data
    }
    if dialogue_id:
        payload["dialogue_id"] = dialogue_id
    
    # 작업 생성
    response = _api_request_with_retry("POST", url, json=payload)
    
    if not response or response.status_code != 201:
        return None
    
    task_data = response.json()
    task_id = task_data.get("task_id")
    
    # 작업 완료 정보가 있으면 업데이트
    if output_data is not None or duration_ms is not None:
        complete_url = f"{API_BASE_URL}/api/v1/agent-tasks/{task_id}/complete"
        complete_payload = {}
        if output_data:
            complete_payload["output_data"] = output_data
        if duration_ms:
            complete_payload["duration_ms"] = duration_ms
        
        _api_request_with_retry("POST", complete_url, json=complete_payload)
    
    return task_id


def _update_session_context(**kwargs) -> Tuple[bool, Optional[str]]:
    """세션 컨텍스트를 업데이트
    Returns: (success: bool, error_info: Optional[str])
    """
    if not REQUESTS_AVAILABLE or not API_ENABLE:
        return False, "API 비활성화"
    
    # 컨텍스트가 비어있으면 업데이트할 필요 없음
    if not kwargs:
        return False, "컨텍스트 업데이트 내용 없음"
    
    backend_session_id = _ensure_backend_session()
    if not backend_session_id:
        # 세션이 없으면 실패
        return False, "세션 생성 실패"
    
    url = f"{API_BASE_URL}/api/v1/sessions/{backend_session_id}/context"
    
    response = _api_request_with_retry("PUT", url, json=kwargs)
    
    if response is None:
        return False, "서버 연결 실패"
    
    if response.status_code == 200:
        return True, None
    
    # 에러 응답 파싱
    try:
        error_detail = response.json().get("detail", response.text[:200])
    except:
        error_detail = response.text[:200] if response.text else "알 수 없는 오류"
    
    # 에러 응답 로깅 (디버깅용)
    if API_SHOW_ERRORS:
        try:
            st.warning(f"⚠️ 세션 컨텍스트 업데이트 실패 ({response.status_code}): {error_detail}")
        except:
            pass
    
    return False, f"HTTP {response.status_code}: {error_detail}"


# ─────────────────────────────────────────────────────────────
# event_log 중심 로깅 함수 (Supabase 직접 삽입)
# ─────────────────────────────────────────────────────────────

def _log_to_event_log(event_name: str, **kwargs) -> Tuple[bool, Optional[str]]:
    """
    event_log 테이블에 직접 이벤트를 기록합니다 (로그 중심 DB)
    
    Returns:
        (success: bool, error_info: Optional[str])
    """
    supabase = get_supabase_client()
    if not supabase:
        return False, "Supabase 클라이언트를 사용할 수 없습니다"
    
    # event_time은 현재 시간 (UTC)
    event_time = datetime.now(timezone.utc)
    
    # session_id: backend_session_id 사용 (없으면 None)
    session_id = _get_backend_session_id()
    
    # dialogue_id: 대화 관련 이벤트에서만 사용 (kwargs에서 추출)
    dialogue_id = kwargs.get("dialogue_id")
    
    # surface, source: kwargs에서 추출
    surface = kwargs.get("surface")
    source = kwargs.get("source")
    
    # ref_id: news_id, term 등 참조 ID를 저장 (우선순위: news_id > term)
    ref_id = None
    if kwargs.get("news_id"):
        ref_id = str(kwargs.get("news_id"))
    elif kwargs.get("term"):
        ref_id = str(kwargs.get("term"))
    
    # payload: 모든 추가 정보를 JSON으로 저장 (분석용)
    payload = {}
    
    # 기본 정보
    user_id = _get_user_id()
    if user_id:
        payload["user_id"] = user_id
    
    # 세션 정보 (payload에도 포함 - 분석용)
    if session_id is not None:
        payload["session_id"] = session_id
    
    # UI 컨텍스트 정보 (payload에도 포함 - 분석용)
    if surface:
        payload["surface"] = surface
    if source:
        payload["source"] = source
    
    # 이벤트별 특화 정보 수집
    if kwargs.get("message"):
        payload["message"] = kwargs.get("message")
    if kwargs.get("note"):
        payload["note"] = kwargs.get("note")
    if kwargs.get("title"):
        payload["title"] = kwargs.get("title")
    if kwargs.get("click_count") is not None:
        payload["click_count"] = kwargs.get("click_count")
    if kwargs.get("answer_len") is not None:
        payload["answer_len"] = kwargs.get("answer_len")
    if kwargs.get("via"):
        payload["via"] = kwargs.get("via")
    if kwargs.get("latency_ms") is not None:
        payload["latency_ms"] = kwargs.get("latency_ms")
    
    # 응답 관련 정보 (분석용)
    if kwargs.get("response"):
        response = kwargs.get("response")
        # 너무 길면 요약해서 저장 (분석은 가능하도록)
        if len(str(response)) > 2000:
            payload["response_preview"] = str(response)[:2000] + "..."
            payload["response_length"] = len(str(response))
        else:
            payload["response"] = response
    
    # RAG 정보 (분석용)
    if kwargs.get("rag_info"):
        rag_info = kwargs.get("rag_info")
        if isinstance(rag_info, dict):
            payload["rag_info"] = rag_info
    
    # API 정보 (분석용)
    if kwargs.get("api_info"):
        api_info = kwargs.get("api_info")
        if isinstance(api_info, dict):
            payload["api_info"] = api_info
    
    # 기존 payload가 있으면 병합 (kwargs의 payload가 우선)
    existing_payload = kwargs.get("payload", {})
    if isinstance(existing_payload, dict):
        payload.update(existing_payload)
    elif isinstance(existing_payload, str):
        try:
            parsed = json.loads(existing_payload)
            if isinstance(parsed, dict):
                payload.update(parsed)
        except:
            pass
    
    # news_id, term은 payload에도 포함 (ref_id와 함께)
    if kwargs.get("news_id"):
        payload["news_id"] = kwargs.get("news_id")
    if kwargs.get("term"):
        payload["term"] = kwargs.get("term")
    
    # Supabase에 삽입할 데이터 구성
    insert_data = {
        "event_time": event_time.isoformat(),
        "event_name": event_name,
        "payload": payload
    }
    
    # user_id를 별도 컬럼으로 추가 (사용자별 집계를 위해)
    if user_id:
        insert_data["user_id"] = user_id
    
    # 선택적 필드 추가 (None이 아닐 때만)
    if session_id is not None:
        insert_data["session_id"] = session_id
    if dialogue_id is not None:
        insert_data["dialogue_id"] = dialogue_id
    if surface:
        insert_data["surface"] = surface
    if source:
        insert_data["source"] = source
    if ref_id:
        insert_data["ref_id"] = ref_id
    
    try:
        response = supabase.table("event_logs").insert(insert_data).execute()
        return True, None
    except Exception as e:
        error_msg = str(e)
        if API_SHOW_ERRORS:
            try:
                st.warning(f"⚠️ event_log 삽입 실패 ({event_name}): {error_msg}")
            except:
                pass
        return False, error_msg


# ─────────────────────────────────────────────────────────────
# 기존 로깅 함수 (CSV + API + event_log)
# ─────────────────────────────────────────────────────────────

def log_event(event_name: str, **kwargs):
    """
    로깅 함수 (서버 중심 모드)
    --------------------------------------------------------
    ✅ 역할:
        - 사용자의 행동(이벤트)을 서버 API로 기록합니다.
        - CSV는 선택적으로 저장 (CSV_ENABLE=True일 때만)
        - 예: 뉴스 클릭, 용어 클릭, 챗봇 질문 등
    --------------------------------------------------------
    """

    # CSV 저장 (선택적 - 서버 중심 모드에서는 비활성화)
    if CSV_ENABLE:
        ensure_log_file()
        row = {
            # ================== 기본 메타 정보 ==================
            "event_id": str(uuid.uuid4()),
            "event_time": now_utc_iso(),                     # 🕓 이벤트 발생 시각 (UTC 기준, ISO 포맷)
            "event_name": event_name,                        # 🏷️ 이벤트 이름 (예: "news_click", "chat_question")

            # ================== 사용자/세션 정보 ==================
            "user_id": _get_user_id(),   # 👤 유저 식별자 (서버 UUID 우선 사용, CSV와 API 동일)
            "session_id": st.session_state.get("session_id", ""), # 💬 세션 식별자 (브라우저 새로고침마다 유지됨)

            # ================== UI 위치/출처 정보 ==================
            "surface": _nz(kwargs.get("surface", "")),       # 🧭 화면 구역 (예: "home", "detail", "sidebar")
            "source":  _nz(kwargs.get("source", "")),        # 🧩 이벤트가 발생한 세부 위치 (예: "chat", "list", "term_box")

            # ================== 콘텐츠 식별자 ==================
            "news_id": _nz(kwargs.get("news_id", "")),       # 📰 클릭/요약된 뉴스의 고유 ID
            "term":    _nz(kwargs.get("term", "")),          # 💡 클릭한 금융용어 (예: "양적완화")

            # ================== 사용자 입력/노트 관련 ==================
            "message": _as_json_text(kwargs.get("message", "")),  # 💬 사용자가 입력한 메시지 (챗봇 질문 등)
            "note":    _nz(kwargs.get("note", "")),               # 🗒️ 임시 메모/추가 코멘트
            "title":   _nz(kwargs.get("title", "")),              # 🏷️ 뉴스나 카드의 제목 (클릭된 항목 표시용)
            "click_count": _nz(kwargs.get("click_count", "")),    # 🔢 특정 UI 요소 클릭 횟수 (실험용)

            # ================== 챗봇 응답/성능 메타 ==================
            "answer_len": _nz(kwargs.get("answer_len", "")),      # 📏 챗봇 응답 길이 (토큰/문자 수)
            "via":        _nz(kwargs.get("via", "")),             # ⚙️ 사용된 모델 혹은 라우팅 경로 (예: "openai", "mock")
            "latency_ms": _nz(kwargs.get("latency_ms", "")),      # ⏱️ 응답 지연 시간(ms 단위)

            # ================== 추가 정보(JSON) ==================
            "payload": _as_json_text(kwargs.get("payload", {})),
            # 📦 상세 데이터(JSON 형태로 저장)
            # 예시: {"browser": "Chrome", "os": "Windows", "ref": "sidebar-term", "exp_group": "A"}
        }

        # DictWriter로 CSV에 한 줄씩 기록
        with open(LOG_FILE, "a", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=CSV_HEADER,
                quoting=csv.QUOTE_MINIMAL,
                extrasaction="ignore"
            )
            writer.writerow(row)
    
    # 🎯 대화 관련 이벤트는 dialogue 생성이 필요하므로 먼저 처리
    # (dialogue_id가 생성된 후 event_log에 기록되어야 함)
    dialogue_events = ("chat_question", "chat_answer", "chat_response", "glossary_answer", "glossary_click")
    if event_name in dialogue_events:
        # _route_event_to_api를 먼저 실행 (dialogue 생성 및 event_log 기록 포함)
        if SUPABASE_ENABLE or (API_ENABLE and REQUESTS_AVAILABLE):
            try:
                success, error_info = _route_event_to_api(event_name, **kwargs)
                # dialogue 이벤트는 _route_event_to_api에서 이미 event_log에 기록됨
                # (성공/실패 여부와 관계없이 계속 진행)
            except Exception as e:
                # 에러 발생해도 계속 진행
                if API_SHOW_ERRORS:
                    try:
                        st.warning(f"⚠️ 대화 이벤트 처리 실패 ({event_name}): {str(e)}")
                    except:
                        pass
        return  # dialogue 이벤트는 여기서 종료
    
    # 🎯 event_log에 직접 기록 (로그 중심 DB - 우선순위 1)
    if SUPABASE_ENABLE:
        event_log_success, event_log_error = _log_to_event_log(event_name, **kwargs)
        # event_log 기록 실패해도 계속 진행 (다른 방식으로 기록 시도)
    
    # API로 전송 (서비스 DB - 선택적, 기존 호환성 유지)
    if API_ENABLE and REQUESTS_AVAILABLE:
        try:
            success, error_info = _route_event_to_api(event_name, **kwargs)
            # API 전송 상태 추적 (디버깅용)
            if "api_send_status" not in st.session_state:
                st.session_state["api_send_status"] = {
                    "success": 0, 
                    "failed": 0,
                    "failed_events": []  # 실패한 이벤트 목록
                }
            if success:
                st.session_state["api_send_status"]["success"] += 1
            else:
                st.session_state["api_send_status"]["failed"] += 1
                # 실패한 이벤트 정보 저장 (최대 10개)
                if error_info:
                    failed_events = st.session_state["api_send_status"]["failed_events"]
                    failed_events.append({
                        "event": event_name,
                        "error": error_info,
                        "time": now_utc_iso()
                    })
                    # 최대 10개만 유지
                    if len(failed_events) > 10:
                        failed_events.pop(0)
        except Exception as e:
            # API 실패해도 앱은 계속 작동 (CSV는 이미 저장됨)
            if "api_send_status" not in st.session_state:
                st.session_state["api_send_status"] = {
                    "success": 0, 
                    "failed": 0,
                    "failed_events": []
                }
            st.session_state["api_send_status"]["failed"] += 1
            failed_events = st.session_state["api_send_status"]["failed_events"]
            failed_events.append({
                "event": event_name,
                "error": str(e),
                "time": now_utc_iso()
            })
            if len(failed_events) > 10:
                failed_events.pop(0)
            if API_SHOW_ERRORS:
                st.error(f"❌ API 전송 실패 ({event_name}): {str(e)}")


def _parse_message(message: str) -> str:
    """JSON 문자열 형태의 메시지를 파싱하여 실제 내용 추출"""
    if not message:
        return ""
    try:
        if isinstance(message, str) and message.startswith("{"):
            message_dict = json.loads(message)
            if isinstance(message_dict, dict):
                return message_dict.get("content", message)
    except:
        pass
    return message


def _handle_dialogue_event(
    event_name: str,
    sender_type: str,
    intent: str,
    default_via: str,
    default_agent_id: int,
    **kwargs
) -> Tuple[bool, Optional[str]]:
    """
    대화 관련 이벤트 처리 공통 함수
    
    Args:
        event_name: 이벤트 이름
        sender_type: "user" 또는 "assistant"
        intent: 대화 의도 (예: "question", "answer", "glossary_explanation")
        default_via: 기본 via 값
        default_agent_id: 기본 agent_id
        **kwargs: 추가 파라미터
    """
    # sender_type에 따라 적절한 content 선택
    if sender_type == "assistant":
        # assistant의 경우: response 우선, 없으면 message 사용
        message = kwargs.get("response") or _parse_message(kwargs.get("message", ""))
        
        # glossary_answer의 경우 response가 없으면 term 기반으로 기본 메시지 생성
        if not message and event_name == "glossary_answer":
            term = kwargs.get("term", "")
            if term:
                message = f"{term} 용어에 대한 설명"
            else:
                message = "금융 용어 설명"
    else:
        # user의 경우: message 사용
        message = _parse_message(kwargs.get("message", ""))
    
    if not message:
        return False, "메시지가 없습니다"
    
    dialogue_id, error = _log_dialogue(sender_type, message, intent=intent)
    
    # dialogue_id가 생성되었으면 kwargs에 추가
    if dialogue_id:
        kwargs["dialogue_id"] = dialogue_id
    
    # 🎯 dialogue 생성 성공 여부와 관계없이 event_log에 기록
    # (dialogue 생성 실패해도 이벤트는 기록되어야 함)
    if SUPABASE_ENABLE:
        _log_to_event_log(event_name, **kwargs)
    
    # dialogue_id가 없으면 에러 반환 (하지만 event_log는 이미 기록됨)
    if not dialogue_id:
        return False, error or "대화 생성 실패"
    
    # 에이전트 작업 처리
    via = kwargs.get("via", default_via)
    agent_id = AGENT_ID_MAPPING.get(via, default_agent_id)
    
    input_data = {
        "message": message,
        "context": kwargs.get("surface", "")
    }
    
    # 용어 관련 이벤트는 term 추가
    term = kwargs.get("term", "")
    if term:
        input_data["term"] = term
    
    # 응답 관련 이벤트는 output_data 추가
    output_data = {}
    answer_len = kwargs.get("answer_len")
    latency_ms = kwargs.get("latency_ms")
    
    # 기본 정보
    if answer_len is not None:
        output_data["answer_len"] = answer_len
    if via:
        output_data["via"] = via
    
    # OpenAI API 정보 수집 (메타데이터가 있는 경우)
    if "api_info" in kwargs:
        api_info = kwargs["api_info"]
        if isinstance(api_info, dict):
            output_data["model"] = api_info.get("model")
            output_data["tokens"] = api_info.get("tokens")
            output_data["api_params"] = api_info.get("api_params")
    
    # RAG 정보 수집
    if "rag_info" in kwargs:
        rag_info = kwargs["rag_info"]
        if isinstance(rag_info, dict):
            output_data["rag_info"] = rag_info
    
    # 실제 응답 수집 (너무 길면 요약)
    if "response" in kwargs:
        response = kwargs.get("response", "")
        if len(response) > 1000:
            output_data["response_preview"] = response[:1000] + "..."
            output_data["response_length"] = len(response)
        else:
            output_data["response"] = response
    
    # 에러 정보 수집
    if "error" in kwargs:
        error_info = kwargs["error"]
        if isinstance(error_info, dict):
            output_data["error"] = error_info
        else:
            output_data["error"] = {"message": str(error_info)}
    
    # 에이전트 작업 로깅 (output_data가 비어있어도 기본 정보는 저장)
    # via 정보가 있으면 항상 로깅 (에이전트 타입 정보가 중요)
    if via or output_data:
        # output_data가 비어있으면 기본 정보만 저장
        if not output_data:
            output_data = {}
            if via:
                output_data["via"] = via
        
        _log_agent_task(
            agent_id=agent_id,
            dialogue_id=dialogue_id,
            input_data=input_data,
            output_data=output_data if output_data else None,
            duration_ms=latency_ms
        )
    
    return True, None


def _route_event_to_api(event_name: str, **kwargs) -> Tuple[bool, Optional[str]]:
    """
    이벤트 타입에 따라 적절한 API로 라우팅
    Returns: (success: bool, error_info: Optional[str])
    """
    
    # 1. 뉴스 상호작용 이벤트
    if event_name in EVENT_TO_INTERACTION_TYPE:
        interaction_type = EVENT_TO_INTERACTION_TYPE[event_name]
        news_id = kwargs.get("news_id")
        # news_id가 None이 아니고 빈 문자열이 아닌 경우
        if news_id is not None and news_id != "":
            # news_id를 문자열로 변환 (함수 시그니처 호환을 위해)
            news_id_str = str(news_id) if news_id is not None else ""
            # news_id를 kwargs에서 제거하여 중복 전달 방지
            filtered_kwargs = {k: v for k, v in kwargs.items() if k != "news_id"}
            # 원래 이벤트 이름을 함께 전달 (로그 뷰어에서 복원하기 위해)
            return _log_news_interaction(news_id_str, interaction_type, original_event_name=event_name, **filtered_kwargs)
        return False, "news_id가 없습니다"
    
    # 2. 챗봇 질문
    elif event_name == "chat_question":
        return _handle_dialogue_event(
            event_name=event_name,
            sender_type="user",
            intent="question",
            default_via="openai",
            default_agent_id=1,
            **kwargs
        )
    
    # 3. 챗봇 응답 (chat_answer 또는 chat_response)
    elif event_name in ("chat_answer", "chat_response"):
        return _handle_dialogue_event(
            event_name=event_name,
            sender_type="assistant",
            intent="answer",
            default_via="openai",
            default_agent_id=1,
            **kwargs
        )
    
    # 4. 용어 설명 응답 (glossary_answer)
    elif event_name == "glossary_answer":
        return _handle_dialogue_event(
            event_name=event_name,
            sender_type="assistant",
            intent="glossary_explanation",
            default_via="rag",
            default_agent_id=3,
            **kwargs
        )
    
    # 5. 용어 클릭 (glossary_click) - 자동 질문 생성
    elif event_name == "glossary_click":
        return _handle_dialogue_event(
            event_name=event_name,
            sender_type="user",
            intent="glossary_question",
            default_via="rag",
            default_agent_id=3,
            **kwargs
        )
    
    # 6. 스크롤 깊이, 체류시간 등 UI 컨텍스트 정보
    elif event_name in ("scroll_depth", "view_duration"):
        return _handle_context_update_event(event_name, **kwargs)
    
    # 7. 세션 시작
    elif event_name == "session_start":
        # event_log 중심 모드에서는 API 연결 실패해도 성공 처리
        # session_start는 event_log에 이미 기록되므로 항상 성공
        if API_ENABLE:
            # API 활성화 시에만 세션 생성 시도 (실패해도 계속 진행)
            backend_session_id = _ensure_backend_session()
            if backend_session_id:
                # 세션 컨텍스트 업데이트 (선택적)
                payload = kwargs.get("payload", {})
                if payload:
                    context_updates = {
                        "session_start": True,
                        "session_start_time": now_utc_iso(),
                    }
                    if isinstance(payload, dict):
                        context_updates.update(payload)
                    _update_session_context(**context_updates)
        
        # event_log에 기록되었으므로 항상 성공
        return True, None
    
    # 8. 기타 이벤트는 처리하지 않음 (CSV에만 저장)
    else:
        return False, f"처리되지 않는 이벤트 타입: {event_name}"


def _parse_payload(payload: Any) -> Dict[str, Any]:
    """payload를 딕셔너리로 변환"""
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            return json.loads(payload) if payload else {}
        except:
            return {}
    return {}


def _handle_context_update_event(event_name: str, **kwargs) -> Tuple[bool, Optional[str]]:
    """스크롤 깊이, 체류시간 등 컨텍스트 업데이트 이벤트 처리"""
    context_updates = {}
    payload = _parse_payload(kwargs.get("payload", {}))
    
    # 이벤트별 컨텍스트 정보 추출
    if event_name == "scroll_depth":
        depth_pct = payload.get("depth_pct")
        if depth_pct is not None:
            context_updates["scroll_depth"] = depth_pct
    elif event_name == "view_duration":
        duration_sec = payload.get("duration_sec")
        max_depth_pct = payload.get("max_depth_pct")
        if duration_sec is not None:
            context_updates["view_duration"] = duration_sec
        if max_depth_pct is not None:
            context_updates["max_depth_pct"] = max_depth_pct
    
    # 기타 컨텍스트 정보 추가
    for key in ["surface", "source", "term", "click_count"]:
        value = kwargs.get(key)
        if value:
            context_updates[key] = value
    
    if not context_updates:
        return False, "컨텍스트 업데이트 내용 없음"
    
    success, error_info = _update_session_context(**context_updates)
    return (success, error_info)


# ──────────────────────────────
# 추가: 스크롤 깊이 및 뉴스 체류시간 이벤트
# ──────────────────────────────


def log_scroll_depth(depth_pct: float):
    """
    사용자가 뉴스 리스트를 스크롤했을 때 깊이를 로깅합니다.
    depth_pct: 스크롤 진행률 (0~100)
    """
    payload = {"depth_pct": round(depth_pct, 1)}
    log_event(
        event_name="scroll_depth",
        surface="news_list",
        payload=payload
    )


def start_view_timer(news_id: str):
    """
    뉴스 상세 보기 시작 시 호출.
    st.session_state에 시작 시간을 저장합니다.
    """
    st.session_state["view_start_time"] = time.time()
    st.session_state["view_news_id"] = news_id
    st.session_state["detail_max_depth_pct"] = 0.0


def end_view_timer():
    """
    뉴스 상세 보기 종료 시 호출.
    체류시간(duration_sec) + max_depth_pct를 payload을 계산하여 로그로 남깁니다.
    """
    if "view_start_time" in st.session_state:
        duration_sec = time.time() - st.session_state["view_start_time"]
        news_id = st.session_state.get("view_news_id", None)
        max_depth = st.session_state.get("detail_max_depth_pct", 0.0)
        payload = {
            "news_id": news_id,
            "duration_sec": round(duration_sec, 2),
            "max_depth_pct": round(max_depth, 1),
        }
        log_event(
            event_name="view_duration",
            surface="news_detail",
            news_id=news_id,
            payload=payload
        )
        # 세션 초기화
        for k in ("view_start_time", "view_news_id", "detail_max_depth_pct"):
            if k in st.session_state:
                del st.session_state[k]

def update_detail_scroll_depth_eval(step: float = 5.0, key: str = "detail_scroll"):
    """
    기사 상세 화면에서 호출: 현재 스크롤%를 읽어 detail_max_depth_pct를 갱신.
    - step: 이전 최대값 대비 최소 상승폭(%)
    """
    depth = streamlit_js_eval(
        js_expressions="""
(() => {
  const doc = document.documentElement, body = document.body;
  const y = (window.pageYOffset || doc.scrollTop || body.scrollTop || 0);
  const inner = window.innerHeight || doc.clientHeight || 0;
  const full = Math.max(body.scrollHeight, body.offsetHeight, doc.clientHeight, doc.scrollHeight, doc.offsetHeight) || 1;
  return Math.min(100, ((y + inner) / full) * 100);
})()
""",
        key=key,
        want_output=True,
    )

    if isinstance(depth, (int, float)):
        prev = float(st.session_state.get("detail_max_depth_pct", 0.0))
        if depth >= 99.0 or depth - prev >= step:
            st.session_state["detail_max_depth_pct"] = max(prev, float(depth))

def is_page_hidden_eval(key: str = "vis_eval") -> bool:
    """
    document.hidden 값을 JS로 평가해 True/False 반환.
    """
    hidden = streamlit_js_eval(
        js_expressions="document.hidden",
        key=key,
        want_output=True,
    )
    return bool(hidden)