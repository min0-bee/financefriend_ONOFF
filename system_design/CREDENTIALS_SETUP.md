# 🔐 FinanceFriend 데이터베이스 인증 정보

> **⚠️ 경고: 이 파일을 Git에 절대 커밋하지 마세요!**  
> 이 파일은 로컬에서만 사용하며, `.gitignore`에 추가되어야 합니다.

---

## 📋 Supabase 프로젝트 정보

### 프로젝트 이름
```
financefriend
```

### 데이터베이스 비밀번호
```
K8CZGllYyplDcy0y
```

### 전체 연결 문자열 (DATABASE_URL)

**형식**:
```
postgresql://postgres:K8CZGllYyplDcy0y@db.[PROJECT_REF].supabase.co:5432/postgres
```

**설정 방법**:
1. Supabase 대시보드 → Settings → Database
2. Connection String의 **Host** 부분에서 `[PROJECT_REF]` 확인
3. 위 형식에서 `[PROJECT_REF]`를 실제 값으로 교체
4. `.env` 파일에 붙여넣기

---

## 🛠️ .env 파일 생성 방법

### Step 1: 템플릿 복사
```powershell
cd system_design
Copy-Item env_template.txt .env
```

### Step 2: .env 파일 편집
```powershell
notepad .env
```

### Step 3: DATABASE_URL 설정

`.env` 파일에 다음을 붙여넣기 (실제 PROJECT_REF로 교체):

```env
DATABASE_URL=postgresql://postgres:K8CZGllYyplDcy0y@db.[YOUR_PROJECT_REF].supabase.co:5432/postgres
API_HOST=0.0.0.0
API_PORT=8000
API_RELOAD=True
ALLOWED_ORIGINS=http://localhost:8501
```

**예시** (PROJECT_REF가 `abcdefghijklmnop`인 경우):
```env
DATABASE_URL=postgresql://postgres:K8CZGllYyplDcy0y@db.abcdefghijklmnop.supabase.co:5432/postgres
```

---

## ✅ 설정 확인

```powershell
# 연결 테스트
python test_supabase_connection.py
```

성공 시:
```
[SUCCESS] Connected to Supabase PostgreSQL!
```

---

## 👥 팀원에게 공유하는 방법

### 방법 1: 안전한 메시징 (권장)
- Slack DM
- Discord DM
- 암호화된 이메일
- 1Password / LastPass 등 비밀번호 관리 도구

### 방법 2: 이 파일 직접 전달
- 이 파일(`CREDENTIALS_SETUP.md`)을 USB, 이메일 등으로 전달
- **⚠️ 주의**: Git에는 절대 커밋하지 않기!

### 전달 메시지 예시:
```
안녕하세요!

Supabase 데이터베이스 비밀번호입니다:
K8CZGllYyplDcy0y

설정 방법은 CREDENTIALS_SETUP.md 또는 TEAM_SETUP_GUIDE.md를 참고해주세요.

이 비밀번호는 안전하게 보관하시고, 공개 채널에 올리지 마세요!
```

---

## 🔒 보안 체크리스트

설정 후 반드시 확인:

- [ ] `.env` 파일이 `.gitignore`에 포함되어 있음
- [ ] `CREDENTIALS_SETUP.md`가 `.gitignore`에 포함되어 있음
- [ ] Git 상태 확인: `git status`에 `.env` 파일이 안 보임
- [ ] 비밀번호를 공개 채널(Slack 단체방, GitHub Issues 등)에 올리지 않음

---

## 🚨 비밀번호 유출 시 대응

만약 비밀번호가 Git에 커밋되었거나 공개되었다면:

1. **즉시 Supabase 비밀번호 변경**
   - Supabase 대시보드 → Settings → Database
   - "Reset database password" 클릭

2. **Git 히스토리에서 제거** (심각한 경우)
   ```powershell
   # Git 히스토리 재작성 (주의!)
   git filter-branch --force --index-filter \
   "git rm --cached --ignore-unmatch system_design/.env" \
   --prune-empty --tag-name-filter cat -- --all
   ```

3. **팀원에게 알림**
   - 새 비밀번호 안전하게 공유
   - `.env` 파일 재설정 요청

---

## 📝 비밀번호 변경 시

비밀번호를 변경했다면:

1. 이 파일 업데이트
2. `.env` 파일 업데이트
3. 팀원에게 새 비밀번호 안전하게 전달

---

**마지막 업데이트**: 2025.11.04  
**보안 등급**: ⚠️ **기밀** (외부 공유 금지)

---

## ⚠️ 다시 한 번 경고!

이 파일을 Git에 커밋하지 마세요!
```powershell
# .gitignore에 추가 확인
echo "system_design/CREDENTIALS_SETUP.md" >> .gitignore
```

