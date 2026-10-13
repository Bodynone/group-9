from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .rubric import VERSION


class CreateTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)
    rubric_version: str = VERSION

    @field_validator("text")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("请粘贴非空的匿名作业文本")
        return value


class ReviewDimension(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Literal["A", "B", "C", "D", "E", "F"]
    level: Literal[100, 70, 30, 0]
    reason: str = Field(min_length=1)
    reviewed: bool

    @field_validator("level", mode="before")
    @classmethod
    def integer_level(cls, value):
        if type(value) is not int:
            raise ValueError("档位必须为100、70、30或0")
        return value

    @field_validator("reason")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("请填写评分理由")
        return value


class UpdateReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_version: str
    dimensions: list[ReviewDimension] = Field(min_length=6, max_length=6)

    @field_validator("dimensions")
    @classmethod
    def unique_dimensions(cls, value):
        if len({item.id for item in value}) != 6:
            raise ValueError("A—F六维须各出现一次")
        return value
