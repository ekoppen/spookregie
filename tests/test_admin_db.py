from admin.app.db import init_db


def test_init_db_creates_expected_tables(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }

    assert {"media", "scare_zone_config", "mirror_config", "schedule"} <= tables


def test_init_db_is_idempotent(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    conn = init_db(path)  # tweede keer mag niet crashen

    assert conn is not None
