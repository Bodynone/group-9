"""Protocol substitute for v2 integration tests. Never a grading benchmark."""

import json

from backend.provider import ModelError
from backend.tools_v2 import DynamicToolbox


class DynamicTestProvider:
    async def complete(self, messages, tools):
        metadata = json.loads(messages[1]["content"])
        if "[V2_FAIL]" in metadata["assignment_text"]:
            raise ModelError("test_failure", "受控模型故障")
        results = [json.loads(message["content"]) for message in messages if message["role"] == "tool"]
        count = len(results)
        if not results:
            name, args = "read_rubric", {}
        elif count == 1:
            name, args = "locate_evidence", {"quote": metadata["assignment_text"][:40]}
        elif count == 2:
            definition = results[0]["definition"]
            level = next(level["id"] for level in definition["levels"] if level["percent"] == "100.00")
            name, args = "calculate_scores", {"dimensions": [{"dimension_id": d["id"], "level_id": level} for d in definition["dimensions"]]}
        else:
            rubric, evidence, calculation = results[:3]
            definition = rubric["definition"]
            level = next(level["id"] for level in definition["levels"] if level["percent"] == "100.00")
            draft = {"status": "draft", "input_version": metadata["input_version"], "rubric_hash": metadata["rubric_hash"],
                     "context_hash": metadata["context_hash"], "total": calculation["total"], "dimensions": [
                         {**score, "level_id": level, "reason": "测试替身按脚本给出档位，不代表大模型判断质量。",
                          "evidence": [evidence["evidence"]], "needs_review": False, "review_note": ""}
                         for score in calculation["dimensions"]]}
            name, args = "validate_draft", {"draft": draft}
        return {"role": "assistant", "content": None, "reasoning_content": "test protocol", "usage": {"prompt_tokens": 10, "completion_tokens": 2},
                "tool_calls": [{"id": f"call-{count}", "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}]}
