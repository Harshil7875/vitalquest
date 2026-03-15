"""
Apple HealthKit Adapter (Pathway A: Device-to-Cloud)

Apple does not have a server-queryable health API. The VitalQuest mobile app
reads the local HealthKit database on the device, packages the data into
a signed JSON payload, and POSTs it to /api/health/sync.

The adapter's job:
  1. Verify the app signature (the mobile client signs the payload with a
     device-bound key to prove the app wasn't tampered with).
  2. Map Apple's proprietary HKQuantityTypeIdentifier strings to MetricType.
  3. Normalize units (HealthKit sends kg, but some locales show lbs; we store kg).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime
from typing import Any

from health_service.adapters.base import (
    BaseAdapter,
    MetricType,
    VitalQuestStandardPayload,
    lbs_to_kg,
    mmol_l_to_mg_dl,
    normalize_timestamp,
)

logger = logging.getLogger(__name__)

# Apple's internal type identifiers → our canonical MetricType
_HK_TYPE_MAP: dict[str, MetricType] = {
    "HKQuantityTypeIdentifierStepCount": MetricType.STEPS,
    "HKQuantityTypeIdentifierBloodGlucose": MetricType.GLUCOSE,
    "HKQuantityTypeIdentifierHeartRate": MetricType.HEART_RATE,
    "HKQuantityTypeIdentifierBodyMass": MetricType.WEIGHT_KG,
    "HKQuantityTypeIdentifierBloodPressureSystolic": MetricType.BLOOD_PRESSURE_SYSTOLIC,
    "HKQuantityTypeIdentifierBloodPressureDiastolic": MetricType.BLOOD_PRESSURE_DIASTOLIC,
    "HKCategoryTypeIdentifierSleepAnalysis": MetricType.SLEEP_HOURS,
}

# Expected unit for each type (Apple's canonical units)
_HK_BASELINE_UNITS: dict[MetricType, str] = {
    MetricType.STEPS: "count",
    MetricType.GLUCOSE: "mg/dL",
    MetricType.HEART_RATE: "count/min",
    MetricType.WEIGHT_KG: "kg",
    MetricType.BLOOD_PRESSURE_SYSTOLIC: "mmHg",
    MetricType.BLOOD_PRESSURE_DIASTOLIC: "mmHg",
    MetricType.SLEEP_HOURS: "hr",
}


class AppleHealthKitAdapter(BaseAdapter):
    """
    Parses HealthKit payloads submitted by the iOS VitalQuest app.

    Expected shape:
    {
        "app_signature": "<hex>",
        "device_id": "<uuid>",
        "timezone_offset_hours": -5.0,
        "samples": [
            {
                "type": "HKQuantityTypeIdentifierStepCount",
                "value": 5000,
                "unit": "count",
                "start_date": "2024-01-15T08:00:00",
                "end_date": "2024-01-15T23:59:59"
            }, ...
        ]
    }
    """

    MANUFACTURER = "APPLE_HEALTHKIT"

    def __init__(self, app_signing_secret: str):
        self._signing_secret = app_signing_secret.encode()

    def verify_signature(self, raw_body: bytes, signature_header: str) -> bool:
        expected = hmac.new(self._signing_secret, raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature_header)

    def adapt(self, user_id: int, raw_body: dict[str, Any]) -> list[VitalQuestStandardPayload]:
        device_id = raw_body.get("device_id", "unknown")
        tz_offset = float(raw_body.get("timezone_offset_hours", 0.0))
        app_signature = raw_body.get("app_signature")
        samples = raw_body.get("samples", [])

        payloads: list[VitalQuestStandardPayload] = []

        for sample in samples:
            hk_type = sample.get("type", "")
            metric_type = _HK_TYPE_MAP.get(hk_type)
            if metric_type is None:
                logger.debug("Unknown HealthKit type '%s', skipping sample.", hk_type)
                continue

            raw_value = float(sample.get("value", 0))
            raw_unit = sample.get("unit", "")
            recorded_str = sample.get("start_date") or sample.get("end_date")
            recorded_at = normalize_timestamp(
                datetime.fromisoformat(recorded_str),
                tz_offset,
            )

            # Unit normalization
            value, unit = _normalize_hk_units(metric_type, raw_value, raw_unit)

            payloads.append(
                VitalQuestStandardPayload(
                    user_id=user_id,
                    device_id=device_id,
                    manufacturer=self.MANUFACTURER,
                    metric_type=metric_type,
                    value=value,
                    unit=unit,
                    recorded_at=recorded_at,
                    hardware_signature=app_signature,
                    raw_source_type=hk_type,
                )
            )

        return payloads


def _normalize_hk_units(
    metric_type: MetricType, value: float, raw_unit: str
) -> tuple[float, str]:
    """Convert to VitalQuest internal baseline units."""
    if metric_type == MetricType.GLUCOSE:
        if raw_unit.lower() in ("mmol/l", "mmol"):
            return mmol_l_to_mg_dl(value), "mg/dL"
        return value, "mg/dL"

    if metric_type == MetricType.WEIGHT_KG:
        if raw_unit.lower() in ("lb", "lbs"):
            return lbs_to_kg(value), "kg"
        return value, "kg"

    baseline_unit = _HK_BASELINE_UNITS.get(metric_type, raw_unit)
    return value, baseline_unit
