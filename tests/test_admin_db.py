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


def test_scenes_table_created(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    tables = {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }

    assert "scenes" in tables


def test_existing_mirror_config_migrates_to_one_scene(tmp_path):
    path = str(tmp_path / "test.db")
    conn = init_db(path)
    conn.execute(
        "INSERT INTO mirror_config (id, effect, params, overlay_hash, scale, position) "
        "VALUES (1, 'thermal', '{\"intensity\": 0.5}', NULL, 1.5, '[0.2, 0.3]')"
    )
    conn.commit()
    conn.close()

    conn2 = init_db(path)  # tweede init_db-run simuleert een herstart na upgrade

    scenes = conn2.execute("SELECT name, trigger_type, effect, scale FROM scenes").fetchall()
    assert scenes == [("Basis", "always", "thermal", 1.5)]


def test_scene_migration_is_idempotent(tmp_path):
    path = str(tmp_path / "test.db")
    conn = init_db(path)
    conn.execute(
        "INSERT INTO mirror_config (id, effect, params, overlay_hash, scale, position) "
        "VALUES (1, 'xray', '{}', NULL, 1.0, '[0.5, 0.5]')"
    )
    conn.commit()
    conn.close()
    init_db(path)  # eerste migratie

    conn3 = init_db(path)  # nogmaals -- mag niet nog een scene toevoegen

    count = conn3.execute("SELECT COUNT(*) FROM scenes").fetchone()[0]
    assert count == 1


def test_scene_migration_does_nothing_without_existing_mirror_config(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))  # verse DB, geen mirror_config-rij

    count = conn.execute("SELECT COUNT(*) FROM scenes").fetchone()[0]
    assert count == 0


def test_scene_edges_table_created(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    tables = {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }

    assert "scene_edges" in tables


def test_existing_scenes_migrate_to_star_graph(tmp_path):
    path = str(tmp_path / "test.db")
    conn = init_db(path)
    conn.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode, trigger_type) VALUES "
        "(1, 'Basis', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera', 'always')"
    )
    conn.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode, trigger_type) VALUES "
        "(2, 'Scare', 1, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'scare_video', 'motion')"
    )
    conn.commit()
    conn.close()

    conn2 = init_db(path)  # tweede run simuleert een herstart na upgrade

    root = conn2.execute("SELECT id FROM scenes WHERE is_root = 1").fetchall()
    assert root == [(1,)]
    edges = conn2.execute(
        "SELECT from_scene_id, to_scene_id, trigger_type FROM scene_edges ORDER BY from_scene_id"
    ).fetchall()
    assert edges == [(1, 2, "motion"), (2, 1, "always")]


def test_graph_migration_is_idempotent(tmp_path):
    path = str(tmp_path / "test.db")
    conn = init_db(path)
    conn.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode, trigger_type) VALUES "
        "(1, 'Basis', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera', 'always')"
    )
    conn.commit()
    conn.close()
    init_db(path)  # eerste migratie

    conn3 = init_db(path)  # nogmaals -- mag geen extra edges toevoegen

    count = conn3.execute("SELECT COUNT(*) FROM scene_edges").fetchone()[0]
    assert count == 0


def test_graph_migration_does_nothing_without_scenes(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    count = conn.execute("SELECT COUNT(*) FROM scene_edges").fetchone()[0]
    assert count == 0
