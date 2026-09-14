"""Catalog schemas (Pydantic v2).

The JSON structure of a template (``content``) is defined once per
category via ``template_categories.input_schema`` — templates themselves
carry no schema, they are only validated against their category.
``schema_hint`` is accepted as a deprecated alias of ``input_schema``.
"""
from datetime import datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class CategoryCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=64, examples=["python"])
    description: str | None = None
    input_schema: dict[str, Any] | None = Field(
        default=None, validation_alias=AliasChoices("input_schema", "schema_hint")
    )


class CategoryUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    description: str | None = None
    input_schema: dict[str, Any] | None = Field(
        default=None, validation_alias=AliasChoices("input_schema", "schema_hint")
    )
    is_active: bool | None = None


class CategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    name: str
    description: str | None = None
    input_schema: dict[str, Any] | None = None
    # deprecated mirror of input_schema for backward compatibility
    schema_hint: dict[str, Any] | None = None
    is_active: bool
    created_at: datetime | None = None


class TemplateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128, examples=["hello.py"])
    version: int = Field(default=1, ge=1)
    category_id: int
    content: Any = Field(examples=[{"language": "python", "source": "print('hello')"}])


class TemplateUpdate(BaseModel):
    content: Any | None = Field(default=None)
    is_active: bool | None = None


class TemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    version: int
    category_id: int
    category_name: str = ""
    content: Any
    is_active: bool
    created_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TemplateFetch(BaseModel):
    """Payload returned by GET /templates/{id}/fetch (needs template:use + use grant)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    version: int
    content: Any
