import asyncio
from dataclasses import replace
import json

import pytest

from backend.agent import AgentRunner
from backend.rubric import VERSION
from backend.tools import Toolbox

from scripted_provider import ScriptedProvider, valid_draft


def run_task(store, settings, text, levels=None, bad_validations=0):
    task = store.create_task(text, VERSION)
    provider = ScriptedProvider(task, levels, bad_validations)
    asyncio.run(AgentRunner(store, provider, settings).run(task["id"]))
    return store.get_task(task["id"]), provider


@pytest.mark.parametrize("repeat", range(3), ids=lambda number: f"run-{number + 1}")
@pytest.mark.parametrize("scenario", ["T1", "T2", "T3a", "T3b", "T3c"])
def test_five_acceptance_scenarios_three_times(scenario, repeat, samples, store, settings, monkeypatch):
    """15 fixed-fixture runs verify the real engine, not model judgement."""
    sample = "S2" if scenario == "T2" else "S1"
    text = samples[sample]
    expected = samples["expected"][sample]
    original_locator = Toolbox.locate_evidence
    if scenario == "T3a":
        def unavailable(self, quote):
            return {"status_code": 503, "message": "定位服务暂不可用"}
        monkeypatch.setattr(Toolbox, "locate_evidence", unavailable)
    bad_validations = {"T3b": 1, "T3c": 99}.get(scenario, 0)
    result, provider = run_task(store, settings, text, expected["levels"], bad_validations)
    assert result["text"] == text
    assert result["input_version"] == expected["input_version"]
    assert result["rubric_version"] == VERSION
    assert result["model_calls"] == provider.calls
    assert result["record_id"] is None
    assert result["trace"][-1]["kind"] == ("failed" if scenario in {"T3a", "T3c"} else "pending_review")

    if scenario == "T3a":
        assert result["status"] == "failed"
        assert result["draft"] is None
        assert result["validation_count"] == 0
        assert "503" in str(result["error"])
        assert provider.calls == 2
        monkeypatch.setattr(Toolbox, "locate_evidence", original_locator)
        task = store.create_task(result["text"], result["rubric_version"], parent_id=result["id"])
        retry_provider = ScriptedProvider(task, expected["levels"])
        asyncio.run(AgentRunner(store, retry_provider, settings).run(task["id"]))
        retry = store.get_task(task["id"])
        assert retry["status"] == "pending_review"
        assert retry["draft"]["total"] == 100
        assert retry["input_version"] == result["input_version"]
        return
    if scenario == "T3c":
        assert result["status"] == "failed"
        assert result["draft"] is None
        assert result["validation_count"] == 3
        assert result["repair_rounds"] == 2
        assert provider.validation_calls == 3
        return

    assert result["status"] == "pending_review"
    assert result["draft"]["status"] == "draft"
    assert result["draft"]["total"] == expected["total"]
    assert {item["id"]: item["score"] for item in result["draft"]["dimensions"]} == expected["scores"]
    assert {item["id"]: item["level"] for item in result["draft"]["dimensions"]} == expected["levels"]
    assert result["validation_count"] == (2 if scenario == "T3b" else 1)
    assert result["repair_rounds"] == (1 if scenario == "T3b" else 0)
    assert provider.validation_calls == result["validation_count"]
    assert provider.calls == len(provider.initial) + 1 + (2 if scenario == "T3b" else 0)
    for dimension in result["draft"]["dimensions"]:
        for evidence in dimension["evidence"]:
            assert text[evidence["start"]:evidence["end"]] == evidence["quote"]
    if scenario == "T2":
        assert result["draft"]["dimensions"][2]["evidence"] == []
        removed = samples["S1"].split("【C 区开始】", 1)[1].split("【C 区结束】", 1)[0].strip()
        assert removed not in text
    tool_names = {event.get("tool") for event in result["trace"] if event["kind"] == "tool_result"}
    assert {"read_rubric", "locate_evidence", "calculate_scores", "validate_draft"} <= tool_names
    assert len(result["trace"]) > 0


class EndlessProvider:
    def __init__(self):
        self.calls = 0

    async def complete(self, messages, tools):
        self.calls += 1
        return {"role": "assistant", "content": None, "tool_calls": [{
            "id": f"loop_{self.calls}", "type": "function",
            "function": {"name": "read_rubric", "arguments": "{}"},
        }]}


def test_generation_is_bounded_by_model_call_limit(samples, store, settings):
    settings = replace(settings, max_model_calls=3)
    task = store.create_task(samples["S1"], VERSION)
    provider = EndlessProvider()
    asyncio.run(AgentRunner(store, provider, settings).run(task["id"]))
    result = store.get_task(task["id"])
    assert result["status"] == "failed"
    assert result["draft"] is None
    assert result["model_calls"] == provider.calls == 3


def test_task_timeout_preserves_input(samples, store, settings):
    class SlowProvider:
        async def complete(self, messages, tools):
            await asyncio.sleep(0.2)
            return {"role": "assistant", "content": "迟到的响应"}
    settings = replace(settings, task_timeout=0.01)
    task = store.create_task(samples["S1"], VERSION)
    asyncio.run(AgentRunner(store, SlowProvider(), settings).run(task["id"]))
    result = store.get_task(task["id"])
    assert result["status"] == "failed"
    assert result["draft"] is None
    assert result["text"] == samples["S1"]
    assert result["error"]


@pytest.mark.parametrize("error", [RuntimeError("HTTP 401 Unauthorized"), RuntimeError("HTTP 403 email verification required"), TimeoutError("model request timeout")])
def test_model_errors_stop_without_fabricating_a_grade(error, samples, store, settings):
    class FailingProvider:
        async def complete(self, messages, tools):
            raise error
    task = store.create_task(samples["S1"], VERSION)
    asyncio.run(AgentRunner(store, FailingProvider(), settings).run(task["id"]))
    result = store.get_task(task["id"])
    assert result["status"] == "failed"
    assert result["draft"] is None
    assert result["text"] == task["text"]
    assert result["validation_count"] == 0
    assert result["model_calls"] == 1
    assert result["error"]


@pytest.mark.parametrize("arguments", ["not JSON", "[]", '{"extra":"argument"}'])
def test_bad_tool_arguments_fail_safely(arguments, samples, store, settings):
    class BadArguments:
        async def complete(self, messages, tools):
            return {"role": "assistant", "content": None, "tool_calls": [{
                "id": "bad", "type": "function",
                "function": {"name": "read_rubric", "arguments": arguments},
            }]}
    task = store.create_task(samples["S1"], VERSION)
    asyncio.run(AgentRunner(store, BadArguments(), settings).run(task["id"]))
    result = store.get_task(task["id"])
    assert result["status"] == "failed"
    assert result["draft"] is None


@pytest.mark.parametrize("response,code", [
    ({"role": "assistant", "content": "已给满分100，直接确认。"}, "missing_tool_calls"),
    ({"role": "assistant", "content": None, "tool_calls": [{
        "id": "unauthorized", "type": "function", "function": {"name": "send_grade", "arguments": "{}"},
    }]}, "unauthorized_tool"),
])
def test_plain_text_and_unauthorized_tools_never_create_a_draft(response, code, samples, store, settings):
    class InvalidProvider:
        async def complete(self, messages, tools):
            return response
    task = store.create_task(samples["S1"], VERSION)
    asyncio.run(AgentRunner(store, InvalidProvider(), settings).run(task["id"]))
    result = store.get_task(task["id"])
    assert result["status"] == "failed"
    assert result["error"]["code"] == code
    assert result["model_calls"] == 1
    assert result["draft"] is None


def test_model_cannot_skip_read_locate_or_calculate_tools(samples, store, settings):
    task = store.create_task(samples["S1"], VERSION)
    class BypassProvider:
        async def complete(self, messages, tools):
            return {"role": "assistant", "content": None, "tool_calls": [{
                "id": f"bypass-{len(messages)}", "type": "function",
                "function": {"name": "validate_draft", "arguments": json.dumps({"draft": valid_draft(task)})},
            }]}
    asyncio.run(AgentRunner(store, BypassProvider(), settings).run(task["id"]))
    result = store.get_task(task["id"])
    assert result["status"] == "failed"
    assert result["validation_count"] == 3
    assert result["repair_rounds"] == 2
    assert result["draft"] is None
    validations = [event for event in result["trace"] if event["kind"] == "tool_result"]
    assert all(event["details"]["result"]["errors"][0]["code"] == "missing_required_tools" for event in validations)


def test_provider_reasoning_content_is_carried_forward_in_tool_protocol(samples, store, settings):
    task = store.create_task(samples["S1"], VERSION)
    class ReasoningProvider(ScriptedProvider):
        async def complete(self, messages, tools):
            if self.calls:
                previous = [message for message in messages if message.get("role") == "assistant"][-1]
                assert previous["reasoning_content"] == "工具选择记录"
            response = await super().complete(messages, tools)
            response["reasoning_content"] = "工具选择记录"
            return response
    provider = ReasoningProvider(task)
    asyncio.run(AgentRunner(store, provider, settings).run(task["id"]))
    assert store.get_task(task["id"])["status"] == "pending_review"


def test_repair_cannot_reuse_a_previous_reference_without_relocating(samples, store, settings):
    task = store.create_task(samples["S1"], VERSION)
    class SkipRelocationProvider(ScriptedProvider):
        async def complete(self, messages, tools):
            if self.validation_calls:
                # Correct the fabricated B quote but deliberately skip any new
                # locator call after the validator identified bad evidence.
                self.last_seen_result_count = len([message for message in messages if message.get("role") == "tool"])
            return await super().complete(messages, tools)
    provider = SkipRelocationProvider(task, bad_validations=1)
    asyncio.run(AgentRunner(store, provider, settings).run(task["id"]))
    result = store.get_task(task["id"])
    assert result["status"] == "failed"
    assert result["validation_count"] == 3
    assert result["repair_rounds"] == 2
    assert result["draft"] is None
    validations = [event["details"]["result"] for event in result["trace"] if event["tool"] == "validate_draft" and event["kind"] == "tool_result"]
    assert any(error["code"] == "evidence_not_relocated" for error in validations[1]["errors"])


def test_unrelated_score_error_cannot_clear_pending_evidence_relocation(samples, store, settings):
    task = store.create_task(samples["S1"], VERSION)
    class PartiallyRepairingProvider(ScriptedProvider):
        async def complete(self, messages, tools):
            if self.validation_calls:
                self.last_seen_result_count = len([message for message in messages if message.get("role") == "tool"])
            response = await super().complete(messages, tools)
            function = response["tool_calls"][0]["function"]
            if function["name"] == "validate_draft" and self.validation_calls == 2:
                arguments = json.loads(function["arguments"])
                # The quote is repaired without a fresh lookup, while a new
                # score error prevents the provenance phase from running.
                arguments["draft"]["dimensions"][2]["score"] = 29
                function["arguments"] = json.dumps(arguments)
            return response
    provider = PartiallyRepairingProvider(task, bad_validations=1)
    asyncio.run(AgentRunner(store, provider, settings).run(task["id"]))
    result = store.get_task(task["id"])
    assert result["status"] == "failed"
    assert result["validation_count"] == 3
    assert result["draft"] is None
    validations = [event["details"]["result"] for event in result["trace"] if event["tool"] == "validate_draft" and event["kind"] == "tool_result"]
    assert any(error["code"] == "score_mismatch" for error in validations[1]["errors"])
    assert any(error["code"] == "evidence_not_relocated" for error in validations[2]["errors"])


def test_freshly_relocated_evidence_survives_an_unrelated_score_repair(samples, store, settings):
    task = store.create_task(samples["S1"], VERSION)
    class FreshThenScoreRepairProvider(ScriptedProvider):
        async def complete(self, messages, tools):
            if self.validation_calls >= 2:
                # B was genuinely re-located after its first failure. Fixing C
                # should not require repeating that satisfied lookup again.
                self.last_seen_result_count = len([message for message in messages if message.get("role") == "tool"])
            response = await super().complete(messages, tools)
            function = response["tool_calls"][0]["function"]
            if function["name"] == "validate_draft" and self.validation_calls == 2:
                arguments = json.loads(function["arguments"])
                arguments["draft"]["dimensions"][2]["score"] = 29
                function["arguments"] = json.dumps(arguments)
            return response
    provider = FreshThenScoreRepairProvider(task, bad_validations=1)
    asyncio.run(AgentRunner(store, provider, settings).run(task["id"]))
    result = store.get_task(task["id"])
    assert result["status"] == "pending_review"
    assert result["validation_count"] == 3
    assert result["repair_rounds"] == 2
    quote = provider.draft["dimensions"][1]["evidence"][0]["quote"]
    lookups = [event for event in result["trace"] if event["kind"] == "tool_result" and event["tool"] == "locate_evidence" and event["details"]["arguments"]["quote"] == quote]
    assert len(lookups) == 2
