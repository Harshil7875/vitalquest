"""Unit tests for health_service.core.crypto."""

from __future__ import annotations

import pytest

from health_service.core.crypto import (
    EncryptedString,
    decrypt_str,
    encrypt_str,
    lookup_hash,
)


class TestEncryptDecrypt:
    def test_round_trip_ascii(self):
        ct = encrypt_str("user@example.com")
        assert ct != "user@example.com"
        assert decrypt_str(ct) == "user@example.com"

    def test_round_trip_unicode(self):
        ct = encrypt_str("ünïcødé 🔒 emoji")
        assert decrypt_str(ct) == "ünïcødé 🔒 emoji"

    def test_round_trip_empty_string(self):
        ct = encrypt_str("")
        assert decrypt_str(ct) == ""

    def test_each_encryption_is_unique(self):
        # Fernet tokens include a random IV, so the same plaintext produces
        # different ciphertexts every time. Critical for indistinguishability.
        ct1 = encrypt_str("same plaintext")
        ct2 = encrypt_str("same plaintext")
        assert ct1 != ct2
        assert decrypt_str(ct1) == decrypt_str(ct2) == "same plaintext"

    def test_encrypt_none_raises(self):
        with pytest.raises(ValueError, match="None"):
            encrypt_str(None)  # type: ignore[arg-type]

    def test_decrypt_none_raises(self):
        with pytest.raises(ValueError, match="None"):
            decrypt_str(None)  # type: ignore[arg-type]

    def test_decrypt_garbage_raises(self):
        with pytest.raises(RuntimeError, match="invalid|tampered|different key"):
            decrypt_str("not-a-fernet-token")

    def test_decrypt_tampered_raises(self):
        ct = encrypt_str("hello")
        # Flip a byte in the middle — should fail HMAC
        tampered = ct[:20] + ("X" if ct[20] != "X" else "Y") + ct[21:]
        with pytest.raises(RuntimeError):
            decrypt_str(tampered)


class TestLookupHash:
    def test_deterministic(self):
        assert lookup_hash("user@example.com") == lookup_hash("user@example.com")

    def test_distinct_inputs_distinct_outputs(self):
        assert lookup_hash("a@x.com") != lookup_hash("b@x.com")

    def test_case_sensitive(self):
        # Callers are responsible for case-folding before hashing.
        assert lookup_hash("User@X.com") != lookup_hash("user@x.com")

    def test_hex_format(self):
        h = lookup_hash("user@example.com")
        assert len(h) == 64  # SHA-256 hex
        assert all(c in "0123456789abcdef" for c in h)

    def test_distinct_from_encryption_key(self):
        # The lookup HMAC key is derived from the encryption key but must
        # not equal it — key separation is the whole point.
        from health_service.config import settings
        h = lookup_hash(settings.encryption_key)
        assert h != settings.encryption_key


class TestEncryptedStringTypeDecorator:
    def test_bind_param_encrypts(self):
        td = EncryptedString()
        encrypted = td.process_bind_param("plaintext value", dialect=None)
        assert encrypted != "plaintext value"
        # Sanity check: the round-trip works through the decorator.
        assert td.process_result_value(encrypted, dialect=None) == "plaintext value"

    def test_bind_param_none_passthrough(self):
        td = EncryptedString()
        assert td.process_bind_param(None, dialect=None) is None

    def test_result_value_none_passthrough(self):
        td = EncryptedString()
        assert td.process_result_value(None, dialect=None) is None
