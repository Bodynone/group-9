"""Token 消耗审计测试（WBS 4.3）：usage 解析、成本折算与 Trace 审计事件。"""

import asyncio
import json

import httpx

from backend.agent import AgentRunner
from backend.provider import ChatProvider, usage_cost
from backend.rubric import VERSION
from scripted_provider import ScriptedProvider


def test_usage_cost_requires_explicit_prices():
    usage = {"prompt_tokens": 1000, "completion_tokens": 500}
    assert usage_cost(usage) is None
    assert usage_cost(usage, prompt_price="2", completion_price="8") == 0.006
    assert usage_cost({"prompt_tokens": 0, "completion_tokens": 0}, prompt_price="2", completion_price="8") == 0.0
    assert usage_cost({}, prompt_price="2", completion_price="8") is None


def test_invalid_usage_or_prices_do_not_invent_costs():
    for tokens in (-1, True, "100", float("nan")):
        assert usage_cost({"prompt_tokens": tokens, "completion_tokens": 10}, prompt_price="2", completion_price="8") is None
    for price in (None, "NaN", "Infinity", "-1", "not-a-price"):
        assert usage_cost({"prompt_tokens": 10, "completion_tokens": 10}, prompt_price=price, completion_price="8") is None


def test_provider_passes_usage_through_only_when_present(settings, monkeypatch):
    original_client = httpx.AsyncClient

    def mock_transport(handler):
        monkeypatch.setattr("backend.provider.httpx.AsyncClient", lambda *args, **kwargs: original_client(
            *args, transport=httpx.MockTransport(handler), **kwargs,
        ))

    with_usage = {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "完成"}}],
                  "usage": {"prompt_tokens": 12, "completion_tokens": 34, "total_tokens": 46}}
    mock_transport(lambda request: httpx.Response(200, json=with_usage))
    message = asyncio.run(ChatProvider(settings).complete([], []))
    assert message["usage"] == {"prompt_tokens": 12, "completion_tokens": 34, "total_tokens": 46}

    without_usage = {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "完成"}}]}
    mock_transport(lambda request: httpx.Response(200, json=without_usage))
    message = asyncio.run(ChatProvider(settings).complete([], []))
    assert "usage" not in message


_UNSET = object()


class UsageProvider(ScriptedProvider):
    """每个模型响应附带 usage，并记录每次请求的消息序列以检查回传污染。"""

    USAGE = {"prompt_tokens": 1200, "completion_tokens": 300, "total_tokens": 1500}

    def __init__(self, task, levels=None, usage=_UNSET):
        super().__init__(task, levels)
        self.usage = self.USAGE if usage is _UNSET else usage
        self.seen_requests = []

    async def complete(self, messages, tools):
        self.seen_requests.append(messages)
        response = await super().complete(messages, tools)
        if self.usage is not None:
            response["usage"] = self.usage
        return response


def test_agent_records_usage_audit_events_per_model_call(samples, store, settings):
    task = store.create_task(samples["S1"], VERSION)
    provider = UsageProvider(task)
    asyncio.run(AgentRunner(store, provider, settings).run(task["id"]))
    result = store.get_task(task["id"])
    usage_events = [event for event in result["trace"] if event["kind"] == "model_usage"]
    assert len(usage_events) == provider.calls
    for event in usage_events:
        details = event["details"]
        assert details["prompt_tokens"] == 1200
        assert details["completion_tokens"] == 300
        assert details["total_tokens"] == 1500
        assert details["cost_cny"] == usage_cost({"prompt_tokens": 1200, "completion_tokens": 300})
    # usage 不得回传进模型消息流
    for messages in provider.seen_requests:
        for message in messages:
            assert "usage" not in message, f"usage 泄漏进消息流：{message.get('role')}"


def test_malformed_or_absent_usage_leaves_no_audit_event(samples, store, settings):
    task = store.create_task(samples["S1"], VERSION)
    provider = UsageProvider(task, usage={"prompt_tokens": 10})  # 缺 completion_tokens
    asyncio.run(AgentRunner(store, provider, settings).run(task["id"]))
    assert not [event for event in store.get_task(task["id"])["trace"] if event["kind"] == "model_usage"]

    task = store.create_task(samples["S1"], VERSION)
    provider = UsageProvider(task, usage=None)  # 上游未返回 usage
    asyncio.run(AgentRunner(store, provider, settings).run(task["id"]))
    assert not [event for event in store.get_task(task["id"])["trace"] if event["kind"] == "model_usage"]


def test_negative_usage_cannot_fail_grading_or_enter_audit(samples, store, settings):
    task = store.create_task(samples["S1"], VERSION)
    provider = UsageProvider(task, usage={"prompt_tokens": -1, "completion_tokens": 2})
    asyncio.run(AgentRunner(store, provider, settings).run(task["id"]))
    result = store.get_task(task["id"])
    assert result["status"] == "pending_review"
    assert not [event for event in result["trace"] if event["kind"] == "model_usage"]


def test_agent_uses_configured_prices_and_labels_estimates(samples, store, settings):
    settings.input_price_cny_per_million = "2"
    settings.output_price_cny_per_million = "8"
    task = store.create_task(samples["S1"], VERSION)
    asyncio.run(AgentRunner(store, UsageProvider(task), settings).run(task["id"]))
    event = next(event for event in store.get_task(task["id"])["trace"] if event["kind"] == "model_usage")
    assert event["details"]["cost_cny"] == 0.0048
    assert event["details"]["cost_basis"] == "configured_estimate"
