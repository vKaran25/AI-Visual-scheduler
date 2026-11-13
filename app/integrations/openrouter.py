"""Free-only, budgeted structured model calls (OpenRouter or Groq). No calendar mutation tools."""

import copy
import json
import logging
import threading
import time

import httpx
from pydantic import ValidationError

from app.core import config
from app.runtime import context

logger = logging.getLogger(__name__)


class ModelUnavailable(RuntimeError):
    pass


_client = httpx.Client(base_url=config.LLM_BASE_URL, timeout=45)
_catalog = {}
_catalog_at = 0
_catalog_lock = threading.Lock()
# Groq's free plan allows only ~8K tokens a minute, so send one request at a time there.
_semaphore = threading.BoundedSemaphore(1 if config.LLM_PROVIDER == "groq" else 2)
# Free preview models sometimes return an empty or invalid reply; retry the same model before falling back.
ATTEMPTS_PER_MODEL = 3


def strict_schema(model):
    schema = copy.deepcopy(model.model_json_schema())

    def visit(value):
        if isinstance(value, dict):
            value.pop("default", None)
            if value.get("type") == "object" and "properties" in value:
                value["required"] = list(value["properties"])
                value["additionalProperties"] = False
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(schema)
    return schema


def verify_free(model_id: str):
    global _catalog, _catalog_at
    if not model_id.endswith(":free"):
        raise ModelUnavailable("Only explicitly configured free models are allowed")
    with _catalog_lock:
        if time.monotonic() - _catalog_at > 3600 or not _catalog:
            try:
                response = _client.get("/models", timeout=10)
                response.raise_for_status()
                _catalog = {m["id"]: m for m in response.json()["data"]}
                _catalog_at = time.monotonic()
            except Exception as exc:
                raise ModelUnavailable("Cannot verify the free-model catalog; retry later") from exc
        entry = _catalog.get(model_id)
        if not entry or any(float(value or 0) > 0 for value in entry.get("pricing", {}).values()):
            raise ModelUnavailable("Configured model is unavailable or no longer free")
        supported = set(entry.get("supported_parameters", []))
        if not {"response_format", "structured_outputs"} <= supported:
            raise ModelUnavailable("Configured model does not advertise structured outputs")


def _request_parts(model_id, prompt, data, output_type, strict):
    """Headers and JSON body for the active provider."""
    schema = {
        "type": "json_schema",
        "json_schema": {"name": output_type.__name__, "strict": strict, "schema": strict_schema(output_type)},
    }
    body = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(data, default=str)},
        ],
        "temperature": 0.1,
        "response_format": schema,
    }
    headers = {"Authorization": f"Bearer {config.LLM_API_KEY}"}
    if config.LLM_PROVIDER == "groq":
        body["max_completion_tokens"] = 2500
        body["include_reasoning"] = False
        if "gpt-oss" in model_id:
            body["reasoning_effort"] = "low"
    else:
        body["max_tokens"] = 6000
        body["provider"] = {"require_parameters": True, "max_price": {"prompt": 0, "completion": 0}}
        headers.update({"HTTP-Referer": config.APP_BASE_URL, "X-Title": "Predestination"})
    return headers, body


def _rate_limit_pause(error):
    """Seconds to wait after HTTP 429, honouring Retry-After (capped), else None."""
    if isinstance(error, httpx.HTTPStatusError) and error.response.status_code == 429:
        try:
            return min(max(float(error.response.headers.get("retry-after", "2")), 1.0), 20.0)
        except ValueError:
            return 5.0
    return None


def generate(role: str, prompt: str, data: dict, output_type, cache_key: str):
    prior = context.artifact(cache_key)
    if prior:
        return output_type.model_validate(prior["output"])
    if not config.LLM_API_KEY:
        raise ModelUnavailable(
            "The AI assistant is not connected yet (no model key is set). "
            "You can still add events yourself with Fill details."
        )
    primary = config.LLM_EVALUATOR_MODEL if role in config.LLM_LIGHT_ROLES else config.LLM_WORKER_MODEL
    models = list(dict.fromkeys([primary] + config.LLM_FALLBACK_MODELS))
    strict = True
    for model_id in models:
        if config.LLM_PROVIDER == "openrouter":
            try:
                verify_free(model_id)
            except ModelUnavailable:
                continue
        # Each network attempt consumes a durable budget, including failed attempts.
        for attempt in range(ATTEMPTS_PER_MODEL):
            pause = 1.0
            with _semaphore:
                context.reserve_attempt()
                try:
                    headers, request_body = _request_parts(model_id, prompt, data, output_type, strict)
                    response = _client.post("/chat/completions", headers=headers, json=request_body)
                    response.raise_for_status()
                    body = response.json()
                    output = output_type.model_validate_json(body["choices"][0]["message"]["content"])
                    context.save_artifact(
                        cache_key,
                        "model_call",
                        {
                            "output": output.model_dump(mode="json"),
                            "role": role,
                            "provider": config.LLM_PROVIDER,
                            "requested_model": model_id,
                            "actual_model": body.get("model"),
                            "usage": body.get("usage", {}),
                            "prompt_version": config.PROMPT_VERSION,
                        },
                    )
                    return output
                except (ValidationError, ValueError, KeyError, httpx.HTTPError) as error:
                    pause = _rate_limit_pause(error) or pause
                    status = error.response.status_code if isinstance(error, httpx.HTTPStatusError) else None
                    logger.warning(
                        "model call failed: provider=%s model=%s role=%s attempt=%d status=%s error=%s detail=%.200s",
                        config.LLM_PROVIDER,
                        model_id,
                        role,
                        attempt + 1,
                        status,
                        type(error).__name__,
                        " ".join((error.response.text if status else str(error)).split()),
                    )
                    if (
                        config.LLM_PROVIDER == "groq"
                        and isinstance(error, httpx.HTTPStatusError)
                        and error.response.status_code == 400
                    ):
                        strict = False  # this model rejected the strict schema; use best-effort mode
            if attempt < ATTEMPTS_PER_MODEL - 1:
                time.sleep(pause)
    raise ModelUnavailable(
        "The AI models could not complete this request right now. Your progress is saved; try again shortly."
    )
