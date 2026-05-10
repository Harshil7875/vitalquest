"""
OAuth 2.0 state-parameter management.

Mints a server-stored nonce when a user starts an OAuth flow, then verifies
it on the callback to prevent CSRF on token binding (audit finding #3).

Storage: Redis key `oauth_state:{nonce}` → str(user_id), TTL 10 minutes.
Verification uses GETDEL so a state can be redeemed exactly once.
"""

from __future__ import annotations

import logging
import secrets

from health_service.publisher.redis_publisher import get_redis

logger = logging.getLogger(__name__)

STATE_TTL_SECONDS = 600  # 10 minutes — long enough for an OAuth dance, short enough to limit replay
STATE_KEY_PREFIX = "oauth_state:"


def _key(nonce: str) -> str:
    return f"{STATE_KEY_PREFIX}{nonce}"


async def mint_state(user_id: int) -> str:
    """
    Generate a fresh nonce, persist `nonce → user_id` in Redis with TTL,
    and return the nonce. Caller passes the nonce to the OAuth provider as
    the `state` parameter; the callback handler then redeems it via verify_state.
    """
    nonce = secrets.token_urlsafe(32)
    redis = await get_redis()
    await redis.set(_key(nonce), str(user_id), ex=STATE_TTL_SECONDS)
    logger.debug("Minted oauth state for user_id=%d", user_id)
    return nonce


async def verify_state(nonce: str, expected_user_id: int) -> bool:
    """
    Atomically read-and-delete the state, then verify it belongs to the
    expected user. Returns False on any failure (missing, expired, wrong user)
    so the caller can return a single 400 response without leaking which
    branch failed.

    GETDEL is atomic in Redis 6.2+; the value is consumed even on mismatch
    so a leaked state cannot be replayed against a different user.
    """
    redis = await get_redis()
    stored = await redis.getdel(_key(nonce))
    if stored is None:
        logger.warning("OAuth state verification failed: missing or expired.")
        return False
    if stored != str(expected_user_id):
        logger.warning(
            "OAuth state verification failed: state belongs to a different user."
        )
        return False
    return True
