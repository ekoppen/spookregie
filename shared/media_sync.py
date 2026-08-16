import hashlib
import os
import urllib.request


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
                return resp.read()

    os.makedirs(cache_dir, exist_ok=True)
    result = {}
    for h in wanted_hashes:
        local_path = os.path.join(cache_dir, h)
        if os.path.exists(local_path):
            result[h] = local_path
            continue
        try:
            data = fetch(f"{base_url}/api/media/{h}")
        except Exception:
            continue
        with open(local_path, "wb") as f:
            f.write(data)
        result[h] = local_path
    return result
