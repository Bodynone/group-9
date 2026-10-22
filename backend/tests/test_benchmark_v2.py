import importlib.util
from pathlib import Path

from backend.rubric_service import RubricService

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ablation_study_v2.py"
spec = importlib.util.spec_from_file_location("ablation_v2", SCRIPT)
study = importlib.util.module_from_spec(spec)
spec.loader.exec_module(study)


def test_36_samples_three_courses_and_no_fabricated_references():
    samples = study.load_samples()
    assert {category: sum(sample["assignment_id"] == category for sample in samples) for category in ("software", "database", "ethics")} == {"software": 12, "database": 12, "ethics": 12}
    assert all(sample["synthetic"] for sample in samples)
    assert all(study.reference_levels(sample) is None for sample in samples)
    assert {len(sample["definition"]["dimensions"]) for sample in samples} == {4, 5, 6}


def test_reference_gate_requires_two_distinct_reviewers_and_valid_adjudication():
    sample = study.load_samples()[0]
    levels = {d["id"]: sample["definition"]["levels"][0]["id"] for d in sample["definition"]["dimensions"]}
    sample["reference"] = {"status": "adjudicated", "reviewer_a": {"id": "reviewer-a", "levels": levels}, "reviewer_b": {"id": "reviewer-a", "levels": levels}, "adjudicated_levels": levels}
    assert study.reference_levels(sample) is None
    sample["reference"]["reviewer_b"]["id"] = "reviewer-b"
    assert study.reference_levels(sample) == levels
    sample["reference"]["adjudicated_levels"] = {}
    assert study.reference_levels(sample) is None


def test_no_scoring_accuracy_without_verified_reference(store):
    sample = study.load_samples()[0]
    service = RubricService(store)
    context = service.context(None, {"id": "test", "definition": sample["definition"], "content_hash": study.digest(sample["definition"])})
    with store.transaction():
        task = service._create_task({"submission_label": "s", "text": sample["text"]}, context)
    result = study.assess(None, service.task(task["id"]))
    assert not result["reference_verified"] and result["level_agreement"] is None and result["absolute_score_error"] is None


def test_summary_keeps_failed_samples_and_missing_usage_in_denominator(store):
    sample = study.load_samples()[0]
    service = RubricService(store)
    context = service.context(None, {"id": "test", "definition": sample["definition"], "content_hash": study.digest(sample["definition"])})
    with store.transaction():
        task = service._create_task({"submission_label": "s", "text": sample["text"]}, context)
    metrics = study.assess(None, service.task(task["id"]))
    failed = {"course": "software", "condition": "direct", "error": "failed", "seconds": 2,
              "usage": {"prompt_tokens": 0, "completion_tokens": 0, "complete": False}, "metrics": metrics}
    completed = {**failed, "error": None, "metrics": {**metrics, "arithmetic_valid": True, "format_valid": True}, "seconds": 4}
    summary = study.summarize([completed, failed])["software"]["direct"]
    assert summary["samples"] == 2 and summary["completed"] == 1
    assert summary["arithmetic_pct"] == summary["format_pct"] == 50
    assert summary["mean_seconds"] == 3 and summary["mean_tokens"] is None
    assert summary["evidence_pct"] is None and summary["level_agreement_pct"] is None
