"""
Google Fit / Health Connect Adapter (Pathway A: Device-to-Cloud)

Like Apple, Google Health Connect stores data on-device. The VitalQuest
Android app reads it and POSTs to /api/health/sync.

Google Fit uses numeric activity_type codes and a different data structure.
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

# Google Fit data type names → canonical MetricType
_GFIT_TYPE_MAP: dict[str, MetricType] = {
    "com.google.step_count.delta": MetricType.STEPS,
    "com.google.blood_glucose": MetricType.GLUCOSE,
    "com.google.heart_rate.bpm": MetricType.HEART_RATE,
    "com.google.weight": MetricType.WEIGHT_KG,
    "com.google.blood_pressure": MetricType.BLOOD_PRESSURE_SYSTOLIC,
    "com.google.sleep.segment": MetricType.SLEEP_HOURS,
}


class GoogleFitAdapter(BaseAdapter):
    """
    Parses Google Health Connect payloads submitted by the Android app.

    Expected shape:
    {
        "app_signature": "<hex>",
        "device_id": "<android_device_id>",
        "timezone_offset_hours": 5.5,
        "data_points": [
            {
                "dataTypeName": "com.google.step_count.delta",
                "startTimeMillis": 1705276800000,
                "endTimeMillis": 1705363200000,
                "value": [{"intVal": 6200}],
                "originDataSourceId": "raw:com.google.android.gms.fitness"
            }, ...
        ]
    }
    """

    MANUFACTURER = "GOOGLE_FIT"

    def __init__(self, app_signing_secret: str):
        self._signing_secret = app_signing_secret.encode()

    def verify_signature(self, raw_body: bytes, signature_header: str) -> bool:
        expected = hmac.new(self._signing_secret, raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature_header)

    def adapt(self, user_id: int, raw_body: dict[str, Any]) -> list[VitalQuestStandardPayload]:
        device_id = raw_body.get("device_id", "unknown")
        tz_offset = float(raw_body.get("timezone_offset_hours", 0.0))
        app_signature = raw_body.get("app_signature")
        data_points = raw_body.get("data_points", [])

        payloads: list[VitalQuestStandardPayload] = []

        for dp in data_points:
            gfit_type = dp.get("dataTypeName", "")
            metric_type = _GFIT_TYPE_MAP.get(gfit_type)
            if metric_type is None:
                logger.debug("Unknown Google Fit type '%s', skipping.", gfit_type)
                continue

            raw_value = _extract_gfit_value(dp)
            if raw_value is None:
                continue

            # Google uses millisecond epoch timestamps
            end_ms = dp.get("endTimeMillis") or dp.get("startTimeMillis", 0)
            recorded_at = normalize_timestamp(
                datetime.utcfromtimestamp(int(end_ms) / 1000.0),
                tz_offset,
            )

            value, unit = _normalize_gfit_units(metric_type, raw_value)

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
                    raw_source_type=gfit_type,
                )
            )

        return payloads


def _extract_gfit_value(data_point: dict) -> float | None:
    """Google Fit value arrays can contain intVal or fpVal."""
    values = data_point.get("value", [])
    if not values:
        return None
    v = values[0]
    if "fpVal" in v:
        return float(v["fpVal"])
    if "intVal" in v:
        return float(v["intVal"])
    return None


def _normalize_gfit_units(metric_type: MetricType, value: float) -> tuple[float, str]:
    """Google Fit baseline units vary; normalize to VitalQuest internal units."""
    if metric_type == MetricType.GLUCOSE:
        # Google Fit reports glucose in mmol/L by default
        return mmol_l_to_mg_dl(value), "mg/dL"
    if metric_type == MetricType.WEIGHT_KG:
        return value, "kg"  # Google uses kg
    if metric_type == MetricType.STEPS:
        return value, "count"
    if metric_type == MetricType.HEART_RATE:
        return value, "count/min"
    if metric_type == MetricType.SLEEP_HOURS:
        # Google reports sleep in milliseconds
        return round(value / 3_600_000, 2), "hr"
    return value, ""
