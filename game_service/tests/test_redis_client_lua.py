"""
Phase 4 / fix #20 — Lua wrapper rollout.

The pre-existing wrappers `debit_mana_lua` and `set_build_timer_lua` now
delegate to `lua_runner.run`, which catches redis.exceptions.ResponseError
(raised when a Lua script does `return {err = "..."}`) and translates it
into a string return value. The `isinstance(result, str)` checks at every
caller site (economy_actions, guild_manager) finally start matching.

The unit tests here use a stub LuaRunner to verify wiring — the
testcontainers-based integration suite exercises real Lua against
redis:7-alpine.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from game_service.db import redis_client
from game_service.db import lua_runner as lr_module


class StubLuaRunner:
    """Captures (script_name, keys, args) and returns the queued result."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list, list]] = []
        self._queued: tuple[bool, Any] = (True, 100)

    def queue(self, ok: bool, value: Any) -> None:
        self._queued = (ok, value)

    async def run(self, redis, name, keys, args):
        self.calls.append((name, list(keys), list(args)))
        return self._queued


@pytest.fixture
def stub_runner(monkeypatch):
    stub = StubLuaRunner()
    # Patch the singleton imported by redis_client
    monkeypatch.setattr(redis_client, "lua_runner", stub)
    # Patch get_redis so the wrappers don't actually try to connect
    monkeypatch.setattr(redis_client, "get_redis", AsyncMock(return_value=object()))
    return stub


class TestDebitManaLua:
    async def test_success_returns_int(self, stub_runner):
        stub_runner.queue(True, 250)
        result = await redis_client.debit_mana_lua(
            user_id=42, cost=50, idempotency_key="idem-1"
        )
        assert result == 250
        assert isinstance(result, int)

    async def test_lua_error_returns_string_token(self, stub_runner):
        stub_runner.queue(False, "INSUFFICIENT_MANA")
        result = await redis_client.debit_mana_lua(
            user_id=42, cost=999, idempotency_key="idem-2"
        )
        # The whole point of the Phase 4 fix: callers can finally do
        # `if isinstance(result, str)` and have it match.
        assert isinstance(result, str)
        assert result == "INSUFFICIENT_MANA"

    async def test_calls_correct_script_with_correct_keys(self, stub_runner):
        stub_runner.queue(True, 0)
        await redis_client.debit_mana_lua(user_id=42, cost=50, idempotency_key="idem-3")
        name, keys, args = stub_runner.calls[0]
        assert name == "mana_debit"
        assert keys == ["game:state:42"]
        assert args == [50, "idem-3"]

    async def test_duplicate_request_returns_string_token(self, stub_runner):
        stub_runner.queue(False, "DUPLICATE_REQUEST")
        result = await redis_client.debit_mana_lua(
            user_id=42, cost=50, idempotency_key="repeated"
        )
        assert result == "DUPLICATE_REQUEST"


class TestSetBuildTimerLua:
    async def test_success_returns_int(self, stub_runner):
        stub_runner.queue(True, 1500)
        result = await redis_client.set_build_timer_lua(
            user_id=42,
            building_id="apothecary",
            mana_cost=500,
            complete_at_unix=1_800_000_000,
            next_tier=2,
            idempotency_key="idem-4",
            redis=object(),  # not used — mocked
        )
        assert result == 1500

    async def test_calls_correct_script_with_four_keys(self, stub_runner):
        # Phase 9d expanded the KEYS layout from 2 to 4 — sanctuary and
        # techtree keys are now passed in so prereq validation can happen
        # inside the Lua atomically.
        stub_runner.queue(True, 0)
        await redis_client.set_build_timer_lua(
            user_id=42,
            building_id="apothecary",
            mana_cost=500,
            complete_at_unix=1_800_000_000,
            next_tier=2,
            idempotency_key="idem-5",
            redis=object(),
        )
        name, keys, args = stub_runner.calls[0]
        assert name == "build_timer_set"
        assert keys == [
            "game:state:42",
            "game:builds:42",
            "game:sanctuary:42",
            "techtree:apothecary:tier:2",
        ]
        assert args == [500, "apothecary", 1_800_000_000, 2, "idem-5"]

    async def test_insufficient_mana_returns_string(self, stub_runner):
        stub_runner.queue(False, "INSUFFICIENT_MANA")
        result = await redis_client.set_build_timer_lua(
            user_id=42,
            building_id="apothecary",
            mana_cost=999_999,
            complete_at_unix=1_800_000_000,
            next_tier=2,
            idempotency_key="idem-6",
            redis=object(),
        )
        assert result == "INSUFFICIENT_MANA"


class TestDefaultScriptsRegistered:
    """At module import, redis_client should have registered both Lua scripts."""

    def test_mana_debit_registered(self):
        assert "mana_debit" in lr_module.runner._registry

    def test_build_timer_set_registered(self):
        assert "build_timer_set" in lr_module.runner._registry
