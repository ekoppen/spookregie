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
