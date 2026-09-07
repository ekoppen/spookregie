import hashlib
import hmac
import json
import re
import urllib.request


# ponytail: validates domain/service names to prevent path-traversal in URL construction
_HA_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# ponytail: same path-traversal concern as _HA_IDENTIFIER_RE, but a camera
# entity_id has a domain.object_id shape ("camera.voordeur")
CAMERA_ENTITY_RE = re.compile(r"^camera\.[a-z0-9_]+$")


def _default_fetch(url, method="GET", headers=None, body=None):
    req = urllib.request.Request(url, method=method, headers=headers or {}, data=body)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read()


def get_states(ha_url, ha_token, fetch=None):
    fetch = fetch or _default_fetch
    headers = {"Authorization": f"Bearer {ha_token}"}
    try:
        data = fetch(f"{ha_url}/api/states", method="GET", headers=headers)
        return json.loads(data)
    except Exception:
        return []


def call_service(ha_url, ha_token, domain, service, data, fetch=None):
    if not _HA_IDENTIFIER_RE.match(domain) or not _HA_IDENTIFIER_RE.match(service):
        return
    fetch = fetch or _default_fetch
    headers = {"Authorization": f"Bearer {ha_token}", "Content-Type": "application/json"}
    body = json.dumps(data).encode()
    # Geen brede try/except meer hier: een echte netwerk-/HTTP-fout moet naar
    # de aanroeper (routers/ha.py) doorstromen zodat de operator een foutmelding
    # ziet i.p.v. een stille "ok" terwijl HA onbereikbaar was.
    fetch(f"{ha_url}/api/services/{domain}/{service}", method="POST", headers=headers, body=body)


def sign_camera_entity(secret, entity_id):
    """HMAC over entity_id met de admin_password als sleutel -- zodat de
    publiek-bereikbare camera-stream-URL (nodig omdat mirror-node geen
    sessie heeft) niet simpelweg te raden is (bijv. camera.voordeur
    proberen zonder verder iets te weten). Bewust géén verlooptijd: een
    Source.value moet net zo permanent blijven werken als een
    RTSP-URL-met-credentials dat al doet -- de URL wordt opnieuw
    gegenereerd via de picker als het admin-wachtwoord ooit wijzigt."""
    return hmac.new(secret.encode(), entity_id.encode(), hashlib.sha256).hexdigest()


def verify_camera_entity_signature(secret, entity_id, signature):
    if not signature:
        return False
    return hmac.compare_digest(sign_camera_entity(secret, entity_id), signature)


def open_camera_stream(ha_url, ha_token, entity_id, opener=None):
    """Opent een streaming GET naar HA's ingebouwde camera_proxy_stream
    endpoint -- een MJPEG multipart-stream die HA voor vrijwel elke
    camera-integratie aanbiedt, ongeacht merk of onderliggend protocol.
    Geeft het open response-object terug (niet uitgelezen) zodat de
    aanroeper 'm chunked kan doorstreamen i.p.v. de in principe oneindige
    stream in het geheugen te laden. entity_id is al gevalideerd door de
    aanroeper (CAMERA_ENTITY_RE)."""
    opener = opener or urllib.request.urlopen
    headers = {"Authorization": f"Bearer {ha_token}"}
    req = urllib.request.Request(f"{ha_url}/api/camera_proxy_stream/{entity_id}", headers=headers)
    return opener(req, timeout=10)
