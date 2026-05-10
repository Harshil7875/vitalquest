"""
Source-level guards for the device-attestation enrollment flow.

Mirrors the Phase 10 test pattern — Path.read_text() inspection rather than
importing the FastAPI app, since the app's import chain spins up the
SQLAlchemy engine which doesn't behave under sqlite. End-to-end behavior
(actual enrollment via real Postgres) goes through the integration suite.
"""

from __future__ import annotations

from pathlib import Path

DEVICES_SOURCE = (
    Path(__file__).parent.parent / "api" / "devices.py"
).read_text()


class TestEndpointSurface:
    def test_three_endpoints_declared(self):
        # POST /enroll, GET (list), DELETE /{manufacturer}/{device_id}
        assert '@router.post("/enroll"' in DEVICES_SOURCE
        assert '@router.get("",' in DEVICES_SOURCE
        assert '@router.delete(' in DEVICES_SOURCE
        assert '"/{manufacturer}/{device_id}"' in DEVICES_SOURCE

    def test_enroll_returns_201(self):
        assert "status.HTTP_201_CREATED" in DEVICES_SOURCE

    def test_revoke_returns_204(self):
        assert "status.HTTP_204_NO_CONTENT" in DEVICES_SOURCE


class TestKeyHandling:
    def test_uses_secrets_token_bytes_for_key(self):
        # The audit's #6 fix depends on the per-device key being unguessable.
        # secrets.token_bytes pulls from the OS CSPRNG; random.random() does
        # NOT. This guard catches accidental downgrades.
        assert "secrets.token_bytes(HMAC_KEY_BYTES)" in DEVICES_SOURCE

    def test_key_is_32_bytes(self):
        assert "HMAC_KEY_BYTES = 32" in DEVICES_SOURCE

    def test_key_returned_only_in_enroll_response(self):
        # The list endpoint must NEVER include the HMAC key. Guard against
        # someone "helpfully" exposing it on /devices for debugging.
        assert "DeviceListItem" in DEVICES_SOURCE
        # DeviceListItem field set must not include hmac_key.
        list_block_start = DEVICES_SOURCE.index("class DeviceListItem")
        list_block_end = DEVICES_SOURCE.index("class DeviceListResponse")
        list_block = DEVICES_SOURCE[list_block_start:list_block_end]
        assert "hmac_key" not in list_block.lower()

    def test_key_stored_via_encrypted_string(self):
        # The hmac_key_encrypted column is EncryptedString, so assigning
        # plaintext encrypts it on bind. Confirm we're using that column
        # name (Phase 1 invariant).
        assert "hmac_key_encrypted=key_b64" in DEVICES_SOURCE


class TestEnrollDedupe:
    def test_409_on_existing_active_attestation(self):
        # The audit-flagged abuse: re-enrollment silently rotating the key
        # would let an attacker who owns the JWT shadow the legit device.
        # Forcing explicit revoke-then-enroll surfaces the rotation in audit
        # logs and lets the user notice.
        assert "HTTP_409_CONFLICT" in DEVICES_SOURCE
        assert "revoked_at.is_(None)" in DEVICES_SOURCE


class TestRevocationSemantics:
    def test_soft_delete_sets_revoked_at(self):
        # Hard-delete would lose the audit trail. Soft-delete preserves
        # the row so we can prove "this device WAS enrolled and is now
        # revoked" for compliance reviews.
        assert "attestation.revoked_at = datetime.utcnow()" in DEVICES_SOURCE

    def test_404_when_no_active_attestation_matches(self):
        # Trying to revoke a non-existent or already-revoked device must
        # 404 — no silent success.
        assert "HTTP_404_NOT_FOUND" in DEVICES_SOURCE


class TestManufacturerValidation:
    def test_uppercases_manufacturer_input(self):
        # User-facing input is case-insensitive; storage is canonical
        # (uppercase to match ALLOWED_MANUFACTURERS in anti_cheat.py).
        assert "manufacturer.upper()" in DEVICES_SOURCE

    def test_rejects_non_allowlisted_manufacturer(self):
        assert "ALLOWED_MANUFACTURERS" in DEVICES_SOURCE
        assert "HTTP_400_BAD_REQUEST" in DEVICES_SOURCE


class TestRouterMounted:
    def test_devices_router_in_main(self):
        main_source = (
            Path(__file__).parent.parent / "main.py"
        ).read_text()
        assert "from health_service.api.devices" in main_source
        assert "app.include_router(devices_router)" in main_source
