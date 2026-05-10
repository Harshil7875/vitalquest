"""
SQLAlchemy ORM models for the Health Vault (PostgreSQL).

This is the ONLY service with access to these tables. The game_service
container does not receive the POSTGRES_DSN environment variable.

Encrypted columns use the `EncryptedString` TypeDecorator from
`health_service.core.crypto`, which transparently encrypts on bind and
decrypts on read. ORM users always see plaintext; raw `SELECT` returns
ciphertext. The column suffix `_encrypted` is preserved so the storage
contract is visible at the SQL boundary.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from health_service.core.crypto import EncryptedString


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # Encrypted at rest via EncryptedString. The unique constraint moves to
    # email_lookup_hash because Fernet ciphertext is non-deterministic — two
    # encryptions of the same email produce different tokens, so a UNIQUE on
    # email_encrypted would be enforced but never collide.
    email_encrypted: Mapped[str] = mapped_column(EncryptedString(), nullable=False)
    # Deterministic HMAC-SHA256 of the lowercased email. Used for indexed
    # lookup and uniqueness — see core/crypto.lookup_hash.
    email_lookup_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    hashed_password: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(
        Enum("free", "pro", "admin", name="user_role"), nullable=False, default="free"
    )
    # IANA timezone (e.g. "America/Los_Angeles"). Default "UTC" preserves the
    # legacy behavior; the daily-cap fix in Phase 6 reads this column.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    guild_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    guild_status: Mapped[str] = mapped_column(
        Enum("active", "resting", "kick_eligible", name="guild_member_status"),
        default="active",
    )

    goals: Mapped[list["UserGoal"]] = relationship("UserGoal", back_populates="user")
    biometric_logs: Mapped[list["BiometricLog"]] = relationship(
        "BiometricLog", back_populates="user"
    )
    mana_ledger: Mapped[list["ManaLedger"]] = relationship(
        "ManaLedger", back_populates="user"
    )


class BiometricLog(Base):
    """
    Raw health payload storage. This table never leaves the Health Vault.
    Values here are the actual medical metrics (steps, glucose readings, etc.).
    """

    __tablename__ = "biometric_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    data_type: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    source_manufacturer: Mapped[str] = mapped_column(String(64), nullable=False)
    hardware_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    quarantined: Mapped[bool] = mapped_column(Boolean, default=False)
    clinical_log_only: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship("User", back_populates="biometric_logs")


class UserGoal(Base):
    __tablename__ = "user_goals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    data_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    mana_reward: Mapped[int] = mapped_column(Integer, default=50)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship("User", back_populates="goals")


class ManaLedger(Base):
    """
    Immutable append-only record of every reward event issued by this service.
    """

    __tablename__ = "mana_ledger"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_mana_idempotency"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    awarded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship("User", back_populates="mana_ledger")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    detail_json_encrypted: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DeletionRequest(Base):
    __tablename__ = "deletion_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # user_id is anonymized (replaced with hash) when the cascade completes
    # in clinical.py — keeping the column nullable to support that.
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("pending", "processing", "completed", name="deletion_status"),
        default="pending",
    )


class OAuthToken(Base):
    """
    OAuth 2.0 tokens for cloud-to-cloud device integrations (Dexcom, Oura, Fitbit).

    `provider_user_id` is the upstream provider's stable identifier for the
    user (e.g. Dexcom's patientId). It is stored UNENCRYPTED and indexed so
    webhook lookups can resolve a payload's provider_user_id back to the
    correct VitalQuest user_id without scanning every row.
    """

    __tablename__ = "oauth_tokens"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_user_provider"),
        UniqueConstraint("provider", "provider_user_id", name="uq_provider_user"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    provider: Mapped[str] = mapped_column(
        Enum("dexcom", "oura", "fitbit", "withings", name="oauth_provider"), nullable=False
    )
    # NOT encrypted — needs to be indexed for webhook user resolution.
    provider_user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    access_token_encrypted: Mapped[str] = mapped_column(EncryptedString(), nullable=False)
    refresh_token_encrypted: Mapped[str] = mapped_column(EncryptedString(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    scope: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class DeviceToken(Base):
    """Push notification device tokens (APNs/FCM)."""

    __tablename__ = "device_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    token: Mapped[str] = mapped_column(String(512), nullable=False)
    platform: Mapped[str] = mapped_column(
        Enum("apns", "fcm", name="device_platform"), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DeviceAttestation(Base):
    """
    Per-device HMAC keys used by HardwareVerificationRule (Phase 3 / fix #6).

    Each row holds the symmetric key shared between the VitalQuest mobile app
    and this service, used to sign biometric payloads on the device. The key
    itself is encrypted at rest. Provisioning (rotation, initial enrollment)
    is intentionally out of scope here — the table just has to exist so the
    anti-cheat pipeline can resolve `(user_id, manufacturer, device_id)` to
    a key.
    """

    __tablename__ = "device_attestations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    manufacturer: Mapped[str] = mapped_column(String(64), nullable=False)
    device_id: Mapped[str] = mapped_column(String(128), nullable=False)
    hmac_key_encrypted: Mapped[str] = mapped_column(EncryptedString(), nullable=False)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# Partial unique index — uniqueness only applies to ACTIVE attestations
# (revoked_at IS NULL). After soft-revoke, the row stays for audit but no
# longer blocks a fresh enrollment of the same (user, manufacturer, device).
Index(
    "uq_active_device_attestation",
    DeviceAttestation.user_id,
    DeviceAttestation.manufacturer,
    DeviceAttestation.device_id,
    unique=True,
    postgresql_where=DeviceAttestation.revoked_at.is_(None),
)


class DeadLetterPayload(Base):
    __tablename__ = "dead_letter_payloads"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_body_encrypted: Mapped[str] = mapped_column(EncryptedString(), nullable=False)
    failed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)


class Guild(Base):
    __tablename__ = "guilds"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    invite_code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )
    member_cap: Mapped[int] = mapped_column(Integer, default=50)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RewardOutbox(Base):
    """
    Transactional outbox for the Phase 5 publish-after-commit pattern.

    `publish_event(...)` writes a row here inside the same transaction as the
    ManaLedger insert. A background task drains unpublished rows by writing
    to the Redis Stream (`health.rewards`), then sets `published_at`. This
    guarantees that a published reward is always backed by a committed
    Postgres row — no more "ghost" awards from a Redis publish that happens
    before the surrounding transaction rolls back.
    """

    __tablename__ = "reward_outbox"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    idempotency_key: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)


# Composite index for the drain task's "unpublished, oldest first" query.
Index(
    "ix_reward_outbox_unpublished",
    RewardOutbox.created_at,
    postgresql_where=RewardOutbox.published_at.is_(None),
)
