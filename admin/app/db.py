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
        """CREATE TABLE IF NOT EXISTS schedule (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            on_time TEXT NOT NULL DEFAULT '18:00',
            off_time TEXT NOT NULL DEFAULT '22:00',
            enabled INTEGER NOT NULL DEFAULT 1
        )"""
    )
    conn.commit()
    return conn
