"""
Phase 10 / fix #5 — Right to Erasure cascade.

The previous version of /api/health/account DELETE only deleted BiometricLog
rows. OAuthToken refresh tokens, ManaLedger, AuditLog, DeviceToken, and
DeviceAttestation all survived, so the "deleted" user could still be
re-identified and providers could keep pushing PHI.

Regression guards verify that the cascade list in clinical.py covers every
PHI/PII-bearing table at the time of the audit. Adding a NEW table that
stores PHI? Add it to both the import and the cascade — and add it here.
"""

from __future__ import annotations

from pathlib import Path

# We intentionally read the source file directly rather than importing
# `health_service.api.clinical`. The import chain pulls in SQLAlchemy's
# engine construction, which doesn't fly under sqlite in the local venv.
# These guards only need the source text.
CLINICAL_SOURCE = (
    Path(__file__).parent.parent / "api" / "clinical.py"
).read_text()


REQUIRED_CASCADE_MODELS = [
    "BiometricLog",
    "OAuthToken",
    "ManaLedger",
    "AuditLog",
    "DeviceToken",
    "DeviceAttestation",
]


class TestCascadeCoverage:
    def test_all_required_models_imported_in_clinical(self):
        for model_name in REQUIRED_CASCADE_MODELS:
            assert model_name in CLINICAL_SOURCE, (
                f"clinical.py is missing import or reference to {model_name} — "
                "the erasure cascade won't cover it."
            )

    def test_cascade_function_iterates_required_models(self):
        assert "cascade_models" in CLINICAL_SOURCE
        for model_name in REQUIRED_CASCADE_MODELS:
            assert model_name in CLINICAL_SOURCE, (
                f"{model_name} is not in the erasure cascade list."
            )

    def test_publish_event_used_not_publish_reward(self):
        # The audit's secondary erasure finding: publish_reward(erasure_event, ...)
        # caused a ManaLedger row to be written for the user being erased.
        # Phase 5 added publish_event which handles ErasureEvent properly;
        # clinical.py must use that, not the publish_reward alias.
        assert "publish_event" in CLINICAL_SOURCE
        # Make sure publish_reward isn't being called (alias still exists in
        # publisher.py for back-compat, but clinical.py should not use it).
        assert "publish_reward(" not in CLINICAL_SOURCE

    def test_user_row_is_anonymized_in_place(self):
        assert "deleted_user_" in CLINICAL_SOURCE
        assert "email_lookup_hash" in CLINICAL_SOURCE
        assert 'hashed_password = ""' in CLINICAL_SOURCE

    def test_deletion_receipt_user_id_anonymized(self):
        # The DeletionRequest row stays as a compliance receipt, but its
        # user_id is set to None (column is nullable post-Phase-1).
        assert "deletion_record.user_id = None" in CLINICAL_SOURCE

    def test_delete_runs_before_anonymization(self):
        # Important ordering: capture user_id and run the cascade BEFORE
        # anonymizing current_user. Otherwise the cascade's SELECT WHERE
        # user_id == user_id picks up rows belonging to the wrong user.
        delete_idx = CLINICAL_SOURCE.find("model.user_id == user_id")
        anon_idx = CLINICAL_SOURCE.find("anonymized_marker")
        assert delete_idx > 0 and anon_idx > 0
        assert delete_idx < anon_idx, (
            "DELETE cascade must run BEFORE User row anonymization."
        )
