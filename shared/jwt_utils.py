"""
JWT utilities shared by both health_service and game_service.
Both services validate tokens independently using the same secret.
"""

from __future__ import annotations

import os
import time
from typing import Optional

from jose import JWTError, jwt

from shared.schemas import TokenPayload

_SECRET = os.environ.get("JWT_SECRET", "")
_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
_ACCESS_TOKEN_EXPIRE_SECONDS = 60 * 60 * 24  # 24 hours


def create_access_token(user_id: int, role: str) -> str:
    payload = {
        "user_id": user_id,
        "role": role,
        "exp": int(time.time()) + _ACCESS_TOKEN_EXPIRE_SECONDS,
    }
    return jwt.encode(payload, _SECRET, algorithm=_ALGORITHM)


def verify_token(token: str) -> Optional[TokenPayload]:
    """Returns TokenPayload on success, None on any failure."""
    try:
        data = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])
        return TokenPayload(**data)
    except (JWTError, Exception):
        return None
