import os
import time

from shared.media_sync import content_hash


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
    path = get_media_path(media_dir, hash_)
    cursor = conn.execute("DELETE FROM media WHERE hash = ?", (hash_,))
    conn.commit()
    if path is not None:
        os.remove(path)
    return cursor.rowcount > 0
