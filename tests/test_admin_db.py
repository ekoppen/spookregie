import sqlite3

from admin.app.db import init_db

# Schema van de 'scenes'-tabel zoals die bestond vóór de graaf-feature
# (dus zonder is_root/canvas_x/canvas_y -- die komen pas via _ensure_column
# binnen deze feature). Gebruikt om een echte pre-upgrade-deployment na te
# bootsen: de legacy-rijen staan al in het bestand vóórdat init_db() onder
# de nieuwe code ooit draait, in plaats van ertussenin ingevoegd te worden.
_LEGACY_SCENES_DDL = """CREATE TABLE scenes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    order_index INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    source_mode TEXT NOT NULL DEFAULT 'camera',
    effect TEXT NOT NULL DEFAULT 'xray',
    params TEXT NOT NULL DEFAULT '{}',
    overlay_hash TEXT,
    scale REAL NOT NULL DEFAULT 1.0,
    position TEXT NOT NULL DEFAULT '[0.5, 0.5]',
    canvas_width INTEGER,
    canvas_height INTEGER,
    source_scale REAL NOT NULL DEFAULT 1.0,
    source_position TEXT NOT NULL DEFAULT '[0.5, 0.5]',
    trigger_type TEXT NOT NULL DEFAULT 'always',
    trigger_from TEXT,
    trigger_until TEXT
)"""


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
    """Simuleert een echte pre-graaf-deployment: de legacy scene-rijen
    staan al in het databasebestand vóórdat init_db() ooit onder de
    nieuwe code draait (i.p.v. ertussenin ingevoegd, wat de
    user_version-marker ten onrechte al op 1 zou zetten bij een lege
    scenes-tabel)."""
    path = str(tmp_path / "test.db")
    raw = sqlite3.connect(path)
    raw.execute(_LEGACY_SCENES_DDL)
    raw.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode, trigger_type) VALUES "
        "(1, 'Basis', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera', 'always')"
    )
    raw.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode, trigger_type) VALUES "
        "(2, 'Scare', 1, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'scare_video', 'motion')"
    )
    raw.commit()
    raw.close()

    conn = init_db(path)  # eerste keer onder de nieuwe code -- de upgrade zelf

    root = conn.execute("SELECT id FROM scenes WHERE is_root = 1").fetchall()
    assert root == [(1,)]
    edges = conn.execute(
        "SELECT from_scene_id, to_scene_id, trigger_type FROM scene_edges ORDER BY from_scene_id"
    ).fetchall()
    assert edges == [(1, 2, "motion"), (2, 1, "always")]


def test_graph_migration_is_idempotent(tmp_path):
    path = str(tmp_path / "test.db")
    raw = sqlite3.connect(path)
    raw.execute(_LEGACY_SCENES_DDL)
    raw.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode, trigger_type) VALUES "
        "(1, 'Basis', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera', 'always')"
    )
    raw.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode, trigger_type) VALUES "
        "(2, 'Scare', 1, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'scare_video', 'motion')"
    )
    raw.commit()
    raw.close()
    init_db(path)  # eerste (echte) migratie, onder de nieuwe code

    conn2 = init_db(path)  # herstart -- mag geen extra edges toevoegen

    count = conn2.execute("SELECT COUNT(*) FROM scene_edges").fetchone()[0]
    assert count == 2  # motion-edge + terugkeer-edge, niet verdubbeld


def test_graph_migration_does_nothing_without_scenes(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    count = conn.execute("SELECT COUNT(*) FROM scene_edges").fetchone()[0]
    assert count == 0


def test_fresh_graph_era_scenes_survive_restart_without_edges(tmp_path):
    """Regressie voor Critical 3: een verse installatie waarin de
    gebruiker via de nieuwe graaf-UI scenes heeft aangemaakt maar nog
    niet gekoppeld (dus nul edges -- precies wat een echte
    pre-migratie-installatie ook heeft) mag bij een herstart NIET alsnog
    als legacy-data gezien worden. Dat zou is_root herschrijven naar
    'welke scene sorteert als eerste' en fabricage-edges aanmaken."""
    path = str(tmp_path / "test.db")
    conn = init_db(path)  # verse DB, nul scenes -- user_version wordt hier al op 1 gezet
    conn.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode, trigger_type, is_root) VALUES "
        "(1, 'Kamer A', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera', 'always', 0)"
    )
    conn.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode, trigger_type, is_root) VALUES "
        "(2, 'Kamer B', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera', 'always', 1)"
    )
    conn.commit()
    conn.close()

    conn2 = init_db(path)  # herstart, zoals een systemd-restart van de admin-app

    root = conn2.execute("SELECT id FROM scenes WHERE is_root = 1").fetchall()
    assert root == [(2,)]  # ongewijzigd -- niet teruggezet naar de eerst-sorterende scene
    edge_count = conn2.execute("SELECT COUNT(*) FROM scene_edges").fetchone()[0]
    assert edge_count == 0  # geen gefabriceerde edges


def test_outputs_table_created(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    assert "outputs" in tables


def test_default_output_created_from_mirror_camera_source(tmp_path):
    path = str(tmp_path / "test.db")
    conn = init_db(path)
    conn.execute(
        "INSERT INTO app_settings (id, mqtt_host, mqtt_port, ha_url, mirror_camera_source) "
        "VALUES (1, 'broker', 1883, 'http://ha', 'rtsp://cam.local/stream')"
    )
    conn.commit()
    conn.close()

    conn2 = init_db(path)

    rows = conn2.execute("SELECT name, camera_source FROM outputs").fetchall()
    assert rows == [("Spiegel", "rtsp://cam.local/stream")]


def test_default_output_migration_is_idempotent(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    init_db(path)

    conn = init_db(path)
    count = conn.execute("SELECT COUNT(*) FROM outputs").fetchone()[0]
    assert count == 1


def test_existing_scenes_get_output_id_from_migration(tmp_path):
    path = str(tmp_path / "test.db")
    conn = init_db(path)
    conn.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode, is_root) VALUES "
        "(1, 'Basis', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera', 1)"
    )
    conn.commit()
    conn.close()

    conn2 = init_db(path)

    output_id = conn2.execute("SELECT id FROM outputs LIMIT 1").fetchone()[0]
    scene_output_id = conn2.execute("SELECT output_id FROM scenes WHERE id = 1").fetchone()[0]
    assert scene_output_id == output_id


def test_scenes_color_column_defaults_to_null(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    conn.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode) VALUES (1, 'X', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera')"
    )
    conn.commit()

    color = conn.execute("SELECT color FROM scenes WHERE id = 1").fetchone()[0]
    assert color is None
