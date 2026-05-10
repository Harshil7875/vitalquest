"""
Unit tests for the Lua runner.

The "no Redis" tests use the inline-text registration path and a stub Redis
that simulates EVALSHA / NOSCRIPT / ResponseError behavior — they don't need
a real Redis. The "real Redis" tests are gated on the `redis_container`
fixture from conftest.py and run actual Lua against redis:7-alpine.
"""

from __future__ import annotations

from typing import Any

import pytest
from redis.exceptions import NoScriptError, ResponseError

from game_service.db.lua_runner import KNOWN_ERROR_TOKENS, LuaRunner


class StubRedis:
    """Tracks calls and lets the test inject return values / exceptions."""

    def __init__(self) -> None:
        self.script_load_calls = 0
        self.evalsha_calls: list[tuple[str, int, tuple]] = []
        self._return_value: Any = None
        self._raise_on_evalsha: list[Exception] = []
        self._loaded_sha = "abc123"

    def queue_evalsha_exception(self, exc: Exception) -> None:
        self._raise_on_evalsha.append(exc)

    def set_return_value(self, value: Any) -> None:
        self._return_value = value

    async def script_load(self, text: str) -> str:
        self.script_load_calls += 1
        return self._loaded_sha

    async def evalsha(self, sha: str, num_keys: int, *keys_and_args: Any) -> Any:
        self.evalsha_calls.append((sha, num_keys, keys_and_args))
        if self._raise_on_evalsha:
            raise self._raise_on_evalsha.pop(0)
        return self._return_value


class TestLuaRunnerStubRedis:
    @pytest.fixture
    def runner(self) -> LuaRunner:
        r = LuaRunner()
        r.register_text("test_script", "return 42")
        return r

    async def test_success_returns_ok_and_value(self, runner: LuaRunner):
        redis = StubRedis()
        redis.set_return_value(42)
        ok, value = await runner.run(redis, "test_script", keys=["k1"], args=[1, 2])
        assert ok is True
        assert value == 42

    async def test_known_error_token_returned_as_false_tuple(self, runner: LuaRunner):
        redis = StubRedis()
        redis.queue_evalsha_exception(ResponseError("INSUFFICIENT_MANA"))
        ok, token = await runner.run(redis, "test_script", keys=["k1"], args=[])
        assert ok is False
        assert token == "INSUFFICIENT_MANA"

    async def test_unknown_error_still_returns_false(self, runner: LuaRunner):
        redis = StubRedis()
        redis.queue_evalsha_exception(ResponseError("SOMETHING_WEIRD"))
        ok, token = await runner.run(redis, "test_script", keys=[], args=[])
        assert ok is False
        assert token == "SOMETHING_WEIRD"

    async def test_noscript_triggers_reload(self, runner: LuaRunner):
        redis = StubRedis()
        redis.queue_evalsha_exception(NoScriptError("NOSCRIPT"))
        redis.set_return_value(99)
        ok, value = await runner.run(redis, "test_script", keys=[], args=[])
        assert ok is True
        assert value == 99
        # First load happened on initial _ensure_loaded; reload happened after NOSCRIPT.
        assert redis.script_load_calls == 2
        assert len(redis.evalsha_calls) == 2

    async def test_first_run_loads_script(self, runner: LuaRunner):
        redis = StubRedis()
        redis.set_return_value(0)
        await runner.run(redis, "test_script", keys=[], args=[])
        assert redis.script_load_calls == 1

    async def test_second_run_uses_cached_sha(self, runner: LuaRunner):
        redis = StubRedis()
        redis.set_return_value(0)
        await runner.run(redis, "test_script", keys=[], args=[])
        await runner.run(redis, "test_script", keys=[], args=[])
        # Only the first call should have triggered a SCRIPT LOAD.
        assert redis.script_load_calls == 1
        assert len(redis.evalsha_calls) == 2

    async def test_unregistered_script_raises_keyerror(self, runner: LuaRunner):
        redis = StubRedis()
        with pytest.raises(KeyError, match="not registered"):
            await runner.run(redis, "nope", keys=[], args=[])

    def test_double_registration_raises(self):
        r = LuaRunner()
        r.register_text("dup", "return 1")
        with pytest.raises(ValueError, match="already registered"):
            from pathlib import Path
            r.register("dup", Path("/nonexistent"))


class TestKnownErrorTokens:
    """The audit's high-confidence findings depend on these tokens being present."""

    def test_canonical_tokens_present(self):
        for required in [
            "INSUFFICIENT_MANA",
            "INSUFFICIENT_GEMS",
            "DUPLICATE_REQUEST",
            "INSUFFICIENT_PREREQ",
            "GUILD_FULL",
        ]:
            assert required in KNOWN_ERROR_TOKENS


# ─── Real-Redis integration ───────────────────────────────────────────────────


@pytest.mark.integration
class TestLuaRunnerRealRedis:
    """Validates the runner against actual Lua execution in redis:7-alpine."""

    async def test_lua_err_translates_to_false_tuple(self, redis_container):
        runner = LuaRunner()
        runner.register_text("err_script", 'return redis.error_reply("INSUFFICIENT_MANA")')
        ok, token = await runner.run(redis_container, "err_script", keys=[], args=[])
        assert ok is False
        assert token == "INSUFFICIENT_MANA"

    async def test_lua_int_return_translates_to_true_int(self, redis_container):
        runner = LuaRunner()
        runner.register_text("ok_script", "return tonumber(ARGV[1]) + tonumber(ARGV[2])")
        ok, value = await runner.run(redis_container, "ok_script", keys=[], args=[40, 2])
        assert ok is True
        assert value == 42

    async def test_lua_with_keys_can_mutate(self, redis_container):
        runner = LuaRunner()
        runner.register_text(
            "incr_script",
            'return redis.call("INCRBY", KEYS[1], ARGV[1])',
        )
        ok, value = await runner.run(redis_container, "incr_script", keys=["counter"], args=[5])
        assert ok is True
        assert value == 5
        ok, value = await runner.run(redis_container, "incr_script", keys=["counter"], args=[3])
        assert ok is True
        assert value == 8

    async def test_script_flush_triggers_reload(self, redis_container):
        runner = LuaRunner()
        runner.register_text("recoverable", "return 7")
        # First call loads the script and caches the SHA.
        ok, value = await runner.run(redis_container, "recoverable", keys=[], args=[])
        assert (ok, value) == (True, 7)
        # SCRIPT FLUSH wipes the server cache. The next call should hit NOSCRIPT
        # internally and reload transparently.
        await redis_container.script_flush()
        ok, value = await runner.run(redis_container, "recoverable", keys=[], args=[])
        assert (ok, value) == (True, 7)
