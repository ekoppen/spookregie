import os
from dataclasses import asdict, dataclass


@dataclass
class RuntimeSettings:
    mqtt_host: str
    mqtt_port: int
    mqtt_user: str
    mqtt_pass: str
    ha_url: str
    ha_token: str
    mirror_stream_url: str
    mqtt_topic_prefix: str = ""
    mirror_camera_source: str = ""


def _env_defaults() -> RuntimeSettings:
    """Zelfde variabelenamen/defaults als config.get_settings() vroeger
    gebruikte voor deze velden -- alleen gelezen zolang er nog geen
    app_settings-rij is (eerste-opstart-seed van een bestaande deploy).
    mirror_camera_source heeft nooit een backend-kant env var gehad, dus
    default gewoon leeg."""
    return RuntimeSettings(
        mqtt_host=os.environ.get("MQTT_HOST", "homeassistant.local"),
        mqtt_port=int(os.environ.get("MQTT_PORT", "1883")),
        mqtt_user=os.environ.get("MQTT_USER", ""),
        mqtt_pass=os.environ.get("MQTT_PASS", ""),
        ha_url=os.environ.get("HA_URL", "http://homeassistant.local:8123"),
        ha_token=os.environ.get("HA_TOKEN", ""),
        mirror_stream_url="",
        mqtt_topic_prefix=os.environ.get("MQTT_TOPIC_PREFIX", ""),
        mirror_camera_source="",
    )


def read_runtime_settings(conn) -> RuntimeSettings:
    row = conn.execute(
        "SELECT mqtt_host, mqtt_port, mqtt_user, mqtt_pass, ha_url, ha_token, mirror_stream_url, "
        "mqtt_topic_prefix, mirror_camera_source FROM app_settings WHERE id = 1"
    ).fetchone()
    if row is None:
        return _env_defaults()
    return RuntimeSettings(*row)


def write_runtime_settings(conn, **updates) -> RuntimeSettings:
    """Overschrijft alleen de meegegeven velden t.o.v. de huidige effectieve
    waarden (DB-rij, of env-defaults als er nog geen rij is) en persisteert
    de volledige rij -- zelfde aanpak als put_mirror_config."""
    current = read_runtime_settings(conn)
    result = RuntimeSettings(**{**asdict(current), **updates})
    conn.execute(
        """INSERT INTO app_settings
               (id, mqtt_host, mqtt_port, mqtt_user, mqtt_pass, ha_url, ha_token, mirror_stream_url,
                mqtt_topic_prefix, mirror_camera_source)
           VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               mqtt_host=excluded.mqtt_host, mqtt_port=excluded.mqtt_port,
               mqtt_user=excluded.mqtt_user, mqtt_pass=excluded.mqtt_pass,
               ha_url=excluded.ha_url, ha_token=excluded.ha_token,
               mirror_stream_url=excluded.mirror_stream_url,
               mqtt_topic_prefix=excluded.mqtt_topic_prefix,
               mirror_camera_source=excluded.mirror_camera_source""",
        (
            result.mqtt_host, result.mqtt_port, result.mqtt_user, result.mqtt_pass,
            result.ha_url, result.ha_token, result.mirror_stream_url, result.mqtt_topic_prefix,
            result.mirror_camera_source,
        ),
    )
    conn.commit()
    return result
