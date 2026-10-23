"""Deterministic learning workflow substitute. Never use as a quality reference."""
import asyncio
import json


class LearningTestProvider:
    def __init__(self, audit_mode="disagree"):
        self.audit_mode = audit_mode
        self.audit_inputs = []

    async def complete(self, messages, tools):
        metadata = json.loads(messages[1]["content"])
        usage = {"prompt_tokens": 10, "completion_tokens": 2}
        if metadata.get("role") == "independent_reviewer":
            self.audit_inputs.append(metadata)
            if self.audit_mode == "timeout":
                await asyncio.sleep(5)
            if self.audit_mode == "bad":
                return {"content": "not JSON", "usage": usage}
            definition = metadata["rubric"]
            levels = definition["levels"]
            high = next(l["id"] for l in levels if l["percent"] == "100.00")
            lower = next((l["id"] for l in levels if l["percent"] == "70.00"), high)
            rows = [{"dimension_id": d["id"], "level_id": lower if i == 0 and self.audit_mode == "disagree" else high,
                     "reason": "测试审校脚本，不能作为真实评分效果证据。", "evidence_quotes": [metadata["assignment_text"][:20]]}
                    for i, d in enumerate(definition["dimensions"])]
            if self.audit_mode == "fabricated":
                rows[0]["evidence_quotes"] = ["不存在的审校证据"]
            return {"content": json.dumps({"dimensions": rows}, ensure_ascii=False), "usage": usage}
        results = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        if not results:
            name, arguments = "read_rubric", {}
        else:
            definition = next(r["definition"] for r in results if "definition" in r)
            searched = {r["dimension_id"] for r in results if "matches" in r}
            searched.update(r["dimension_id"] for result in results for r in result.get("course_materials", []))
            missing = [d for d in definition["dimensions"] if d["id"] not in searched]
            level = next(l["id"] for l in definition["levels"] if l["percent"] == "100.00")
            if any(t["function"]["name"] == "search_materials" for t in tools) and missing:
                name, arguments = "search_materials", {"dimension_id": missing[0]["id"], "query": "SQL LEFT JOIN 查询"}
            elif not any("found" in r for r in results):
                name, arguments = "locate_evidence", {"quote": metadata["assignment_text"][:20]}
            elif not any(r.get("ok") for r in results):
                name, arguments = "calculate_scores", {"dimensions": [{"dimension_id": d["id"], "level_id": level} for d in definition["dimensions"]]}
            else:
                evidence = next(r["evidence"] for r in results if r.get("found"))
                calculation = next(r for r in results if r.get("ok"))
                draft = {"status": "draft", **{k: metadata[k] for k in ("input_version", "rubric_hash", "context_hash")}, "total": calculation["total"],
                         "dimensions": [{**d, "level_id": level, "reason": "测试评分脚本，不能作为真实评分效果证据。", "evidence": [evidence], "needs_review": False, "review_note": ""} for d in calculation["dimensions"]]}
                name, arguments = "validate_draft", {"draft": draft}
        return {"tool_calls": [{"id": f"learning-{len(results)}", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}], "content": None, "usage": usage}
