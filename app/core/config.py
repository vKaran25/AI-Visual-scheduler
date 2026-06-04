import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parents[2]
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'scheduler.db'}")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev_change_me_scheduler_secret")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000")
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
NVIDIA_NIM_MODEL = os.getenv("NVIDIA_NIM_MODEL", "openai/gpt-oss-120b")
NVIDIA_NIM_BASE_URL = os.getenv("NVIDIA_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
