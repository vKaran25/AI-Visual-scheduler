"""Free-only, budgeted structured model calls. No calendar mutation tools."""

import copy
import json
import threading
import time

import httpx
from pydantic import ValidationError

from app.core import config
from app.runtime import context


class ModelUnavailable(RuntimeError):
    pass


_client = httpx.Client(base_url="https://openrouter.ai/api/v1", timeout=30)
_catalog = {}
_catalog_at = 0
_catalog_lock = threading.Lock()
_semaphore = threading.BoundedSemaphore(2)
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


def generate(role: str, prompt: str, data: dict, output_type, cache_key: str):
    prior = context.artifact(cache_key)
    if prior:
        return output_type.model_validate(prior["output"])
    if not config.OPENROUTER_API_KEY:
        raise ModelUnavailable(
            "The AI assistant is not connected yet (no model key is set). "
            "You can still add events yourself with Fill details."
        )
    primary = config.OPENROUTER_EVALUATOR_MODEL if role == "evaluator" else config.OPENROUTER_WORKER_MODEL
    models = list(dict.fromkeys([primary] + config.OPENROUTER_FALLBACK_MODELS))
    for model_id in models:
        try:
            verify_free(model_id)
        except ModelUnavailable:
            continue
        # Each network attempt consumes a durable budget, including failed attempts.
        for attempt in range(ATTEMPTS_PER_MODEL):
            with _semaphore:
                context.reserve_attempt()
                try:
                    response = _client.post(
                        "/chat/completions",
                        headers={
                            "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                            "HTTP-Referer": config.APP_BASE_URL,
                            "X-Title": "Predestination",
                        },
                        json={
                            "model": model_id,
                            "messages": [
                                {"role": "system", "content": prompt},
                                {"role": "user", "content": json.dumps(data, default=str)},
                            ],
                            "temperature": 0.1,
                            "max_tokens": 6000,
                            "provider": {
                                "require_parameters": True,
                                "max_price": {"prompt": 0, "completion": 0},
                            },
                            "response_format": {
                                "type": "json_schema",
                                "json_schema": {
                                    "name": output_type.__name__,
                                    "strict": True,
                                    "schema": strict_schema(output_type),
                                },
                            },
                        },
                    )
                    response.raise_for_status()
                    body = response.json()
                    output = output_type.model_validate_json(body["choices"][0]["message"]["content"])
                    context.save_artifact(
                        cache_key,
                        "model_call",
                        {
                            "output": output.model_dump(mode="json"),
                            "role": role,
                            "requested_model": model_id,
                            "actual_model": body.get("model"),
                            "usage": body.get("usage", {}),
                            "prompt_version": config.PROMPT_VERSION,
                        },
                    )
                    return output
                except (ValidationError, ValueError, KeyError, httpx.HTTPError):
                    if attempt < ATTEMPTS_PER_MODEL - 1:
                        time.sleep(1)
    raise ModelUnavailable(
        "Free model providers could not complete this request. Your progress is saved; retry later."
    )
