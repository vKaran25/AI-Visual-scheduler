import httpx

from app.core.config import NVIDIA_API_KEY, NVIDIA_NIM_BASE_URL, NVIDIA_NIM_MODEL


def chat_completion(messages: list[dict], provider: str = "nvidia_nim", response_format: dict | None = None, temperature: float = 0.2) -> str:
    if provider != "nvidia_nim":
        raise ValueError(f"Unsupported provider: {provider}")
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
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]

