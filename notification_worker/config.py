from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    redis_url: str

    # APNs credentials (iOS)
    apns_key_path: str = ""          # path to .p8 key file
    apns_key_id: str = ""
    apns_team_id: str = ""
    apns_bundle_id: str = "com.vitalquest.app"
    apns_use_sandbox: bool = True    # False in production

    # FCM (Android)
    fcm_server_key: str = ""         # FCM v1 service account JSON path

    # Queue keys (must match health_service and game_service config)
    notification_queue_health_key: str = "notify:stream_a"
    notification_queue_game_key: str = "notify:stream_b"
    notification_dlq_key: str = "notify:dlq"

    max_retries: int = 3
    retry_base_delay_seconds: int = 5

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
