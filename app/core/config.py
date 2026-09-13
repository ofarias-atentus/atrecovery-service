"""Central application configuration (Pydantic Settings).

All secrets/URLs come from environment (.env supported).
Stage 0 only: no auth model imports here to avoid circulars.
"""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "template-mgmt-poc"
    APP_VERSION: str = "0.1.0"
    ENV: str = "dev"

    DATABASE_URL: str = "sqlite+aiosqlite:///./data/app.db"

    JWT_SECRET: str = "dev-only-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:8000"]
    LOG_LEVEL: str = "INFO"

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _parse_cors(cls, v: object) -> list[str]:
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("["):
                import json

                try:
                    parsed = json.loads(s)
                    if isinstance(parsed, list):
                        return [str(x) for x in parsed]
                except ValueError:
                    pass
            return [x.strip() for x in s.split(",") if x.strip()]
        return v  # type: ignore[return-value]


@lru_cache
def get_settings() -> Settings:
    return Settings()
