"""Snapshot-scoped deterministic tools for arbitrary teacher-defined dimensions."""

from copy import deepcopy
from decimal import Decimal

from .schemas_v2 import money
from .tools import Toolbox, tool_schemas


class DynamicToolbox(Toolbox):
    def read_rubric(self):
        return {"definition": deepcopy(self.task["rubric_snapshot"]), **{key: self.task[key] for key in
                ("rubric_version_id", "rubric_hash", "context_hash", "input_version")}}

    def calculate_scores(self, dimensions):
        definition = self.task["rubric_snapshot"]
        configured = {dimension["id"]: dimension for dimension in definition["dimensions"]}
        levels = {level["id"]: Decimal(level["percent"]) for level in definition["levels"]}
        bad = {"ok": False, "errors": ["须提供本快照的全部维度与合法档位，且各维只出现一次"]}
        if (not isinstance(dimensions, list) or len(dimensions) != len(configured)
                or any(not isinstance(d, dict) or not isinstance(d.get("dimension_id"), str)
                       or not isinstance(d.get("level_id"), str) for d in dimensions)):
            return bad
        entries = {d["dimension_id"]: d for d in dimensions}
        if set(entries) != set(configured) or any(d["level_id"] not in levels for d in dimensions):
            return bad
        scores = [{"dimension_id": key, "score": money(Decimal(d["max_score"]) * levels[entries[key]["level_id"]] / 100)}
                  for key, d in configured.items()]
        return {"ok": True, "dimensions": scores, "total": money(sum((Decimal(d["score"]) for d in scores), Decimal(0))),
                **{key: self.task[key] for key in ("input_version", "rubric_hash", "context_hash")}}

    def validate_draft(self, draft):
        errors = []

        def error(code, message, dimension=None):
            errors.append({"code": code, "message": message, "dimension": dimension})

        if not isinstance(draft, dict):
            return {"valid": False, "errors": [{"code": "invalid_draft", "message": "草稿须为对象"}]}
        if draft.get("status") != "draft":
            error("invalid_state", "仅能生成待教师确认的草稿")
        for key in ("input_version", "rubric_hash", "context_hash"):
            if draft.get(key) != self.task[key]:
                error("version_mismatch", key + "不匹配")
        calculation = self.calculate_scores(draft.get("dimensions"))
        if not calculation["ok"]:
            error("invalid_dimensions", calculation["errors"][0])
            return {"valid": False, "errors": errors}
        levels = {level["id"]: Decimal(level["percent"]) for level in self.task["rubric_snapshot"]["levels"]}
        scores = {d["dimension_id"]: d["score"] for d in calculation["dimensions"]}
        for d in draft["dimensions"]:
            identifier = d["dimension_id"]
            if d.get("score") != scores[identifier]:
                error("score_mismatch", "分项须照计分工具返回的两位小数字符串填写", identifier)
            if not isinstance(d.get("reason"), str) or not d["reason"].strip():
                error("missing_reason", "须说明具体评分依据", identifier)
            if type(d.get("needs_review")) is not bool or not isinstance(d.get("review_note"), str) or (d["needs_review"] and not d["review_note"].strip()):
                error("missing_review_note", "须填写待核查标记及核查问题", identifier)
            evidence = d.get("evidence")
            if not isinstance(evidence, list):
                error("invalid_evidence", "证据须为数组", identifier)
                continue
            if not evidence and levels[d["level_id"]] != 0:
                error("missing_evidence", "非零档须提供原文证据", identifier)
            for reference in evidence:
                if not isinstance(reference, dict):
                    error("invalid_evidence", "须使用定位工具返回的对象", identifier)
                    continue
                quote, start, end = reference.get("quote"), reference.get("start"), reference.get("end")
                if not (isinstance(quote, str) and quote and type(start) is int and type(end) is int
                        and 0 <= start < end <= len(self.task["text"]) and self.task["text"][start:end] == quote):
                    error("evidence_not_found", "引用与学生原文的字符切片不一致", identifier)
                elif type(reference.get("paragraph")) is not int or reference["paragraph"] != self.task["text"][:start].count("\n") + 1:
                    error("paragraph_mismatch", "段落不匹配", identifier)
        if draft.get("total") != calculation["total"]:
            error("total_mismatch", "总分须照计分工具返回值填写")
        if errors:
            return {"valid": False, "errors": errors}
        canonical = deepcopy(draft)
        entries = {d["dimension_id"]: d for d in draft["dimensions"]}
        canonical["dimensions"] = [entries[d["id"]] for d in self.task["rubric_snapshot"]["dimensions"]]
        return {"valid": True, "errors": [], "draft": canonical}


def dynamic_schemas(task):
    schemas = tool_schemas()
    ids = [d["id"] for d in task["rubric_snapshot"]["dimensions"]]
    levels = [level["id"] for level in task["rubric_snapshot"]["levels"]]
    choice = {"type": "object", "properties": {"dimension_id": {"type": "string", "enum": ids},
              "level_id": {"type": "string", "enum": levels}}, "required": ["dimension_id", "level_id"], "additionalProperties": False}
    schemas[2]["function"]["parameters"]["properties"]["dimensions"]["items"] = choice
    draft = schemas[3]["function"]["parameters"]["properties"]["draft"]
    dimension = draft["properties"]["dimensions"]["items"]
    dimension["properties"].pop("id")
    dimension["properties"].pop("level")
    dimension["properties"].update(choice["properties"])
    dimension["properties"]["score"] = {"type": "string", "description": "计分工具返回的两位小数"}
    dimension["required"] = ["dimension_id", "level_id", "score", "reason", "evidence", "needs_review", "review_note"]
    draft["properties"].pop("rubric_version")
    draft["properties"].update({"rubric_hash": {"type": "string"}, "context_hash": {"type": "string"}, "total": {"type": "string"}})
    draft["required"] = ["dimensions", "total", "status", "rubric_hash", "context_hash", "input_version"]
    return schemas
