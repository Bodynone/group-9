"""Token 消耗审计测试（WBS 4.3）：usage 解析、成本折算与 Trace 审计事件。"""

import asyncio
import json

import httpx

from backend.agent import AgentRunner
from backend.provider import ChatProvider, usage_cost
from backend.rubric import VERSION
from scripted_provider import ScriptedProvider


def test_usage_cost_follows_standard_prices():
    assert usage_cost({"prompt_tokens": 1000, "completion_tokens": 500}) == 0.006  # 0.002 + 0.004
    assert usage_cost({"prompt_tokens": 0, "completion_tokens": 0}) == 0.0
    assert usage_cost({}) == 0.0


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
