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
