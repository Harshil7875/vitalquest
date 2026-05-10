"""
Game Service Configuration

Note: There is intentionally NO postgres_dsn field here.
The game service cannot access the Health Vault database.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    redis_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
