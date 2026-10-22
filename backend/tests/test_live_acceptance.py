import asyncio
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

from backend.agent import AgentRunner
from backend.config import Settings
from backend.rubric import VERSION

from scripted_provider import ScriptedProvider


SPEC = importlib.util.spec_from_file_location("live_acceptance", Path(__file__).resolve().parents[1] / "scripts/live_acceptance.py")
live = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(live)


@pytest.fixture
def valid_task(samples, store, settings):
    task = store.create_task(samples["S1"], VERSION)
    asyncio.run(AgentRunner(store, ScriptedProvider(task), settings).run(task["id"]))
    return store.get_task(task["id"])


def test_real_acceptance_assessment_requires_reference_scores_current_evidence_and_actual_tools(valid_task, samples):
    assert live.assess(valid_task, samples["expected"]["S1"], samples["S1"])["passed"] is True
    missing_tool = deepcopy(valid_task)
    missing_tool["trace"] = [event for event in missing_tool["trace"] if event.get("tool") != "read_rubric"]
    assert live.assess(missing_tool, samples["expected"]["S1"], samples["S1"])["passed"] is False
    bad_quote = deepcopy(valid_task)
    bad_quote["draft"]["dimensions"][0]["evidence"][0]["quote"] = "捏造的引文"
    assert live.assess(bad_quote, samples["expected"]["S1"], samples["S1"])["passed"] is False
    wrong_score = deepcopy(valid_task)
    wrong_score["draft"]["dimensions"][0]["score"] = 10.5
    assert live.assess(wrong_score, samples["expected"]["S1"], samples["S1"])["passed"] is False


def test_acceptance_export_metadata_redacts_credentials_and_service_query():
    assert live.safe_service("https://user:password@model.invalid:8443/v1?api_key=secret#token") == "https://model.invalid:8443/v1"
    assert live.redact({"trace": [{"message": "failure secret-value"}]}, "secret-value") == {"trace": [{"message": "failure [已隐藏]"}]}


def test_missing_real_service_configuration_saves_failure_and_exits_one(samples, tmp_path, monkeypatch, capsys):
    sample_dir = tmp_path / "samples"
    sample_dir.mkdir()
    (sample_dir / "S1.txt").write_text(samples["S1"], encoding="utf-8")
    (sample_dir / "expected.json").write_text(json.dumps(samples["expected"]), encoding="utf-8")
    monkeypatch.setattr(live, "ROOT", tmp_path)
    monkeypatch.setattr(live.Settings, "from_env", lambda: Settings(api_key=""))
    assert asyncio.run(live.run_sample("S1")) == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "failed"
    assert printed["error"]["code"] == "model_not_configured"
    record = json.loads(Path(printed["output"]).read_text(encoding="utf-8"))
    assert record["human_approval"] == "pending"
    assert record["task"]["text"] == samples["S1"]
    assert record["assessment"]["passed"] is False
    assert record["started_at"].endswith("+08:00")
    assert record["request_timeout_seconds"] == 90
