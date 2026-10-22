"""Keep the evaluation driver aligned with the backend's live contracts."""

import asyncio
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.rubric import RUBRIC, VERSION
from backend.guardrails import SecurityGuardrails
from backend.storage import Store
from backend.provider import ChatProvider, ModelError
from scripted_provider import ScriptedProvider, valid_draft


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ablation_study.py"
spec = importlib.util.spec_from_file_location("ablation_study", SCRIPT)
study = importlib.util.module_from_spec(spec)
spec.loader.exec_module(study)


def test_benchmark_uses_current_rubric_and_real_files():
    samples = list(study.load_samples(20))
    assert len(samples) == 20
    assert RUBRIC["version"] == VERSION == "2026-v1"
    assert {row["id"] for row in samples} == {f"S{i:02d}" for i in range(1, 21)}
    for sample in samples:
        raw = (study.BENCHMARK.parent / sample["file"]).read_bytes()
        assert raw.decode("utf-8") == sample["text"]
        task = Store._new_task(sample["text"], VERSION)
        assert task["input_version"] == sample["sha256"]
        expected_risk = "high" if sample["prompt_injection_expected"] else "none"
        assert SecurityGuardrails().scan_text(sample["text"]).risk_level == expected_risk


def test_metrics_reject_duplicate_dimensions_and_false_evidence():
    sample = next(study.load_samples(1))
    dimensions = [
        {"id": key, "level": 100, "score": weight, "reason": "有证据", "evidence": ["不存在的逐字引用"]}
        for key, weight in study.WEIGHTS.items()
    ]
    draft = {"dimensions": dimensions, "total": 100}
    result = study.assess(draft, sample["text"])
    assert result["arithmetic"] and result["format"]
    assert result["evidence_total"] == 6 and result["evidence_valid"] == 0
    draft["dimensions"][5]["id"] = "A"
    assert not study.assess(draft, sample["text"])["format"]


def test_half_agent_uses_tools_without_validation():
    sample = next(study.load_samples(1))
    task = Store._new_task(sample["text"], VERSION)

    class Provider:
        def __init__(self):
            self.index = 0
            self.seen_tools = []

        async def complete(self, messages, tools):
            self.seen_tools.append({tool["function"]["name"] for tool in tools})
            calls = [
                ("read_rubric", {}),
                ("locate_evidence", {"quote": sample["text"][:12]}),
                ("calculate_scores", {"dimensions": [{"id": key, "level": 100} for key in study.WEIGHTS]}),
            ]
            if self.index < len(calls):
                name, args = calls[self.index]
                self.index += 1
                return {"tool_calls": [{"id": f"call-{self.index}", "function": {
                    "name": name, "arguments": json.dumps(args, ensure_ascii=False),
                }}]}
            return {"content": json.dumps({"dimensions": [], "total": 0})}

    provider = Provider()
    draft, _ = asyncio.run(study.half_agent(provider, task, RUBRIC, 8))
    assert draft["total"] == 0
    assert len(provider.seen_tools) == 4
    assert all("validate_draft" not in tools for tools in provider.seen_tools)


def test_benchmark_hash_check_does_not_normalize_edited_newlines(tmp_path, monkeypatch):
    data = json.loads(study.BENCHMARK.read_text(encoding="utf-8"))
    source = study.BENCHMARK.parent / data["samples"][0]["file"]
    (tmp_path / source.name).write_bytes(source.read_bytes().replace(b"\n", b"\r\n"))
    benchmark = tmp_path / "benchmark.json"
    benchmark.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(study, "BENCHMARK", benchmark)
    with pytest.raises(AssertionError, match="S01"):
        list(study.load_samples(1))


@pytest.mark.parametrize("bad_id", [[], {}, None, 1])
def test_malformed_dimension_ids_are_metric_failures(bad_id):
    sample = next(study.load_samples(1))
    draft = valid_draft(Store._new_task(sample["text"], VERSION))
    draft["dimensions"][0]["id"] = bad_id
    result = study.assess(draft, sample["text"])
    assert not result["format"]


@pytest.mark.parametrize("changes", [
    {"start": 999999, "end": 1000000},
    {"start": False},
    {"paragraph": 999},
    {"start": 3, "end": 5},
])
def test_evidence_objects_must_match_codepoint_slice(changes):
    text = "\ufeff🧪\r\n原文证据"
    draft = valid_draft(Store._new_task(next(study.load_samples(1))["text"], VERSION))
    evidence = {"quote": "原文证据", "start": 4, "end": 8, "paragraph": 2}
    for dimension in draft["dimensions"]:
        dimension["evidence"] = [dict(evidence)]
    assert study.assess(draft, text)["evidence_valid"] == 6
    draft["dimensions"][0]["evidence"][0].update(changes)
    metrics = study.assess(draft, text)
    assert metrics["evidence_total"] == 6 and metrics["evidence_valid"] == 5


def test_half_agent_preserves_reasoning_and_excludes_usage_from_messages():
    sample = next(study.load_samples(1))
    task = Store._new_task(sample["text"], VERSION)

    class ReasoningProvider:
        async def complete(self, messages, tools):
            if len(messages) > 2:
                assistant = messages[2]
                assert assistant["reasoning_content"] == "先取得量表和工具结果"
                assert "usage" not in assistant
                return {"content": json.dumps(valid_draft(task)),
                        "usage": {"prompt_tokens": 5, "completion_tokens": 1}}
            requests = [("read_rubric", {}), ("locate_evidence", {"quote": task["text"][:10]}),
                        ("calculate_scores", {"dimensions": [{"id": k, "level": 100} for k in study.WEIGHTS]})]
            return {"reasoning_content": "先取得量表和工具结果", "content": None,
                    "usage": {"prompt_tokens": 10, "completion_tokens": 2},
                    "tool_calls": [{"id": str(i), "type": "function", "function": {
                        "name": name, "arguments": json.dumps(arguments)}}
                        for i, (name, arguments) in enumerate(requests)]}

    draft, usage = asyncio.run(study.half_agent(ReasoningProvider(), task, RUBRIC, 3))
    assert draft["total"] == 100
    assert usage == {"prompt_tokens": 15, "completion_tokens": 3, "complete": True}


class EvaluationProvider:
    """Exercise all three real tool paths without network or production storage."""

    def __init__(self, settings):
        self.settings = settings
        self.full = None

    redact = ChatProvider.redact

    async def complete(self, messages, tools):
        names = {tool["function"]["name"] for tool in tools}
        if "validate_draft" in names:
            if self.full is None:
                metadata = json.loads(messages[1]["content"])
                task = Store._new_task(metadata["assignment_text"], VERSION)
                self.full = ScriptedProvider(task)
            response = await self.full.complete(messages, tools)
        else:
            task = Store._new_task(messages[1]["content"], VERSION)
            if names and len(messages) == 2:
                requests = [("read_rubric", {}), ("locate_evidence", {"quote": task["text"][:10]}),
                            ("calculate_scores", {"dimensions": [{"id": k, "level": 100} for k in study.WEIGHTS]})]
                response = {"tool_calls": [{"id": str(i), "type": "function", "function": {
                    "name": name, "arguments": json.dumps(arguments)}}
                    for i, (name, arguments) in enumerate(requests)]}
            else:
                response = {"content": json.dumps(valid_draft(task))}
        return {**response, "usage": {"prompt_tokens": 10, "completion_tokens": 2}}


def test_three_conditions_write_auditable_results_without_production_database(tmp_path, monkeypatch, settings):
    (tmp_path / "docs").mkdir()
    monkeypatch.setattr(study, "ROOT", tmp_path)
    monkeypatch.setattr("backend.config.Settings.from_env", lambda: settings)
    monkeypatch.setattr("backend.provider.ChatProvider", EvaluationProvider)
    original_store = Store.__init__

    def memory_only(store, path):
        assert path == ":memory:"
        original_store(store, path)

    monkeypatch.setattr(Store, "__init__", memory_only)
    assert asyncio.run(study.run(SimpleNamespace(samples=1))) == 0
    record = json.loads((tmp_path / "docs/eval-results.json").read_text(encoding="utf-8"))
    for rows in record["results"].values():
        row = rows[0]
        assert row["error"] is None and row["draft"]["total"] == 100
        assert row["input_version"] == next(study.load_samples(1))["sha256"]
        assert row["metrics"]["evidence_valid"] == row["metrics"]["evidence_total"] == 6
        assert row["usage"]["complete"]
    assert record["parameters"]["task_timeout"] == settings.task_timeout
    assert settings.api_key not in (tmp_path / "docs/eval-results.json").read_text(encoding="utf-8")


def test_run_caps_half_agent_time_and_redacts_failed_requests(tmp_path, monkeypatch, settings, capsys):
    (tmp_path / "docs").mkdir()
    monkeypatch.setattr(study, "ROOT", tmp_path)
    settings = replace(settings, task_timeout=0.02)
    monkeypatch.setattr("backend.config.Settings.from_env", lambda: settings)

    class FailingProvider(EvaluationProvider):
        async def complete(self, messages, tools):
            if not tools:
                raise ModelError("bad", "Bearer " + settings.api_key)
            if not any(tool["function"]["name"] == "validate_draft" for tool in tools):
                await asyncio.Event().wait()
            return await super().complete(messages, tools)

    monkeypatch.setattr("backend.provider.ChatProvider", FailingProvider)
    assert asyncio.run(study.run(SimpleNamespace(samples=1))) == 1
    saved = (tmp_path / "docs/eval-results.json").read_text(encoding="utf-8")
    assert settings.api_key not in saved + capsys.readouterr().out
    record = json.loads(saved)
    assert "TimeoutError" in record["results"]["half_agent"][0]["error"]
    assert study.summarize(record["results"]["baseline"])["tokens_per_sample"] is None
