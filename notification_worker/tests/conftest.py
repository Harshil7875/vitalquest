"""Test env defaults for notification_worker."""
from __future__ import annotations

import os

os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("APNS_KEY_PATH", "")
os.environ.setdefault("APNS_KEY_ID", "")
os.environ.setdefault("APNS_TEAM_ID", "")
os.environ.setdefault("FCM_SERVER_KEY", "")
