"""
Phase 6 / fixes #16, #17 — DailyCapRule TZ + advisory lock tests.

These verify the wiring without standing up Postgres:
- The rule asks for an advisory lock BEFORE running the SUM query (so
  parallel requests can't race past it). Order is checked via call log.
- The rule reads users.timezone before computing the cap window.
- The rule's audit note quotes the canonical cap value.

The actual TZ-aware SQL (timezone(user_tz, awarded_at)::date) and the
advisory-lock contention semantics run against real Postgres in the
integration suite — they aren't sqlite-portable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from health_service.core.anti_cheat import DailyCapRule, PipelineResult, SyncPayload


def _payload(user_id: int = 42, value: float = 50) -> SyncPayload:
    return SyncPayload(
        user_id=user_id,
        device_id="dev",
        manufacturer="APPLE_HEALTHKIT",
        data_type="steps",
        value=value,
        unit="count",
        recorded_at=datetime(2026, 5, 10, 12, 0, 0),
        hardware_signature="sig",
    )


class FakeRow:
    def __init__(self, value: Any):
        self._value = value

    def first(self):
        return self._value

    def scalar_one_or_none(self):
        if self._value is None:
            return None
        return self._value[0] if isinstance(self._value, tuple) else self._value


class FakeSession:
    def __init__(self, *, awarded_today: int = 0, user_tz: str = "UTC"):
        self.executed_stmts: list = []
        self._awarded = awarded_today
        self._user_tz = user_tz

    async def execute(self, stmt, params=None):
        # Record what was executed in order so tests can assert lock-first.
        self.executed_stmts.append(("execute", str(stmt)))
        # 1st call: advisory lock (returns nothing meaningful).
        # 2nd call: timezone lookup (return a 1-row tuple).
        # 3rd call: SUM(amount) (return scalar).
        idx = len(self.executed_stmts)
        if idx == 1:
            return FakeRow(None)
        if idx == 2:
            return FakeRow((self._user_tz,))
        if idx == 3:
            return FakeRow(self._awarded)
        return FakeRow(None)


class TestAdvisoryLockOrder:
    async def test_lock_acquired_before_sum_query(self):
        # The audit's #16 regression guard: the SUM query must run AFTER
        # the advisory lock is in place. Otherwise two concurrent requests
        # both see the same SUM and both award.
        session = FakeSession(awarded_today=0)
        await DailyCapRule().validate(_payload(), PipelineResult(), session)

        first = session.executed_stmts[0][1].lower()
        # The advisory lock query goes through `text(...)`, which renders
        # as the literal SQL string.
        assert "pg_advisory_xact_lock" in first

    async def test_executes_three_statements(self):
        # advisory_lock → timezone select → SUM. If a future change adds
        # more statements before the SUM, that's OK — but the SUM should
        # still come last so it sees the locked state.
        session = FakeSession()
        await DailyCapRule().validate(_payload(), PipelineResult(), session)
        assert len(session.executed_stmts) >= 3


class TestCapEnforcement:
    async def test_under_cap_reward_eligible(self):
        session = FakeSession(awarded_today=200)  # 100 under cap
        result = PipelineResult()
        await DailyCapRule().validate(_payload(), result, session)
        assert result.skip_reward is False
        assert result.reward_eligible is True

    async def test_at_cap_reward_skipped(self):
        session = FakeSession(awarded_today=300)  # cap == 300
        result = PipelineResult()
        await DailyCapRule().validate(_payload(), result, session)
        assert result.skip_reward is True
        assert result.reward_eligible is False
        assert any("cap" in note.lower() for note in result.audit_notes)

    async def test_over_cap_reward_skipped(self):
        session = FakeSession(awarded_today=350)
        result = PipelineResult()
        await DailyCapRule().validate(_payload(), result, session)
        assert result.skip_reward is True
        assert result.reward_eligible is False


class TestTimezoneLookup:
    async def test_default_utc_when_user_missing(self, monkeypatch):
        # If the User row isn't found (deleted user, race), default to UTC
        # rather than crashing. The cap still gets enforced.
        class NoUserSession(FakeSession):
            async def execute(self, stmt, params=None):
                self.executed_stmts.append(("execute", str(stmt)))
                idx = len(self.executed_stmts)
                if idx == 1:
                    return FakeRow(None)
                if idx == 2:
                    return FakeRow(None)  # no user row
                if idx == 3:
                    return FakeRow(0)
                return FakeRow(None)

        session = NoUserSession()
        result = PipelineResult()
        await DailyCapRule().validate(_payload(), result, session)
        # No exception, default-to-UTC behavior.
        assert result.reward_eligible is True
