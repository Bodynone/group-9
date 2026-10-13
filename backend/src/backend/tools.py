from copy import deepcopy
from decimal import Decimal, InvalidOperation

from .rubric import IDS, LEVELS, RUBRIC, VERSION, score


class ToolError(Exception):
    def __init__(self, message: str, code: str = "tool_error", tool: str | None = None):
        super().__init__(message)
        self.code, self.message, self.tool = code, message, tool


class Toolbox:
    def __init__(self, task: dict):
        self.task = task

    def read_rubric(self) -> dict:
        return deepcopy(RUBRIC)

    def locate_evidence(self, quote: str) -> dict:
        if not isinstance(quote, str):
            raise ToolError("原文定位参数须为字符串", tool="locate_evidence")
        index = self.task["text"].find(quote) if quote else -1
        if index < 0:
            return {"found": False, "message": "该部分未提供" if not quote else "未在本次作业中找到该引用", "input_version": self.task["input_version"]}
        evidence = {"quote": quote, "start": index, "end": index + len(quote), "paragraph": self.task["text"][:index].count("\n") + 1}
        return {"found": True, "evidence": evidence, "input_version": self.task["input_version"]}

    def calculate_scores(self, dimensions: list[dict]) -> dict:
        errors = []
        if not isinstance(dimensions, list) or len(dimensions) != 6 or any(not isinstance(d, dict) for d in dimensions):
            return {"ok": False, "errors": ["须提供A—F六维档位"]}
        ids = [d.get("id") for d in dimensions]
        if len(set(str(i) for i in ids)) != 6 or set(str(i) for i in ids) != set(IDS):
            errors.append("A—F六维须各出现一次")
        calculated = []
        total = Decimal(0)
        for d in dimensions:
            try:
                value = score(d.get("id"), d.get("level"))
                calculated.append({"id": d["id"], "score": float(value)})
                total += value
            except (ValueError, TypeError):
                errors.append(f"{d.get('id', '?')}维档位不合法")
        if errors:
            return {"ok": False, "errors": errors}
        calculated.sort(key=lambda d: IDS.index(d["id"]))
        return {"ok": True, "dimensions": calculated, "total": float(total), "rubric_version": VERSION, "input_version": self.task["input_version"]}

    def validate_draft(self, draft: dict) -> dict:
        errors = []

        def error(code, message, dimension=None):
            errors.append({"code": code, "message": message, "dimension": dimension})

        if not isinstance(draft, dict):
            return {"valid": False, "errors": [{"code": "invalid_draft", "message": "草稿须为对象", "dimension": None}]}
        if draft.get("status") != "draft":
            error("invalid_state", "生成结果只能为draft草稿")
        if draft.get("rubric_version") != VERSION or draft.get("rubric_version") != self.task["rubric_version"]:
            error("rubric_mismatch", "量表版本不一致")
        if draft.get("input_version") != self.task["input_version"]:
            error("input_mismatch", "引用不能沿用其他输入版本")
        dimensions = draft.get("dimensions")
        calculation = self.calculate_scores(dimensions)
        if not calculation["ok"]:
            for message in calculation["errors"]:
                error("invalid_dimensions", message)
            return {"valid": False, "errors": errors}
        expected_scores = {d["id"]: d["score"] for d in calculation["dimensions"]}

        def equals(value, expected):
            try:
                return type(value) in (int, float, str, Decimal) and Decimal(str(value)).is_finite() and Decimal(str(value)) == Decimal(str(expected))
            except (InvalidOperation, ValueError):
                return False

        for d in dimensions:
            dimension = d["id"]
            if not equals(d.get("score"), expected_scores[dimension]):
                error("score_mismatch", "分项得分与量表档位不符，请重新计分", dimension)
            if not isinstance(d.get("reason"), str) or not d["reason"].strip():
                error("missing_reason", "须提供具体评分理由", dimension)
            evidence = d.get("evidence")
            if not isinstance(evidence, list):
                error("invalid_evidence", "证据须为列表", dimension)
                continue
            if d["level"] == 0:
                if evidence:
                    error("missing_has_evidence", "整体缺失维度不得引用其他部分作为证据", dimension)
                if "该部分未提供" not in str(d.get("reason", "")):
                    error("missing_label", "缺失项理由须明确写该部分未提供", dimension)
            elif not evidence:
                error("missing_evidence", "非缺失维度须提供原文证据", dimension)
            for reference in evidence:
                if not isinstance(reference, dict):
                    error("invalid_evidence", "证据字段不完整", dimension)
                    continue
                quote, start, end = reference.get("quote"), reference.get("start"), reference.get("end")
                valid = isinstance(quote, str) and bool(quote) and type(start) is int and type(end) is int and 0 <= start < end <= len(self.task["text"]) and self.task["text"][start:end] == quote
                if not valid:
                    error("evidence_not_found", "引用与本次原文不一致，请重新定位", dimension)
                elif type(reference.get("paragraph")) is not int or reference["paragraph"] != self.task["text"][:start].count("\n") + 1:
                    error("paragraph_mismatch", "引用段落位置不正确", dimension)
            if type(d.get("needs_review")) is not bool or not isinstance(d.get("review_note"), str):
                error("missing_review_flag", "须提供待核查标记及具体问题字段", dimension)
            elif d["needs_review"] and not d["review_note"].strip():
                error("missing_review_note", "待核查项目须说明具体问题", dimension)
        if not equals(draft.get("total"), calculation["total"]):
            error("total_mismatch", "总分与分项精确相加结果不一致")
        if errors:
            return {"valid": False, "errors": errors}
        canonical = deepcopy(draft)
        canonical["dimensions"].sort(key=lambda d: IDS.index(d["id"]))
        for d in canonical["dimensions"]:
            d["score"] = expected_scores[d["id"]]
        canonical["total"] = calculation["total"]
        return {"valid": True, "errors": [], "draft": canonical}


def tool_schemas() -> list[dict]:
    dimension_level = {"type": "object", "properties": {"id": {"type": "string", "enum": list(IDS)}, "level": {"type": "integer", "enum": list(LEVELS)}}, "required": ["id", "level"], "additionalProperties": False}
    evidence = {"type": "object", "properties": {"quote": {"type": "string"}, "paragraph": {"type": "integer"}, "start": {"type": "integer"}, "end": {"type": "integer"}}, "required": ["quote", "paragraph", "start", "end"], "additionalProperties": False}
    dimension = {"type": "object", "properties": {**dimension_level["properties"], "score": {"type": "number"}, "reason": {"type": "string"}, "evidence": {"type": "array", "items": evidence}, "needs_review": {"type": "boolean"}, "review_note": {"type": "string"}}, "required": ["id", "level", "score", "reason", "evidence", "needs_review", "review_note"], "additionalProperties": False}
    draft = {"type": "object", "properties": {"dimensions": {"type": "array", "items": dimension}, "total": {"type": "number"}, "status": {"type": "string", "enum": ["draft"]}, "rubric_version": {"type": "string"}, "input_version": {"type": "string"}}, "required": ["dimensions", "total", "status", "rubric_version", "input_version"], "additionalProperties": False}

    def schema(name, description, properties, required):
        return {"type": "function", "function": {"name": name, "description": description, "parameters": {"type": "object", "properties": properties, "required": required, "additionalProperties": False}}}

    return [
        schema("read_rubric", "读取本次固定A—F量表；必须先获取量表依据。", {}, []),
        schema("locate_evidence", "逐字定位本次作业中的真实引用，返回Unicode字符偏移及段落。需要核查证据时调用；整体缺失可用空quote查询。", {"quote": {"type": "string"}}, ["quote"]),
        schema("calculate_scores", "对完整六维档位进行Decimal精确计分。", {"dimensions": {"type": "array", "items": dimension_level}}, ["dimensions"]),
        schema("validate_draft", "提交完整评分草稿做最后校验；错误会返回具体问题，最多2轮修正、3次校验。通过后任务立即结束。", {"draft": draft}, ["draft"]),
    ]
