import sqlite3

from admin.app.db import init_db
from admin.app.runtime_settings import read_runtime_settings, write_runtime_settings


def test_read_without_row_falls_back_to_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MQTT_HOST", "env-broker")
    monkeypatch.setenv("MQTT_PORT", "1899")
    monkeypatch.delenv("MQTT_USER", raising=False)
    conn = init_db(str(tmp_path / "test.db"))

    settings = read_runtime_settings(conn)

    assert settings.mqtt_host == "env-broker"
    assert settings.mqtt_port == 1899
    assert settings.mqtt_user == ""
    assert settings.mirror_stream_url == ""


def test_read_without_row_uses_sane_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("MQTT_HOST", raising=False)
    monkeypatch.delenv("MQTT_PORT", raising=False)
    conn = init_db(str(tmp_path / "test.db"))

    settings = read_runtime_settings(conn)

    assert settings.mqtt_host == "homeassistant.local"
    assert settings.mqtt_port == 1883
    assert settings.ha_url == "http://homeassistant.local:8123"


def test_write_then_read_roundtrip(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    write_runtime_settings(conn, mqtt_host="pi-broker", mqtt_port=1884)
    settings = read_runtime_settings(conn)

    assert settings.mqtt_host == "pi-broker"
    assert settings.mqtt_port == 1884


def test_write_only_updates_given_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("HA_URL", "http://ha.local:8123")
    conn = init_db(str(tmp_path / "test.db"))
    write_runtime_settings(conn, mqtt_host="pi-broker")

    write_runtime_settings(conn, mqtt_user="operator")
    settings = read_runtime_settings(conn)

    assert settings.mqtt_host == "pi-broker"
    assert settings.mqtt_user == "operator"
    assert settings.ha_url == "http://ha.local:8123"


def test_read_without_row_falls_back_to_env_for_topic_prefix(tmp_path, monkeypatch):
    monkeypatch.setenv("MQTT_TOPIC_PREFIX", "env-prefix")
    conn = init_db(str(tmp_path / "test.db"))

    settings = read_runtime_settings(conn)

    assert settings.mqtt_topic_prefix == "env-prefix"


def test_read_without_row_defaults_topic_prefix_to_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("MQTT_TOPIC_PREFIX", raising=False)
    conn = init_db(str(tmp_path / "test.db"))

    settings = read_runtime_settings(conn)

    assert settings.mqtt_topic_prefix == ""


def test_write_then_read_roundtrip_topic_prefix(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    write_runtime_settings(conn, mqtt_topic_prefix="test")
    settings = read_runtime_settings(conn)

    assert settings.mqtt_topic_prefix == "test"


def test_init_db_adds_missing_column_to_existing_app_settings_table(tmp_path):
    """Regressie: app_settings bestond al (uit een eerdere feature) zonder
    mqtt_topic_prefix-kolom. init_db moet die kolom alsnog toevoegen aan een
    bestaande tabel -- CREATE TABLE IF NOT EXISTS alleen is hier niet genoeg."""
    db_path = str(tmp_path / "old-schema.db")
    old_conn = sqlite3.connect(db_path)
    old_conn.execute(
        """CREATE TABLE app_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            mqtt_host TEXT NOT NULL,
            mqtt_port INTEGER NOT NULL,
            mqtt_user TEXT NOT NULL DEFAULT '',
            mqtt_pass TEXT NOT NULL DEFAULT '',
            ha_url TEXT NOT NULL,
            ha_token TEXT NOT NULL DEFAULT '',
            mirror_stream_url TEXT NOT NULL DEFAULT ''
        )"""
    )
    old_conn.execute(
        "INSERT INTO app_settings (id, mqtt_host, mqtt_port, ha_url) VALUES (1, 'oude-broker', 1883, 'http://ha.local:8123')"
    )
    old_conn.commit()
    old_conn.close()

    conn = init_db(db_path)
    settings = read_runtime_settings(conn)

    assert settings.mqtt_host == "oude-broker"
    assert settings.mqtt_topic_prefix == ""
