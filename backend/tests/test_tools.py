from copy import deepcopy

import pytest

from backend.rubric import VERSION
from backend.tools import Toolbox

from scripted_provider import DIMENSIONS, valid_draft


@pytest.fixture
def task(samples, store):
    return store.create_task(samples["S1"], VERSION)


def test_decimal_scores_preserve_half_points(task):
    result = Toolbox(task).calculate_scores([
        {"id": dimension, "level": 70} for dimension in DIMENSIONS
    ])
    assert result["total"] == 70
    assert {item["id"]: item["score"] for item in result["dimensions"]} == {
        "A": 10.5, "B": 14, "C": 21, "D": 10.5, "E": 7, "F": 7,
    }


@pytest.mark.parametrize("levels", [
    [{"id": dimension, "level": 75} for dimension in DIMENSIONS],
    [{"id": dimension, "level": True} for dimension in DIMENSIONS],
    [{"id": dimension, "level": "100"} for dimension in DIMENSIONS],
    [{"id": dimension, "level": 100} for dimension in "ABCDE"],
    [{"id": dimension, "level": 100} for dimension in "ABCDEE"],
    [{"id": dimension, "level": 100} for dimension in "ABCDEG"],
])
def test_score_tool_rejects_illegal_levels_and_dimension_sets(task, levels):
    result = Toolbox(task).calculate_scores(levels)
    assert result["ok"] is False
    assert result["errors"]


def test_locator_returns_exact_current_text_offsets(task):
    quote = "用户是课程教师。"
    result = Toolbox(task).locate_evidence(quote)
    assert result["found"] is True
    evidence = result["evidence"]
    assert task["text"][evidence["start"]:evidence["end"]] == quote
    assert evidence["quote"] == quote
    assert Toolbox(task).locate_evidence("不存在的引文")["found"] is False


def test_draft_validation_accepts_a_well_formed_draft(task):
    result = Toolbox(task).validate_draft(valid_draft(task))
    assert result["valid"] is True
    assert result["errors"] == []


@pytest.mark.parametrize("mutation", [
    "missing_dimension", "duplicate_dimension", "illegal_level", "wrong_score",
    "wrong_total", "made_up_quote", "wrong_offset", "wrong_paragraph", "wrong_paragraph_type",
    "stale_input", "wrong_rubric", "confirmed_status", "empty_reason", "missing_evidence",
])
def test_draft_validator_rejects_invalid_or_stale_results(task, mutation):
    draft = valid_draft(task)
    first = draft["dimensions"][0]
    if mutation == "missing_dimension":
        draft["dimensions"].pop()
    elif mutation == "duplicate_dimension":
        draft["dimensions"][-1]["id"] = "A"
    elif mutation == "illegal_level":
        first["level"] = 50
    elif mutation == "wrong_score":
        first["score"] = 14
    elif mutation == "wrong_total":
        draft["total"] = 99
    elif mutation == "made_up_quote":
        first["evidence"][0]["quote"] = "编造的原文引用"
    elif mutation == "wrong_offset":
        first["evidence"][0]["start"] += 1
    elif mutation == "wrong_paragraph":
        first["evidence"][0]["paragraph"] += 1
    elif mutation == "wrong_paragraph_type":
        first["evidence"][0]["paragraph"] = float(first["evidence"][0]["paragraph"])
    elif mutation == "stale_input":
        draft["input_version"] = "previous-version"
    elif mutation == "wrong_rubric":
        draft["rubric_version"] = "previous-rubric"
    elif mutation == "confirmed_status":
        draft["status"] = "confirmed"
    elif mutation == "empty_reason":
        first["reason"] = "   "
    elif mutation == "missing_evidence":
        first["evidence"] = []
    result = Toolbox(task).validate_draft(draft)
    assert result["valid"] is False
    assert result["errors"]


def test_changed_input_cannot_reuse_old_evidence(task):
    draft = valid_draft(task)
    changed_task = deepcopy(task)
    changed_task["text"] = "新增前言。\n" + task["text"]
    changed_task["input_version"] = "changed-input"
    assert Toolbox(changed_task).validate_draft(draft)["valid"] is False


def test_zero_requires_explicit_missing_label(task):
    draft = valid_draft(task, {dimension: 0 if dimension == "C" else 100 for dimension in DIMENSIONS})
    draft["dimensions"][2]["reason"] = "内容缺失"
    assert Toolbox(task).validate_draft(draft)["valid"] is False
