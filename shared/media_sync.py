import hashlib
import os
import re
import urllib.request


# ponytail: path-traversal defense, validates hash format before use in paths/URLs
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")

# ponytail: size-cap defense, prevents memory/disk exhaustion on Pi
_FETCH_MAX_SIZE = 50 * 1024 * 1024  # 50 MB


def _read_with_size_cap(resp, max_size=_FETCH_MAX_SIZE):
    """Read from response object, raising if data exceeds max_size."""
    chunk_size = 8192
    data = b''
    while True:
        chunk = resp.read(chunk_size)
        if not chunk:
            break
        data += chunk
        if len(data) > max_size:
            raise ValueError(f"Response exceeds {max_size} bytes")
    return data


def content_hash(data):
    return hashlib.sha256(data).hexdigest()


def sync_media(base_url, cache_dir, wanted_hashes, fetch=None):
    """Zorgt dat elk hash uit `wanted_hashes` lokaal in `cache_dir` staat
    (bestandsnaam = de hash). Haalt ontbrekende bestanden op via
    `GET {base_url}/api/media/<hash>`. `fetch` is injecteerbaar voor
    tests; standaard gebruikt het `urllib`. Hashes die niet opgehaald
    konden worden ontbreken in het resultaat — de aanroeper (main.py)
    logt dat apart en blijft op de vorige stand draaien."""
    if fetch is None:
        def fetch(url):
            with urllib.request.urlopen(url, timeout=10) as resp:
                return _read_with_size_cap(resp)

    os.makedirs(cache_dir, exist_ok=True)
    result = {}
    for h in wanted_hashes:
        if not _HASH_RE.match(h):
            continue
        local_path = os.path.join(cache_dir, h)
        if os.path.exists(local_path):
            result[h] = local_path
            continue
        try:
            data = fetch(f"{base_url}/api/media/{h}")
        except Exception:
            continue
        # ponytail: content verification, detects corrupted/wrong data from backend
        if content_hash(data) != h:
            continue
        with open(local_path, "wb") as f:
            f.write(data)
        result[h] = local_path
    return result
