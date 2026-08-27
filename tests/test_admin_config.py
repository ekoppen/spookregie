import pytest
from admin.app.config import get_settings


def test_get_settings_reads_env_vars(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "geheim123")

    settings = get_settings()

    assert settings.admin_password == "geheim123"


def test_get_settings_has_sane_defaults(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "iets")

    settings = get_settings()

    assert settings.port == 8000


def test_get_settings_raises_without_admin_password(monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

    with pytest.raises(RuntimeError):
        get_settings()
