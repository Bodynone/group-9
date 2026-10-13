import asyncio
from dataclasses import replace

import httpx
import pytest

from backend.provider import ChatProvider, ModelError
from backend.tools import tool_schemas


def mock_transport(monkeypatch, handler):
    original_client = httpx.AsyncClient
    monkeypatch.setattr("backend.provider.httpx.AsyncClient", lambda *args, **kwargs: original_client(
        *args, transport=httpx.MockTransport(handler), **kwargs,
    ))


def test_openai_compatible_request_and_reasoning_message_round_trip(settings, monkeypatch):
    seen = []
    response_message = {
        "role": "assistant", "content": None, "reasoning_content": "选择量表工具",
        "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "read_rubric", "arguments": "{}"}}],
    }
    def handler(request):
        import json
        seen.append(json.loads(request.content))
        assert str(request.url) == "https://model.invalid/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-key-not-a-secret"
        return httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": response_message}]})
    mock_transport(monkeypatch, handler)
    messages = [{"role": "system", "content": "test"}, {"role": "user", "content": "anonymous"}]
    assert asyncio.run(ChatProvider(settings).complete(messages, tool_schemas())) == response_message
    assert seen[0]["model"] == settings.model
    assert seen[0]["messages"] == messages
    assert seen[0]["tools"] == tool_schemas()
    assert seen[0]["stream"] is False


@pytest.mark.parametrize("status,message,code", [
    (401, "invalid test-key-not-a-secret Bearer test-key-not-a-secret", "model_http_401"),
    (403, "email verification required", "model_http_403"),
    (503, "service unavailable", "model_http_503"),
])
def test_service_errors_are_structured_and_credentials_redacted(status, message, code, settings, monkeypatch):
    mock_transport(monkeypatch, lambda request: httpx.Response(status, json={"error": {"message": message}}))
    with pytest.raises(ModelError) as captured:
        asyncio.run(ChatProvider(settings).complete([], tool_schemas()))
    assert captured.value.code == code
    assert settings.api_key not in captured.value.message
    if status == 403:
        assert "邮箱验证" in captured.value.message


def test_transport_timeout_is_explicit(settings, monkeypatch):
    def handler(request):
        raise httpx.ReadTimeout("fake transport timeout", request=request)
    mock_transport(monkeypatch, handler)
    with pytest.raises(ModelError) as captured:
        asyncio.run(ChatProvider(settings).complete([], tool_schemas()))
    assert captured.value.code == "model_timeout"


@pytest.mark.parametrize("body", [
    {}, {"choices": []}, {"choices": [42]}, {"choices": [{"message": "not an object"}]},
])
def test_malformed_service_response_is_rejected(body, settings, monkeypatch):
    mock_transport(monkeypatch, lambda request: httpx.Response(200, json=body))
    with pytest.raises(ModelError) as captured:
        asyncio.run(ChatProvider(settings).complete([], tool_schemas()))
    assert captured.value.code == "model_invalid_response"


def test_truncated_output_cannot_be_treated_as_a_complete_tool_call(settings, monkeypatch):
    mock_transport(monkeypatch, lambda request: httpx.Response(200, json={
        "choices": [{"finish_reason": "length", "message": {"role": "assistant", "content": "partial"}}],
    }))
    with pytest.raises(ModelError) as captured:
        asyncio.run(ChatProvider(settings).complete([], tool_schemas()))
    assert captured.value.code == "model_output_truncated"


def test_missing_configuration_never_attempts_network(settings, monkeypatch):
    def forbidden_network(*args, **kwargs):
        pytest.fail("missing credentials must be rejected before creating a network client")
    monkeypatch.setattr("backend.provider.httpx.AsyncClient", forbidden_network)
    with pytest.raises(ModelError) as captured:
        asyncio.run(ChatProvider(replace(settings, api_key="")).complete([], tool_schemas()))
    assert captured.value.code == "model_not_configured"
