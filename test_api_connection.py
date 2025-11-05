"""
간단한 API 연결 테스트 스크립트

사용법:
    streamlit run test_api_connection.py
"""

import streamlit as st
from core.logger import log_event
from core.config import API_ENABLE, API_BASE_URL, API_SHOW_ERRORS
import requests

st.set_page_config(page_title="API 연결 테스트", layout="wide")

st.title("🔗 API 연결 테스트")
st.markdown("---")

# 설정 확인
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("API 활성화", "✅ 활성화" if API_ENABLE else "❌ 비활성화")
with col2:
    st.metric("서버 주소", API_BASE_URL)
with col3:
    st.metric("에러 표시", "✅ 표시" if API_SHOW_ERRORS else "❌ 숨김")

st.markdown("---")

# 서버 연결 확인
st.subheader("1️⃣ 서버 연결 확인")

if st.button("🔍 서버 연결 테스트"):
    try:
        response = requests.get(f"{API_BASE_URL}/docs", timeout=5)
        if response.status_code == 200:
            st.success(f"✅ 서버 연결 성공! ({API_BASE_URL})")
            st.info(f"Swagger UI: {API_BASE_URL}/docs")
        else:
            st.warning(f"⚠️ 서버 응답: {response.status_code}")
    except requests.ConnectionError:
        st.error(f"❌ 서버 연결 실패: {API_BASE_URL}에 연결할 수 없습니다.")
        st.info("💡 백엔드 서버가 실행 중인지 확인하세요.")
    except Exception as e:
        st.error(f"❌ 에러 발생: {str(e)}")

st.markdown("---")

# 세션 상태 리셋
st.subheader("🔧 세션 상태 관리")
col_reset1, col_reset2, col_reset3 = st.columns(3)
with col_reset1:
    if st.button("🔄 세션 상태 리셋"):
        # 세션 상태 초기화
        if "backend_user_created" in st.session_state:
            del st.session_state["backend_user_created"]
        if "backend_user_id" in st.session_state:
            del st.session_state["backend_user_id"]
        if "backend_session_id" in st.session_state:
            del st.session_state["backend_session_id"]
        if "session_token" in st.session_state:
            del st.session_state["session_token"]
        if "user_id_mapping" in st.session_state:
            del st.session_state["user_id_mapping"]
        st.success("✅ 세션 상태가 리셋되었습니다.")
with col_reset2:
    if st.button("📊 현재 세션 상태 확인"):
        # 로컬 user_id 가져오기
        from core.user import get_or_create_user_id
        local_user_id = get_or_create_user_id()
        backend_user_id = st.session_state.get("backend_user_id", None)
        user_id_mapping = st.session_state.get("user_id_mapping", {})
        
        st.markdown("### 🔗 user_id 매핑 관계")
        col_map1, col_map2 = st.columns(2)
        with col_map1:
            st.info(f"**로컬 user_id**:\n`{local_user_id}`")
        with col_map2:
            if backend_user_id:
                st.success(f"**서버 user_id**:\n`{backend_user_id}`")
            else:
                st.warning("**서버 user_id**:\n없음 (서버 연결 필요)")
        
        if user_id_mapping:
            st.markdown("**매핑 정보**:")
            st.json(user_id_mapping)
        
        st.markdown("### 📋 세션 상태")
        st.json({
            "backend_user_created": st.session_state.get("backend_user_created", False),
            "backend_user_id": backend_user_id,
            "backend_session_id": st.session_state.get("backend_session_id", None),
            "session_token": st.session_state.get("session_token", None),
        })
        
        st.info("💡 **이해하기**: 로컬 `user_id`는 서버의 `username`으로 저장되고, 서버가 새로운 UUID 형식 `user_id`를 생성합니다. 이후 모든 API 호출은 서버의 `user_id`를 사용합니다.")
with col_reset3:
    if st.button("👤 사용자 생성 강제 시도"):
        from core.user import get_or_create_user_id
        from core.logger import _ensure_backend_user, _get_user_id
        import streamlit as st
        
        local_user_id = get_or_create_user_id()
        st.info(f"🔍 로컬 user_id: `{local_user_id}`")
        
        # 사용자 생성 시도 (silent=False로 상세 에러 표시)
        st.info("🔧 서버에 사용자 생성 요청 중...")
        success = _ensure_backend_user(local_user_id, silent=False)
        
        if success:
            backend_user_id = st.session_state.get("backend_user_id")
            if backend_user_id:
                st.success(f"✅ 사용자 생성/확인 성공!")
                st.info(f"📋 서버 user_id: `{backend_user_id}`")
                st.json({
                    "로컬 user_id (username)": local_user_id,
                    "서버 user_id (UUID)": backend_user_id,
                    "backend_user_created": st.session_state.get("backend_user_created", False)
                })
            else:
                st.warning("⚠️ 사용자 생성은 성공했지만 backend_user_id를 가져올 수 없습니다.")
        else:
            st.error("❌ 사용자 생성 실패")
            st.info("💡 위의 '🔍 상세 진단 정보'를 확인하여 서버 연결 문제를 해결하세요.")

st.markdown("---")

# 테스트 이벤트 전송
st.subheader("2️⃣ 테스트 이벤트 전송")

col_test1, col_test2, col_test3 = st.columns(3)

with col_test1:
    if st.button("📰 뉴스 클릭 테스트"):
        log_event(
            "news_click",
            news_id="999",  # 테스트용
            surface="test",
            source="test_script",
            title="테스트 뉴스"
        )
        st.success("✅ 뉴스 클릭 이벤트 전송 완료!")

with col_test2:
    if st.button("💬 챗봇 질문 테스트"):
        # 세션 생성 상태 확인
        from core.logger import _get_backend_session_id, _ensure_backend_session, _get_user_id, _ensure_backend_user
        user_id = _get_user_id()
        
        # 세션 생성 시도
        session_id_before = _get_backend_session_id()
        st.info(f"🔍 세션 생성 전: {session_id_before}")
        st.info(f"👤 사용자 ID: {user_id}")
        
        # 사용자 생성 확인
        st.info("🔧 사용자 생성 확인 중...")
        user_created = _ensure_backend_user(user_id)
        if user_created:
            st.success("✅ 사용자 확인/생성 완료")
        else:
            st.warning("⚠️ 사용자 생성 실패 또는 이미 존재")
            # 사용자 생성 API 직접 호출해서 에러 확인
            st.info("🔍 사용자 생성 API 직접 호출 테스트...")
            try:
                from core.config import ANONYMOUS_USER_ID
                import secrets
                
                url = f"{API_BASE_URL}/api/v1/users/"
                user_type = "guest" if user_id == ANONYMOUS_USER_ID or user_id.startswith("user_") else "user"
                email = f"{user_id}@example.com" if user_id.startswith("user_") or user_id == ANONYMOUS_USER_ID else f"{user_id}@user.example.com"
                password = secrets.token_urlsafe(16)
                
                payload = {
                    "email": email,
                    "username": user_id,
                    "user_type": user_type,
                    "password": password
                }
                
                response = requests.post(url, json=payload, timeout=5)
                
                st.code(f"Request URL: {url}")
                st.code(f"Request Body: {payload}")
                st.code(f"Response Status: {response.status_code}")
                
                if response.status_code not in [201, 400]:  # 201: 생성 성공, 400: 이미 존재
                    try:
                        error_data = response.json()
                        st.error(f"❌ 사용자 생성 실패 ({response.status_code})")
                        st.json(error_data)
                        st.info("💡 Swagger UI에서 POST /api/v1/users/ 엔드포인트의 Request Body 스키마를 확인하세요.")
                    except:
                        st.error(f"❌ 응답: {response.text[:500]}")
                elif response.status_code == 201:
                    data = response.json()
                    st.success("✅ 사용자 생성 성공!")
                    st.json(data)
                    # 서버가 생성한 user_id 저장
                    server_user_id = data.get("user_id")
                    if server_user_id:
                        st.session_state["backend_user_id"] = server_user_id
                        st.session_state["backend_user_created"] = True
                        st.info(f"💡 서버 user_id: {server_user_id}")
                elif response.status_code == 400:
                    st.info("ℹ️ 사용자가 이미 존재합니다 (400 Bad Request)")
                    # 사용자 조회 시도
                    st.info("🔍 사용자 조회 시도...")
                    # GET /api/v1/users/{user_id} 또는 GET /api/v1/users/?username={username} 시도
                    try:
                        # username으로 조회 시도
                        get_url = f"{API_BASE_URL}/api/v1/users/"
                        get_params = {"username": user_id}
                        get_response = requests.get(get_url, params=get_params, timeout=5)
                        if get_response.status_code == 200:
                            users = get_response.json()
                            if users and len(users) > 0:
                                server_user_id = users[0].get("user_id")
                                st.session_state["backend_user_id"] = server_user_id
                                st.session_state["backend_user_created"] = True
                                st.success(f"✅ 사용자 조회 성공! (user_id: {server_user_id})")
                                st.json(users[0])
                            else:
                                st.warning("⚠️ 사용자를 찾을 수 없습니다.")
                        else:
                            st.warning(f"⚠️ 사용자 조회 실패 ({get_response.status_code})")
                    except Exception as e:
                        st.warning(f"⚠️ 사용자 조회 중 에러: {str(e)}")
            except Exception as e:
                st.error(f"❌ API 호출 실패: {str(e)}")
        
        # 세션 생성 직접 시도
        st.info("🔧 세션 생성 시도 중...")
        session_id_after = _ensure_backend_session()
        
        if session_id_after:
            st.success(f"✅ 세션 생성 성공! (세션 ID: {session_id_after})")
            # 이벤트 전송
            log_event(
                "chat_question",
                message="테스트 질문입니다",
                via="openai",
                surface="chat",
                source="test_script"
            )
            st.success("✅ 챗봇 질문 이벤트 전송 완료!")
        else:
            st.error("❌ 세션 생성 실패!")
            # 세션 생성 API 직접 호출해서 에러 확인
            st.info("🔍 세션 생성 API 직접 호출 테스트...")
            try:
                url = f"{API_BASE_URL}/api/v1/sessions/"
                context = {}
                payload = {"user_id": user_id, "context": context}
                response = requests.post(url, json=payload, timeout=5)
                
                st.code(f"Request URL: {url}")
                st.code(f"Request Body: {payload}")
                st.code(f"Response Status: {response.status_code}")
                
                if response.status_code != 201:
                    try:
                        error_data = response.json()
                        st.error(f"❌ 세션 생성 실패 ({response.status_code})")
                        st.json(error_data)
                        st.info("💡 Swagger UI에서 POST /api/v1/sessions/ 엔드포인트의 Request Body 스키마를 확인하세요.")
                    except:
                        st.error(f"❌ 응답: {response.text[:500]}")
                else:
                    data = response.json()
                    st.success("✅ 세션 생성 성공!")
                    st.json(data)
            except Exception as e:
                st.error(f"❌ API 호출 실패: {str(e)}")

with col_test3:
    if st.button("📊 스크롤 깊이 테스트"):
        log_event(
            "scroll_depth",
            surface="news_list",
            payload={"depth_pct": 50.5}
        )
        st.success("✅ 스크롤 깊이 이벤트 전송 완료!")

st.markdown("---")

# 서버 데이터 확인
st.subheader("3️⃣ 서버 데이터 확인")

st.info("""
서버에서 데이터를 확인하려면:

1. **Swagger UI**: {}/docs
2. **뉴스 상호작용**: GET /api/v1/news/user/{{user_id}}/interactions
3. **대화**: GET /api/v1/dialogues/
4. **세션**: GET /api/v1/sessions/
""".format(API_BASE_URL))

if st.button("🔗 Swagger UI 열기"):
    st.markdown(f"[Swagger UI 열기]({API_BASE_URL}/docs)")

# 서버 데이터 직접 확인
st.markdown("---")
st.subheader("📊 서버 데이터 직접 확인")

col_check1, col_check2, col_check3 = st.columns(3)

with col_check1:
    if st.button("📰 뉴스 상호작용 확인"):
        try:
            # 실제 user_id 가져오기 (서버가 생성한 것 우선)
            from core.logger import _get_user_id
            user_id = _get_user_id()
            url = f"{API_BASE_URL}/api/v1/news/user/{user_id}/interactions"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                st.success(f"✅ {len(data)}개의 상호작용 발견")
                if data:
                    st.json(data[:3])  # 최근 3개만 표시
                else:
                    st.info("아직 데이터가 없습니다. 뉴스를 클릭해보세요!")
            else:
                # 에러 응답 자세히 표시
                try:
                    error_data = response.json()
                    st.warning(f"⚠️ 응답 코드: {response.status_code}")
                    st.json(error_data)
                    st.info(f"💡 사용한 user_id: {user_id}")
                except:
                    st.warning(f"⚠️ 응답 코드: {response.status_code}")
                    st.text(f"응답: {response.text[:200]}")
        except Exception as e:
            st.error(f"❌ 확인 실패: {str(e)}")

with col_check2:
    if st.button("💬 대화 확인"):
        try:
            # session_id가 필수 파라미터인 것 같음
            from core.logger import _get_backend_session_id
            session_id = _get_backend_session_id()
            
            if not session_id:
                st.warning("⚠️ 세션이 없습니다. 먼저 '💬 챗봇 질문 테스트'를 실행하여 세션을 생성하세요.")
                st.info("💡 세션을 생성하려면 앱에서 이벤트를 발생시키거나 '💬 챗봇 질문 테스트' 버튼을 클릭하세요.")
            else:
                # session_id를 query parameter로 전송
                url = f"{API_BASE_URL}/api/v1/dialogues/"
                params = {"session_id": session_id}
                response = requests.get(url, params=params, timeout=5)
                
                if response.status_code == 200:
                    data = response.json()
                    st.success(f"✅ {len(data)}개의 대화 발견")
                    if data:
                        st.json(data[:3])  # 최근 3개만 표시
                    else:
                        st.info("아직 데이터가 없습니다. 챗봇에 질문해보세요!")
                else:
                    # 에러 응답 자세히 표시
                    try:
                        error_data = response.json()
                        st.warning(f"⚠️ 응답 코드: {response.status_code}")
                        st.json(error_data)
                        st.info(f"💡 사용한 session_id: {session_id}")
                        st.info("💡 Swagger UI에서 GET /api/v1/dialogues/ 엔드포인트의 파라미터를 확인하세요.")
                    except:
                        st.warning(f"⚠️ 응답 코드: {response.status_code}")
                        st.text(f"응답: {response.text[:200]}")
        except Exception as e:
            st.error(f"❌ 확인 실패: {str(e)}")

with col_check3:
    if st.button("🔐 세션 확인"):
        try:
            # user_id로 필터링 시도
            from core.logger import _get_user_id
            user_id = _get_user_id()
            
            # user_id로 필터링
            url = f"{API_BASE_URL}/api/v1/sessions/"
            params = {"user_id": user_id}
            response = requests.get(url, params=params, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                st.success(f"✅ {len(data)}개의 세션 발견")
                if data:
                    st.json(data[:3])  # 최근 3개만 표시
                else:
                    st.info("아직 세션이 없습니다.")
            else:
                # 파라미터 없이 시도
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    st.success(f"✅ {len(data)}개의 세션 발견")
                    if data:
                        st.json(data[:3])
                    else:
                        st.info("아직 세션이 없습니다.")
                else:
                    # 에러 응답 자세히 표시
                    try:
                        error_data = response.json()
                        st.warning(f"⚠️ 응답 코드: {response.status_code}")
                        st.json(error_data)
                        st.info(f"💡 사용한 user_id: {user_id}")
                        st.info("💡 Swagger UI에서 GET /api/v1/sessions/ 엔드포인트의 파라미터를 확인하세요.")
                    except:
                        st.warning(f"⚠️ 응답 코드: {response.status_code}")
                        st.text(f"응답: {response.text[:200]}")
        except Exception as e:
            st.error(f"❌ 확인 실패: {str(e)}")

st.markdown("---")

# 로컬 CSV 확인
st.subheader("4️⃣ 로컬 CSV 확인")

from core.config import LOG_FILE
import os

if os.path.exists(LOG_FILE):
    file_size = os.path.getsize(LOG_FILE)
    st.success(f"✅ CSV 파일 존재: {LOG_FILE}")
    st.caption(f"파일 크기: {file_size:,} bytes")
    
    if st.button("📄 CSV 파일 보기"):
        from core.utils import load_logs_as_df
        df = load_logs_as_df(LOG_FILE)
        if not df.empty:
            st.dataframe(df.tail(10), use_container_width=True)
            st.caption(f"총 {len(df)}개의 로그가 있습니다.")
        else:
            st.info("CSV 파일이 비어있습니다.")
else:
    st.warning(f"⚠️ CSV 파일이 없습니다: {LOG_FILE}")

st.markdown("---")

# 테스트 결과 요약
st.subheader("📋 테스트 체크리스트")

checklist = st.container()

with checklist:
    st.markdown("""
    - [ ] 서버 연결 성공
    - [ ] 뉴스 클릭 이벤트 전송 성공
    - [ ] 챗봇 질문 이벤트 전송 성공
    - [ ] 서버에서 데이터 확인 완료
    - [ ] CSV 파일에도 정상 저장 확인
    """)

st.markdown("---")
st.caption("💡 모든 테스트가 성공하면 커밋하세요!")

