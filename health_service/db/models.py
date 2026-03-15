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
