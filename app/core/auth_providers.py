"""Pluggable authentication providers (Stage 1).

Add new login systems (OAuth2/OIDC, business SSO) by subclassing
``AuthProvider`` and registering in ``PROVIDERS`` — routers stay unchanged.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_password
from app.models.identity import AuthIdentity, User


class AuthProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def authenticate(self, db: AsyncSession, username: str, password: str) -> User | None:
        """Return the user on success, None on failure."""
        raise NotImplementedError


class LocalProvider(AuthProvider):
    name = "local"

    async def authenticate(self, db: AsyncSession, username: str, password: str) -> User | None:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if user is None or not user.is_active:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user


class BusinessSSOProvider(AuthProvider):
    """Stub for a business-specific SSO / custom auth system.

    Stage 1 only defines the interface. A real implementation would:
      1. redirect to the corporate IdP (get_authorization_url),
      2. exchange the code for the provider subject in the callback router,
      3. link via link_identity() below.
    """

    name = "business_sso"

    async def authenticate(self, db: AsyncSession, username: str, password: str) -> User | None:
        raise NotImplementedError("BusinessSSOProvider not configured for this PoC")

    def get_authorization_url(self) -> str:
        raise NotImplementedError("BusinessSSOProvider not configured for this PoC")

    async def link_identity(
        self, db: AsyncSession, user: User, provider_sub: str, extra: dict | None = None
    ) -> AuthIdentity:
        identity = AuthIdentity(
            user_id=user.id, provider=self.name, provider_sub=provider_sub, extra=extra
        )
        db.add(identity)
        await db.flush()
        return identity


PROVIDERS: dict[str, AuthProvider] = {
    "local": LocalProvider(),
    "business_sso": BusinessSSOProvider(),
}
