import os
from admin.app.config import get_settings


def test_get_settings_reads_env_vars(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "geheim123")
    monkeypatch.setenv("MQTT_HOST", "test-broker")
    monkeypatch.setenv("MQTT_PORT", "1884")

    settings = get_settings()

    assert settings.admin_password == "geheim123"
    assert settings.mqtt_host == "test-broker"
    assert settings.mqtt_port == 1884


def test_get_settings_has_sane_defaults(monkeypatch):
    monkeypatch.delenv("MQTT_HOST", raising=False)
    monkeypatch.delenv("MQTT_PORT", raising=False)

    settings = get_settings()

    assert settings.mqtt_host == "homeassistant.local"
    assert settings.mqtt_port == 1883
    assert settings.port == 8000
