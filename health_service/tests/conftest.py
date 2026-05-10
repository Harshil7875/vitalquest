"""
pytest fixtures shared by all health_service tests.

Sets a deterministic ENCRYPTION_KEY before any health_service module imports,
so crypto helpers can initialize at import time. Settings is a pydantic
BaseSettings so we patch via os.environ before the first import.
"""

from __future__ import annotations

import os

# Deterministic Fernet key for tests. Generated once with Fernet.generate_key().
# DO NOT use this value in production — it's checked into source intentionally.
_TEST_FERNET_KEY = "lT8O3cZcTQiPKZ8X7n_2Nf4VrM6_p4rcOX6EmUqJtJ8="

os.environ.setdefault("ENCRYPTION_KEY", _TEST_FERNET_KEY)
# Unit tests don't actually connect — POSTGRES_DSN just needs to satisfy
# Settings validation and SQLAlchemy engine construction. sqlite+aiosqlite
# avoids requiring asyncpg, which has no Python 3.14 wheels yet.
# Production (Python 3.12 in Docker) uses postgresql+asyncpg via .env.
os.environ.setdefault(
    "POSTGRES_DSN", "sqlite+aiosqlite:///:memory:"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-at-least-32-characters-long")
