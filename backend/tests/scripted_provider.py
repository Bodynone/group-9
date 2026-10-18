"""A protocol-level model substitute; all grading tools still really execute.

The fixture reference grades are deliberately confined to tests. This provider
does not model how an LLM judges prose, and its results are not a live benchmark.
"""

from copy import deepcopy
from decimal import Decimal
import json


DIMENSIONS = "ABCDEF"
MAXIMA = dict(zip(DIMENSIONS, (15, 25, 25, 15, 10, 10), strict=True))
INJECTED_QUOTE = "【不存在的证据 QX-001】"


def anchors(text):
    lines = text.splitlines()
    result = {}
    for dimension in DIMENSIONS:
        for index, line in enumerate(lines):
            if line.startswith(dimension + " "):
                result[dimension] = lines[index + 1]
                break
    return result


def located_evidence(text, quote):
    start = text.index(quote)
    return {
        "quote": quote,
        "paragraph": text[:start].count("\n") + 1,
        "start": start,
        "end": start + len(quote),
    }


def valid_draft(task, levels=None):
    levels = levels or {dimension: 100 for dimension in DIMENSIONS}
    quotes = anchors(task["text"])
    dimensions = []
    for dimension in DIMENSIONS:
        level = levels[dimension]
        dimensions.append({
            "id": dimension,
            "level": level,
            "score": float(Decimal(MAXIMA[dimension]) * Decimal(level) / 100),
            "reason": "该维度的原文满足固定量表的要求。" if level else "该部分未提供，正文整体缺失，需教师核查。",
            "evidence": [located_evidence(task["text"], quotes[dimension])] if level else [],
            "needs_review": level == 0,
            "review_note": "请核查正文缺失。" if level == 0 else "",
        })
    return {
        "dimensions": dimensions,
        "total": sum(item["score"] for item in dimensions),
        "status": "draft",
        "rubric_version": task["rubric_version"],
        "input_version": task["input_version"],
    }


class ScriptedProvider:
    """Issue real tools, optionally ask the engine to repair bad B evidence."""

    def __init__(self, task, levels=None, bad_validations=0):
        self.task = task
        self.draft = valid_draft(task, levels)
        self.bad_validations = bad_validations
        self.validation_calls = 0
        self.calls = 0
        self.seen_tool_results = []
        self.initial = [
            ("read_rubric", {}),
            *[("locate_evidence", {"quote": item["evidence"][0]["quote"]})
              for item in self.draft["dimensions"] if item["evidence"]],
            ("calculate_scores", {"dimensions": [
                {"id": item["id"], "level": item["level"]}
                for item in self.draft["dimensions"]
            ]}),
        ]
        self.pending = list(self.initial)
        self.last_seen_result_count = 0

    async def complete(self, messages, tools):
        self.calls += 1
        results = [message for message in messages if message.get("role") == "tool"]
        self.seen_tool_results = results
        if results and len(results) > self.last_seen_result_count:
            self.last_seen_result_count = len(results)
            last_result = json.loads(results[-1]["content"])
            if last_result.get("valid") is False:
                quote = self.draft["dimensions"][1]["evidence"][0]["quote"]
                self.pending.append(("locate_evidence", {"quote": quote}))
        if self.pending:
            name, arguments = self.pending.pop(0)
        else:
            name = "validate_draft"
            draft = deepcopy(self.draft)
            if self.validation_calls < self.bad_validations:
                draft["dimensions"][1]["evidence"][0]["quote"] = INJECTED_QUOTE
            self.validation_calls += 1
            arguments = {"draft": draft}
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": f"call_{self.calls}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
            }],
        }


def reviewed_dimensions(task, levels=None, reviewed=True):
    original = task.get("draft", {}).get("dimensions", []) if task.get("draft") else []
    original_levels = {item["id"]: item["level"] for item in original}
    selected = levels or original_levels or {dimension: 100 for dimension in DIMENSIONS}
    return [
        {"id": dimension, "level": selected[dimension], "reason": "教师已逐项核查原文与档位。", "reviewed": reviewed}
        for dimension in DIMENSIONS
    ]
