import json
import urllib.request


def _default_fetch(url, timeout):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read()


def fetch_topic_prefix(backend_url, fallback, fetch=None, timeout=3):
    """Haalt de actuele MQTT-topic-prefix op bij de backend
    (`GET {backend_url}/api/node-config`). Lukt dat niet (backend
    onbereikbaar, ongeldig antwoord, verkeerd veldtype), dan `fallback` --
    nooit een uitzondering naar de aanroeper, consistent met de fail-safe-
    filosofie van de nodes (zelfstandig blijven werken zonder backend)."""
    fetch = fetch or _default_fetch
    try:
        data = fetch(f"{backend_url}/api/node-config", timeout)
        parsed = json.loads(data)
        prefix = parsed.get("mqtt_topic_prefix")
        if isinstance(prefix, str):
            return prefix
        return fallback
    except Exception:
        return fallback


def fetch_mirror_camera_source(backend_url, fallback, fetch=None, timeout=3):
    """Haalt de actuele mirror-camera-bron op bij de backend
    (`GET {backend_url}/api/node-config`). Lukt dat niet (backend
    onbereikbaar, ongeldig antwoord, verkeerd veldtype), dan `fallback` --
    zelfde fail-safe-patroon als fetch_topic_prefix, bewust een eigen kleine
    functie in plaats van die functie te verbreden (zie de spec)."""
    fetch = fetch or _default_fetch
    try:
        data = fetch(f"{backend_url}/api/node-config", timeout)
        parsed = json.loads(data)
        source = parsed.get("mirror_camera_source")
        if isinstance(source, str):
            return source
        return fallback
    except Exception:
        return fallback
