import os
import time

from shared.media_sync import content_hash, is_content_hash

# Zelfde plafond als shared/media_sync.py's fetch-cap: een grotere upload zou
# door de nodes nooit opgehaald kunnen worden.
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB


def validate_upload(data, category):
    """Geeft een foutmelding terug, of None als de upload in orde is.
    Alleen de magic bytes worden gecheckt — genoeg om een verkeerd bestand
    bij upload te weigeren in plaats van een node er later op te laten
    stuklopen (zie spec)."""
    if len(data) > MAX_UPLOAD_SIZE:
        return f"bestand is groter dan {MAX_UPLOAD_SIZE // (1024 * 1024)} MB"
    if category == "mirror_overlay" and not data.startswith(b"\x89PNG"):
        return "overlay moet een PNG-bestand zijn"
    if category == "scare_audio" and not (data[:4] == b"RIFF" and data[8:12] == b"WAVE"):
        return "scare-audio moet een WAV-bestand zijn"
    return None


def save_media(conn, media_dir, data, filename, category):
    os.makedirs(media_dir, exist_ok=True)
    hash_ = content_hash(data)
    with open(os.path.join(media_dir, hash_), "wb") as f:
        f.write(data)
    conn.execute(
        "INSERT OR REPLACE INTO media (hash, filename, category, uploaded_at) VALUES (?, ?, ?, ?)",
        (hash_, filename, category, str(time.time())),
    )
    conn.commit()
    return hash_


def get_media_path(media_dir, hash_):
    if not is_content_hash(hash_):
        return None
    path = os.path.join(media_dir, hash_)
    return path if os.path.exists(path) else None


def list_media(conn, category=None):
    if category is not None:
        rows = conn.execute(
            "SELECT hash, filename, category, uploaded_at FROM media WHERE category = ? ORDER BY uploaded_at DESC",
            (category,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT hash, filename, category, uploaded_at FROM media ORDER BY uploaded_at DESC"
        ).fetchall()
    return [
        {"hash": r[0], "filename": r[1], "category": r[2], "uploaded_at": r[3]}
        for r in rows
    ]


def delete_media(conn, media_dir, hash_):
    if not is_content_hash(hash_):
        return False
    cursor = conn.execute("DELETE FROM media WHERE hash = ?", (hash_,))
    conn.commit()

    # Only attempt file removal if DB row actually existed.
    # DB is source of truth: orphan files (file exists but no DB row) are left alone.
    if cursor.rowcount > 0:
        path = get_media_path(media_dir, hash_)
        if path is not None:
            try:
                os.remove(path)
            except OSError:
                # File already gone or inaccessible; DB row is deleted regardless.
                pass

    return cursor.rowcount > 0
