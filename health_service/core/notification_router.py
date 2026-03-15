"""
Secure Notification Router — "Clean Payload" policy.

Health reminders are never sent as human-readable text through third-party
push notification services (APNs/FCM) because that would leak PHI to Apple
and Google. Instead, the backend issues opaque trigger codes. The mobile
client holds the decryption table locally and renders the actual text on-device.

The mapping is server-side only and never returned to the client directly.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Server-side mapping: event_type → opaque trigger code
# The client app contains the reverse map to render human-readable text.
_TRIGGER_MAP: dict[str, str] = {
    "medication_reminder": "ACTION_REQUIRED_01",
    "glucose_check": "ACTION_REQUIRED_02",
    "blood_pressure_log": "ACTION_REQUIRED_03",
    "step_goal_reminder": "ACTION_REQUIRED_04",
    "weekly_export_ready": "ACTION_REQUIRED_05",
    "appointment_reminder": "ACTION_REQUIRED_06",
    "insulin_dose_window": "ACTION_REQUIRED_07",
    "cgm_calibration": "ACTION_REQUIRED_08",
    "hydration_reminder": "ACTION_REQUIRED_09",
    "sleep_log_prompt": "ACTION_REQUIRED_10",
    # Game notifications — these are safe to send as plain text via FCM/APNs
    "guild_raid_starting": "GAME_EVENT_01",
    "sanctuary_upgrade_complete": "GAME_EVENT_02",
    "daily_quest_available": "GAME_EVENT_03",
    "boss_defeated": "GAME_EVENT_04",
    "mana_cap_reached": "GAME_EVENT_05",
}


def generate_trigger_code(event_type: str) -> str:
    """
    Returns the opaque trigger code for a given event type.
    Raises ValueError for unknown event types rather than silently leaking
    a plain-text fallback.
    """
    code = _TRIGGER_MAP.get(event_type)
    if code is None:
        raise ValueError(
            f"Unknown event_type '{event_type}'. Register it in _TRIGGER_MAP "
            "before sending push notifications."
        )
    return code


def is_health_notification(event_type: str) -> bool:
    """Health reminders require the clean-payload routing path."""
    code = _TRIGGER_MAP.get(event_type, "")
    return code.startswith("ACTION_REQUIRED_")
