import json
import re
import urllib.request


# ponytail: validates domain/service names to prevent path-traversal in URL construction
_HA_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]*$")


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
    try:
        fetch(f"{ha_url}/api/services/{domain}/{service}", method="POST", headers=headers, body=body)
    except Exception:
        pass
