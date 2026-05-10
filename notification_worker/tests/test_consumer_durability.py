"""
Phase 12 / fix #11 — BLMOVE notification durability tests.

The audit's #11: BLPOP destructively dequeued into worker memory, so
SIGKILL/OOM/container-restart between the dequeue and dispatch lost
the job permanently. BLMOVE-into-processing-list keeps the job in
Redis until success or DLQ; replay_stranded_jobs at boot re-queues
anything left in the processing list from a prior worker.

These tests use a stub Redis to validate the wiring. The actual
crash-recovery semantics are covered in the integration suite.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from notification_worker import consumer


class TestProcessingKey:
    def test_format(self):
        assert consumer.processing_key("notify:stream_a") == "notify:stream_a:processing"
        assert consumer.processing_key("notify:stream_b") == "notify:stream_b:processing"


class TestReplayStrandedJobs:
    async def test_drains_processing_list_into_main_queue(self):
        # Three stranded jobs in the processing list.
        redis = AsyncMock()
        redis.lmove.side_effect = ["job-c", "job-b", "job-a", None]
        moved = await consumer.replay_stranded_jobs(redis, "notify:stream_a")
        assert moved == 3
        # Each call must be (RIGHT → LEFT) so oldest pending re-enters at
        # the head of the queue.
        for call in redis.lmove.call_args_list[:3]:
            kwargs = call.kwargs
            assert kwargs["src"] == "RIGHT"
            assert kwargs["dest"] == "LEFT"
            args = call.args
            assert args == ("notify:stream_a:processing", "notify:stream_a")

    async def test_empty_processing_list_returns_zero(self):
        redis = AsyncMock()
        redis.lmove.return_value = None
        moved = await consumer.replay_stranded_jobs(redis, "notify:stream_a")
        assert moved == 0


class TestConsumeStreamWiring:
    async def test_replay_called_before_first_dequeue(self, monkeypatch):
        # The audit's regression guard: stranded jobs must be drained at
        # boot, BEFORE the consumer starts pulling new jobs. Otherwise a
        # restart could let a fresh job leapfrog a stranded one.
        call_order: list[str] = []

        async def replay(redis, key):
            call_order.append("replay")
            return 0

        async def fake_blmove(*a, **kw):
            call_order.append("blmove")
            # Cancel the loop after the first BLMOVE so the test exits.
            raise __import__("asyncio").CancelledError

        monkeypatch.setattr(consumer, "replay_stranded_jobs", replay)
        redis = AsyncMock()
        redis.blmove.side_effect = fake_blmove

        await consumer.consume_stream(redis, "notify:stream_a")

        assert call_order[0] == "replay"
        assert "blmove" in call_order

    async def test_blmove_uses_processing_list(self, monkeypatch):
        # The atomic dequeue moves into the per-worker processing list.
        captured: list[tuple] = []

        async def blmove(*args, **kwargs):
            captured.append(kwargs)
            raise __import__("asyncio").CancelledError

        async def replay(redis, key):
            return 0

        monkeypatch.setattr(consumer, "replay_stranded_jobs", replay)
        redis = AsyncMock()
        redis.blmove.side_effect = blmove

        await consumer.consume_stream(redis, "notify:stream_a")

        assert len(captured) == 1
        assert captured[0]["src"] == "LEFT"  # head of queue
        assert captured[0]["dest"] == "RIGHT"  # tail of processing list

    async def test_lrem_removes_job_after_processing(self, monkeypatch):
        # After dispatch, the job must be LREM'd from the processing list
        # so it doesn't get replayed on the next boot.
        async def replay(redis, key):
            return 0

        async def stub_process(raw, redis):
            return None

        monkeypatch.setattr(consumer, "replay_stranded_jobs", replay)
        monkeypatch.setattr(consumer, "_process_job", stub_process)

        redis = AsyncMock()
        # First BLMOVE returns a job, second raises CancelledError to exit.
        redis.blmove.side_effect = [
            "the-raw-job",
            __import__("asyncio").CancelledError,
        ]

        await consumer.consume_stream(redis, "notify:stream_a")

        redis.lrem.assert_awaited_once_with(
            "notify:stream_a:processing", 1, "the-raw-job"
        )
