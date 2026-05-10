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
