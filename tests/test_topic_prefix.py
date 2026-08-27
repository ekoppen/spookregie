from shared.topic_prefix import fetch_topic_prefix


def test_fetch_topic_prefix_returns_backend_value():
    def fake_fetch(url, timeout):
        assert url == "http://backend:8000/api/node-config"
        return b'{"mqtt_topic_prefix": "test"}'

    result = fetch_topic_prefix("http://backend:8000", fallback="fallback", fetch=fake_fetch)

    assert result == "test"


def test_fetch_topic_prefix_returns_empty_string_prefix_correctly():
    # Een backend zonder ingestelde prefix geeft expliciet "" terug -- dat
    # is een geldig antwoord, geen fout, en moet NIET op de fallback vallen.
    def empty_prefix_fetch(url, timeout):
        return b'{"mqtt_topic_prefix": ""}'

    result = fetch_topic_prefix("http://backend:8000", fallback="fallback", fetch=empty_prefix_fetch)

    assert result == ""


def test_fetch_topic_prefix_falls_back_on_connection_error():
    def failing_fetch(url, timeout):
        raise OSError("onbereikbaar")

    result = fetch_topic_prefix("http://backend:8000", fallback="fallback", fetch=failing_fetch)

    assert result == "fallback"


def test_fetch_topic_prefix_falls_back_on_malformed_json():
    def bad_fetch(url, timeout):
        return b"not json"

    result = fetch_topic_prefix("http://backend:8000", fallback="fallback", fetch=bad_fetch)

    assert result == "fallback"


def test_fetch_topic_prefix_falls_back_when_field_missing():
    def missing_field_fetch(url, timeout):
        return b"{}"

    result = fetch_topic_prefix("http://backend:8000", fallback="fallback", fetch=missing_field_fetch)

    assert result == "fallback"


def test_fetch_topic_prefix_falls_back_when_field_wrong_type():
    def wrong_type_fetch(url, timeout):
        return b'{"mqtt_topic_prefix": 123}'

    result = fetch_topic_prefix("http://backend:8000", fallback="fallback", fetch=wrong_type_fetch)

    assert result == "fallback"
