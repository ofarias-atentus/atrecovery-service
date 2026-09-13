"""Auth router: OAuth2 password login, refresh, self profile, provider stub."""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_providers import PROVIDERS
from app.core.deps import get_current_user, get_user_permissions
from app.core.security import TokenError, create_access_token, create_refresh_token, decode_token
from app.db.session import get_db
from app.models.identity import User
from app.schemas.identity import MeRead, RefreshRequest, Token

router = APIRouter()


def _issue(user: User) -> Token:
    sub = str(user.id)
    return Token(access_token=create_access_token(sub), refresh_token=create_refresh_token(sub))


@router.post("/token", response_model=Token, summary="OAuth2 password login")
async def login(
    form: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)
) -> Token:
    provider = PROVIDERS["local"]
    user = await provider.authenticate(db, form.username, form.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="incorrect username or password"
        )
    return _issue(user)


@router.post("/refresh", response_model=Token, summary="Rotate tokens with a refresh token")
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)) -> Token:
    from sqlalchemy import select

    try:
        payload = decode_token(body.refresh_token, expected_type="refresh")
    except TokenError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)) from e
    result = await db.execute(select(User).where(User.id == int(payload["sub"])))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
    return _issue(user)


@router.get("/me", response_model=MeRead, summary="Current user profile")
async def me(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> MeRead:
    perms = await get_user_permissions(db, user)
    return MeRead(
        id=user.id,
        username=user.username,
        email=user.email,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        roles=[r.name for r in user.roles],
        created_at=user.created_at,
        permissions=sorted(perms),
    )


@router.get("/{provider}/callback", summary="External/custom provider callback (stub)")
async def provider_callback(provider: str) -> dict[str, str]:
    if provider == "local":
        return {"detail": "local provider uses POST /token, no callback needed"}
    if provider not in PROVIDERS:
        raise HTTPException(status_code=404, detail=f"unknown provider: {provider}")
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"{provider} callback not configured — implement in core/auth_providers.py",
    )
