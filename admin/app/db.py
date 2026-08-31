import sqlite3


def init_db(path):
    conn = sqlite3.connect(path, check_same_thread=False)
    # ponytail: 'players' bestaat pas na de allereerste (of hernoemde)
    # migratie -- vóór die tijd heet de tabel nog 'scenes'. Zonder deze
    # guard zou de onvoorwaardelijke CREATE TABLE IF NOT EXISTS scenes
    # hieronder bij elke herstart ná de hernoeming een lege spooktabel
    # 'scenes' terugzetten (IF NOT EXISTS blokkeert alleen een tabel die
    # exact zo heet, en die bestaat na de rename niet meer).
    _players_already_exists = "players" in {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
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
    if not _players_already_exists:
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
        """CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'camera_stream',
            value TEXT NOT NULL DEFAULT '',
            canvas_x REAL NOT NULL DEFAULT 0,
            canvas_y REAL NOT NULL DEFAULT 0
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS player_branches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER NOT NULL,
            name TEXT NOT NULL DEFAULT 'Uitgang 1'
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS output_connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            output_id INTEGER NOT NULL,
            from_branch_id INTEGER NOT NULL
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
    _ensure_column(conn, "outputs", "canvas_x", "REAL NOT NULL DEFAULT 0")
    _ensure_column(conn, "outputs", "canvas_y", "REAL NOT NULL DEFAULT 0")
    _tables_before_players_rename = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "scenes" in _tables_before_players_rename:
        _ensure_column(conn, "scenes", "is_root", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "scenes", "canvas_x", "REAL NOT NULL DEFAULT 0")
        _ensure_column(conn, "scenes", "canvas_y", "REAL NOT NULL DEFAULT 0")
        _ensure_column(conn, "scenes", "output_id", "INTEGER")
        _ensure_column(conn, "scenes", "color", "TEXT")
    _migrate_mirror_config_to_scenes(conn)
    _migrate_scenes_to_graph(conn)
    _migrate_outputs(conn)
    _migrate_sources(conn)
    _migrate_scene_edges_to_triggers(conn)
    _migrate_scenes_to_players(conn)
    _migrate_player_branches(conn)
    _migrate_triggers_to_branches(conn)
    _migrate_output_canvas_position(conn)
    _migrate_output_connections(conn)
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
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "scenes" not in tables:
        return  # al hernoemd naar players in een vorige run -- niets te doen
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
    niets zodra er al een output is -- met opzet geen 'camera_source nog
    leeg? opnieuw vullen vanuit app_settings'-pad op elke run, want dat
    zou een bewust leeggemaakte (uitgeschakelde) output bij elke herstart
    stilletjes terugzetten."""
    existing = conn.execute("SELECT COUNT(*) FROM outputs").fetchone()[0]
    if existing == 0:
        row = conn.execute("SELECT mirror_camera_source FROM app_settings WHERE id = 1").fetchone()
        camera_source = row[0] if row else ""
        cursor = conn.execute(
            "INSERT INTO outputs (name, camera_source) VALUES ('Spiegel', ?)", (camera_source,)
        )
        output_id = cursor.lastrowid
    else:
        output_id = conn.execute("SELECT id FROM outputs LIMIT 1").fetchone()[0]

    # Always link scenes to the output
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "scenes" in tables:
        conn.execute("UPDATE scenes SET output_id = ? WHERE output_id IS NULL", (output_id,))


def _migrate_sources(conn):
    """Zorgt dat er minstens één source bestaat, gevuld vanuit de huidige
    (enige) output's camera_source bij de allereerste run na deze upgrade.
    Idempotent: doet niets zodra er al een source is -- zelfde reden als
    _migrate_outputs hierboven: geen 'value nog leeg? opnieuw vullen'-pad
    op elke run, dat zou een bewust leeggemaakte source terugzetten."""
    existing = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    if existing > 0:
        return
    output_row = conn.execute("SELECT name, camera_source FROM outputs ORDER BY id LIMIT 1").fetchone()
    if output_row is None:
        return
    output_name, camera_source = output_row
    conn.execute(
        "INSERT INTO sources (name, kind, value, canvas_x, canvas_y) VALUES (?, 'camera_stream', ?, ?, ?)",
        (f"{output_name} camera", camera_source, -300.0, 0.0),
    )


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
    # Een A->B- en B->A-trigger tussen dezelfde twee scenes (elke
    # scare_video-scene krijgt van _migrate_scenes_to_graph altijd
    # allebei) berekenen anders exact hetzelfde midpoint en landen
    # boven op elkaar -- de + (id % 4) * 40-term geeft elke trigger een
    # eigen, deterministische offset zodat ze zichtbaar uit elkaar
    # liggen, zonder de formule voor het gewone geval te verstoren.
    conn.execute(
        """UPDATE triggers SET
             canvas_x = COALESCE((
               SELECT (s1.canvas_x + COALESCE(s2.canvas_x, s1.canvas_x + 150)) / 2
               FROM scenes s1 LEFT JOIN scenes s2 ON s2.id = triggers.to_scene_id
               WHERE s1.id = triggers.from_scene_id
             ), 0),
             canvas_y = COALESCE((
               SELECT (s1.canvas_y + COALESCE(s2.canvas_y, s1.canvas_y)) / 2
               FROM scenes s1 LEFT JOIN scenes s2 ON s2.id = triggers.to_scene_id
               WHERE s1.id = triggers.from_scene_id
             ), 0) + 60 + (triggers.id % 4) * 40
        """
    )
    conn.execute("PRAGMA user_version = 2")


def _migrate_scenes_to_players(conn):
    """Hernoemt scenes naar players en voegt de nieuwe afspeel-kolommen toe
    (source_id, playback_mode, repeat_while_ha_entity_id). Moet de LAATSTE
    scenes-migratie in init_db() zijn -- elke migratie ervóór verwacht de
    tabel nog 'scenes' te heten. Idempotent via PRAGMA user_version (>=3
    betekent 'deze migratie is al gedaan', zelfde patroon als de
    scene_edges->triggers-migratie op versie 2)."""
    if conn.execute("PRAGMA user_version").fetchone()[0] >= 3:
        return
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "scenes" in tables:
        conn.execute("ALTER TABLE scenes RENAME TO players")
    else:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS players (
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
    _ensure_column(conn, "players", "source_id", "INTEGER")
    _ensure_column(conn, "players", "playback_mode", "TEXT NOT NULL DEFAULT 'once'")
    _ensure_column(conn, "players", "repeat_while_ha_entity_id", "TEXT")
    default_source = conn.execute("SELECT id FROM sources ORDER BY id LIMIT 1").fetchone()
    if default_source is not None:
        conn.execute("UPDATE players SET source_id = ? WHERE source_id IS NULL", (default_source[0],))
    conn.execute("PRAGMA user_version = 3")


def _migrate_player_branches(conn):
    """Geeft elke bestaande player die nog geen enkele branch heeft er
    precies één ('Uitgang 1'). Idempotent via PRAGMA user_version (>=4)."""
    if conn.execute("PRAGMA user_version").fetchone()[0] >= 4:
        return
    rows = conn.execute(
        "SELECT p.id FROM players p WHERE NOT EXISTS "
        "(SELECT 1 FROM player_branches b WHERE b.player_id = p.id)"
    ).fetchall()
    for (player_id,) in rows:
        conn.execute("INSERT INTO player_branches (player_id, name) VALUES (?, 'Uitgang 1')", (player_id,))
    conn.execute("PRAGMA user_version = 4")


def _migrate_triggers_to_branches(conn):
    """Hernoemt triggers.from_scene_id/to_scene_id naar from_branch_id/
    to_player_id, en vult from_branch_id met de (op dit punt in de
    migratieketen gegarandeerd bestaande, precies-één) default-branch van
    de player die de kolom vroeger rechtstreeks aanduidde. Idempotent via
    PRAGMA user_version (>=5)."""
    if conn.execute("PRAGMA user_version").fetchone()[0] >= 5:
        return
    cols = {row[1] for row in conn.execute("PRAGMA table_info(triggers)")}
    if "from_scene_id" in cols:
        conn.execute("ALTER TABLE triggers RENAME COLUMN from_scene_id TO from_branch_id")
        conn.execute("ALTER TABLE triggers RENAME COLUMN to_scene_id TO to_player_id")
        conn.execute(
            "UPDATE triggers SET from_branch_id = ("
            "  SELECT b.id FROM player_branches b WHERE b.player_id = triggers.from_branch_id LIMIT 1"
            ")"
        )
    conn.execute("PRAGMA user_version = 5")


def _migrate_output_canvas_position(conn):
    """Zet éénmalig een zichtbare canvas-positie op elke output die er nog
    geen heeft (rechts naast waar de players staan) -- zonder dit blijft
    een gemigreerde output op (0, 0) staan, precies bovenop de eerste
    player. PRAGMA-gated (>=6) zodat een handmatig versleepte positie
    nooit teruggezet wordt op een latere restart."""
    if conn.execute("PRAGMA user_version").fetchone()[0] >= 6:
        return
    conn.execute("UPDATE outputs SET canvas_x = 300.0 WHERE canvas_x = 0 AND canvas_y = 0")
    conn.execute("PRAGMA user_version = 6")


def _migrate_output_connections(conn):
    """Koppelt elke bestaande player's default-branch rechtstreeks aan de
    (ene, bestaande) output, zodat alles na de upgrade gewoon op het
    scherm blijft verschijnen zonder dat de gebruiker de graaf opnieuw
    hoeft te bedraden. Idempotent via PRAGMA user_version (>=7)."""
    if conn.execute("PRAGMA user_version").fetchone()[0] >= 7:
        return
    output_row = conn.execute("SELECT id FROM outputs ORDER BY id LIMIT 1").fetchone()
    if output_row is not None:
        output_id = output_row[0]
        branch_rows = conn.execute("SELECT id FROM player_branches").fetchall()
        for (branch_id,) in branch_rows:
            conn.execute(
                "INSERT INTO output_connections (output_id, from_branch_id) VALUES (?, ?)",
                (output_id, branch_id),
            )
    conn.execute("PRAGMA user_version = 7")
