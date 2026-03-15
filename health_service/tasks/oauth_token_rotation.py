"""
OAuth Token Rotation — Background Cron

Runs every 50 minutes. Finds OAuthToken rows expiring within the next
10 minutes and proactively refreshes them. This prevents gaps in health
tracking caused by expired access tokens.

A 10-minute buffer is used because token refresh is async — we want to
guarantee the token is valid when the next webhook or polling cycle runs.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from health_service.adapters.dexcom import refresh_access_token as dexcom_refresh
from health_service.db.models import OAuthToken
from health_service.db.session import async_session_factory

logger = logging.getLogger(__name__)

REFRESH_BUFFER_MINUTES = 10


async def rotate_expiring_tokens() -> None:
    """
    Called by APScheduler. Queries all OAuthTokens expiring soon and refreshes them.
    """
    logger.info("OAuth token rotation starting.")
    expiry_threshold = datetime.utcnow() + timedelta(minutes=REFRESH_BUFFER_MINUTES)

    async with async_session_factory() as db:
        try:
            stmt = select(OAuthToken).where(OAuthToken.expires_at <= expiry_threshold)
            result = await db.execute(stmt)
            tokens = result.scalars().all()

            logger.info("Found %d tokens requiring rotation.", len(tokens))

            for token in tokens:
                await _refresh_token(token, db)

            await db.commit()
            logger.info("OAuth token rotation complete.")
        except Exception:
            await db.rollback()
            logger.exception("OAuth token rotation failed.")


async def _refresh_token(token: OAuthToken, db: AsyncSession) -> None:
    """Refresh a single token using the appropriate provider's API."""
    try:
        if token.provider == "dexcom":
            token_data = await dexcom_refresh(
                token.refresh_token_encrypted  # TODO: decrypt before use
            )
        else:
            logger.warning(
                "No refresh implementation for provider '%s', skipping.", token.provider
            )
            return

        new_expires_at = datetime.utcnow() + timedelta(seconds=token_data["expires_in"])
        token.access_token_encrypted = token_data["access_token"]  # TODO: encrypt
        if "refresh_token" in token_data:
            token.refresh_token_encrypted = token_data["refresh_token"]  # TODO: encrypt
        token.expires_at = new_expires_at

        logger.info(
            "Rotated %s token for user_id=%d, new expiry=%s",
            token.provider,
            token.user_id,
            new_expires_at.isoformat(),
        )

    except Exception:
        logger.exception(
            "Failed to rotate %s token for user_id=%d.",
            token.provider,
            token.user_id,
        )
