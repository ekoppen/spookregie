from fastapi.testclient import TestClient
from admin.app.config import Settings
from admin.app.main import create_app


def _test_settings(tmp_path):
    return Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )


def test_login_with_correct_password_sets_cookie(tmp_path):
    app = create_app(settings=_test_settings(tmp_path))
    client = TestClient(app)

    response = client.post("/api/login", json={"password": "testwachtwoord"})

    assert response.status_code == 200
    assert "session" in response.cookies


def test_login_with_wrong_password_is_rejected(tmp_path):
    app = create_app(settings=_test_settings(tmp_path))
    client = TestClient(app)

    response = client.post("/api/login", json={"password": "verkeerd"})

    assert response.status_code == 401
    assert "session" not in response.cookies


def test_protected_route_requires_session(tmp_path):
    app = create_app(settings=_test_settings(tmp_path))
    client = TestClient(app)

    response = client.get("/api/nodes")

    assert response.status_code == 401


def test_logout_revokes_session(tmp_path):
    app = create_app(settings=_test_settings(tmp_path))
    client = TestClient(app)
    client.post("/api/login", json={"password": "testwachtwoord"})

    client.post("/api/logout")
    response = client.get("/api/nodes")

    assert response.status_code == 401


def test_media_list_without_hash_is_not_public(tmp_path):
    # /api/media (no trailing hash) must stay protected, only the exact
    # /api/media/<hash> download route is public.
    app = create_app(settings=_test_settings(tmp_path))
    client = TestClient(app)

    response = client.get("/api/media")

    assert response.status_code == 401


def test_media_download_with_valid_hash_bypasses_auth_check():
    # The middleware must not depend on the route actually existing to make
    # its auth decision; a GET matching the hash shape passes the
    # middleware itself (any 404 below is Starlette's router, not auth).
    from admin.app.main import _is_public_media_download

    valid_hash = "a" * 64
    assert _is_public_media_download(f"/api/media/{valid_hash}", "GET") is True
    assert _is_public_media_download(f"/api/media/{valid_hash}", "POST") is False
    assert _is_public_media_download("/api/media", "GET") is False
    assert _is_public_media_download("/api/media/", "GET") is False
    assert _is_public_media_download(f"/api/media/{valid_hash}/extra", "GET") is False
    assert _is_public_media_download("/api/media/not-a-hash", "GET") is False
