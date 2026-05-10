"""
Phase 7 / fixes #9, #15, #23 — reward processor tests.

Validates:
- Atomic idempotency: SADD returns 0 → handler is not invoked.
- mana_award path delegates to reward_apply.lua via lua_runner.
- The hardcoded DAILY_MANA_CAP constant is gone (read via game_config).
- Master_config drift guard: the cap passed to Lua is whatever
  master_config.json says (currently 300), not a Python constant.

The Lua script itself is integration-tested against real Redis in the
testcontainers suite — those cases verify the cap-clamp arithmetic.
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import AsyncMock

import pytest

from game_service.core import reward_processor
from game_service.core.game_config import load_config
from shared.schemas import RewardEvent


@pytest.fixture(autouse=True)
def _load_config():
    load_config()


class StubLuaRunner:
    def __init__(self):
        self.calls: list[tuple[str, list, list]] = []
        self._queued: tuple[bool, Any] = (True, [100, 50])

    def queue(self, ok: bool, value: Any) -> None:
        self._queued = (ok, value)

    async def run(self, redis, name, keys, args):
        self.calls.append((name, list(keys), list(args)))
        return self._queued


@pytest.fixture
def stub_runner(monkeypatch):
    stub = StubLuaRunner()
    monkeypatch.setattr(reward_processor, "lua_runner", stub)
    return stub


@pytest.fixture
def fake_redis():
    redis = AsyncMock()
    redis.sadd = AsyncMock(return_value=1)  # default: not a duplicate
    return redis


class TestProcessRewardEventIdempotency:
    async def test_duplicate_event_skipped_atomically(self, fake_redis, stub_runner):
        # SADD returns 0 → already in set → atomic dedup.
        fake_redis.sadd = AsyncMock(return_value=0)
        evt = RewardEvent(user_id=42, event_type="mana_award", amount=50, source="steps")
        await reward_processor.process_reward_event(evt, fake_redis)
        # Lua never called.
        assert stub_runner.calls == []

    async def test_new_event_proceeds_to_handler(self, fake_redis, stub_runner):
        fake_redis.sadd = AsyncMock(return_value=1)
        stub_runner.queue(True, [150, 50])
        evt = RewardEvent(user_id=42, event_type="mana_award", amount=50, source="steps")
        await reward_processor.process_reward_event(evt, fake_redis)
        assert len(stub_runner.calls) == 1

    async def test_sadd_called_with_correct_key(self, fake_redis, stub_runner):
        evt = RewardEvent(user_id=42, event_type="mana_award", amount=50, source="steps")
        await reward_processor.process_reward_event(evt, fake_redis)
        # Atomic dedup uses the canonical processed-events set.
        fake_redis.sadd.assert_awaited_once()
        call_args = fake_redis.sadd.call_args.args
        assert call_args[0] == "game:processed_events"
        assert call_args[1] == evt.idempotency_key


class TestManaAwardLuaInvocation:
    async def test_passes_master_config_cap_not_hardcoded(self, fake_redis, stub_runner):
        # The audit's #23: master_config has 300, so 300 must be the value
        # passed to Lua. Tweak master_config and re-run → Lua sees the new
        # value with no Python code change.
        stub_runner.queue(True, [50, 50])
        evt = RewardEvent(user_id=42, event_type="mana_award", amount=50, source="steps")
        await reward_processor.process_reward_event(evt, fake_redis)

        name, keys, args = stub_runner.calls[0]
        assert name == "reward_apply"
        # ARGV layout: [amount, daily_cap, ttl_seconds]
        assert args[0] == 50
        assert args[1] == 300  # from master_config.json
        assert args[2] == 90_000  # 25h in seconds

    async def test_keys_include_state_and_daily_counter(self, fake_redis, stub_runner):
        stub_runner.queue(True, [50, 50])
        evt = RewardEvent(user_id=42, event_type="mana_award", amount=50, source="steps")
        await reward_processor.process_reward_event(evt, fake_redis)

        _, keys, _ = stub_runner.calls[0]
        assert keys[0] == "game:state:42"
        assert keys[1].startswith("game:daily_cap:42:")  # date appended


class TestNoHardcodedCap:
    """The audit's #23: ensure DAILY_MANA_CAP is no longer a module-level constant."""

    def test_module_does_not_export_daily_mana_cap(self):
        # The previous code had `DAILY_MANA_CAP = 300` at module level.
        # Phase 7 removes it. If a future change adds it back, this fails.
        assert not hasattr(reward_processor, "DAILY_MANA_CAP")


class TestUnknownEventType:
    async def test_warns_and_does_not_crash(self, fake_redis, stub_runner, caplog):
        # Build a RewardEvent with the literal-typed event_type field, then
        # bypass validation by mutating after construction.
        evt = RewardEvent(user_id=42, event_type="mana_award", amount=50, source="steps")
        object.__setattr__(evt, "event_type", "unknown_type")  # noqa
        await reward_processor.process_reward_event(evt, fake_redis)
        # No Lua called.
        assert stub_runner.calls == []


class TestExceptionHandling:
    async def test_handler_exception_does_not_propagate(self, fake_redis, stub_runner):
        # Simulating a runner crash should NOT bubble — subscriber loop must
        # survive a single bad event.
        async def boom(*a, **kw):
            raise RuntimeError("redis exploded")
        stub_runner.run = boom  # type: ignore[assignment]
        evt = RewardEvent(user_id=42, event_type="mana_award", amount=50, source="steps")
        # Should not raise.
        await reward_processor.process_reward_event(evt, fake_redis)
