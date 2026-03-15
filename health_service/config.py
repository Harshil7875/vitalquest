from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    postgres_dsn: str
    redis_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    encryption_key: str  # base64-encoded 32-byte key for PHI at-rest encryption
    daily_mana_cap: int = 300  # GDD v1.8: medication=100, steps=50, diet=25 per day max
    guild_cron_hour: int = 23
    guild_cron_minute: int = 59

    # Physiological plausibility limits used by the anti-cheat engine
    max_steps_per_sync: int = 50_000
    min_glucose_mg_dl: float = 20.0
    max_glucose_mg_dl: float = 600.0
    max_heart_rate_bpm: int = 250
    min_heart_rate_bpm: int = 20

    # OAuth credentials for cloud-to-cloud device integrations
    dexcom_client_id: str = ""
    dexcom_client_secret: str = ""
    dexcom_webhook_secret: str = ""
    oura_webhook_secret: str = ""
    fitbit_webhook_secret: str = ""

    # Redis queue keys for the notification worker
    notification_queue_health_key: str = "notify:stream_a"
    notification_queue_game_key: str = "notify:stream_b"

    class Config:
        env_file = ".env"


settings = Settings()
