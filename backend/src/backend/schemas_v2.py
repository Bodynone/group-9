"""Versioned teacher-authored definitions; scores never use binary arithmetic."""

from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import re

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt


class V2Error(Exception):
    def __init__(self, code, message, status=409, fields=None):
        self.code, self.message, self.status, self.fields = code, message, status, fields


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def money(value):
    return str(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def definition_check(body):
    """Reject unsafe structures; incomplete semantic drafts remain editable."""
    if not isinstance(body, dict) or set(body) != {"title", "total_score", "levels", "dimensions"}:
        raise V2Error("RUBRIC_INVALID", "量表须包含 title、total_score、levels、dimensions", 422)
    try:
        result = json.loads(canonical(body))
    except (TypeError, ValueError):
        raise V2Error("RUBRIC_INVALID", "配置不能包含非有限数值或不可解析对象", 422) from None
    errors = []

    def text(value, field, required=True):
        if not isinstance(value, str) or len(value) > 10000:
            raise V2Error("RUBRIC_INVALID", field + "须为不超过10000字符的文本", 422)
        if required and not value.strip():
            errors.append({"field": field, "message": "不能为空"})

    def number(value, field, maximum):
        if not isinstance(value, str) or not re.fullmatch(r"\d{1,3}(?:\.\d{1,2})?", value):
            raise V2Error("RUBRIC_INVALID", field + "须为最多两位小数的十进制字符串", 422)
        amount = Decimal(value)
        if amount > maximum:
            raise V2Error("RUBRIC_INVALID", field + "超出范围", 422)
        return money(amount)

    text(result["title"], "title")
    result["total_score"] = number(result["total_score"], "total_score", 100)
    if result["total_score"] != "100.00":
        errors.append({"field": "total_score", "message": "满分必须为100.00"})
    levels, dimensions = result["levels"], result["dimensions"]
    if not isinstance(levels, list) or not 2 <= len(levels) <= 8:
        raise V2Error("RUBRIC_INVALID", "档位数量须为2至8个", 422)
    if not isinstance(dimensions, list) or not 1 <= len(dimensions) <= 12:
        raise V2Error("RUBRIC_INVALID", "维度数量须为1至12个", 422)

    def identifiers(items, fields):
        ids = []
        for item in items:
            if not isinstance(item, dict) or set(item) != fields:
                raise V2Error("RUBRIC_INVALID", "配置对象字段不完整或包含未知字段", 422)
            identifier = item["id"]
            if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", identifier):
                raise V2Error("RUBRIC_INVALID", "ID须以字母开头，只含字母、数字、下划线或连字符", 422)
            ids.append(identifier)
        if len(set(ids)) != len(ids):
            raise V2Error("RUBRIC_INVALID", "配置ID不能重复", 422)
        return ids

    level_ids = identifiers(levels, {"id", "label", "percent"})
    identifiers(dimensions, {"id", "name", "description", "max_score", "criteria"})
    for level in levels:
        text(level["label"], "levels.label")
        level["percent"] = number(level["percent"], "levels.percent", 100)
    percentages = [level["percent"] for level in levels]
    if len(set(percentages)) != len(percentages) or not {"0.00", "100.00"}.issubset(percentages):
        raise V2Error("RUBRIC_INVALID", "档位比例须互异且包含0和100", 422)
    for dimension in dimensions:
        text(dimension["name"], "dimensions.name")
        text(dimension["description"], "dimensions.description")
        dimension["max_score"] = number(dimension["max_score"], "dimensions.max_score", 100)
        if Decimal(dimension["max_score"]) <= 0:
            raise V2Error("RUBRIC_INVALID", "各维满分须大于0", 422)
        criteria = dimension["criteria"]
        if not isinstance(criteria, dict) or set(criteria) - set(level_ids):
            raise V2Error("RUBRIC_INVALID", "判据只能引用本量表档位", 422)
        for key in level_ids:
            text(criteria.setdefault(key, ""), f"{dimension['id']}.criteria.{key}")
    total = money(sum((Decimal(d["max_score"]) for d in dimensions), Decimal(0)))
    if total != "100.00":
        errors.append({"field": "dimensions", "message": "各维满分之和须等于100.00"})
    return result, {"publishable": not errors, "field_errors": errors, "total_score": total}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CourseCreate(StrictModel):
    name: str = Field(min_length=1, max_length=200)


class RubricCreate(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    source_version_id: str | None = None


class VersionCopy(StrictModel):
    source_version_id: str


class Revision(StrictModel):
    expected_revision: StrictInt = Field(ge=1)


class DefinitionUpdate(Revision):
    definition: dict


class AssignmentCreate(StrictModel):
    course_id: str
    title: str = Field(min_length=1, max_length=200)
    instructions: str = Field(min_length=1, max_length=10000)
    reference_text: str = Field(default="", max_length=10000)
    rubric_version_id: str


class AssignmentUpdate(Revision):
    title: str = Field(min_length=1, max_length=200)
    instructions: str = Field(min_length=1, max_length=10000)
    reference_text: str = Field(default="", max_length=10000)
    rubric_version_id: str


class Submission(StrictModel):
    submission_label: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=50000)


class TaskCreate(Submission):
    assignment_id: str


class BatchFile(Submission):
    filename: str = Field(min_length=1, max_length=200)


class BatchCreate(StrictModel):
    assignment_id: str
    name: str = Field(min_length=1, max_length=200)
    files: list[BatchFile] = Field(min_length=1, max_length=40)


class Versions(StrictModel):
    input_version: str
    rubric_hash: str
    context_hash: str
    expected_review_revision: StrictInt = Field(ge=0)


class ReviewDimension(StrictModel):
    dimension_id: str
    level_id: str
    reason: str = Field(min_length=1, max_length=10000)
    reviewed: StrictBool


class ReviewUpdate(Versions):
    dimensions: list[ReviewDimension] = Field(min_length=1, max_length=12)
