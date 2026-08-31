import json
from shared.mqtt_contract import SLEEP_PAYLOAD_OFF, SLEEP_PAYLOAD_ON, Topics, trigger_payload


def test_topics_without_prefix_match_bare_names():
    topics = Topics()
    assert topics.mirror_triggered == "mirror/triggered"
    assert topics.system_sleep == "system/sleep"
    assert topics.config_mirror_graph == "config/mirror/graph"
    assert topics.control_mirror_scene_preview == "control/mirror/scene-preview"
    assert topics.control_mirror_test == "control/mirror/test-trigger"
    assert topics.control_mirror_ha_trigger == "control/mirror/ha-trigger"
    assert topics.status_wildcard == "status/+"
    assert topics.log_wildcard == "log/+"
    assert topics.scare_triggered_wildcard == "scare/+/triggered"


def test_topics_with_prefix_prepends_prefix():
    topics = Topics(prefix="test")
    assert topics.mirror_triggered == "test/mirror/triggered"
    assert topics.system_sleep == "test/system/sleep"
    assert topics.status_wildcard == "test/status/+"


def test_topics_prefix_strips_trailing_slash():
    topics = Topics(prefix="test/")
    assert topics.mirror_triggered == "test/mirror/triggered"


def test_scare_topic_formats_zone():
    assert Topics().scare("zone-a") == "scare/zone-a/triggered"
    assert Topics(prefix="test").scare("zone-a") == "test/scare/zone-a/triggered"


def test_log_topic_formats_node():
    assert Topics().log("mirror") == "log/mirror"


def test_status_topic_formats_node():
    assert Topics().status("mirror") == "status/mirror"
    assert Topics().status("scare-zone-a") == "status/scare-zone-a"


def test_config_scare_topic_formats_zone():
    assert Topics().config_scare("zone-a") == "config/scare/zone-a"


def test_control_scare_test_topic_formats_zone():
    assert Topics().control_scare_test("zone-a") == "control/scare/zone-a/test-trigger"


def test_strip_prefix_removes_configured_prefix():
    topics = Topics(prefix="test")
    assert topics.strip_prefix("test/status/mirror") == "status/mirror"


def test_strip_prefix_without_prefix_is_noop():
    topics = Topics()
    assert topics.strip_prefix("status/mirror") == "status/mirror"


def test_strip_prefix_leaves_unrelated_topic_unchanged():
    topics = Topics(prefix="test")
    assert topics.strip_prefix("other/status/mirror") == "other/status/mirror"


def test_sleep_payload_vocabulary():
    # Moet exact overeenkomen met home_assistant/automations/time_window.yaml.
    assert SLEEP_PAYLOAD_ON == "on"
    assert SLEEP_PAYLOAD_OFF == "off"


def test_trigger_payload_is_json_with_timestamp():
    payload = json.loads(trigger_payload())
    assert "ts" in payload
    assert isinstance(payload["ts"], float)


def test_control_mirror_ha_sensor_state_topic():
    topics = Topics()
    assert topics.control_mirror_ha_sensor_state == "control/mirror/ha-sensor-state"


def test_control_mirror_ha_sensor_state_topic_respects_prefix():
    topics = Topics(prefix="halloween")
    assert topics.control_mirror_ha_sensor_state == "halloween/control/mirror/ha-sensor-state"
