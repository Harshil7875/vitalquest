"""
Phase 5 / fixes #18 #19 — Reward publisher + transactional outbox.

Verifies that:
- publish_event writes a RewardOutbox row inside the request transaction
  (no Redis publish until the drainer runs).
- The idempotency check correctly identifies duplicates against both
  RewardOutbox AND ManaLedger (the broken db.get(dict) pattern is gone).
- ErasureEvent doesn't write a ManaLedger row (it's not a reward).
- drain_outbox publishes via Redis and marks rows published_at.

Uses fakes for both the AsyncSession-like behavior and the Redis client so
the suite stays unit-test fast. Postgres-level guarantees (transaction
isolation, the partial index) are exercised in the integration suite.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from health_service.db.models import ManaLedger, RewardOutbox
from health_service.publisher import redis_publisher
from shared.schemas import ErasureEvent, GuildDamageEvent, RewardEvent


class FakeResult:
    def __init__(self, rows: list[Any]):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return _Scalars(self._rows)


class _Scalars:
    def __init__(self, rows: list[Any]):
        self._rows = rows

    def all(self):
        return list(self._rows)


class FakeSession:
    """Minimal AsyncSession stand-in for unit tests."""

    def __init__(self):
        self.added: list[Any] = []
        self.flushed = False
        self.committed = False
        self._existing: dict[type, list[Any]] = {RewardOutbox: [], ManaLedger: []}

    def seed_existing(self, model_type, rows):
        self._existing[model_type] = rows

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed = True

    async def commit(self):
        self.committed = True

    async def execute(self, stmt):
        # Crude SELECT-target inspection: if the SELECT touches RewardOutbox
        # return its seeded rows, same for ManaLedger.
        target = str(stmt).lower()
        if "reward_outbox" in target:
            return FakeResult(self._existing.get(RewardOutbox, []))
        if "mana_ledger" in target:
            return FakeResult(self._existing.get(ManaLedger, []))
        return FakeResult([])


@pytest.fixture
def session():
    return FakeSession()


@pytest.fixture
def fake_redis(monkeypatch):
    redis = AsyncMock()
    redis.publish = AsyncMock()

    async def _get_redis():
        return redis

    monkeypatch.setattr(redis_publisher, "get_redis", _get_redis)
    return redis


class TestPublishEventNew:
    async def test_writes_outbox_row(self, session, fake_redis):
        evt = RewardEvent(user_id=42, event_type="mana_award", amount=50, source="steps")
        ok = await redis_publisher.publish_event(evt, session)
        assert ok is True

        outbox_rows = [a for a in session.added if isinstance(a, RewardOutbox)]
        assert len(outbox_rows) == 1
        assert outbox_rows[0].idempotency_key == evt.idempotency_key
        assert outbox_rows[0].event_type == "mana_award"

    async def test_writes_mana_ledger_for_mana_award(self, session, fake_redis):
        evt = RewardEvent(user_id=42, event_type="mana_award", amount=50, source="steps")
        await redis_publisher.publish_event(evt, session)
        ledger_rows = [a for a in session.added if isinstance(a, ManaLedger)]
        assert len(ledger_rows) == 1
        assert ledger_rows[0].user_id == 42
        assert ledger_rows[0].amount == 50

    async def test_does_not_publish_to_redis_inline(self, session, fake_redis):
        # The whole point of #19 — publish must happen post-commit, in the
        # drainer. publish_event itself never calls redis.publish.
        evt = RewardEvent(user_id=42, event_type="mana_award", amount=50, source="steps")
        await redis_publisher.publish_event(evt, session)
        assert fake_redis.publish.await_count == 0
        assert fake_redis.xadd.await_count == 0

    async def test_erasure_event_no_mana_ledger(self, session, fake_redis):
        evt = ErasureEvent(user_id=42)
        ok = await redis_publisher.publish_event(evt, session)
        assert ok is True
        ledger_rows = [a for a in session.added if isinstance(a, ManaLedger)]
        # Erasure must NOT write to ManaLedger — the user is being deleted.
        assert ledger_rows == []
        # But the outbox still receives it so the game side anonymizes state.
        outbox_rows = [a for a in session.added if isinstance(a, RewardOutbox)]
        assert len(outbox_rows) == 1
        assert outbox_rows[0].event_type == "erasure"

    async def test_guild_damage_no_mana_ledger(self, session, fake_redis):
        evt = GuildDamageEvent(user_id=0, guild_id=7, amount=100)
        await redis_publisher.publish_event(evt, session)
        ledger_rows = [a for a in session.added if isinstance(a, ManaLedger)]
        assert ledger_rows == []
        outbox_rows = [a for a in session.added if isinstance(a, RewardOutbox)]
        assert len(outbox_rows) == 1


class TestPublishEventIdempotency:
    async def test_duplicate_in_outbox_returns_false(self, session, fake_redis):
        prior = RewardOutbox(idempotency_key="prior", event_type="mana_award", payload_json="{}")
        session.seed_existing(RewardOutbox, [prior])
        # Use the same idempotency_key to simulate a retry of the prior call.
        evt = RewardEvent(
            user_id=42, event_type="mana_award", amount=50, source="steps",
            idempotency_key="prior",
        )
        ok = await redis_publisher.publish_event(evt, session)
        assert ok is False
        # No new outbox row, no new ledger row.
        assert all(not isinstance(a, RewardOutbox) for a in session.added)
        assert all(not isinstance(a, ManaLedger) for a in session.added)

    async def test_duplicate_in_ledger_returns_false(self, session, fake_redis):
        # The audit's #18 — db.get(ManaLedger, {dict}) was the broken pattern.
        # Now we explicitly select-where; an existing ledger row dedupes.
        prior_ledger = ManaLedger(
            user_id=42, amount=50, source="steps", idempotency_key="prior",
        )
        session.seed_existing(ManaLedger, [prior_ledger])
        evt = RewardEvent(
            user_id=42, event_type="mana_award", amount=50, source="steps",
            idempotency_key="prior",
        )
        ok = await redis_publisher.publish_event(evt, session)
        assert ok is False


class TestDrainOutbox:
    async def test_publishes_unpublished_rows(self, session, fake_redis):
        rows = [
            RewardOutbox(
                idempotency_key=f"k{i}", event_type="mana_award",
                payload_json=f'{{"amount":{i}}}',
            )
            for i in range(3)
        ]
        session.seed_existing(RewardOutbox, rows)

        published = await redis_publisher.drain_outbox(session)
        assert published == 3
        # Each row should now have published_at set.
        assert all(r.published_at is not None for r in rows)
        # Redis got 3 publishes.
        assert fake_redis.publish.await_count == 3

    async def test_empty_outbox_no_op(self, session, fake_redis):
        session.seed_existing(RewardOutbox, [])
        published = await redis_publisher.drain_outbox(session)
        assert published == 0
        assert fake_redis.publish.await_count == 0
        assert session.committed is False  # nothing to commit

    async def test_publish_failure_keeps_row_unpublished(self, session, fake_redis):
        # If the transport raises, the row's published_at must stay None so
        # the next drain pass tries again.
        fake_redis.publish.side_effect = ConnectionError("redis down")
        row = RewardOutbox(
            idempotency_key="k1", event_type="mana_award", payload_json="{}",
        )
        session.seed_existing(RewardOutbox, [row])

        published = await redis_publisher.drain_outbox(session)
        assert published == 0
        assert row.published_at is None
