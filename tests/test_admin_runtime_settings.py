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
