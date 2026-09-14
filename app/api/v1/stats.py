"""Statistics router: admin definitions + grant-gated value reads.

``GET /stats/definitions`` (admin CRUD) vs ``GET /stats/{name}`` (value).
The literal ``definitions`` and ``grants`` routes are declared first so they
win over the ``{name}`` value route.

Access: no permission codes. Each statistic needs a StatisticGrant row for
the calling user directly or via one of their roles (different users/roles
can see different statistics). Superusers bypass. ``user_id``-scoped stats
additionally require ownership unless caller holds ``admin:manage``.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_admin
from app.db.session import get_db
from app.models.identity import Role, User
from app.models.stats import StatisticDefinition, StatisticGrant
from app.schemas.stats import (
    StatDefinitionCreate,
    StatDefinitionRead,
    StatGrantCreate,
    StatGrantRead,
    StatValueRead,
)
from app.services.activity import GRANT_CHANGED, client_ip, log_activity
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


async def _check_stat_principal(db: AsyncSession, principal_type: str, principal_id: int) -> None:
    model = {"user": User, "role": Role}[principal_type]
    exists = (
        await db.execute(select(model.id).where(model.id == principal_id))
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(
            status_code=404, detail=f"{principal_type} {principal_id} not found"
        )


@router.post(
    "/grants",
    response_model=StatGrantRead,
    status_code=status.HTTP_201_CREATED,
    summary="Grant statistic access to a user/role (admin)",
)
async def create_stat_grant(
    body: StatGrantCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(ADMIN),
) -> StatisticGrant:
    if (
        await db.execute(select(StatisticDefinition.id).where(StatisticDefinition.id == body.statistic_id))
    ).scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="statistic not found")
    await _check_stat_principal(db, body.principal_type, body.principal_id)
    dup = await db.execute(
        select(StatisticGrant).where(
            StatisticGrant.statistic_id == body.statistic_id,
            StatisticGrant.principal_type == body.principal_type,
            StatisticGrant.principal_id == body.principal_id,
        )
    )
    if dup.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="grant already exists")
    g = StatisticGrant(**body.model_dump())
    db.add(g)
    await db.commit()
    await db.refresh(g)
    await log_activity(
        db, action=GRANT_CHANGED, user_id=user.id,
        entity_type="statistic_grant", entity_id=g.id,
        meta={"op": "created", "statistic_id": g.statistic_id,
              "principal_type": g.principal_type, "principal_id": g.principal_id},
        ip=client_ip(request),
    )
    return g


@router.get("/grants", response_model=list[StatGrantRead], summary="List statistic grants (admin)")
async def list_stat_grants(
    statistic_id: int | None = None,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(ADMIN),
) -> list[StatisticGrant]:
    stmt = select(StatisticGrant).order_by(StatisticGrant.id)
    if statistic_id is not None:
        stmt = stmt.where(StatisticGrant.statistic_id == statistic_id)
    return list((await db.execute(stmt.limit(limit).offset(offset))).scalars().all())


@router.delete(
    "/grants/{grant_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete statistic grant"
)
async def delete_stat_grant(
    grant_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(ADMIN),
) -> None:
    g = (await db.execute(select(StatisticGrant).where(StatisticGrant.id == grant_id))).scalar_one_or_none()
    if g is None:
        raise HTTPException(status_code=404, detail="grant not found")
    meta = {"op": "deleted", "statistic_id": g.statistic_id,
            "principal_type": g.principal_type, "principal_id": g.principal_id}
    await db.delete(g)
    await db.commit()
    await log_activity(
        db, action=GRANT_CHANGED, user_id=user.id,
        entity_type="statistic_grant", entity_id=grant_id, meta=meta, ip=client_ip(request),
    )


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
    await check_stat_access(db, user, defn.id, params)
    if defn.source_type == "internal":
        value = await resolve_internal(db, (defn.query_config or {}).get("resolver", ""), params)
    else:
        value = await fetch_external(defn.query_config or {}, params)
    return StatValueRead(name=name, value=value)
