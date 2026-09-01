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
        "SELECT from_branch_id, to_player_id, kind FROM triggers ORDER BY from_branch_id"
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
        "SELECT from_branch_id, to_player_id, kind FROM triggers"
    ).fetchone()
    assert row == (1, 2, "motion")


def test_triggers_new_columns_have_sensible_defaults(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    conn.execute(
        "INSERT INTO players (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode) VALUES (1, 'A', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera')"
    )
    conn.execute(
        "INSERT INTO triggers (from_branch_id, priority) VALUES (1, 0)"
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
        "SELECT from_branch_id, to_player_id, canvas_y FROM triggers ORDER BY id"
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


def test_player_branches_table_created(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    assert "player_branches" in tables


def test_existing_players_each_get_one_default_branch(tmp_path):
    path = str(tmp_path / "test.db")
    raw = sqlite3.connect(path)
    raw.execute(_LEGACY_SCENES_DDL)
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
    raw.commit()
    raw.close()

    conn = init_db(path)

    rows = conn.execute("SELECT player_id, name FROM player_branches ORDER BY player_id").fetchall()
    assert rows == [(1, "Uitgang 1"), (2, "Uitgang 1")]


def test_player_branches_migration_is_idempotent(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    init_db(path)

    conn = init_db(path)
    count = conn.execute("SELECT COUNT(*) FROM player_branches").fetchone()[0]
    assert count == 0  # verse install, geen players -> geen branches


def test_triggers_columns_renamed_to_branch_and_player(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    cols = {row[1] for row in conn.execute("PRAGMA table_info(triggers)")}

    assert "from_branch_id" in cols
    assert "to_player_id" in cols
    assert "from_scene_id" not in cols
    assert "to_scene_id" not in cols


def test_existing_trigger_from_scene_id_becomes_that_players_default_branch(tmp_path):
    path = str(tmp_path / "test.db")
    raw = sqlite3.connect(path)
    raw.execute(_LEGACY_SCENES_DDL)
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
    raw.commit()
    raw.close()

    conn = init_db(path)  # eerste keer onder de nieuwe code

    default_branch_id = conn.execute(
        "SELECT id FROM player_branches WHERE player_id = 1"
    ).fetchone()[0]
    row = conn.execute("SELECT from_branch_id, to_player_id FROM triggers").fetchone()
    assert row == (default_branch_id, 2)


def test_triggers_branch_rename_is_idempotent(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    init_db(path)

    conn = init_db(path)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(triggers)")}
    assert "from_branch_id" in cols


def test_outputs_get_canvas_position_columns(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    cols = {row[1] for row in conn.execute("PRAGMA table_info(outputs)")}

    assert "canvas_x" in cols
    assert "canvas_y" in cols


def test_migrated_output_gets_a_visible_canvas_position(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    row = conn.execute("SELECT canvas_x, canvas_y FROM outputs LIMIT 1").fetchone()
    assert row == (300.0, 0.0)


def test_output_canvas_position_seed_is_idempotent(tmp_path):
    path = str(tmp_path / "test.db")
    conn = init_db(path)
    output_id = conn.execute("SELECT id FROM outputs LIMIT 1").fetchone()[0]
    conn.execute("UPDATE outputs SET canvas_x = 999.0 WHERE id = ?", (output_id,))
    conn.commit()
    conn.close()

    conn2 = init_db(path)  # herstart -- mag de handmatig versleepte positie niet resetten

    row = conn2.execute("SELECT canvas_x FROM outputs WHERE id = ?", (output_id,)).fetchone()
    assert row == (999.0,)


def test_output_connections_table_created(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    assert "output_connections" in tables


def test_existing_players_default_branch_gets_wired_to_the_output(tmp_path):
    path = str(tmp_path / "test.db")
    raw = sqlite3.connect(path)
    raw.execute(_LEGACY_SCENES_DDL)
    raw.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode, trigger_type) VALUES "
        "(1, 'A', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera', 'always')"
    )
    raw.commit()
    raw.close()

    conn = init_db(path)  # eerste keer onder de nieuwe code

    output_id = conn.execute("SELECT id FROM outputs LIMIT 1").fetchone()[0]
    branch_id = conn.execute("SELECT id FROM player_branches WHERE player_id = 1").fetchone()[0]
    row = conn.execute("SELECT output_id, from_branch_id FROM output_connections").fetchone()
    assert row == (output_id, branch_id)


def test_output_connections_migration_is_idempotent(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    init_db(path)

    conn = init_db(path)
    count = conn.execute("SELECT COUNT(*) FROM output_connections").fetchone()[0]
    assert count == 0  # verse install, geen players -> geen connections


def test_full_migration_chain_from_pre_plan_production_state(tmp_path):
    """Regressie voor de volledige migratieketen in één keer (Additioneel
    Punt 9). Elke bestaande migratietest hierboven test maar één hop
    geïsoleerd -- dit had de Taak-5-migratievolgorde-regressie gevonden
    die tijdens deze plan's eigen uitvoering opdook. Bootst de echte
    productie-databasevorm na op dit plan's basiscommit (571f6f1):
    scenes nog niet hernoemd, triggers al wel hernoemd vanaf scene_edges
    maar de from_scene_id/to_scene_id-kolommen nog niet naar
    from_branch_id/to_player_id, user_version=2. Eén init_db()-aanroep
    moet de hele keten (v2 -> v7) in de juiste volgorde afronden."""
    path = str(tmp_path / "test.db")
    raw = sqlite3.connect(path)
    # scenes-schema zoals een echt lang-lopende productie-DB 'm heeft:
    # de basis-DDL plus alle kolommen die _ensure_column er onderweg al
    # aan toegevoegd heeft (is_root/canvas_x/canvas_y/output_id/color).
    raw.execute(
        """CREATE TABLE scenes (
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
            trigger_until TEXT,
            is_root INTEGER NOT NULL DEFAULT 0,
            canvas_x REAL NOT NULL DEFAULT 0,
            canvas_y REAL NOT NULL DEFAULT 0,
            output_id INTEGER,
            color TEXT
        )"""
    )
    # triggers-schema na de scene_edges-rename (user_version=2) maar vóór
    # de from_scene_id/to_scene_id -> from_branch_id/to_player_id-rename
    # (die pas bij v5 gebeurt).
    raw.execute(
        """CREATE TABLE triggers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_scene_id INTEGER NOT NULL,
            to_scene_id INTEGER,
            kind TEXT,
            schedule_from TEXT,
            schedule_until TEXT,
            priority INTEGER NOT NULL DEFAULT 0,
            ha_entity_id TEXT,
            canvas_x REAL NOT NULL DEFAULT 0,
            canvas_y REAL NOT NULL DEFAULT 0,
            name TEXT,
            color TEXT
        )"""
    )
    raw.execute(
        """CREATE TABLE outputs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            camera_source TEXT NOT NULL DEFAULT '',
            canvas_x REAL NOT NULL DEFAULT 0,
            canvas_y REAL NOT NULL DEFAULT 0
        )"""
    )
    raw.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, position, "
        "source_mode, trigger_type, is_root) VALUES "
        "(1, 'Basis', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera', 'always', 1)"
    )
    raw.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, position, "
        "source_mode, trigger_type) VALUES "
        "(2, 'Schrik', 1, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'scare_video', 'motion')"
    )
    raw.execute("INSERT INTO outputs (id, name, camera_source) VALUES (1, 'Spiegel', 'rtsp://cam.local/stream')")
    # Twee echte trigger-rijen, zoals _migrate_scenes_to_graph die voor een
    # scare_video-scene produceert: heen (motion) en terug (always).
    raw.execute("INSERT INTO triggers (id, from_scene_id, to_scene_id, kind) VALUES (1, 1, 2, 'motion')")
    raw.execute("INSERT INTO triggers (id, from_scene_id, to_scene_id, kind) VALUES (2, 2, 1, 'always')")
    raw.execute("PRAGMA user_version = 2")
    raw.commit()
    raw.close()

    conn = init_db(path)  # één aanroep moet de hele v2->v8-keten afronden

    assert conn.execute("PRAGMA user_version").fetchone()[0] == 8

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"players", "sources", "player_branches", "output_connections"} <= tables

    player_cols = {row[1] for row in conn.execute("PRAGMA table_info(players)")}
    assert {"source_id", "playback_mode", "repeat_while_ha_entity_id"} <= player_cols
    source_cols = {row[1] for row in conn.execute("PRAGMA table_info(sources)")}
    assert {"kind", "value"} <= source_cols
    branch_cols = {row[1] for row in conn.execute("PRAGMA table_info(player_branches)")}
    assert {"player_id", "name"} <= branch_cols
    oc_cols = {row[1] for row in conn.execute("PRAGMA table_info(output_connections)")}
    assert {"output_id", "from_branch_id"} <= oc_cols

    names = dict(conn.execute("SELECT id, name FROM players").fetchall())
    assert names == {1: "Basis", 2: "Schrik"}

    branch1 = conn.execute("SELECT id FROM player_branches WHERE player_id = 1").fetchone()[0]
    branch2 = conn.execute("SELECT id FROM player_branches WHERE player_id = 2").fetchone()[0]
    trigger_rows = conn.execute(
        "SELECT from_branch_id, to_player_id, kind FROM triggers ORDER BY id"
    ).fetchall()
    assert trigger_rows == [(branch1, 2, "motion"), (branch2, 1, "always")]


# Schema van 'players' zoals een echte deployment die had op user_version=7
# (dus vlak vóór deze media-library-feature): al hernoemd vanaf scenes, al
# met source_id/playback_mode/repeat_while_ha_entity_id, maar nog zónder
# audio_source_id. Gebruikt om te bewijzen dat de audio_source_id-kolom ook
# op een BESTAANDE deploy toegevoegd wordt -- op v7 slaat
# _migrate_scenes_to_players (PRAGMA-gated op >=3) volledig over.
_V7_PLAYERS_DDL = """CREATE TABLE players (
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
    trigger_until TEXT,
    is_root INTEGER NOT NULL DEFAULT 0,
    canvas_x REAL NOT NULL DEFAULT 0,
    canvas_y REAL NOT NULL DEFAULT 0,
    output_id INTEGER,
    color TEXT,
    source_id INTEGER,
    playback_mode TEXT NOT NULL DEFAULT 'once',
    repeat_while_ha_entity_id TEXT
)"""


def _seed_user_version_7_db(path):
    """Zet een DB neer zoals elke draaiende deployment 'm heeft vlak vóór
    deze feature: user_version=7, players al hernoemd (zonder
    audio_source_id), media nog met de oude 'category'-kolomnaam. De rest
    van de tabellen maakt init_db's onvoorwaardelijke CREATE TABLE IF NOT
    EXISTS-blok zelf aan."""
    raw = sqlite3.connect(path)
    raw.execute(_V7_PLAYERS_DDL)
    raw.execute(
        """CREATE TABLE media (
            hash TEXT PRIMARY KEY, filename TEXT NOT NULL,
            category TEXT NOT NULL, uploaded_at TEXT NOT NULL
        )"""
    )
    raw.execute(
        """CREATE TABLE sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'camera_stream',
            value TEXT NOT NULL DEFAULT '',
            canvas_x REAL NOT NULL DEFAULT 0,
            canvas_y REAL NOT NULL DEFAULT 0
        )"""
    )
    # triggers zoals ze er ná de v5-hernoeming uitzien (from_branch_id/
    # to_player_id) -- staat niet in init_db's onvoorwaardelijke blok.
    raw.execute(
        """CREATE TABLE triggers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_branch_id INTEGER NOT NULL,
            to_player_id INTEGER,
            kind TEXT,
            schedule_from TEXT,
            schedule_until TEXT,
            priority INTEGER NOT NULL DEFAULT 0,
            ha_entity_id TEXT,
            canvas_x REAL NOT NULL DEFAULT 0,
            canvas_y REAL NOT NULL DEFAULT 0,
            name TEXT,
            color TEXT
        )"""
    )
    raw.execute("INSERT INTO sources (id, name, kind, value) VALUES (1, 'Cam', 'camera_stream', 'rtsp://cam')")
    raw.execute(
        "INSERT INTO players (id, name, order_index, effect, params, overlay_hash, scale, position, "
        "source_mode, trigger_type, is_root, source_id) VALUES "
        "(1, 'Basis', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera', 'always', 1, 1)"
    )
    raw.execute("PRAGMA user_version = 7")
    raw.commit()
    raw.close()


def test_existing_v7_deployment_gets_audio_source_id_column(tmp_path):
    """Regressie voor Kritiek 1: audio_source_id werd toegevoegd binnen
    _migrate_scenes_to_players, die op elke bestaande deploy (v7) meteen
    terugkeert. De kolom kwam er dus alleen op een verse installatie, en
    elke upgrade crashte daarna in _list_players met 'no such column'."""
    path = str(tmp_path / "test.db")
    _seed_user_version_7_db(path)

    conn = init_db(path)

    cols = {row[1] for row in conn.execute("PRAGMA table_info(players)")}
    assert "audio_source_id" in cols


def test_upgraded_v7_deployment_can_still_publish_its_graph(tmp_path):
    """Integratiekant van dezelfde regressie: _list_players/publish_graph
    zijn wat er meteen ná init_db op elke CRUD-route én bij elke
    MQTT-reconnect draait. Zonder de kolom is dit een 500 op de hele UI."""
    from admin.app.graph_publish import publish_graph

    path = str(tmp_path / "test.db")
    _seed_user_version_7_db(path)
    conn = init_db(path)

    published = []

    class _FakeBridge:
        def publish_mirror_graph(self, payload):
            published.append(payload)

    publish_graph(conn, _FakeBridge())

    assert published[0]["players"][0]["audio_source_id"] is None


def test_devices_table_starts_empty(tmp_path):
    conn = init_db(str(tmp_path / "admin.db"))
    assert conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 0


def test_devices_table_survives_a_second_init_db_call(tmp_path):
    db_path = str(tmp_path / "admin.db")
    conn = init_db(db_path)
    conn.execute(
        "INSERT INTO devices (device_uuid, name, platform) VALUES ('abc-123', 'Oude MacBook', 'darwin')"
    )
    conn.commit()
    conn.close()

    conn2 = init_db(db_path)
    rows = conn2.execute("SELECT device_uuid, name FROM devices").fetchall()
    assert rows == [("abc-123", "Oude MacBook")]


def test_media_category_column_renamed_to_kind(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    cols = {row[1] for row in conn.execute("PRAGMA table_info(media)")}

    assert "kind" in cols
    assert "category" not in cols


def test_existing_media_categories_are_remapped_to_kinds(tmp_path):
    db_path = str(tmp_path / "test.db")
    # Zet een pre-upgrade media-rij neer met de oude schema-naam, zoals een
    # echte bestaande deployment 'm zou hebben vóór deze migratie ooit draait.
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE media (
            hash TEXT PRIMARY KEY, filename TEXT NOT NULL,
            category TEXT NOT NULL, uploaded_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        "INSERT INTO media VALUES (?, ?, ?, ?)", ("a" * 64, "spook.png", "mirror_overlay", "1.0")
    )
    conn.execute(
        "INSERT INTO media VALUES (?, ?, ?, ?)", ("b" * 64, "gil.wav", "scare_audio", "2.0")
    )
    conn.execute(
        "INSERT INTO media VALUES (?, ?, ?, ?)", ("c" * 64, "zombie.mp4", "mirror_scare_video", "3.0")
    )
    conn.commit()
    conn.close()

    conn = init_db(db_path)

    rows = {r[0]: r[1] for r in conn.execute("SELECT hash, kind FROM media")}
    assert rows["a" * 64] == "image"
    assert rows["b" * 64] == "audio"
    assert rows["c" * 64] == "video"


def test_media_kind_migration_is_idempotent(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    conn.execute(
        "INSERT INTO media (hash, filename, kind, uploaded_at) VALUES (?, ?, ?, ?)",
        ("d" * 64, "geluid.wav", "audio", "1.0"),
    )
    conn.commit()
    conn.close()

    conn = init_db(db_path)  # tweede run mag niet crashen op een niet-bestaande 'category'-kolom

    row = conn.execute("SELECT kind FROM media WHERE hash = ?", ("d" * 64,)).fetchone()
    assert row[0] == "audio"  # ongewijzigd, niet per ongeluk opnieuw geremapt


def test_players_get_audio_source_id_column(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    cols = {row[1] for row in conn.execute("PRAGMA table_info(players)")}

    assert "audio_source_id" in cols


def test_existing_player_audio_source_id_defaults_to_null(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    conn.execute(
        "INSERT INTO players (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode) VALUES (1, 'X', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera')"
    )
    conn.commit()

    audio_source_id = conn.execute("SELECT audio_source_id FROM players WHERE id = 1").fetchone()[0]

    assert audio_source_id is None


def test_media_kind_migration_skips_rename_when_category_is_already_gone(tmp_path):
    """Minor 7: een DB die de kolom al 'kind' noemt maar nog op een oudere
    user_version staat (bv. handmatig teruggezet), mag niet crashen op een
    ontbrekende 'category'-kolom."""
    path = str(tmp_path / "test.db")
    conn = init_db(path)
    conn.execute("PRAGMA user_version = 7")  # forceer de migratie opnieuw
    conn.commit()
    conn.close()

    conn = init_db(path)  # mag niet crashen

    cols = {row[1] for row in conn.execute("PRAGMA table_info(media)")}
    assert "kind" in cols
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 8


def test_devices_get_role_and_camera_stream_url_columns(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    cols = {row[1] for row in conn.execute("PRAGMA table_info(devices)")}

    assert {"is_mirror", "is_camera", "camera_stream_url"} <= cols


def test_existing_device_defaults_to_mirror_only(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    conn.execute(
        "INSERT INTO devices (device_uuid, name, platform) VALUES ('abc-123', 'Oude MacBook', 'darwin')"
    )
    conn.commit()

    row = conn.execute(
        "SELECT is_mirror, is_camera, camera_stream_url FROM devices WHERE device_uuid = 'abc-123'"
    ).fetchone()

    assert row == (1, 0, None)
