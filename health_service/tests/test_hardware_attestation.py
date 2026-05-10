"""
Phase 3 / fix #6 — Hardware HMAC unit tests.

Pure-crypto coverage for canonical_payload, compute_signature, and verify.
The DB-bound lookup_device_key + HardwareVerificationRule integration goes
through the testcontainers-backed integration suite.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from health_service.core.hardware_attestation import (
    canonical_payload,
    compute_signature,
    verify,
)


class TestCanonicalPayload:
    def test_deterministic(self):
        ts = datetime(2026, 5, 10, 12, 0, 0)
        a = canonical_payload(42, "steps", 1234.0, ts)
        b = canonical_payload(42, "steps", 1234.0, ts)
        assert a == b

    def test_user_id_change_affects_payload(self):
        ts = datetime(2026, 5, 10, 12, 0, 0)
        a = canonical_payload(42, "steps", 1234.0, ts)
        b = canonical_payload(43, "steps", 1234.0, ts)
        assert a != b

    def test_value_change_affects_payload(self):
        ts = datetime(2026, 5, 10, 12, 0, 0)
        a = canonical_payload(42, "steps", 1234.0, ts)
        b = canonical_payload(42, "steps", 1235.0, ts)
        assert a != b

    def test_data_type_change_affects_payload(self):
        ts = datetime(2026, 5, 10, 12, 0, 0)
        a = canonical_payload(42, "steps", 1234.0, ts)
        b = canonical_payload(42, "glucose", 1234.0, ts)
        assert a != b

    def test_timestamp_change_affects_payload(self):
        ts1 = datetime(2026, 5, 10, 12, 0, 0)
        ts2 = datetime(2026, 5, 10, 12, 0, 1)
        a = canonical_payload(42, "steps", 1234.0, ts1)
        b = canonical_payload(42, "steps", 1234.0, ts2)
        assert a != b


class TestVerify:
    KEY = b"a-256-bit-symmetric-key-32-bytes"

    @pytest.fixture
    def signed_payload(self):
        ts = datetime(2026, 5, 10, 12, 0, 0)
        canonical = canonical_payload(42, "steps", 1234.0, ts)
        signature = compute_signature(self.KEY, canonical)
        return canonical, signature

    def test_valid_signature(self, signed_payload):
        canonical, signature = signed_payload
        assert verify(self.KEY, canonical, signature) is True

    def test_empty_signature_rejected(self, signed_payload):
        canonical, _ = signed_payload
        assert verify(self.KEY, canonical, "") is False

    def test_wrong_key_rejected(self, signed_payload):
        canonical, signature = signed_payload
        assert verify(b"wrong-key-also-32-bytes-long-xx", canonical, signature) is False

    def test_tampered_payload_rejected(self, signed_payload):
        _, signature = signed_payload
        ts = datetime(2026, 5, 10, 12, 0, 0)
        # Sign value=1234, present value=9999.
        tampered = canonical_payload(42, "steps", 9999.0, ts)
        assert verify(self.KEY, tampered, signature) is False

    def test_tampered_signature_rejected(self, signed_payload):
        canonical, signature = signed_payload
        flipped = signature[:-1] + ("0" if signature[-1] != "0" else "1")
        assert verify(self.KEY, canonical, flipped) is False

    def test_truncated_signature_rejected(self, signed_payload):
        canonical, signature = signed_payload
        assert verify(self.KEY, canonical, signature[:32]) is False
