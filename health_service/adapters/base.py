"""
Adapter Base — VitalQuestStandardPayload and BaseAdapter contract.

All health data entering the system must be normalized to this format
before being passed to the anti-cheat engine or goal evaluator.
This decouples core business logic from third-party API shapes.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class MetricType(str, Enum):
    """Internal canonical metric names. All adapters map to these."""
    STEPS = "steps"
    GLUCOSE = "glucose"
    HEART_RATE = "heart_rate"
    MEDICATION_DOSE = "medication"
    DIET_LOG = "diet"
    BLOOD_PRESSURE_SYSTOLIC = "blood_pressure_systolic"
    BLOOD_PRESSURE_DIASTOLIC = "blood_pressure_diastolic"
    SLEEP_HOURS = "sleep_hours"
    WEIGHT_KG = "weight_kg"


@dataclass
class VitalQuestStandardPayload:
    """
    The universal format understood by anti_cheat.py and goal_evaluator.py.
    All raw provider payloads are translated into this before core processing.
    """
    user_id: int
    device_id: str
    manufacturer: str           # canonical: "APPLE_HEALTHKIT", "GOOGLE_FIT", etc.
    metric_type: MetricType
    value: float                # always in the internal baseline unit
    unit: str                   # always the internal baseline unit string
    recorded_at: datetime       # always UTC
    hardware_signature: str | None = None
    raw_source_type: str = ""   # original proprietary type string, for audit


# ─── Unit Conversion Helpers ──────────────────────────────────────────────────

def mmol_l_to_mg_dl(mmol: float) -> float:
    """European CGMs often report in mmol/L. Internal baseline is mg/dL."""
    return round(mmol * 18.0182, 1)


def mg_dl_to_mmol_l(mg_dl: float) -> float:
    return round(mg_dl / 18.0182, 2)


def lbs_to_kg(lbs: float) -> float:
    return round(lbs * 0.453592, 2)


def normalize_timestamp(dt: datetime, user_timezone_offset_hours: float = 0.0) -> datetime:
    """
    Ensures all timestamps are stored as UTC.
    If the incoming datetime is naive (no tzinfo), apply the user's timezone
    offset to interpret it, then convert to UTC.
    """
    if dt.tzinfo is None:
        from datetime import timedelta
        offset = timedelta(hours=user_timezone_offset_hours)
        dt = dt.replace(tzinfo=timezone(offset))
    return dt.astimezone(timezone.utc).replace(tzinfo=None)  # store as naive UTC


# ─── Base Adapter ──────────────────────────────────────────────────────────────

class BaseAdapter(abc.ABC):
    """
    All source-specific adapters implement this interface.
    The core engine only calls `adapt()` — it never knows which adapter ran.
    """

    @abc.abstractmethod
    def adapt(self, user_id: int, raw_body: dict[str, Any]) -> list[VitalQuestStandardPayload]:
        """
        Translate a raw provider payload into one or more standard payloads.
        One sync from Apple HealthKit can carry multiple metric types.
        """
        ...

    @abc.abstractmethod
    def verify_signature(self, raw_body: bytes, signature_header: str) -> bool:
        """
        Cryptographic verification that the payload originates from the
        claimed hardware or cloud source. Returns False if verification fails.
        """
        ...
