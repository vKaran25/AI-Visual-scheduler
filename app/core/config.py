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
# Secure cross-site cookies are required when a Netlify frontend calls an HTTPS API.
# For local HTTP development use false and serve the frontend from the same site.
COOKIE_SAMESITE = "none" if COOKIE_SECURE else "lax"
CORS_ORIGINS = [origin.strip().rstrip("/") for origin in os.getenv(
    "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000,http://localhost:8000,http://127.0.0.1:8000,https://predestinationai.netlify.app"
).split(",") if origin.strip()]
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000")
# All calendar timestamps are converted to this IANA zone for local scheduler dates/times.
GOOGLE_CALENDAR_TIMEZONE = os.getenv("GOOGLE_CALENDAR_TIMEZONE", "UTC")
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
NVIDIA_NIM_MODEL = os.getenv("NVIDIA_NIM_MODEL", "openai/gpt-oss-120b")
NVIDIA_NIM_BASE_URL = os.getenv("NVIDIA_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
