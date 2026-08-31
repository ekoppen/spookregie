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

    assert "players" in tables


_LEGACY_MIRROR_CONFIG_DDL = """CREATE TABLE mirror_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    effect TEXT NOT NULL DEFAULT 'xray',
    params TEXT NOT NULL DEFAULT '{}',
    overlay_hash TEXT,
    scale REAL NOT NULL DEFAULT 1.0,
    position TEXT NOT NULL DEFAULT '[0.5, 0.5]'
)"""


def test_existing_mirror_config_migrates_to_one_scene(tmp_path):
    # Simuleert een echte pre-scenes-deployment: de mirror_config-rij staat
    # al in het databasebestand vóórdat init_db() ooit onder de nieuwe code
    # draait (zelfde patroon als de legacy-scenes-tests hieronder) -- niet
    # ertussenin ingevoegd, want die migratie is inmiddels (net als
    # scenes->graaf en scene_edges->triggers) een eenmalig upgrade-pad dat
    # stopt zodra de scenes-tabel al hernoemd is naar players.
    path = str(tmp_path / "test.db")
    raw = sqlite3.connect(path)
    raw.execute(_LEGACY_MIRROR_CONFIG_DDL)
    raw.execute(
        "INSERT INTO mirror_config (id, effect, params, overlay_hash, scale, position) "
        "VALUES (1, 'thermal', '{\"intensity\": 0.5}', NULL, 1.5, '[0.2, 0.3]')"
    )
    raw.commit()
    raw.close()

    conn = init_db(path)  # eerste keer onder de nieuwe code -- de migratie zelf

    scenes = conn.execute("SELECT name, trigger_type, effect, scale FROM players").fetchall()
    assert scenes == [("Basis", "always", "thermal", 1.5)]


def test_scene_migration_is_idempotent(tmp_path):
    path = str(tmp_path / "test.db")
    raw = sqlite3.connect(path)
    raw.execute(_LEGACY_MIRROR_CONFIG_DDL)
    raw.execute(
        "INSERT INTO mirror_config (id, effect, params, overlay_hash, scale, position) "
        "VALUES (1, 'xray', '{}', NULL, 1.0, '[0.5, 0.5]')"
    )
    raw.commit()
    raw.close()
    init_db(path)  # eerste migratie

    conn2 = init_db(path)  # nogmaals -- mag niet nog een scene toevoegen

    count = conn2.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    assert count == 1


def test_scene_migration_does_nothing_without_existing_mirror_config(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))  # verse DB, geen mirror_config-rij

    count = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    assert count == 0


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

    root = conn.execute("SELECT id FROM players WHERE is_root = 1").fetchall()
    assert root == [(1,)]
    edges = conn.execute(
        "SELECT from_scene_id, to_scene_id, kind FROM triggers ORDER BY from_scene_id"
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

    count = conn2.execute("SELECT COUNT(*) FROM triggers").fetchone()[0]
    assert count == 2  # motion-edge + terugkeer-edge, niet verdubbeld


def test_graph_migration_does_nothing_without_scenes(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    count = conn.execute("SELECT COUNT(*) FROM triggers").fetchone()[0]
    assert count == 0


def test_fresh_graph_era_scenes_survive_restart_without_edges(tmp_path):
    """Regressie voor Critical 3: een verse installatie waarin de
    gebruiker via de nieuwe graaf-UI scenes heeft aangemaakt maar nog
    niet gekoppeld (dus nul edges -- precies wat een echte
    pre-migratie-installatie ook heeft) mag bij een herstart NIET alsnog
    als legacy-data gezien worden. Dat zou is_root herschrijven naar
    'welke scene sorteert als eerste' en fabricage-edges aanmaken."""
    path = str(tmp_path / "test.db")
    conn = init_db(path)  # verse DB, nul scenes -- user_version wordt hier al op 3 gezet
    conn.execute(
        "INSERT INTO players (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode, trigger_type, is_root) VALUES "
        "(1, 'Kamer A', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera', 'always', 0)"
    )
    conn.execute(
        "INSERT INTO players (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode, trigger_type, is_root) VALUES "
        "(2, 'Kamer B', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera', 'always', 1)"
    )
    conn.commit()
    conn.close()

    conn2 = init_db(path)  # herstart, zoals een systemd-restart van de admin-app

    root = conn2.execute("SELECT id FROM players WHERE is_root = 1").fetchall()
    assert root == [(2,)]  # ongewijzigd -- niet teruggezet naar de eerst-sorterende scene
    edge_count = conn2.execute("SELECT COUNT(*) FROM triggers").fetchone()[0]
    assert edge_count == 0  # geen gefabriceerde edges


def test_outputs_table_created(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    assert "outputs" in tables


def test_default_output_created_from_mirror_camera_source(tmp_path):
    # Zaadt app_settings (incl. mirror_camera_source) vóórdat init_db ooit
    # draait -- de realistische upgrade-situatie: een bestaande deploy die
    # de instelling al had ingevuld vóórdat de outputs-tabel bestond.
    path = str(tmp_path / "test.db")
    raw = sqlite3.connect(path)
    raw.execute(
        """CREATE TABLE app_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            mqtt_host TEXT NOT NULL,
            mqtt_port INTEGER NOT NULL,
            mqtt_user TEXT NOT NULL DEFAULT '',
            mqtt_pass TEXT NOT NULL DEFAULT '',
            ha_url TEXT NOT NULL,
            ha_token TEXT NOT NULL DEFAULT '',
            mirror_stream_url TEXT NOT NULL DEFAULT '',
            mqtt_topic_prefix TEXT NOT NULL DEFAULT '',
            mirror_camera_source TEXT NOT NULL DEFAULT ''
        )"""
    )
    raw.execute(
        "INSERT INTO app_settings (id, mqtt_host, mqtt_port, ha_url, mirror_camera_source) "
        "VALUES (1, 'broker', 1883, 'http://ha', 'rtsp://cam.local/stream')"
    )
    raw.commit()
    raw.close()

    conn = init_db(path)

    rows = conn.execute("SELECT name, camera_source FROM outputs").fetchall()
    assert rows == [("Spiegel", "rtsp://cam.local/stream")]


def test_blanked_output_camera_source_is_not_reverted_on_restart(tmp_path):
    """Regression voor Finding 2: een gebruiker die de camera_source van
    een output bewust leegmaakt (bv. om 'm uit te schakelen) mag die niet
    op de volgende backend-restart teruggezet krijgen vanuit
    app_settings.mirror_camera_source."""
    path = str(tmp_path / "test.db")
    conn = init_db(path)
    conn.execute(
        "INSERT INTO app_settings (id, mqtt_host, mqtt_port, ha_url, mirror_camera_source) "
        "VALUES (1, 'broker', 1883, 'http://ha', 'rtsp://cam.local/stream')"
    )
    output_id = conn.execute("SELECT id FROM outputs LIMIT 1").fetchone()[0]
    conn.execute("UPDATE outputs SET camera_source = 'rtsp://cam.local/stream' WHERE id = ?", (output_id,))
    conn.execute("UPDATE outputs SET camera_source = '' WHERE id = ?", (output_id,))
    conn.commit()
    conn.close()

    conn2 = init_db(path)  # restart

    rows = conn2.execute("SELECT camera_source FROM outputs").fetchall()
    assert rows == [("",)]


def test_default_output_migration_is_idempotent(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    init_db(path)

    conn = init_db(path)
    count = conn.execute("SELECT COUNT(*) FROM outputs").fetchone()[0]
    assert count == 1


def test_existing_scenes_get_output_id_from_migration(tmp_path):
    # Zelfde reden als hierboven: output_id-koppeling is een eenmalig
    # upgrade-pad op de scenes-tabel, dus de legacy-rij moet er al staan
    # vóórdat init_db() ooit onder de nieuwe code draait.
    path = str(tmp_path / "test.db")
    raw = sqlite3.connect(path)
    raw.execute(_LEGACY_SCENES_DDL)
    raw.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode, trigger_type) VALUES "
        "(1, 'Basis', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera', 'always')"
    )
    raw.commit()
    raw.close()

    conn = init_db(path)  # eerste keer onder de nieuwe code -- de koppeling zelf

    output_id = conn.execute("SELECT id FROM outputs LIMIT 1").fetchone()[0]
    scene_output_id = conn.execute("SELECT output_id FROM players WHERE id = 1").fetchone()[0]
    assert scene_output_id == output_id


def test_scenes_color_column_defaults_to_null(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    conn.execute(
        "INSERT INTO players (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode) VALUES (1, 'X', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera')"
    )
    conn.commit()

    color = conn.execute("SELECT color FROM players WHERE id = 1").fetchone()[0]
    assert color is None


def test_triggers_table_replaces_scene_edges(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    assert "triggers" in tables
    assert "scene_edges" not in tables


def test_existing_scene_edges_data_survives_rename(tmp_path):
    """Simuleert een echte pre-triggers-rename deployment: de legacy
    scene_edges-rij staat al in het databasebestand vóórdat init_db()
    ooit onder de nieuwe code draait (zelfde patroon als
    test_existing_scenes_migrate_to_star_graph hierboven) -- niet via
    init_db() zelf ingevoegd, want een verse (0-scenes) init_db()-call
    rondt de user_version 0->2-keten in één keer af en zou scene_edges
    dus alweer naar triggers hebben hernoemd vóórdat de test kan
    invoegen."""
    path = str(tmp_path / "test.db")
    raw = sqlite3.connect(path)
    raw.execute(_LEGACY_SCENES_DDL)
    raw.execute(
        """CREATE TABLE scene_edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_scene_id INTEGER NOT NULL,
            to_scene_id INTEGER,
            trigger_type TEXT,
            trigger_from TEXT,
            trigger_until TEXT,
            priority INTEGER NOT NULL DEFAULT 0
        )"""
    )
    raw.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode, trigger_type) VALUES "
        "(1, 'A', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera', 'always')"
    )
    raw.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode, trigger_type) VALUES "
        "(2, 'B', 1, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera', 'always')"
    )
    raw.execute(
        "INSERT INTO scene_edges (from_scene_id, to_scene_id, trigger_type, priority) "
        "VALUES (1, 2, 'motion', 0)"
    )
    raw.commit()
    raw.close()

    conn = init_db(path)  # eerste keer onder de nieuwe code -- de rename zelf

    row = conn.execute(
        "SELECT from_scene_id, to_scene_id, kind FROM triggers"
    ).fetchone()
    assert row == (1, 2, "motion")


def test_triggers_new_columns_have_sensible_defaults(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    conn.execute(
        "INSERT INTO players (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode) VALUES (1, 'A', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera')"
    )
    conn.execute(
        "INSERT INTO triggers (from_scene_id, priority) VALUES (1, 0)"
    )
    conn.commit()

    row = conn.execute(
        "SELECT ha_entity_id, name, color FROM triggers"
    ).fetchone()
    assert row == (None, None, None)


def test_reciprocal_triggers_get_distinct_canvas_positions(tmp_path):
    """Regression voor Finding 6: een scare_video-scene krijgt van
    _migrate_scenes_to_graph altijd zowel een A->B- als een B->A-trigger.
    Beide zaten voorheen op exact hetzelfde (symmetrische) midpoint --
    één knoop verdween volledig achter de andere op de canvas."""
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

    rows = conn.execute(
        "SELECT from_scene_id, to_scene_id, canvas_y FROM triggers ORDER BY id"
    ).fetchall()
    assert len(rows) == 2
    canvas_ys = [r[2] for r in rows]
    assert canvas_ys[0] != canvas_ys[1]


def test_triggers_migration_is_idempotent(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    init_db(path)

    conn = init_db(path)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "triggers" in tables


def test_sources_table_created(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    assert "sources" in tables


def test_default_source_created_from_output_camera_source(tmp_path):
    path = str(tmp_path / "test.db")
    raw = sqlite3.connect(path)
    raw.execute(
        """CREATE TABLE app_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            mqtt_host TEXT NOT NULL,
            mqtt_port INTEGER NOT NULL,
            mqtt_user TEXT NOT NULL DEFAULT '',
            mqtt_pass TEXT NOT NULL DEFAULT '',
            ha_url TEXT NOT NULL,
            ha_token TEXT NOT NULL DEFAULT '',
            mirror_stream_url TEXT NOT NULL DEFAULT '',
            mqtt_topic_prefix TEXT NOT NULL DEFAULT '',
            mirror_camera_source TEXT NOT NULL DEFAULT ''
        )"""
    )
    raw.execute(
        "INSERT INTO app_settings (id, mqtt_host, mqtt_port, ha_url, mirror_camera_source) "
        "VALUES (1, 'broker', 1883, 'http://ha', 'rtsp://cam.local/stream')"
    )
    raw.commit()
    raw.close()

    conn = init_db(path)  # eerste keer onder de nieuwe code -- outputs- en sources-migratie samen

    rows = conn.execute("SELECT name, kind, value FROM sources").fetchall()
    assert rows == [("Spiegel camera", "camera_stream", "rtsp://cam.local/stream")]


def test_source_migration_is_idempotent(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    init_db(path)

    conn = init_db(path)
    count = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    assert count == 1


def test_blanked_source_value_is_not_reverted_on_restart(tmp_path):
    """Zelfde soort regressie als Finding 2 op outputs: een bewust
    leeggemaakte source-waarde mag niet teruggezet worden bij herstart."""
    path = str(tmp_path / "test.db")
    conn = init_db(path)
    source_id = conn.execute("SELECT id FROM sources LIMIT 1").fetchone()[0]
    conn.execute("UPDATE sources SET value = '' WHERE id = ?", (source_id,))
    conn.commit()
    conn.close()

    conn2 = init_db(path)  # herstart

    rows = conn2.execute("SELECT value FROM sources").fetchall()
    assert rows == [("",)]


def test_players_table_replaces_scenes(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    assert "players" in tables
    assert "scenes" not in tables


def test_existing_scenes_data_survives_rename_to_players(tmp_path):
    path = str(tmp_path / "test.db")
    raw = sqlite3.connect(path)
    raw.execute(_LEGACY_SCENES_DDL)
    raw.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode, trigger_type) VALUES "
        "(1, 'Basis', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera', 'always')"
    )
    raw.commit()
    raw.close()

    conn = init_db(path)  # eerste keer onder de nieuwe code -- de rename zelf

    row = conn.execute("SELECT name FROM players WHERE id = 1").fetchone()
    assert row == ("Basis",)


def test_players_get_new_playback_columns_with_sensible_defaults(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    conn.execute(
        "INSERT INTO players (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode) VALUES (1, 'A', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera')"
    )
    conn.commit()

    row = conn.execute(
        "SELECT playback_mode, repeat_while_ha_entity_id FROM players WHERE id = 1"
    ).fetchone()
    assert row == ("once", None)


def test_existing_players_get_source_id_from_migration(tmp_path):
    path = str(tmp_path / "test.db")
    raw = sqlite3.connect(path)
    raw.execute(_LEGACY_SCENES_DDL)
    raw.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode, trigger_type) VALUES "
        "(1, 'Basis', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera', 'always')"
    )
    raw.commit()
    raw.close()

    conn = init_db(path)

    default_source_id = conn.execute("SELECT id FROM sources LIMIT 1").fetchone()[0]
    player_source_id = conn.execute("SELECT source_id FROM players WHERE id = 1").fetchone()[0]
    assert player_source_id == default_source_id


def test_players_rename_is_idempotent_across_restarts(tmp_path):
    """Regressie voor de kern-hazard van deze taak: init_db() draait
    meerdere keren na de rename en mag niet crashen op 'no such table:
    scenes' (de oude, ongeconditioneerde migraties die dat literal nog
    noemen)."""
    path = str(tmp_path / "test.db")
    init_db(path)
    init_db(path)

    conn = init_db(path)  # derde run -- als een van de oude scenes-migraties
    # niet correct geguard is, gooit een van deze drie calls al een
    # sqlite3.OperationalError

    count = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    assert count == 0  # geen crash, en (verse install) nog geen players


def test_scenes_table_does_not_reappear_after_a_restart(tmp_path):
    """Regressie voor een extra spookgevaar naast de kern-hazard: de
    onvoorwaardelijke CREATE TABLE IF NOT EXISTS scenes bovenaan init_db()
    zou zonder guard bij elke herstart ná de rename een lege 'scenes'-tabel
    terugzetten (IF NOT EXISTS blokkeert alleen een tabel die na de rename
    nog exact zo heet, en die bestaat niet meer)."""
    path = str(tmp_path / "test.db")
    init_db(path)

    conn = init_db(path)  # herstart

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "scenes" not in tables
