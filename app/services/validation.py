"""JSON structure validation (routines + resources + metadata).

- Routines: ``content`` JSON validated against the owning
  ``routine_categories.input_schema``.
- Resources: ``data`` JSON validated against the owning
  ``resource_types.schema``.
- Resource metadata: ``data`` JSON validated against the owning
  ``metadata_types.schema``.
All three share this helper, so structure validation works "in the same way".
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status


def validate_json_data(data: Any, schema: dict[str, Any] | None, *, label: str = "data") -> None:
    """Validate ``data`` against a JSON Schema dict; no-op when schema is None.

    Raises 422 HTTPException on validation errors, 422 on invalid schema.
    """
    if schema is None:
        return
    try:
        import jsonschema
    except ImportError as e:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="jsonschema package not installed",
        ) from e
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{label} does not match schema: {e.message}",
        ) from e
    except jsonschema.SchemaError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid schema for {label}: {e.message}",
        ) from e


def category_schema(cat: Any | None) -> dict[str, Any] | None:
    """Return the category input_schema (legacy ``schema_hint`` fallback)."""
    if cat is None:
        return None
    schema = getattr(cat, "input_schema", None)
    if schema is not None:
        return schema
    return getattr(cat, "schema_hint", None)
