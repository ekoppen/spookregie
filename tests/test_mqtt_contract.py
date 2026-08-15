import json
from shared.mqtt_contract import (
    SLEEP_PAYLOAD_OFF,
    SLEEP_PAYLOAD_ON,
    TOPIC_MIRROR_TRIGGERED,
    TOPIC_SYSTEM_SLEEP,
    trigger_payload,
    scare_topic,
    log_topic,
    status_topic,
)


def test_topic_constants():
    assert TOPIC_MIRROR_TRIGGERED == "mirror/triggered"
    assert TOPIC_SYSTEM_SLEEP == "system/sleep"


def test_scare_topic_formats_zone():
    assert scare_topic("zone-a") == "scare/zone-a/triggered"


def test_log_topic_formats_node():
    assert log_topic("mirror") == "log/mirror"


def test_status_topic_formats_node():
    assert status_topic("mirror") == "status/mirror"
    assert status_topic("scare-zone-a") == "status/scare-zone-a"


def test_sleep_payload_vocabulary():
    # Moet exact overeenkomen met home_assistant/automations/time_window.yaml.
    assert SLEEP_PAYLOAD_ON == "on"
    assert SLEEP_PAYLOAD_OFF == "off"


def test_trigger_payload_is_json_with_timestamp():
    payload = json.loads(trigger_payload())
    assert "ts" in payload
    assert isinstance(payload["ts"], float)
