"""
Phase 2 / fix #3 — OAuth state nonce CSRF defense.

Verifies that mint_state stores a TTL'd `oauth_state:{nonce}` → user_id mapping
in Redis, and that verify_state redeems it via GETDEL — so a leaked state can't
be replayed against a different user, can't be used twice, and expires.
"""

from __future__ import annotations

import pytest

from health_service.core import oauth_state


class FakeRedis:
    """Minimal in-memory async Redis shim covering set(ex=...) and getdel."""

    def __init__(self) -> None:
        self.store: dict[str, tuple[str, int | None]] = {}
        self.set_calls: list[tuple[str, str, int | None]] = []

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.set_calls.append((key, value, ex))
        self.store[key] = (value, ex)
        return True

    async def getdel(self, key: str) -> str | None:
        entry = self.store.pop(key, None)
        return entry[0] if entry is not None else None


@pytest.fixture
def fake_redis(monkeypatch) -> FakeRedis:
    fake = FakeRedis()

    async def _get_redis():
        return fake

    monkeypatch.setattr(oauth_state, "get_redis", _get_redis)
    return fake


class TestMintState:
    async def test_returns_url_safe_token(self, fake_redis):
        nonce = await oauth_state.mint_state(user_id=42)
        assert isinstance(nonce, str)
        assert len(nonce) >= 32  # token_urlsafe(32) yields ~43 chars

    async def test_stores_with_ttl(self, fake_redis):
        nonce = await oauth_state.mint_state(user_id=42)
        key, value, ttl = fake_redis.set_calls[-1]
        assert key == f"oauth_state:{nonce}"
        assert value == "42"
        assert ttl == oauth_state.STATE_TTL_SECONDS

    async def test_each_call_unique(self, fake_redis):
        a = await oauth_state.mint_state(user_id=1)
        b = await oauth_state.mint_state(user_id=1)
        assert a != b


class TestVerifyState:
    async def test_happy_path(self, fake_redis):
        nonce = await oauth_state.mint_state(user_id=42)
        assert await oauth_state.verify_state(nonce, expected_user_id=42) is True

    async def test_consumed_after_first_verify(self, fake_redis):
        nonce = await oauth_state.mint_state(user_id=42)
        assert await oauth_state.verify_state(nonce, expected_user_id=42) is True
        # Replay must fail — getdel removed it on first redemption.
        assert await oauth_state.verify_state(nonce, expected_user_id=42) is False

    async def test_wrong_user_rejected_and_consumed(self, fake_redis):
        nonce = await oauth_state.mint_state(user_id=42)
        # Attacker tries to bind state for user 99.
        assert await oauth_state.verify_state(nonce, expected_user_id=99) is False
        # And the state is consumed — even the original user can't redeem it now.
        assert await oauth_state.verify_state(nonce, expected_user_id=42) is False

    async def test_unknown_state_rejected(self, fake_redis):
        assert (
            await oauth_state.verify_state("never-minted-state", expected_user_id=1)
            is False
        )
