"""Bulk resource import from CSV rows or equivalent JSON rows.

Single shared implementation used by the admin-only REST endpoints and the
admin UI import view, so every client gets identical validation.

Mapping (external CSV/JSON field -> domain):
- Resource.identifier + data.udid: ``device_id``
- Resource.name + data.nombre: ``device_nombre``
- Resource.resource_type: ``mobile_device``
- Resource.is_active: ``activo`` (strict boolean)
- data.plataforma: ``platform``
- data.version_plataforma: ``platform_version``
- data.descripcion: ``device_descripcion``
- data.device_ultima_actualizacion: ``device_ultima_actualizacion`` (UTC-naive)
- data.fecha_ultima_replicacion: ``fecha_ultima_replicacion`` (UTC-naive)
- ResourceMetadata (type ``monitor``):
  monitor=``monitor_id``, nodo=``nodo_id``, nombre=``nombre``,
  descripcion=``descripcion``, hostname=``hostname``, host=``replic_dbhost``,
  servidor_log=``servidor_log``, source_id=``id``

Behavior is atomic: every row is validated first; any invalid row rolls back
the whole import. Existing identifiers are updated (resource + monitor entry);
missing identifiers are created.
"""
from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import ActivityLog
from app.models.resources import MetadataType, Resource, ResourceMetadata, ResourceType
from app.services.validation import validate_json_data

REQUIRED_FIELDS = (
    "monitor_id",
    "nodo_id",
    "nombre",
    "descripcion",
    "hostname",
    "replic_dbhost",
    "servidor_log",
    "id",
    "device_id",
    "device_nombre",
    "activo",
    "device_descripcion",
    "device_ultima_actualizacion",
    "platform",
    "platform_version",
    "fecha_ultima_replicacion",
)

RESOURCE_TYPE_NAME = "mobile_device"
METADATA_TYPE_NAME = "monitor"

MAX_CSV_BYTES = 2 * 1024 * 1024
MAX_ROWS = 1000

_TRUE_VALUES = {"true", "1", "t", "yes", "y"}
_FALSE_VALUES = {"false", "0", "f", "no", "n"}


def parse_csv_text(payload: str, *, source: str = "csv") -> list[dict[str, str]]:
    """Parse CSV text into raw row dicts, enforcing header contract + limits."""
    if len(payload.encode("utf-8")) > MAX_CSV_BYTES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{source}: file exceeds {MAX_CSV_BYTES} bytes",
        )
    try:
        reader = csv.DictReader(io.StringIO(payload))
    except csv.Error as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{source}: malformed CSV: {e}",
        ) from e
    if reader.fieldnames is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{source}: missing header row",
        )
    headers = [h.strip() if h else "" for h in reader.fieldnames]
    missing = [f for f in REQUIRED_FIELDS if f not in headers]
    extra = [h for h in headers if h not in REQUIRED_FIELDS]
    if missing or extra:
        parts = []
        if missing:
            parts.append(f"missing columns: {', '.join(missing)}")
        if extra:
            parts.append(f"unexpected columns: {', '.join(extra)}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{source}: invalid header ({'; '.join(parts)})",
        )
    rows: list[dict[str, str]] = []
    try:
        for lineno, raw in enumerate(reader, start=2):
            if raw is None or all((v is None or str(v).strip() == "") for v in raw.values()):
                continue
            rows.append({k: ("" if v is None else str(v)) for k, v in raw.items()})
            if len(rows) > MAX_ROWS:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"{source}: exceeds {MAX_ROWS} rows",
                )
    except csv.Error as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{source}: malformed CSV: {e}",
        ) from e
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{source}: no data rows",
        )
    return rows


def parse_bool(value: Any, *, row: int, field: str, source: str) -> bool:
    text = str(value).strip().lower() if value is not None else ""
    if text in _TRUE_VALUES:
        return True
    if text in _FALSE_VALUES:
        return False
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"{source} row {row}: field '{field}' must be a boolean (true/false)",
    )


def parse_timestamp(value: Any, *, row: int, field: str, source: str) -> str:
    """Normalize an external timestamp to naive UTC ``YYYY-MM-DD HH:MM:SS.fff``."""
    text = str(value).strip() if value is not None else ""
    if not text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{source} row {row}: field '{field}' must not be empty",
        )
    candidate = text
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{source} row {row}: field '{field}' must be a timestamp",
        ) from e
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _require_text(
    raw: dict[str, Any], field: str, *, row: int, source: str, allow_empty: bool = False
) -> str:
    value = raw.get(field)
    text = "" if value is None else str(value).strip()
    if not allow_empty and not text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{source} row {row}: field '{field}' must not be empty",
        )
    return text


def normalize_row(raw: dict[str, Any], *, row: int, source: str) -> dict[str, Any]:
    """Validate external field presence/types and build domain payloads."""
    missing = [f for f in REQUIRED_FIELDS if f not in raw]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{source} row {row}: missing fields: {', '.join(missing)}",
        )
    device_id = _require_text(raw, "device_id", row=row, source=source)
    device_nombre = _require_text(raw, "device_nombre", row=row, source=source)
    if len(device_id) > 128 or len(device_nombre) > 128:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{source} row {row}: device_id/device_nombre exceed 128 chars",
        )
    platform = _require_text(raw, "platform", row=row, source=source)
    platform_version = _require_text(raw, "platform_version", row=row, source=source)
    device_descripcion = _require_text(
        raw, "device_descripcion", row=row, source=source, allow_empty=True
    )
    is_active = parse_bool(raw.get("activo"), row=row, field="activo", source=source)
    device_updated = parse_timestamp(
        raw.get("device_ultima_actualizacion"),
        row=row,
        field="device_ultima_actualizacion",
        source=source,
    )
    replicated_at = parse_timestamp(
        raw.get("fecha_ultima_replicacion"),
        row=row,
        field="fecha_ultima_replicacion",
        source=source,
    )
    monitor_id = _require_text(raw, "monitor_id", row=row, source=source)
    nodo_id = _require_text(raw, "nodo_id", row=row, source=source)
    nombre = _require_text(raw, "nombre", row=row, source=source, allow_empty=True)
    descripcion = _require_text(raw, "descripcion", row=row, source=source, allow_empty=True)
    hostname = _require_text(raw, "hostname", row=row, source=source)
    host = _require_text(raw, "replic_dbhost", row=row, source=source)
    servidor_log = _require_text(raw, "servidor_log", row=row, source=source)
    source_id = _require_text(raw, "id", row=row, source=source)

    data = {
        "udid": device_id,
        "nombre": device_nombre,
        "plataforma": platform,
        "version_plataforma": platform_version,
        "descripcion": device_descripcion,
        "device_ultima_actualizacion": device_updated,
        "fecha_ultima_replicacion": replicated_at,
    }
    metadata = {
        "monitor": monitor_id,
        "nodo": nodo_id,
        "nombre": nombre,
        "descripcion": descripcion,
        "hostname": hostname,
        "host": host,
        "servidor_log": servidor_log,
        "source_id": source_id,
    }
    return {
        "identifier": device_id,
        "name": device_nombre,
        "is_active": is_active,
        "data": data,
        "metadata": metadata,
    }


async def _resolve_active_type(
    db: AsyncSession, model: type[ResourceType | MetadataType], name: str, *, source: str
) -> ResourceType | MetadataType:
    obj = (
        await db.execute(select(model).where(model.name == name))  # type: ignore[attr-defined]
    ).scalar_one_or_none()
    if obj is None or not obj.is_active:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{source}: type '{name}' is missing or inactive",
        )
    return obj


async def import_rows(
    db: AsyncSession,
    rows: list[dict[str, Any]],
    *,
    source: str,
    user_id: int | None = None,
    ip: str | None = None,
) -> dict[str, Any]:
    """Validate + atomically upsert normalized rows. Rolls back on any error."""
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{source}: no data rows",
        )
    if len(rows) > MAX_ROWS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{source}: exceeds {MAX_ROWS} rows",
        )
    normalized = [normalize_row(raw, row=i + 1, source=source) for i, raw in enumerate(rows)]
    seen: set[str] = set()
    for i, item in enumerate(normalized, start=1):
        if item["identifier"] in seen:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{source} row {i}: duplicate device_id '{item['identifier']}'",
            )
        seen.add(item["identifier"])

    try:
        rtype = await _resolve_active_type(db, ResourceType, RESOURCE_TYPE_NAME, source=source)
        mtype = await _resolve_active_type(db, MetadataType, METADATA_TYPE_NAME, source=source)
        created = 0
        updated = 0
        identifiers: list[str] = []
        for i, item in enumerate(normalized, start=1):
            validate_json_data(item["data"], rtype.schema, label=f"{source} row {i} data")
            validate_json_data(
                item["metadata"], mtype.schema, label=f"{source} row {i} metadata"
            )
            resource = (
                await db.execute(
                    select(Resource).where(Resource.identifier == item["identifier"])
                )
            ).scalar_one_or_none()
            if resource is None:
                resource = Resource(
                    name=item["name"],
                    identifier=item["identifier"],
                    resource_type_id=rtype.id,
                    data=item["data"],
                    is_active=item["is_active"],
                )
                db.add(resource)
                await db.flush()
                created += 1
            else:
                resource.name = item["name"]
                resource.resource_type_id = rtype.id
                resource.data = item["data"]
                resource.is_active = item["is_active"]
                updated += 1
            link = (
                await db.execute(
                    select(ResourceMetadata).where(
                        ResourceMetadata.resource_id == resource.id,
                        ResourceMetadata.metadata_type_id == mtype.id,
                    )
                )
            ).scalar_one_or_none()
            if link is None:
                db.add(
                    ResourceMetadata(
                        resource_id=resource.id,
                        metadata_type_id=mtype.id,
                        data=item["metadata"],
                    )
                )
            else:
                link.data = item["metadata"]
            identifiers.append(item["identifier"])
        db.add(
            ActivityLog(
                action="resource.imported",
                user_id=user_id,
                entity_type="resource",
                entity_id=None,
                meta={"source": source, "created": created, "updated": updated},
                ip=ip,
            )
        )
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    return {"created": created, "updated": updated, "total": len(normalized), "identifiers": identifiers}
