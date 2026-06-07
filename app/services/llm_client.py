import logging

import httpx

from app.core.config import (
    GROQ_API_KEY,
    GROQ_BASE_URL,
    GROQ_MODEL,
    NVIDIA_API_KEY,
    NVIDIA_NIM_BASE_URL,
    NVIDIA_NIM_MODEL,
)

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30


def _call_nvidia_nim(messages: list[dict], response_format: dict | None = None, temperature: float = 0.2) -> str:
    if not NVIDIA_API_KEY:
        raise ValueError("NVIDIA_API_KEY is required")
    payload = {
        "model": NVIDIA_NIM_MODEL,
        "messages": messages,
        "temperature": temperature,
    }
    if response_format:
        payload["response_format"] = response_format
    response = httpx.post(
        f"{NVIDIA_NIM_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {NVIDIA_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def _call_groq(messages: list[dict], response_format: dict | None = None, temperature: float = 0.2) -> str:
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY is required")
    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": temperature,
    }
    if response_format:
        payload["response_format"] = response_format
    response = httpx.post(
        f"{GROQ_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def chat_completion(messages: list[dict], provider: str = "nvidia_nim", response_format: dict | None = None, temperature: float = 0.2) -> str:
    try:
        return _call_nvidia_nim(messages, response_format, temperature)
    except Exception as nim_exc:
        logger.warning("NVIDIA NIM failed (%s), falling back to Groq", nim_exc)
        try:
            return _call_groq(messages, response_format, temperature)
        except Exception:
            raise nim_exc
