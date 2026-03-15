"""
SQLAlchemy ORM models for the Health Vault (PostgreSQL).

This is the ONLY service with access to these tables. The game_service
container does not receive the POSTGRES_DSN environment variable.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # email stored encrypted at application layer (sqlalchemy-utils EncryptedType
    # in production; plain string here for clarity — encrypt before INSERT)
    email_encrypted: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(
        Enum("free", "pro", "admin", name="user_role"), nullable=False, default="free"
    )
    guild_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Grace Protocol fields (v1.6)
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
    data_type: Mapped[str] = mapped_column(String(64), nullable=False)  # "steps", "glucose", etc.
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
    """
    The user's prescribed health target. Compared against BiometricLog values
    by goal_evaluator.py to determine whether a reward event should be issued.
    """

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
    The idempotency_key prevents double-awarding on retries.
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
    """
    Security and compliance event log. detail_json is encrypted at rest.
    Used for quarantine flags, manual entry attempts, and rule violations.
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    detail_json_encrypted: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DeletionRequest(Base):
    """Tracks Right to Erasure workflow state."""

    __tablename__ = "deletion_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("pending", "processing", "completed", name="deletion_status"),
        default="pending",
    )


class OAuthToken(Base):
    """
    Stores OAuth 2.0 tokens for cloud-to-cloud device integrations (Dexcom, Oura, Fitbit).
    Tokens are encrypted at rest. The refresh_token is used to rotate access_tokens
    before they expire via the oauth_token_rotation cron job.
    """

    __tablename__ = "oauth_tokens"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_user_provider"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    provider: Mapped[str] = mapped_column(
        Enum("dexcom", "oura", "fitbit", "withings", name="oauth_provider"), nullable=False
    )
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    scope: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class DeviceToken(Base):
    """
    Push notification device tokens (APNs/FCM).
    Stored in health_service Postgres — not game_service — to stay within the PHI boundary
    (device tokens are PII). The notification_worker reads these via the Redis queue,
    never directly from this table.
    """

    __tablename__ = "device_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    token: Mapped[str] = mapped_column(String(512), nullable=False)
    platform: Mapped[str] = mapped_column(
        Enum("apns", "fcm", name="device_platform"), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DeadLetterPayload(Base):
    """
    Failed webhook/adapter payloads quarantined for engineering review.
    Ensures no patient data is permanently lost due to a parsing error.
    """

    __tablename__ = "dead_letter_payloads"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_body_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    failed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)


class Guild(Base):
    """
    Guild membership authority. Only the health_service knows which users
    belong to which guild (for nightly aggregation). The game_service
    references guild_id as an opaque integer.
    """

    __tablename__ = "guilds"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    invite_code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )
    member_cap: Mapped[int] = mapped_column(Integer, default=50)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
