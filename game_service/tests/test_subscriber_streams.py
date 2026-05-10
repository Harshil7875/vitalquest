"""
Phase 11 / fix #10 — Pub/Sub → Streams subscriber tests.

The pre-Phase-11 subscriber used redis.pubsub() which is at-most-once: any
event published during a reconnect window was silently dropped. The Streams
version uses a consumer group with XACK, so an entry isn't considered
delivered until process_reward_event succeeds. Crashes leave the entry
in the Pending Entries List (PEL) and XAUTOCLAIM picks it up on the
next iteration.

These unit tests use stub Redis behavior to verify the wiring. The actual
delivery semantics (XACK timing, XAUTOCLAIM stealing stale entries,
ack-only-on-success) are exercised in the integration suite.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from game_service.subscriber import redis_subscriber as sub
from shared.schemas import RewardEvent


class TestEnsureConsumerGroup:
    async def test_creates_group_with_mkstream(self):
        redis = AsyncMock()
        await sub._ensure_consumer_group(redis)
        redis.xgroup_create.assert_awaited_once_with(
            sub.REWARDS_STREAM, sub.CONSUMER_GROUP, id="$", mkstream=True
        )

    async def test_busygroup_is_swallowed(self):
        from redis.exceptions import ResponseError
        redis = AsyncMock()
        redis.xgroup_create.side_effect = ResponseError("BUSYGROUP Consumer Group already exists")
        # Should not raise — the group already existing is the success case
        # for an idempotent boot.
        await sub._ensure_consumer_group(redis)


class TestProcessEntry:
    async def test_valid_event_returns_true(self, monkeypatch):
        called = AsyncMock()
        monkeypatch.setattr(sub, "process_reward_event", called)
        evt = RewardEvent(user_id=42, event_type="mana_award", amount=50, source="steps")
        fields = {"payload": evt.model_dump_json()}
        ok = await sub._process_entry("1234-0", fields, AsyncMock())
        assert ok is True
        called.assert_awaited_once()

    async def test_invalid_json_acks_to_drain(self, monkeypatch):
        # A malformed payload should be ACK'd so it doesn't loop forever
        # in the PEL — replaying invalid JSON will never succeed.
        called = AsyncMock()
        monkeypatch.setattr(sub, "process_reward_event", called)
        ok = await sub._process_entry("1234-0", {"payload": "not json"}, AsyncMock())
        assert ok is True
        called.assert_not_awaited()

    async def test_processing_exception_returns_false(self, monkeypatch):
        async def boom(*a, **kw):
            raise RuntimeError("redis exploded")
        monkeypatch.setattr(sub, "process_reward_event", boom)
        evt = RewardEvent(user_id=42, event_type="mana_award", amount=50, source="steps")
        fields = {"payload": evt.model_dump_json()}
        ok = await sub._process_entry("1234-0", fields, AsyncMock())
        # The whole point of #10: failures must NOT ack, so XAUTOCLAIM
        # later picks the entry back up.
        assert ok is False

    async def test_missing_payload_field_acks(self, monkeypatch):
        called = AsyncMock()
        monkeypatch.setattr(sub, "process_reward_event", called)
        ok = await sub._process_entry("1234-0", {}, AsyncMock())
        assert ok is True
        called.assert_not_awaited()

    async def test_payload_as_bytes_decoded(self, monkeypatch):
        # If decode_responses=False, fields come back as bytes. The handler
        # should still work.
        called = AsyncMock()
        monkeypatch.setattr(sub, "process_reward_event", called)
        evt = RewardEvent(user_id=42, event_type="mana_award", amount=50, source="steps")
        fields = {b"payload": evt.model_dump_json().encode("utf-8")}
        ok = await sub._process_entry("1234-0", fields, AsyncMock())
        assert ok is True
        called.assert_awaited_once()


class TestStreamConstants:
    """Sanity checks on the canonical stream / consumer-group identifiers."""

    def test_stream_name_matches_publisher(self):
        # The publisher writes to "health.rewards" via XADD; the subscriber
        # must consume from the same stream.
        from health_service.publisher import redis_publisher
        assert sub.REWARDS_STREAM == redis_publisher.REWARDS_STREAM
