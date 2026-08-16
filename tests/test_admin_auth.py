from admin.app.auth import check_password, SessionStore


def test_check_password_matches():
    assert check_password("geheim123", "geheim123") is True


def test_check_password_does_not_match():
    assert check_password("verkeerd", "geheim123") is False


def test_session_store_create_and_validate():
    store = SessionStore()
    token = store.create()

    assert store.is_valid(token) is True
    assert store.is_valid("een-willekeurig-ander-token") is False


def test_session_store_revoke():
    store = SessionStore()
    token = store.create()
    store.revoke(token)

    assert store.is_valid(token) is False
