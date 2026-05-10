"""Tests for game_config helpers — get_* accessors and sync_to_redis."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from game_service.core.game_config import (
    REDIS_KEY_DAILY_MANA_CAP,
    REDIS_KEY_WORLD_BOSS_HP,
    get_daily_mana_cap,
    get_world_boss_hp,
    load_config,
    sync_to_redis,
    techtree_key,
)


@pytest.fixture(autouse=True)
def _load_config():
    """Ensure the singleton is loaded before any test runs."""
    load_config()


class TestAccessors:
    def test_daily_mana_cap_matches_master_config(self):
        # master_config.json sets economy.daily_mana_cap = 300
        assert get_daily_mana_cap() == 300

    def test_world_boss_hp_matches_master_config(self):
        # master_config.json sets world_boss.boss_hp = 100000
        assert get_world_boss_hp() == 100000


class TestTechtreeKey:
    def test_format(self):
        assert techtree_key("apothecary", 3) == "techtree:apothecary:tier:3"
        assert techtree_key("scout_tower", "5") == "techtree:scout_tower:tier:5"


class TestSyncToRedis:
    async def test_writes_canonical_config_keys(self):
        # Mock redis with a pipeline that captures all calls.
        captured: list[tuple[str, tuple, dict]] = []

        class FakePipe:
            def set(self, key, value):
                captured.append(("set", (key, value), {}))
                return self

            def delete(self, key):
                captured.append(("delete", (key,), {}))
                return self

            def hset(self, key, mapping=None, **kwargs):
                captured.append(("hset", (key,), {"mapping": mapping}))
                return self

            async def execute(self):
                return []

        redis = MagicMock()
        redis.pipeline = MagicMock(return_value=FakePipe())

        await sync_to_redis(redis)

        # Daily Mana cap and boss HP must be written.
        set_calls = [c for c in captured if c[0] == "set"]
        assert (REDIS_KEY_DAILY_MANA_CAP, "300") in [c[1] for c in set_calls]
        assert (REDIS_KEY_WORLD_BOSS_HP, "100000") in [c[1] for c in set_calls]

    async def test_writes_techtree_prereqs(self):
        captured: list[tuple[str, tuple, dict]] = []

        class FakePipe:
            def set(self, *a, **kw): captured.append(("set", a, kw)); return self
            def delete(self, *a, **kw): captured.append(("delete", a, kw)); return self
            def hset(self, *a, **kw): captured.append(("hset", a, kw)); return self
            async def execute(self): return []

        redis = MagicMock()
        redis.pipeline = MagicMock(return_value=FakePipe())

        await sync_to_redis(redis)

        # apothecary tier 3 has prereqs {apothecary: 2, scout_tower: 1}
        # — must produce an HSET with that mapping.
        apothecary_t3_calls = [
            c for c in captured
            if c[0] == "hset"
            and c[1] == ("techtree:apothecary:tier:3",)
        ]
        assert len(apothecary_t3_calls) == 1
        mapping = apothecary_t3_calls[0][2]["mapping"]
        assert mapping == {"apothecary": "2", "scout_tower": "1"}

    async def test_idempotent_delete_before_hset(self):
        """Each tier key is DEL'd before being rewritten so removed prereqs
        don't linger from a prior sync."""
        captured: list[str] = []

        class FakePipe:
            def set(self, *a, **kw): captured.append("set"); return self
            def delete(self, *a, **kw): captured.append("delete"); return self
            def hset(self, *a, **kw): captured.append("hset"); return self
            async def execute(self): return []

        redis = MagicMock()
        redis.pipeline = MagicMock(return_value=FakePipe())

        await sync_to_redis(redis)

        # For every tier with prereqs, delete must precede hset.
        for i, op in enumerate(captured):
            if op == "hset" and i > 0:
                assert "delete" in captured[:i]
