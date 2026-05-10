"""
Phase 8 / fixes #12, #24 — boss damage atomicity + master_config-driven HP.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from game_service.core import raid_manager
from game_service.core.game_config import load_config


@pytest.fixture(autouse=True)
def _load_config():
    load_config()


class StubLuaRunner:
    def __init__(self):
        self.calls: list[tuple[str, list, list]] = []
        self._queued: tuple[bool, Any] = (True, [99000, 0])

    def queue(self, ok: bool, value: Any) -> None:
        self._queued = (ok, value)

    async def run(self, redis, name, keys, args):
        self.calls.append((name, list(keys), list(args)))
        return self._queued


@pytest.fixture
def stub_runner(monkeypatch):
    stub = StubLuaRunner()
    monkeypatch.setattr(raid_manager, "lua_runner", stub)
    # Stub add_guild_damage so we don't hit Redis on the daily-progress write.
    monkeypatch.setattr(raid_manager, "add_guild_damage", AsyncMock(return_value=0))
    return stub


@pytest.fixture
def fake_redis():
    return AsyncMock()


class TestApplyGuildDamage:
    async def test_calls_boss_damage_lua(self, fake_redis, stub_runner):
        await raid_manager.apply_guild_damage(guild_id=7, damage=500, redis=fake_redis)
        name, keys, args = stub_runner.calls[0]
        assert name == "boss_damage"
        assert keys == ["game:guild:7"]
        # ARGV layout: [damage, initial_hp]. initial_hp must come from master_config.
        assert args[0] == 500
        assert args[1] == 100000  # the audit's #24: master_config.world_boss.boss_hp

    async def test_returns_true_only_when_defeated_by_this_call(self, fake_redis, stub_runner):
        # Lua signals "this call is the kill" via the second return value.
        stub_runner.queue(True, [0, 1])
        defeated = await raid_manager.apply_guild_damage(7, 100, fake_redis)
        assert defeated is True

    async def test_returns_false_when_already_defeated(self, fake_redis, stub_runner):
        # current_hp <= 0 in Lua → defeated_by_this_call = 0 → False.
        # This is the regression guard for double-firing loot distribution.
        stub_runner.queue(True, [-50, 0])
        defeated = await raid_manager.apply_guild_damage(7, 100, fake_redis)
        assert defeated is False

    async def test_returns_false_on_partial_damage(self, fake_redis, stub_runner):
        # Boss still alive after damage.
        stub_runner.queue(True, [98_500, 0])
        defeated = await raid_manager.apply_guild_damage(7, 1500, fake_redis)
        assert defeated is False

    async def test_lua_error_returns_false_safely(self, fake_redis, stub_runner):
        stub_runner.queue(False, "DUPLICATE_REQUEST")
        defeated = await raid_manager.apply_guild_damage(7, 100, fake_redis)
        assert defeated is False

    async def test_daily_progress_still_updated(self, fake_redis, stub_runner):
        await raid_manager.apply_guild_damage(7, 250, fake_redis)
        # Phase 8 keeps the daily-progress hash update outside the Lua —
        # HINCRBY is atomic and progress is purely additive, so the
        # concurrency concern doesn't apply.
        raid_manager.add_guild_damage.assert_awaited_once_with(7, 250)


class TestNoHardcodedBossHp:
    """The audit's #24: literal 100000 must not appear in raid_manager."""

    def test_module_does_not_reference_literal_100000(self):
        import inspect
        source = inspect.getsource(raid_manager)
        assert "100000" not in source, (
            "raid_manager.py contains a literal 100000 — boss HP must come "
            "from game_config.get_world_boss_hp()."
        )
