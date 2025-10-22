import os

# OpenAI 연결 여부 (MVP: False)
USE_OPENAI = False

# 로그 경로
LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "events.csv")
USER_FILE = os.path.join(LOG_DIR, "user_info.json")
