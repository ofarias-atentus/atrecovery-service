"""JSON structure validation (templates + resources).

Both templates (``content`` JSON validated against ``input_schema`` or the
category ``schema_hint``) and resources (``data`` JSON validated against the
resource-type ``schema``) share this helper, so structure validation works
"in the same way" for both domains.
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


def effective_template_schema(
    input_schema: dict[str, Any] | None,
    category_schema_hint: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Template structure rule: per-template ``input_schema`` wins, else category hint."""
    return input_schema if input_schema is not None else category_schema_hint
