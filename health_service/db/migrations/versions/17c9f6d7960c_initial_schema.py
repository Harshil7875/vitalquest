"""initial_schema

Revision ID: 17c9f6d7960c
Revises:
Create Date: 2026-03-15 04:48:07.874324

Squashed for the Critical+High remediation. The repository is pre-launch with
no real users, so a single migration that reflects the post-remediation schema
is preferable to a chain that walks through known-broken intermediate states
(plaintext PHI, missing provider_user_id, etc.). Wipe and re-`alembic upgrade head`
on a fresh database.

Encrypted columns are declared as `Text` at the SQL layer because the ORM-side
EncryptedString TypeDecorator transparently encrypts/decrypts; ciphertext can
exceed any reasonable String(N) bound.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '17c9f6d7960c'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('email_encrypted', sa.Text(), nullable=False),
        sa.Column('email_lookup_hash', sa.String(length=64), nullable=False),
        sa.Column('hashed_password', sa.String(length=256), nullable=False),
        sa.Column(
            'role',
            sa.Enum('free', 'pro', 'admin', name='user_role'),
            nullable=False,
        ),
        sa.Column('timezone', sa.String(length=64), nullable=False, server_default='UTC'),
        sa.Column('guild_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('last_login_at', sa.DateTime(), nullable=True),
        sa.Column(
            'guild_status',
            sa.Enum('active', 'resting', 'kick_eligible', name='guild_member_status'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email_lookup_hash'),
    )
    op.create_index(
        'ix_users_email_lookup_hash', 'users', ['email_lookup_hash'], unique=False
    )

    op.create_table(
        'biometric_logs',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('data_type', sa.String(length=64), nullable=False),
        sa.Column('value', sa.Float(), nullable=False),
        sa.Column('unit', sa.String(length=32), nullable=False),
        sa.Column('recorded_at', sa.DateTime(), nullable=False),
        sa.Column('source_manufacturer', sa.String(length=64), nullable=False),
        sa.Column('hardware_verified', sa.Boolean(), nullable=False),
        sa.Column('quarantined', sa.Boolean(), nullable=False),
        sa.Column('clinical_log_only', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'user_goals',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('data_type', sa.String(length=64), nullable=False),
        sa.Column('target_value', sa.Float(), nullable=False),
        sa.Column('unit', sa.String(length=32), nullable=False),
        sa.Column('mana_reward', sa.Integer(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'mana_ledger',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('amount', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(length=64), nullable=False),
        sa.Column('idempotency_key', sa.String(length=64), nullable=False),
        sa.Column('awarded_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('idempotency_key', name='uq_mana_idempotency'),
    )

    op.create_table(
        'audit_logs',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('detail_json_encrypted', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'deletion_requests',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=True),
        sa.Column('requested_at', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column(
            'status',
            sa.Enum('pending', 'processing', 'completed', name='deletion_status'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'oauth_tokens',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column(
            'provider',
            sa.Enum('dexcom', 'oura', 'fitbit', 'withings', name='oauth_provider'),
            nullable=False,
        ),
        sa.Column('provider_user_id', sa.String(length=128), nullable=False),
        sa.Column('access_token_encrypted', sa.Text(), nullable=False),
        sa.Column('refresh_token_encrypted', sa.Text(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('scope', sa.String(length=256), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'provider', name='uq_user_provider'),
        sa.UniqueConstraint(
            'provider', 'provider_user_id', name='uq_provider_user'
        ),
    )
    op.create_index(
        'ix_oauth_tokens_provider_user_id',
        'oauth_tokens',
        ['provider_user_id'],
        unique=False,
    )

    op.create_table(
        'device_tokens',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('token', sa.String(length=512), nullable=False),
        sa.Column(
            'platform',
            sa.Enum('apns', 'fcm', name='device_platform'),
            nullable=False,
        ),
        sa.Column('last_seen_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'device_attestations',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('manufacturer', sa.String(length=64), nullable=False),
        sa.Column('device_id', sa.String(length=128), nullable=False),
        sa.Column('hmac_key_encrypted', sa.Text(), nullable=False),
        sa.Column('enrolled_at', sa.DateTime(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    # Partial unique index — uniqueness only on rows that haven't been
    # soft-revoked. Re-enrolling after a revoke is a supported flow; the
    # historical row stays for audit and the new row is the active one.
    op.create_index(
        'uq_active_device_attestation',
        'device_attestations',
        ['user_id', 'manufacturer', 'device_id'],
        unique=True,
        postgresql_where=sa.text('revoked_at IS NULL'),
    )

    op.create_table(
        'dead_letter_payloads',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('source', sa.String(length=64), nullable=False),
        sa.Column('raw_body_encrypted', sa.Text(), nullable=False),
        sa.Column('failed_at', sa.DateTime(), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'guilds',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('invite_code', sa.String(length=16), nullable=False),
        sa.Column('created_by_user_id', sa.BigInteger(), nullable=False),
        sa.Column('member_cap', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('invite_code'),
    )

    op.create_table(
        'reward_outbox',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('idempotency_key', sa.String(length=64), nullable=False),
        sa.Column('event_type', sa.String(length=32), nullable=False),
        sa.Column('payload_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('idempotency_key'),
    )
    op.create_index(
        'ix_reward_outbox_idempotency_key',
        'reward_outbox',
        ['idempotency_key'],
        unique=False,
    )
    op.create_index(
        'ix_reward_outbox_created_at',
        'reward_outbox',
        ['created_at'],
        unique=False,
    )
    op.create_index(
        'ix_reward_outbox_published_at',
        'reward_outbox',
        ['published_at'],
        unique=False,
    )
    # Partial index for the drain query: unpublished rows ordered by age.
    op.create_index(
        'ix_reward_outbox_unpublished',
        'reward_outbox',
        ['created_at'],
        unique=False,
        postgresql_where=sa.text('published_at IS NULL'),
    )


def downgrade() -> None:
    op.drop_index('ix_reward_outbox_unpublished', table_name='reward_outbox')
    op.drop_index('ix_reward_outbox_published_at', table_name='reward_outbox')
    op.drop_index('ix_reward_outbox_created_at', table_name='reward_outbox')
    op.drop_index('ix_reward_outbox_idempotency_key', table_name='reward_outbox')
    op.drop_table('reward_outbox')
    op.drop_table('guilds')
    op.drop_table('dead_letter_payloads')
    op.drop_index('uq_active_device_attestation', table_name='device_attestations')
    op.drop_table('device_attestations')
    op.drop_table('device_tokens')
    op.drop_index('ix_oauth_tokens_provider_user_id', table_name='oauth_tokens')
    op.drop_table('oauth_tokens')
    op.drop_table('deletion_requests')
    op.drop_table('audit_logs')
    op.drop_table('mana_ledger')
    op.drop_table('user_goals')
    op.drop_table('biometric_logs')
    op.drop_index('ix_users_email_lookup_hash', table_name='users')
    op.drop_table('users')
    sa.Enum(name='deletion_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='device_platform').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='oauth_provider').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='guild_member_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='user_role').drop(op.get_bind(), checkfirst=True)
