"""Model provider switching (OpenRouter or Groq) without any network access."""

import json

import httpx
import pytest
from pydantic import BaseModel

from app.core import config
from app.integrations import openrouter


class Reply(BaseModel):
    answer: str


def completion(text):
    return {"model": "test-model", "usage": {"total_tokens": 12}, "choices": [{"message": {"content": text}}]}


@pytest.fixture
def groq(monkeypatch):
    """Groq selected, artifacts held in memory, sleeping recorded instead of performed."""
    saved, pauses, calls = {}, [], []
    monkeypatch.setattr(config, "LLM_PROVIDER", "groq")
    monkeypatch.setattr(config, "LLM_API_KEY", "test-groq-key")
    monkeypatch.setattr(config, "LLM_WORKER_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setattr(config, "LLM_EVALUATOR_MODEL", "openai/gpt-oss-20b")
    monkeypatch.setattr(config, "LLM_FALLBACK_MODELS", ["openai/gpt-oss-20b"])
    monkeypatch.setattr(config, "LLM_LIGHT_ROLES", frozenset({"evaluator", "optimizer", "voice"}))
    monkeypatch.setattr(openrouter.context, "artifact", lambda key: saved.get(key))
    monkeypatch.setattr(openrouter.context, "reserve_attempt", lambda: None)
    monkeypatch.setattr(
        openrouter.context, "save_artifact", lambda key, kind, payload: saved.update({key: payload})
    )
    monkeypatch.setattr(openrouter.time, "sleep", pauses.append)

    def use(handler):
        def recording(request):
            calls.append(request)
            return handler(request)

        client = httpx.Client(base_url=config.LLM_BASE_URL, transport=httpx.MockTransport(recording))
        monkeypatch.setattr(openrouter, "_client", client)

    return use, saved, pauses, calls


def test_groq_request_has_no_openrouter_fields_and_uses_strict_schema(groq):
    use, saved, _, calls = groq
    use(lambda request: httpx.Response(200, json=completion('{"answer": "hi"}')))
    result = openrouter.generate("planning", "system text", {"a": 1}, Reply, "key-1")
    assert result.answer == "hi"
    request = calls[0]
    body = json.loads(request.content)
    assert request.headers["authorization"] == "Bearer test-groq-key"
    assert "provider" not in body and "HTTP-Referer" not in request.headers
    assert body["model"] == "openai/gpt-oss-120b"
    assert body["reasoning_effort"] == "low" and body["max_completion_tokens"] == 2500
    schema = body["response_format"]["json_schema"]
    assert schema["strict"] is True and schema["schema"]["additionalProperties"] is False
    assert saved["key-1"]["provider"] == "groq"


def test_rate_limit_waits_for_retry_after_then_succeeds(groq):
    use, _, pauses, calls = groq
    replies = iter(
        [
            httpx.Response(429, headers={"retry-after": "7"}),
            httpx.Response(200, json=completion('{"answer": "ok"}')),
        ]
    )
    use(lambda request: next(replies))
    assert openrouter.generate("orchestrator", "s", {}, Reply, "key-2").answer == "ok"
    assert pauses == [7.0] and len(calls) == 2


def test_rejected_strict_schema_falls_back_to_best_effort_mode(groq):
    use, _, _, calls = groq
    replies = iter(
        [
            httpx.Response(400, json={"error": "schema"}),
            httpx.Response(200, json=completion('{"answer": "ok"}')),
        ]
    )
    use(lambda request: next(replies))
    assert openrouter.generate("orchestrator", "s", {}, Reply, "key-3").answer == "ok"
    modes = [json.loads(call.content)["response_format"]["json_schema"]["strict"] for call in calls]
    assert modes == [True, False]


def test_failing_model_hands_over_to_the_fallback_model(groq):
    use, _, _, calls = groq

    def handler(request):
        if json.loads(request.content)["model"] == "openai/gpt-oss-120b":
            return httpx.Response(500)
        return httpx.Response(200, json=completion('{"answer": "from fallback"}'))

    use(handler)
    assert openrouter.generate("planning", "s", {}, Reply, "key-4").answer == "from fallback"
    models = [json.loads(call.content)["model"] for call in calls]
    assert models[: openrouter.ATTEMPTS_PER_MODEL] == ["openai/gpt-oss-120b"] * openrouter.ATTEMPTS_PER_MODEL
    assert models[-1] == "openai/gpt-oss-20b"


def test_exhausted_models_raise_a_friendly_error(groq):
    use, *_ = groq
    use(lambda request: httpx.Response(200, json=completion("not json")))
    with pytest.raises(openrouter.ModelUnavailable, match="try again shortly"):
        openrouter.generate("orchestrator", "s", {}, Reply, "key-5")


def test_missing_key_is_reported_in_plain_language(groq, monkeypatch):
    monkeypatch.setattr(config, "LLM_API_KEY", "")
    with pytest.raises(openrouter.ModelUnavailable, match="not connected yet"):
        openrouter.generate("orchestrator", "s", {}, Reply, "key-6")


def test_openrouter_requests_keep_the_price_ceiling_and_headers(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "openrouter")
    monkeypatch.setattr(config, "LLM_API_KEY", "test-openrouter-key")
    headers, body = openrouter._request_parts("vendor/model:free", "s", {}, Reply, True)
    assert body["provider"]["max_price"] == {"prompt": 0, "completion": 0}
    assert "X-Title" in headers and "reasoning_effort" not in body


def test_groq_splits_roles_across_models_to_share_the_token_limit(groq):
    use, _, _, calls = groq
    use(lambda request: httpx.Response(200, json=completion('{"answer": "ok"}')))
    openrouter.generate("evaluator", "s", {}, Reply, "key-7")
    openrouter.generate("planning", "s", {}, Reply, "key-8")
    assert [json.loads(call.content)["model"] for call in calls] == [
        "openai/gpt-oss-20b",
        "openai/gpt-oss-120b",
    ]
