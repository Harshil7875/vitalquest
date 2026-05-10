"""
Phase 9a / fix #13 — skip_build_timer atomicity tests.

Validates that skip_build_timer routes through skip_timer.lua via lua_runner
and that error tokens are translated to user-friendly ActionResult messages.

The Lua atomicity itself (idempotency, partial-failure rollback, race-free
gem debit) is integration-tested against real Redis in the testcontainers
suite.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from game_service.core import economy_actions


class StubLuaRunner:
    def __init__(self):
        self.calls: list[tuple[str, list, list]] = []
        self._queued: tuple[bool, Any] = (True, [50, 2])

    def queue(self, ok: bool, value: Any) -> None:
        self._queued = (ok, value)

    async def run(self, redis, name, keys, args):
        self.calls.append((name, list(keys), list(args)))
        return self._queued


@pytest.fixture
def stub_runner(monkeypatch):
    stub = StubLuaRunner()
    monkeypatch.setattr(economy_actions, "lua_runner", stub)
    return stub


@pytest.fixture
def stub_state(monkeypatch):
    """Stub get_build_timers and get_game_state helpers."""
    timers = {
        "apothecary:complete_at": "1700000000",  # Far past so remaining_minutes = 0
        "apothecary:pending_tier": "2",
    }
    monkeypatch.setattr(
        economy_actions, "get_build_timers", AsyncMock(return_value=timers)
    )
    monkeypatch.setattr(
        economy_actions, "get_game_state",
        AsyncMock(return_value={"mana_balance": "500", "astral_gems": "100"}),
    )


class TestSkipBuildTimerWiring:
    async def test_calls_skip_timer_lua(self, stub_runner, stub_state):
        await economy_actions.skip_build_timer(
            user_id=42, building_id="apothecary",
            idempotency_key="idem-1", redis=AsyncMock(),
        )
        name, keys, args = stub_runner.calls[0]
        assert name == "skip_timer"
        # KEYS layout matches the Lua script's expectations.
        assert keys == [
            "game:state:42",
            "game:builds:42",
            "game:sanctuary:42",
        ]
        # ARGV: [building_id, gem_cost, next_tier, idempotency_key]
        assert args[0] == "apothecary"
        assert args[3] == "idem-1"

    async def test_no_active_timer_returns_false(self, stub_runner, monkeypatch):
        # No timers at all — never reaches the Lua call.
        monkeypatch.setattr(
            economy_actions, "get_build_timers", AsyncMock(return_value={})
        )
        result = await economy_actions.skip_build_timer(
            user_id=42, building_id="apothecary",
            idempotency_key="idem-1", redis=AsyncMock(),
        )
        assert result.success is False
        assert "no active" in result.message.lower()
        assert stub_runner.calls == []

    async def test_lua_insufficient_gems_translated(self, stub_runner, stub_state):
        stub_runner.queue(False, "INSUFFICIENT_GEMS")
        result = await economy_actions.skip_build_timer(
            user_id=42, building_id="apothecary",
            idempotency_key="idem-1", redis=AsyncMock(),
        )
        assert result.success is False
        assert "Astral Gems" in result.message

    async def test_lua_duplicate_request_translated(self, stub_runner, stub_state):
        stub_runner.queue(False, "DUPLICATE_REQUEST")
        result = await economy_actions.skip_build_timer(
            user_id=42, building_id="apothecary",
            idempotency_key="idem-1", redis=AsyncMock(),
        )
        assert result.success is False
        assert "already processed" in result.message.lower()

    async def test_success_returns_new_tier(self, stub_runner, stub_state):
        stub_runner.queue(True, [50, 2])
        result = await economy_actions.skip_build_timer(
            user_id=42, building_id="apothecary",
            idempotency_key="idem-1", redis=AsyncMock(),
        )
        assert result.success is True
        assert "tier 2" in result.message


class TestOpenChestPersistedRoll:
    """Phase 9b / fix #14 — chest_result:{idem_key} drives idempotent replay."""

    async def test_persisted_result_returns_same_items_no_reroll(self, stub_runner, monkeypatch):
        # If chest_result:{idem_key} exists, we must return THOSE items —
        # no fresh roll, no Lua call. Without this, a network-dropped
        # response on a successful chest open would let the user retry
        # and get a different set of items than what was already
        # deposited.
        from game_service.core import economy_actions as ea

        roll_calls = []
        def stub_roll(rarity):
            roll_calls.append(rarity)
            return [ea.ItemGrant(item_id="should_never_be_returned", quantity=99)]
        monkeypatch.setattr(ea, "roll_chest", stub_roll)
        monkeypatch.setattr(
            ea, "get_game_state", AsyncMock(return_value={"mana_balance": "100"})
        )

        # Persisted payload for the previous, successful open.
        persisted_json = '[{"item_id": "rare_gem", "quantity": 3}]'
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=persisted_json)

        result = await ea.open_chest(
            user_id=42, chest_rarity="common",
            idempotency_key="idem-replay", redis=redis,
        )

        assert result.success is True
        assert "replay" in result.message.lower()
        assert len(result.items_granted) == 1
        assert result.items_granted[0].item_id == "rare_gem"
        # No reroll happened — the audit's gotcha.
        assert roll_calls == []
        # No Lua call happened either.
        assert stub_runner.calls == []

    async def test_first_call_rolls_and_invokes_lua(self, stub_runner, monkeypatch):
        from game_service.core import economy_actions as ea

        monkeypatch.setattr(
            ea, "roll_chest",
            lambda r: [ea.ItemGrant(item_id="potion", quantity=2)],
        )
        monkeypatch.setattr(
            ea, "get_game_state", AsyncMock(return_value={"mana_balance": "100"})
        )

        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)  # no persisted result

        stub_runner.queue(True, 1)

        result = await ea.open_chest(
            user_id=42, chest_rarity="common",
            idempotency_key="idem-fresh", redis=redis,
        )

        assert result.success is True
        # Lua got called with the chest_rarity, idem_key, payload, ttl, then
        # flat (item_id, qty) pairs.
        name, keys, args = stub_runner.calls[0]
        assert name == "open_chest"
        assert args[0] == "common"
        assert args[1] == "idem-fresh"
        # ARGV[3] is the result_payload_json — should round-trip the items.
        import json
        roundtrip = json.loads(args[2])
        assert roundtrip == [{"item_id": "potion", "quantity": 2}]
        # ARGV[4] is the TTL.
        assert args[3] == ea.CHEST_RESULT_TTL_SECONDS
        # ARGV[5..] is the flattened (item_id, qty) tail.
        assert args[4:] == ["potion", 2]

    async def test_lua_chest_empty_translated(self, stub_runner, monkeypatch):
        from game_service.core import economy_actions as ea
        monkeypatch.setattr(ea, "roll_chest", lambda r: [])
        monkeypatch.setattr(
            ea, "get_game_state", AsyncMock(return_value={"mana_balance": "100"})
        )

        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)

        stub_runner.queue(False, "CHEST_EMPTY")

        result = await ea.open_chest(
            user_id=42, chest_rarity="legendary",
            idempotency_key="idem-x", redis=redis,
        )
        assert result.success is False
        assert "no legendary chests" in result.message.lower()
