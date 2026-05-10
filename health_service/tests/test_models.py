"""
Phase 1 sanity checks for the encrypted-at-rest schema.

These tests inspect SQLAlchemy metadata only — no DB spin-up. End-to-end
round-trip with Postgres is exercised in the final verification phase via
the testcontainers fixture (and the `alembic upgrade head` smoke check).
"""

from __future__ import annotations

import pytest

from health_service.core.crypto import EncryptedString
from health_service.db.models import (
    Base,
    DeviceAttestation,
    OAuthToken,
    RewardOutbox,
    User,
)


class TestUserModel:
    def test_email_encrypted_uses_encrypted_string(self):
        col = User.__table__.c["email_encrypted"]
        # The column itself appears as a TypeDecorator at the SQLA layer.
        assert isinstance(col.type, EncryptedString)

    def test_email_lookup_hash_is_unique_indexed(self):
        col = User.__table__.c["email_lookup_hash"]
        assert col.unique is True
        # The column is also marked index=True (separate from the unique index).
        assert col.index is True

    def test_email_encrypted_is_not_unique(self):
        # Fernet ciphertext is non-deterministic; uniqueness on it would be
        # technically enforced but never collide. Uniqueness must move to the hash.
        col = User.__table__.c["email_encrypted"]
        assert col.unique is None or col.unique is False

    def test_timezone_default_utc(self):
        col = User.__table__.c["timezone"]
        # The default is "UTC" — used by the daily-cap fix in Phase 6.
        assert col.default.arg == "UTC"


class TestOAuthTokenModel:
    def test_provider_user_id_unencrypted_indexed(self):
        col = OAuthToken.__table__.c["provider_user_id"]
        # Must NOT be EncryptedString — webhook lookups need an indexed
        # equality match, which doesn't work against non-deterministic ciphertext.
        assert not isinstance(col.type, EncryptedString)
        assert col.index is True

    def test_access_and_refresh_tokens_encrypted(self):
        for col_name in ("access_token_encrypted", "refresh_token_encrypted"):
            col = OAuthToken.__table__.c[col_name]
            assert isinstance(col.type, EncryptedString)

    def test_uq_provider_user_constraint(self):
        constraint_names = {c.name for c in OAuthToken.__table__.constraints}
        assert "uq_provider_user" in constraint_names
        assert "uq_user_provider" in constraint_names


class TestEncryptedColumnsCoverage:
    """Every column whose name ends in `_encrypted` must use EncryptedString."""

    def test_no_plaintext_in_encrypted_columns(self):
        offenders: list[str] = []
        for table in Base.metadata.tables.values():
            for col in table.columns:
                if col.name.endswith("_encrypted") and not isinstance(col.type, EncryptedString):
                    offenders.append(f"{table.name}.{col.name}")
        assert offenders == [], (
            f"These columns are named *_encrypted but use a plaintext type: {offenders}"
        )


class TestNewTablesPresent:
    def test_device_attestations_table(self):
        assert "device_attestations" in Base.metadata.tables
        cols = {c.name for c in DeviceAttestation.__table__.columns}
        assert {"user_id", "manufacturer", "device_id", "hmac_key_encrypted"} <= cols

    def test_reward_outbox_table(self):
        assert "reward_outbox" in Base.metadata.tables
        cols = {c.name for c in RewardOutbox.__table__.columns}
        assert {"idempotency_key", "event_type", "payload_json", "published_at"} <= cols

    def test_reward_outbox_idempotency_key_unique(self):
        col = RewardOutbox.__table__.c["idempotency_key"]
        assert col.unique is True
