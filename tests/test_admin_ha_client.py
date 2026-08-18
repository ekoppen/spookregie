import json
import pytest
from admin.app.ha_client import get_states, call_service


def test_get_states_calls_correct_url_and_parses_json():
    calls = []

    def fake_fetch(url, method="GET", headers=None, body=None):
        calls.append((url, method, headers))
        return json.dumps([{"entity_id": "light.wled_voortuin", "state": "on"}]).encode()

    result = get_states("http://ha.local:8123", "mytoken", fetch=fake_fetch)

    assert result == [{"entity_id": "light.wled_voortuin", "state": "on"}]
    assert calls[0][0] == "http://ha.local:8123/api/states"
    assert calls[0][1] == "GET"
    assert calls[0][2]["Authorization"] == "Bearer mytoken"


def test_get_states_returns_empty_list_on_failure():
    def failing_fetch(url, method="GET", headers=None, body=None):
        raise OSError("HA onbereikbaar")

    result = get_states("http://ha.local:8123", "mytoken", fetch=failing_fetch)

    assert result == []


def test_call_service_posts_correct_body():
    calls = []

    def fake_fetch(url, method="GET", headers=None, body=None):
        calls.append((url, method, headers, body))
        return b"{}"

    call_service(
        "http://ha.local:8123", "mytoken", "light", "turn_on",
        {"entity_id": "light.wled_voortuin"}, fetch=fake_fetch,
    )

    url, method, headers, body = calls[0]
    assert url == "http://ha.local:8123/api/services/light/turn_on"
    assert method == "POST"
    assert headers["Authorization"] == "Bearer mytoken"
    assert headers["Content-Type"] == "application/json"
    assert json.loads(body) == {"entity_id": "light.wled_voortuin"}


def test_call_service_propagates_fetch_failure():
    # Een echte netwerk-/HTTP-fout mag niet meer stil verdwijnen: de router
    # (routers/ha.py) vangt 'm op en geeft de operator een foutmelding i.p.v.
    # een stille "ok" terwijl HA onbereikbaar was.
    def failing_fetch(url, method="GET", headers=None, body=None):
        raise OSError("HA onbereikbaar")

    with pytest.raises(OSError):
        call_service("http://ha.local:8123", "mytoken", "light", "turn_on", {}, fetch=failing_fetch)


def test_call_service_rejects_invalid_domain():
    calls = []

    def fake_fetch(url, method="GET", headers=None, body=None):
        calls.append(url)
        return b"{}"

    call_service("http://ha.local:8123", "mytoken", "../config", "turn_on", {}, fetch=fake_fetch)

    assert calls == []
