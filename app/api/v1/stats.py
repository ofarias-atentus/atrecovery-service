"""Statistics router: admin definitions + permission-gated value reads.

``GET /stats/definitions`` (admin CRUD) vs ``GET /stats/{name}`` (value).
The literal ``definitions`` routes are declared first so they win over
the ``{name}`` value route.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_admin
from app.db.session import get_db
from app.models.identity import Permission, User
from app.models.stats import StatisticDefinition
from app.schemas.stats import StatDefinitionCreate, StatDefinitionRead, StatValueRead
from app.services.stats_svc import check_stat_access, fetch_external, resolve_internal

router = APIRouter()
ADMIN = require_admin()


@router.post(
    "/definitions",
    response_model=StatDefinitionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create stat definition (admin)",
)
async def create_definition(
    body: StatDefinitionCreate, db: AsyncSession = Depends(get_db), _: User = Depends(ADMIN)
) -> StatisticDefinition:
    if (
        await db.execute(select(StatisticDefinition).where(StatisticDefinition.name == body.name))
    ).scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="stat already defined")
    if (
        await db.execute(select(Permission.code).where(Permission.code == body.required_permission_code))
    ).scalar_one_or_none() is None:
        raise HTTPException(
            status_code=404, detail=f"permission not found: {body.required_permission_code}"
        )
    if body.source_type not in ("internal", "external"):
        raise HTTPException(status_code=422, detail="source_type must be internal|external")
    defn = StatisticDefinition(**body.model_dump())
    db.add(defn)
    await db.commit()
    await db.refresh(defn)
    return defn


@router.get("/definitions", response_model=list[StatDefinitionRead], summary="List stat definitions")
async def list_definitions(
    db: AsyncSession = Depends(get_db), _: User = Depends(ADMIN)
) -> list[StatisticDefinition]:
    result = await db.execute(select(StatisticDefinition).order_by(StatisticDefinition.name))
    return list(result.scalars().all())


@router.delete(
    "/definitions/{name}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete stat definition"
)
async def delete_definition(
    name: str, db: AsyncSession = Depends(get_db), _: User = Depends(ADMIN)
) -> None:
    defn = (
        await db.execute(select(StatisticDefinition).where(StatisticDefinition.name == name))
    ).scalar_one_or_none()
    if defn is None:
        raise HTTPException(status_code=404, detail="stat not defined")
    await db.delete(defn)
    await db.commit()


@router.get("/{name}", response_model=StatValueRead, summary="Read a stat value")
async def read_stat(
    name: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StatValueRead:
    defn = (
        await db.execute(
            select(StatisticDefinition).where(
                StatisticDefinition.name == name, StatisticDefinition.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()
    if defn is None:
        raise HTTPException(status_code=404, detail="stat not defined")
    params = dict(request.query_params)
    missing = [p for p in (defn.required_params or []) if p not in params]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"missing required params: {', '.join(missing)}",
        )
    await check_stat_access(db, user, defn.required_permission_code, params)
    if defn.source_type == "internal":
        value = await resolve_internal(db, (defn.query_config or {}).get("resolver", ""), params)
    else:
        value = await fetch_external(defn.query_config or {}, params)
    return StatValueRead(name=name, value=value)
