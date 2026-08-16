import json
from shared.mqtt_contract import (
    SLEEP_PAYLOAD_OFF,
    SLEEP_PAYLOAD_ON,
    TOPIC_MIRROR_TRIGGERED,
    TOPIC_SYSTEM_SLEEP,
    TOPIC_CONFIG_MIRROR,
    TOPIC_CONTROL_MIRROR_PREVIEW,
    TOPIC_CONTROL_MIRROR_TEST,
    trigger_payload,
    scare_topic,
    log_topic,
    status_topic,
    config_scare_topic,
    control_scare_test_topic,
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


def test_new_topic_constants():
    assert TOPIC_CONFIG_MIRROR == "config/mirror"
    assert TOPIC_CONTROL_MIRROR_PREVIEW == "control/mirror/preview"
    assert TOPIC_CONTROL_MIRROR_TEST == "control/mirror/test-trigger"


def test_config_scare_topic_formats_zone():
    assert config_scare_topic("zone-a") == "config/scare/zone-a"


def test_control_scare_test_topic_formats_zone():
    assert control_scare_test_topic("zone-a") == "control/scare/zone-a/test-trigger"
