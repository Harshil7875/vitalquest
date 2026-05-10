"""
Phase 2 / fix #2 — Dexcom HMAC fail-closed.

Previously `verify_signature` returned True when the webhook secret was unset,
silently accepting unsigned payloads on any deployment that forgot the
DEXCOM_WEBHOOK_SECRET env var. Now it returns False; the registry route()
caller raises PermissionError, and the request is DLQ'd instead of accepted.
"""

from __future__ import annotations

import hashlib
import hmac

import pytest

from health_service.adapters.dexcom import DexcomAdapter
from health_service.config import settings


@pytest.fixture(autouse=True)
def _swap_secret(monkeypatch):
    """Default each test to a known secret; tests that need empty override."""
    monkeypatch.setattr(settings, "dexcom_webhook_secret", "test-secret-xyz", raising=False)
    yield


class TestDexcomVerifySignature:
    def test_empty_secret_returns_false(self, monkeypatch):
        monkeypatch.setattr(settings, "dexcom_webhook_secret", "", raising=False)
        assert DexcomAdapter().verify_signature(b"any payload", "deadbeef") is False

    def test_valid_signature_returns_true(self):
        body = b'{"events":[]}'
        expected = hmac.new(b"test-secret-xyz", body, hashlib.sha256).hexdigest()
        assert DexcomAdapter().verify_signature(body, expected) is True

    def test_tampered_signature_returns_false(self):
        body = b'{"events":[]}'
        bogus = "0" * 64  # right length, wrong digest
        assert DexcomAdapter().verify_signature(body, bogus) is False

    def test_tampered_body_returns_false(self):
        original_body = b'{"events":[]}'
        tampered_body = b'{"events":[{"foo":1}]}'
        # Sign the original body, present the tampered body — must reject.
        signature = hmac.new(b"test-secret-xyz", original_body, hashlib.sha256).hexdigest()
        assert DexcomAdapter().verify_signature(tampered_body, signature) is False
