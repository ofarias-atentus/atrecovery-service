"""Catalog schemas (Pydantic v2)."""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64, examples=["python"])
    description: str | None = None
    schema_hint: dict[str, Any] | None = None


class CategoryUpdate(BaseModel):
    description: str | None = None
    schema_hint: dict[str, Any] | None = None
    is_active: bool | None = None


class CategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    schema_hint: dict[str, Any] | None = None
    is_active: bool
    created_at: datetime | None = None


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128, examples=["hello.py"])
    version: int = Field(default=1, ge=1)
    category_id: int
    content: str = Field(min_length=1, examples=["print('hello')"])
    input_schema: dict[str, Any] | None = None


class TemplateUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1)
    input_schema: dict[str, Any] | None = None
    is_active: bool | None = None


class TemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    version: int
    category_id: int
    category_name: str = ""
    content: str
    input_schema: dict[str, Any] | None = None
    is_active: bool
    created_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
