import json
from shared.mqtt_contract import (
    TOPIC_MIRROR_TRIGGERED,
    TOPIC_SYSTEM_SLEEP,
    trigger_payload,
    scare_topic,
    log_topic,
)


def test_topic_constants():
    assert TOPIC_MIRROR_TRIGGERED == "mirror/triggered"
    assert TOPIC_SYSTEM_SLEEP == "system/sleep"


def test_scare_topic_formats_zone():
    assert scare_topic("zone-a") == "scare/zone-a/triggered"


def test_log_topic_formats_node():
    assert log_topic("mirror") == "log/mirror"


def test_trigger_payload_is_json_with_timestamp():
    payload = json.loads(trigger_payload())
    assert "ts" in payload
    assert isinstance(payload["ts"], float)
