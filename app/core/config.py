"""Configuration; secrets belong in .env or the deployment secret store."""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://scheduler:scheduler@127.0.0.1:5432/scheduler")
DATABASE_DIRECT_URL = os.getenv("DATABASE_DIRECT_URL", DATABASE_URL)
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "local-development-only-change-before-deployment")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
COOKIE_SAMESITE = "lax"
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
CORS_ORIGINS = [
    s.strip().rstrip("/") for s in os.getenv("CORS_ORIGINS", APP_BASE_URL).split(",") if s.strip()
]
GOOGLE_CALENDAR_TIMEZONE = os.getenv("GOOGLE_CALENDAR_TIMEZONE", "UTC")
GOOGLE_TOKEN_ENCRYPTION_KEY = os.getenv("GOOGLE_TOKEN_ENCRYPTION_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_WORKER_MODEL = os.getenv("OPENROUTER_WORKER_MODEL", "baidu/ernie-5.5-flash-preview:free")
OPENROUTER_EVALUATOR_MODEL = os.getenv("OPENROUTER_EVALUATOR_MODEL", "particle-ai/particle-1:free")
OPENROUTER_FALLBACK_MODELS = [
    s.strip()
    for s in os.getenv("OPENROUTER_FALLBACK_MODELS", OPENROUTER_EVALUATOR_MODEL).split(",")
    if s.strip()
]
# Groq (OpenAI-compatible, free plan, very fast). Strict structured outputs work on the gpt-oss models.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_WORKER_MODEL = os.getenv("GROQ_WORKER_MODEL", "openai/gpt-oss-120b")
GROQ_EVALUATOR_MODEL = os.getenv("GROQ_EVALUATOR_MODEL", "openai/gpt-oss-20b")
GROQ_FALLBACK_MODELS = [
    s.strip() for s in os.getenv("GROQ_FALLBACK_MODELS", GROQ_EVALUATOR_MODEL).split(",") if s.strip()
]
# Which model service to use. Defaults to Groq when a Groq key is present, otherwise OpenRouter.
LLM_PROVIDER = (os.getenv("LLM_PROVIDER") or ("groq" if GROQ_API_KEY else "openrouter")).strip().lower()
if LLM_PROVIDER not in ("openrouter", "groq"):
    raise ValueError("LLM_PROVIDER must be 'openrouter' or 'groq'")
if LLM_PROVIDER == "groq":
    LLM_BASE_URL = "https://api.groq.com/openai/v1"
    LLM_API_KEY, LLM_WORKER_MODEL = GROQ_API_KEY, GROQ_WORKER_MODEL
    LLM_EVALUATOR_MODEL, LLM_FALLBACK_MODELS = GROQ_EVALUATOR_MODEL, GROQ_FALLBACK_MODELS
else:
    LLM_BASE_URL = "https://openrouter.ai/api/v1"
    LLM_API_KEY, LLM_WORKER_MODEL = OPENROUTER_API_KEY, OPENROUTER_WORKER_MODEL
    LLM_EVALUATOR_MODEL, LLM_FALLBACK_MODELS = OPENROUTER_EVALUATOR_MODEL, OPENROUTER_FALLBACK_MODELS
GRAPH_VERSION = "calendar-v1"
PROMPT_VERSION = "2026-10-v1"
MAX_MODEL_ATTEMPTS = 16
MAX_WORK_ORDERS = 6
MAX_OPTIMIZATION_ROUNDS = 2
ACTIVE_RUN_SECONDS = 300
LEASE_SECONDS = 90


def psycopg_url(value: str) -> str:
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://") :]
    if not value.startswith(("postgresql://", "postgresql+psycopg://")):
        raise ValueError("PostgreSQL is required. Configure DATABASE_URL; SQLite is no longer supported.")
    return value.replace("postgresql://", "postgresql+psycopg://", 1)


def raw_postgres_url(value: str) -> str:
    return psycopg_url(value).replace("postgresql+psycopg://", "postgresql://", 1)
