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
OPENROUTER_WORKER_MODEL = os.getenv("OPENROUTER_WORKER_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
OPENROUTER_EVALUATOR_MODEL = os.getenv("OPENROUTER_EVALUATOR_MODEL", "xingchen-agi/xing4.0-29b-a4b:free")
OPENROUTER_FALLBACK_MODELS = [
    s.strip()
    for s in os.getenv("OPENROUTER_FALLBACK_MODELS", OPENROUTER_EVALUATOR_MODEL).split(",")
    if s.strip()
]
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
