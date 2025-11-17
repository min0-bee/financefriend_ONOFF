# OpenAI API 키 환경 변수 설정 가이드 (Windows)

## 방법 1: GUI를 통한 설정 (권장)

### 단계별 안내

1. **시스템 속성 열기**
   - `Win + R` 키를 누르고 `sysdm.cpl` 입력 후 Enter
   - 또는 제어판 > 시스템 > 고급 시스템 설정

2. **환경 변수 버튼 클릭**
   - "고급" 탭에서 "환경 변수" 버튼 클릭

3. **새 사용자 변수 추가**
   - "사용자 변수" 섹션에서 "새로 만들기" 클릭
   - 변수 이름: `OPENAI_API_KEY`
   - 변수 값: `your-api-key-here` (실제 API 키 입력)
   - 확인 클릭

4. **적용 및 확인**
   - 모든 창에서 "확인" 클릭
   - **새 PowerShell/CMD 창을 열어야** 변경사항이 적용됩니다

### 확인 방법

새 PowerShell 창을 열고:
```powershell
echo $env:OPENAI_API_KEY
```

또는 CMD에서:
```cmd
echo %OPENAI_API_KEY%
```

## 방법 2: PowerShell 명령어 (관리자 권한 필요)

### 관리자 권한으로 PowerShell 실행

1. 시작 메뉴에서 "PowerShell" 검색
2. "Windows PowerShell"을 **우클릭** → **관리자 권한으로 실행**

### 명령어 실행

```powershell
# 사용자 환경 변수로 설정 (현재 사용자만)
[System.Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "your-api-key-here", "User")

# 시스템 전체에 설정하려면 (모든 사용자)
# [System.Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "your-api-key-here", "Machine")
```

### 확인

**새 PowerShell 창**을 열고:
```powershell
echo $env:OPENAI_API_KEY
```

## 방법 3: 현재 세션에만 임시 설정

영구 설정이 필요 없고 현재 세션에서만 사용하려면:

```powershell
$env:OPENAI_API_KEY = "your-api-key-here"
```

이 방법은 PowerShell 창을 닫으면 사라집니다.

## 주의사항

1. **보안**: API 키는 민감한 정보입니다. 절대 공개 저장소에 커밋하지 마세요.
2. **새 터미널 필요**: 환경 변수 설정 후 **새 PowerShell/CMD 창**을 열어야 적용됩니다.
3. **관리자 권한**: 시스템 전체 설정은 관리자 권한이 필요합니다.

## 문제 해결

### 환경 변수가 적용되지 않는 경우

1. **새 터미널 창 열기**: 현재 창에서는 적용되지 않을 수 있습니다.
2. **재부팅**: 가끔 재부팅이 필요할 수 있습니다.
3. **경로 확인**: 
   ```powershell
   [System.Environment]::GetEnvironmentVariable("OPENAI_API_KEY", "User")
   ```

### API 키 확인

API 키는 `sk-`로 시작하는 긴 문자열입니다. OpenAI 웹사이트(https://platform.openai.com/api-keys)에서 확인할 수 있습니다.

