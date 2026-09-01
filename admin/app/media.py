import os
import subprocess
import time

from shared.media_sync import content_hash, is_content_hash

# Zelfde plafond als shared/media_sync.py's fetch-cap: een grotere upload zou
# door de nodes nooit opgehaald kunnen worden.
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB


def validate_upload(data, kind):
    """Geeft een foutmelding terug, of None als de upload in orde is.
    Alleen de magic bytes worden gecheckt — genoeg om een verkeerd bestand
    bij upload te weigeren in plaats van een node er later op te laten
    stuklopen (zie spec)."""
    if len(data) > MAX_UPLOAD_SIZE:
        return f"bestand is groter dan {MAX_UPLOAD_SIZE // (1024 * 1024)} MB"
    if kind == "image" and not data.startswith(b"\x89PNG"):
        return "afbeelding moet een PNG-bestand zijn"
    if kind == "audio" and not (data[:4] == b"RIFF" and data[8:12] == b"WAVE"):
        return "audio moet een WAV-bestand zijn"
    if kind == "video" and data[4:8] != b"ftyp":
        return "video moet een MP4-bestand zijn"
    return None


def save_media(conn, media_dir, data, filename, kind):
    os.makedirs(media_dir, exist_ok=True)
    hash_ = content_hash(data)
    with open(os.path.join(media_dir, hash_), "wb") as f:
        f.write(data)
    conn.execute(
        "INSERT OR REPLACE INTO media (hash, filename, kind, uploaded_at) VALUES (?, ?, ?, ?)",
        (hash_, filename, kind, str(time.time())),
    )
    conn.commit()
    return hash_


def get_media_path(media_dir, hash_):
    if not is_content_hash(hash_):
        return None
    path = os.path.join(media_dir, hash_)
    return path if os.path.exists(path) else None


def extract_audio_if_video(media_dir, hash_, kind):
    """Extraheert het geluidsspoor van een geüploade video naar
    <hash>.audio via ffmpeg. Best-effort: geen geluidsspoor, een
    ontbrekende ffmpeg-binary, of een mislukte extractie levert gewoon
    geen bestand op -- de video-upload zelf mag hier nooit op stuklopen."""
    if kind != "video":
        return
    video_path = os.path.join(media_dir, hash_)
    audio_path = video_path + ".audio"
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-vn", "-ar", "44100", "-ac", "2", "-f", "wav", audio_path],
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0 and os.path.exists(audio_path):
            os.remove(audio_path)
    except Exception:
        try:
            if os.path.exists(audio_path):
                os.remove(audio_path)
        except Exception:
            pass


def get_media_audio_path(media_dir, hash_):
    if not is_content_hash(hash_):
        return None
    path = os.path.join(media_dir, hash_ + ".audio")
    return path if os.path.exists(path) else None


def list_media(conn, kind=None):
    if kind is not None:
        rows = conn.execute(
            "SELECT hash, filename, kind, uploaded_at FROM media WHERE kind = ? ORDER BY uploaded_at DESC",
            (kind,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT hash, filename, kind, uploaded_at FROM media ORDER BY uploaded_at DESC"
        ).fetchall()
    return [
        {"hash": r[0], "filename": r[1], "kind": r[2], "uploaded_at": r[3]}
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
        # Anders blijft de spiegelconfig een overlay tonen die niet meer
        # bestaat -- een kapot plaatje in de compositie-tool zonder enige
        # foutmelding.
        conn.execute(
            "UPDATE mirror_config SET overlay_hash = NULL WHERE overlay_hash = ?", (hash_,)
        )
        conn.commit()

    return cursor.rowcount > 0
