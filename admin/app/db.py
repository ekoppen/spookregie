import sqlite3


def init_db(path):
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS media (
            hash TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            category TEXT NOT NULL,
            uploaded_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS scare_zone_config (
            zone TEXT PRIMARY KEY,
            enabled_hashes TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS mirror_config (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            effect TEXT NOT NULL DEFAULT 'xray',
            params TEXT NOT NULL DEFAULT '{}',
            overlay_hash TEXT,
            scale REAL NOT NULL DEFAULT 1.0,
            position TEXT NOT NULL DEFAULT '[0.5, 0.5]'
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS scenes (
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
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS outputs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            camera_source TEXT NOT NULL DEFAULT ''
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS mirror_scare_video_config (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            enabled_hashes TEXT NOT NULL DEFAULT '[]'
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schedule (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            on_time TEXT NOT NULL DEFAULT '18:00',
            off_time TEXT NOT NULL DEFAULT '22:00',
            enabled INTEGER NOT NULL DEFAULT 1
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS app_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            mqtt_host TEXT NOT NULL,
            mqtt_port INTEGER NOT NULL,
            mqtt_user TEXT NOT NULL DEFAULT '',
            mqtt_pass TEXT NOT NULL DEFAULT '',
            ha_url TEXT NOT NULL,
            ha_token TEXT NOT NULL DEFAULT '',
            mirror_stream_url TEXT NOT NULL DEFAULT ''
        )"""
    )
    _ensure_column(conn, "app_settings", "mqtt_topic_prefix", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "app_settings", "mirror_camera_source", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "mirror_config", "canvas_width", "INTEGER")
    _ensure_column(conn, "mirror_config", "canvas_height", "INTEGER")
    _ensure_column(conn, "mirror_config", "source_scale", "REAL NOT NULL DEFAULT 1.0")
    _ensure_column(conn, "mirror_config", "source_position", "TEXT NOT NULL DEFAULT '[0.5, 0.5]'")
    _ensure_column(conn, "scenes", "is_root", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "scenes", "canvas_x", "REAL NOT NULL DEFAULT 0")
    _ensure_column(conn, "scenes", "canvas_y", "REAL NOT NULL DEFAULT 0")
    _ensure_column(conn, "scenes", "output_id", "INTEGER")
    _ensure_column(conn, "scenes", "color", "TEXT")
    _migrate_mirror_config_to_scenes(conn)
    _migrate_scenes_to_graph(conn)
    _migrate_outputs(conn)
    _migrate_scene_edges_to_triggers(conn)
    conn.commit()
    return conn


def _ensure_column(conn, table, column, ddl):
    """Voegt een kolom toe aan een bestaande tabel als die er nog niet is.
    CREATE TABLE IF NOT EXISTS is een no-op op een tabel die al bestaat --
    een kolom toegevoegd door een latere feature (zoals mqtt_topic_prefix
    hier) moet daarom via een aparte ALTER TABLE, anders crasht een
    bestaande deploy bij het opstarten met "no such column"."""
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _migrate_mirror_config_to_scenes(conn):
    """Migreert de (oude, enkelvoudige) mirror_config-rij naar één
    'Basis'-scene, zodat een bestaande deploy na de upgrade precies
    hetzelfde beeld blijft tonen. Idempotent: doet niets zodra er al
    minstens één scene bestaat, en niets als er nooit een
    mirror_config-rij was (verse installatie)."""
    existing = conn.execute("SELECT COUNT(*) FROM scenes").fetchone()[0]
    if existing > 0:
        return
    row = conn.execute(
        "SELECT effect, params, overlay_hash, scale, position, "
        "canvas_width, canvas_height, source_scale, source_position "
        "FROM mirror_config WHERE id = 1"
    ).fetchone()
    if row is None:
        return
    conn.execute(
        """INSERT INTO scenes
             (name, order_index, enabled, source_mode, effect, params, overlay_hash,
              scale, position, canvas_width, canvas_height, source_scale, source_position,
              trigger_type)
           VALUES ('Basis', 0, 1, 'camera', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'always')""",
        row,
    )


def _migrate_scenes_to_graph(conn):
    """Migreert de oude, platte prioriteit+trigger-scenes naar de
    graaf: de 'always'-scene met de laagste order_index wordt root
    (of, als die er niet is, de scene met de laagste order_index);
    elke andere scene met een niet-lege trigger_type krijgt een edge
    vanaf de root met die trigger; elke scare_video-scene krijgt ook
    een edge terug naar de root ('altijd').

    Idempotent via PRAGMA user_version (niet via "zijn er edges?" -- een
    verse graaf-installatie met scenes die de gebruiker nog niet
    gekoppeld heeft, heeft ook nul edges, en zou anders bij elke herstart
    opnieuw als legacy-data gezien worden en is_root/edges herschrijven)."""
    if conn.execute("PRAGMA user_version").fetchone()[0] >= 1:
        return
    conn.execute(
        """CREATE TABLE IF NOT EXISTS scene_edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_scene_id INTEGER NOT NULL,
            to_scene_id INTEGER,
            trigger_type TEXT,
            trigger_from TEXT,
            trigger_until TEXT,
            priority INTEGER NOT NULL DEFAULT 0
        )"""
    )
    if conn.execute("SELECT COUNT(*) FROM scene_edges").fetchone()[0] > 0:
        # Upgrade-pad: al eerder gemigreerd onder de oude edge-count-gate
        # (vóór deze fix). Alleen de marker zetten -- de body opnieuw
        # draaien zou dubbele edges aanmaken op een deploy die na de
        # eerdere migratie al eigen edges heeft toegevoegd/aangepast.
        conn.execute("PRAGMA user_version = 1")
        return
    rows = conn.execute(
        "SELECT id, source_mode, trigger_type, trigger_from, trigger_until, order_index "
        "FROM scenes ORDER BY order_index"
    ).fetchall()
    if not rows:
        conn.execute("PRAGMA user_version = 1")
        return
    always_rows = [r for r in rows if r[2] == "always"]
    root_id = always_rows[0][0] if always_rows else rows[0][0]
    conn.execute("UPDATE scenes SET is_root = 0")
    conn.execute("UPDATE scenes SET is_root = 1 WHERE id = ?", (root_id,))
    for scene_id, source_mode, trigger_type, trigger_from, trigger_until, order_index in rows:
        if scene_id == root_id or not trigger_type:
            continue
        conn.execute(
            """INSERT INTO scene_edges
                 (from_scene_id, to_scene_id, trigger_type, trigger_from, trigger_until, priority)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (root_id, scene_id, trigger_type, trigger_from, trigger_until, order_index),
        )
        if source_mode == "scare_video":
            conn.execute(
                """INSERT INTO scene_edges
                     (from_scene_id, to_scene_id, trigger_type, trigger_from, trigger_until, priority)
                   VALUES (?, ?, 'always', NULL, NULL, 0)""",
                (scene_id, root_id),
            )
    conn.execute("PRAGMA user_version = 1")


def _migrate_outputs(conn):
    """Zorgt dat er minstens één output bestaat, gevuld vanuit de huidige
    mirror_camera_source-instelling bij de allereerste run na deze
    upgrade, en koppelt scenes zonder output_id eraan. Idempotent: doet
    niets zodra er al een output is."""
    existing = conn.execute("SELECT COUNT(*) FROM outputs").fetchone()[0]
    if existing == 0:
        # No outputs yet, create one from app_settings
        row = conn.execute("SELECT mirror_camera_source FROM app_settings WHERE id = 1").fetchone()
        camera_source = row[0] if row else ""
        cursor = conn.execute(
            "INSERT INTO outputs (name, camera_source) VALUES ('Spiegel', ?)", (camera_source,)
        )
        output_id = cursor.lastrowid
    else:
        # Outputs already exist, get the first one
        output_id = conn.execute("SELECT id FROM outputs LIMIT 1").fetchone()[0]
        # If the output has empty camera_source and app_settings now has a value, update it
        row = conn.execute("SELECT mirror_camera_source FROM app_settings WHERE id = 1").fetchone()
        if row and row[0]:
            conn.execute(
                "UPDATE outputs SET camera_source = ? WHERE id = ? AND camera_source = ''",
                (row[0], output_id),
            )

    # Always link scenes to the output
    conn.execute("UPDATE scenes SET output_id = ? WHERE output_id IS NULL", (output_id,))


def _migrate_scene_edges_to_triggers(conn):
    """Hernoemt scene_edges naar triggers (trigger_type->kind,
    trigger_from->schedule_from, trigger_until->schedule_until) en voegt
    de nieuwe trigger-als-knoop-kolommen toe (ha_entity_id, canvas_x/y,
    name, color). Idempotent via PRAGMA user_version (>=2 betekent 'deze
    migratie is al gedaan' -- zelfde patroon als de scenes-naar-graaf-
    migratie op versie 1, één stap verder)."""
    if conn.execute("PRAGMA user_version").fetchone()[0] >= 2:
        return
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "scene_edges" in tables:
        conn.execute("ALTER TABLE scene_edges RENAME TO triggers")
        conn.execute("ALTER TABLE triggers RENAME COLUMN trigger_type TO kind")
        conn.execute("ALTER TABLE triggers RENAME COLUMN trigger_from TO schedule_from")
        conn.execute("ALTER TABLE triggers RENAME COLUMN trigger_until TO schedule_until")
    else:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS triggers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_scene_id INTEGER NOT NULL,
                to_scene_id INTEGER,
                kind TEXT,
                schedule_from TEXT,
                schedule_until TEXT,
                priority INTEGER NOT NULL DEFAULT 0
            )"""
        )
    _ensure_column(conn, "triggers", "ha_entity_id", "TEXT")
    _ensure_column(conn, "triggers", "canvas_x", "REAL NOT NULL DEFAULT 0")
    _ensure_column(conn, "triggers", "canvas_y", "REAL NOT NULL DEFAULT 0")
    _ensure_column(conn, "triggers", "name", "TEXT")
    _ensure_column(conn, "triggers", "color", "TEXT")
    # Zinvolle startpositie: het midden tussen bron- en (indien gezet)
    # doelscene, anders bron-positie + een vaste offset naar rechtsonder.
    conn.execute(
        """UPDATE triggers SET
             canvas_x = COALESCE((
               SELECT (s1.canvas_x + COALESCE(s2.canvas_x, s1.canvas_x + 150)) / 2
               FROM scenes s1 LEFT JOIN scenes s2 ON s2.id = triggers.to_scene_id
               WHERE s1.id = triggers.from_scene_id
             ), 0),
             canvas_y = COALESCE((
               SELECT (s1.canvas_y + COALESCE(s2.canvas_y, s1.canvas_y)) / 2 + 60
               FROM scenes s1 LEFT JOIN scenes s2 ON s2.id = triggers.to_scene_id
               WHERE s1.id = triggers.from_scene_id
             ), 0)
        """
    )
    conn.execute("PRAGMA user_version = 2")
