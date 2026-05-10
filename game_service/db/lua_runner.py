"""
Lua script runner with idempotent registration and proper error translation.

Why this exists:
  Lua scripts in this service signal recoverable failures with `return {err = "..."}`.
  The redis-py client raises that as `redis.exceptions.ResponseError`. The
  pre-existing callers in `redis_client.py` checked `if isinstance(result, str)`,
  which never matched — meaning `INSUFFICIENT_MANA` and `DUPLICATE_REQUEST` errors
  bubbled to FastAPI as 500s instead of 400s/409s. This runner translates them
  into a structured `(ok, value)` tuple.

Key tokens we recognize (match these in Lua scripts):
  INSUFFICIENT_MANA     — caller didn't have enough Mana
  INSUFFICIENT_GEMS     — caller didn't have enough Astral Gems
  INSUFFICIENT_PREREQ   — sanctuary tech-tree prerequisites not met
  DUPLICATE_REQUEST     — idempotency_key already processed
  GUILD_FULL            — guild roster at member_cap
  ALREADY_IN_GUILD      — caller is already a member of a guild
  NOT_GUILDMASTER       — caller is not the guildmaster
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import redis.asyncio as aioredis
from redis.exceptions import NoScriptError, ResponseError

logger = logging.getLogger(__name__)

KNOWN_ERROR_TOKENS = frozenset({
    "INSUFFICIENT_MANA",
    "INSUFFICIENT_GEMS",
    "INSUFFICIENT_PREREQ",
    "DUPLICATE_REQUEST",
    "GUILD_FULL",
    "ALREADY_IN_GUILD",
    "NOT_GUILDMASTER",
    "BUILD_IN_PROGRESS",
    "MAX_TIER_REACHED",
    "BOSS_DEFEATED",
    "TIMER_NOT_ACTIVE",
    "CHEST_EMPTY",
})


class LuaRunner:
    """
    Registers Lua scripts at module import and runs them via EVALSHA, falling
    back to EVAL when the server has flushed its script cache.
    """

    def __init__(self) -> None:
        self._registry: dict[str, str] = {}
        self._sha_cache: dict[str, str] = {}

    def register(self, name: str, path: Path) -> None:
        if name in self._registry:
            raise ValueError(f"Lua script '{name}' is already registered.")
        text = path.read_text()
        self._registry[name] = text
        # SHA is populated lazily on first run via SCRIPT LOAD.

    def register_text(self, name: str, text: str) -> None:
        """Register a script from inline text — primarily for tests."""
        self._registry[name] = text
        self._sha_cache.pop(name, None)

    async def _ensure_loaded(self, redis: aioredis.Redis, name: str) -> str:
        sha = self._sha_cache.get(name)
        if sha is None:
            text = self._registry[name]
            sha = await redis.script_load(text)
            self._sha_cache[name] = sha
        return sha

    async def run(
        self,
        redis: aioredis.Redis,
        name: str,
        keys: list[str],
        args: list[Any],
    ) -> tuple[bool, Any]:
        """
        Execute a registered script atomically.

        Returns:
            (True, value)  — Lua return value on success (int, list, bytes, ...)
            (False, token) — Lua signaled `{err = "..."}`. Token is one of
                             KNOWN_ERROR_TOKENS, or the raw error string.
        """
        if name not in self._registry:
            raise KeyError(f"Lua script '{name}' is not registered.")

        try:
            sha = await self._ensure_loaded(redis, name)
            try:
                result = await redis.evalsha(sha, len(keys), *keys, *args)
            except NoScriptError:
                # Server flushed its script cache (e.g. SCRIPT FLUSH or restart).
                # Reload and retry once.
                logger.info("NOSCRIPT for %s — reloading.", name)
                self._sha_cache.pop(name, None)
                sha = await self._ensure_loaded(redis, name)
                result = await redis.evalsha(sha, len(keys), *keys, *args)
            return (True, result)
        except ResponseError as exc:
            token = str(exc.args[0]) if exc.args else str(exc)
            if token not in KNOWN_ERROR_TOKENS:
                # Unknown error from Lua — log loudly so we notice unexpected
                # failure modes during development.
                logger.warning("Lua script '%s' returned unknown error token: %s", name, token)
            return (False, token)


# Module-level singleton, initialized lazily by callers via register().
runner = LuaRunner()


# ─── Script registration ──────────────────────────────────────────────────────

_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"


def register_default_scripts() -> None:
    """
    Register every .lua script in game_service/scripts/. Called once at
    game_service startup. Idempotent — re-registration is a no-op only if
    the script is registered with the same name; the LuaRunner guards against
    accidental double-registration with different content.
    """
    for path in sorted(_SCRIPTS_DIR.glob("*.lua")):
        name = path.stem
        if name in runner._registry:
            continue
        runner.register(name, path)
        logger.debug("Registered Lua script '%s' from %s", name, path)
