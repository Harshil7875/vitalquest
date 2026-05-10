"""
Phase 9c / fix #21 — guild_create and guild_join atomicity tests.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from game_service.core import guild_manager
from game_service.core.game_config import load_config


@pytest.fixture(autouse=True)
def _load_config():
    load_config()


class StubLuaRunner:
    def __init__(self):
        self.calls: list[tuple[str, list, list]] = []
        self._queued: tuple[bool, Any] = (True, [400, 7])

    def queue(self, ok: bool, value: Any) -> None:
        self._queued = (ok, value)

    async def run(self, redis, name, keys, args):
        self.calls.append((name, list(keys), list(args)))
        return self._queued


@pytest.fixture
def stub_runner(monkeypatch):
    stub = StubLuaRunner()
    monkeypatch.setattr(guild_manager, "lua_runner", stub)
    return stub


class TestCreateGuildAtomicity:
    async def test_routes_through_guild_create_lua(self, stub_runner):
        stub_runner.queue(True, [400, 7])
        result = await guild_manager.create_guild(
            user_id=42,
            guild_name="The Cool Guild",
            idempotency_key="idem-1",
            redis=AsyncMock(),
        )
        assert result.success is True
        assert result.guild_id == 7
        name, keys, args = stub_runner.calls[0]
        assert name == "guild_create"
        assert keys == ["game:state:42", "game:guild_id_counter"]
        # ARGV[1] = creation_cost from master_config (500)
        # ARGV[5] = world_boss_hp from master_config (100000 stringified)
        assert args[0] == 500
        assert args[1] == "The Cool Guild"
        assert args[3] == "idem-1"
        assert args[4] == "100000"
        assert args[5] == "42"

    async def test_insufficient_mana_translated(self, stub_runner):
        stub_runner.queue(False, "INSUFFICIENT_MANA")
        result = await guild_manager.create_guild(
            user_id=42, guild_name="Oops",
            idempotency_key="idem-2", redis=AsyncMock(),
        )
        assert result.success is False
        assert "Insufficient Mana" in result.message

    async def test_duplicate_request_translated(self, stub_runner):
        stub_runner.queue(False, "DUPLICATE_REQUEST")
        result = await guild_manager.create_guild(
            user_id=42, guild_name="Replay",
            idempotency_key="idem-3", redis=AsyncMock(),
        )
        assert result.success is False
        assert "already processed" in result.message.lower()

    async def test_no_partial_state_on_failure(self, stub_runner):
        # The audit's regression guard for #21: a failed create must NOT
        # have already debited Mana via a separate debit_mana_lua call.
        # The single-Lua design means the Mana debit and the rest are
        # one operation — if the Lua returns an error, no state changed.
        stub_runner.queue(False, "INSUFFICIENT_MANA")
        await guild_manager.create_guild(
            user_id=42, guild_name="x",
            idempotency_key="idem-4", redis=AsyncMock(),
        )
        # Only the create script should have been called, not a separate
        # debit script — no partial state path exists.
        assert all(c[0] == "guild_create" for c in stub_runner.calls)


class TestJoinGuildAtomicity:
    async def test_routes_through_guild_join_lua(self, stub_runner, monkeypatch):
        stub_runner.queue(True, 1)
        # Bypass the invite-code → guild_id lookup (covered separately).
        redis = AsyncMock()
        monkeypatch.setattr(guild_manager, "get_redis", AsyncMock(return_value=redis))

        result = await guild_manager.join_guild(user_id=42, guild_id=7)

        assert result.success is True
        name, keys, args = stub_runner.calls[0]
        assert name == "guild_join"
        assert keys == [
            "game:state:42",
            "game:guild:7:roster",
            "game:guild:7:roles",
            "game:last_seen",
        ]
        # ARGV: user_id, guild_id, max_capacity, now
        assert args[0] == "42"
        assert args[1] == "7"
        assert args[2] == guild_manager.GUILD_MAX_CAPACITY

    async def test_already_in_guild_translated(self, stub_runner, monkeypatch):
        stub_runner.queue(False, "ALREADY_IN_GUILD")
        redis = AsyncMock()
        monkeypatch.setattr(guild_manager, "get_redis", AsyncMock(return_value=redis))

        result = await guild_manager.join_guild(user_id=42, guild_id=7)
        assert result.success is False
        assert "leave your current guild" in result.message.lower()

    async def test_guild_full_translated(self, stub_runner, monkeypatch):
        stub_runner.queue(False, "GUILD_FULL")
        redis = AsyncMock()
        monkeypatch.setattr(guild_manager, "get_redis", AsyncMock(return_value=redis))

        result = await guild_manager.join_guild(user_id=42, guild_id=7)
        assert result.success is False
        assert "full" in result.message.lower()

    async def test_invalid_invite_code_short_circuits(self, stub_runner, monkeypatch):
        # Invalid invite code never reaches the Lua call.
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        monkeypatch.setattr(guild_manager, "get_redis", AsyncMock(return_value=redis))

        result = await guild_manager.join_guild(user_id=42, invite_code="bogus")
        assert result.success is False
        assert "Invalid invite code" in result.message
        assert stub_runner.calls == []

    async def test_missing_invite_and_guild_id_short_circuits(self, stub_runner, monkeypatch):
        redis = AsyncMock()
        monkeypatch.setattr(guild_manager, "get_redis", AsyncMock(return_value=redis))

        result = await guild_manager.join_guild(user_id=42)
        assert result.success is False
        assert "invite_code or guild_id" in result.message
        assert stub_runner.calls == []
