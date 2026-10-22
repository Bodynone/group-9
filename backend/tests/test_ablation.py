"""Keep the evaluation driver aligned with the backend's live contracts."""

import asyncio
import importlib.util
import json
from pathlib import Path

from backend.rubric import RUBRIC, VERSION
from backend.guardrails import SecurityGuardrails
from backend.storage import Store


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
