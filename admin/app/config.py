import os
from dataclasses import dataclass


@dataclass
class Settings:
    admin_password: str
    mqtt_host: str
    mqtt_port: int
    mqtt_user: str
    mqtt_pass: str
    ha_url: str
    ha_token: str
    db_path: str
    media_dir: str
    port: int


def get_settings():
    admin_password = os.environ.get("ADMIN_PASSWORD")
    if not admin_password:
        raise RuntimeError(
            "ADMIN_PASSWORD moet ingesteld zijn (geen standaardwaarde om veiligheidsredenen)"
        )
    return Settings(
        admin_password=admin_password,
        mqtt_host=os.environ.get("MQTT_HOST", "homeassistant.local"),
        mqtt_port=int(os.environ.get("MQTT_PORT", "1883")),
        mqtt_user=os.environ.get("MQTT_USER", ""),
        mqtt_pass=os.environ.get("MQTT_PASS", ""),
        ha_url=os.environ.get("HA_URL", "http://homeassistant.local:8123"),
        ha_token=os.environ.get("HA_TOKEN", ""),
        db_path=os.environ.get("ADMIN_DB_PATH", "./admin.db"),
        media_dir=os.environ.get("ADMIN_MEDIA_DIR", "./media_store"),
        port=int(os.environ.get("ADMIN_PORT", "8000")),
    )
