"""
Adapter Registry

Routes incoming health data to the correct adapter based on source.
The core health pipeline only interacts with this registry — it never
imports a concrete adapter directly.
"""

from __future__ import annotations

import logging
from typing import Any

from health_service.adapters.apple_healthkit import AppleHealthKitAdapter
from health_service.adapters.base import BaseAdapter, VitalQuestStandardPayload
from health_service.adapters.dexcom import DexcomAdapter
from health_service.adapters.google_fit import GoogleFitAdapter

logger = logging.getLogger(__name__)

# Adapter instances are singletons — initialized once at startup
# App signing secrets should be loaded from env in production
_REGISTRY: dict[str, BaseAdapter] = {}


def initialize_registry(app_signing_secret: str = "") -> None:
    """Called once at health_service startup to wire adapters."""
    global _REGISTRY
    _REGISTRY = {
        "apple_healthkit": AppleHealthKitAdapter(app_signing_secret),
        "google_fit": GoogleFitAdapter(app_signing_secret),
        "dexcom": DexcomAdapter(),
    }
    logger.info("Adapter registry initialized with sources: %s", list(_REGISTRY.keys()))


def get_adapter(source: str) -> BaseAdapter:
    """
    Returns the adapter for the given source identifier.
    Raises ValueError for unknown sources to prevent silent failures.
    """
    adapter = _REGISTRY.get(source.lower())
    if adapter is None:
        raise ValueError(
            f"No adapter registered for source '{source}'. "
            f"Registered sources: {list(_REGISTRY.keys())}"
        )
    return adapter


def route(
    source: str,
    user_id: int,
    raw_body: dict[str, Any],
    raw_bytes: bytes,
    signature_header: str,
) -> list[VitalQuestStandardPayload]:
    """
    Full pipeline: verify signature → adapt payload.
    Returns list of standard payloads, or raises on signature failure.
    """
    adapter = get_adapter(source)

    if not adapter.verify_signature(raw_bytes, signature_header):
        raise PermissionError(
            f"Signature verification failed for source '{source}'. "
            "Payload may be tampered or from an untrusted origin."
        )

    payloads = adapter.adapt(user_id, raw_body)
    logger.info(
        "Adapter '%s' produced %d standard payloads for user_id=%d.",
        source,
        len(payloads),
        user_id,
    )
    return payloads
