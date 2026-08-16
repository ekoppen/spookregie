import json
import time

TOPIC_MIRROR_TRIGGERED = "mirror/triggered"
TOPIC_SYSTEM_SLEEP = "system/sleep"
TOPIC_CONFIG_MIRROR = "config/mirror"
TOPIC_CONTROL_MIRROR_PREVIEW = "control/mirror/preview"
TOPIC_CONTROL_MIRROR_TEST = "control/mirror/test-trigger"

# Payloads op TOPIC_SYSTEM_SLEEP. Home Assistant publiceert deze exacte
# waarden (zie home_assistant/automations/time_window.yaml).
SLEEP_PAYLOAD_ON = "on"
SLEEP_PAYLOAD_OFF = "off"

_SCARE_TOPIC_TEMPLATE = "scare/{zone}/triggered"
_LOG_TOPIC_TEMPLATE = "log/{node}"
_STATUS_TOPIC_TEMPLATE = "status/{node}"
_CONFIG_SCARE_TEMPLATE = "config/scare/{zone}"
_CONTROL_SCARE_TEST_TEMPLATE = "control/scare/{zone}/test-trigger"


def trigger_payload():
    """JSON payload voor een 'iets is getriggerd'-bericht."""
    return json.dumps({"ts": time.time()})


def scare_topic(zone):
    return _SCARE_TOPIC_TEMPLATE.format(zone=zone)


def log_topic(node):
    return _LOG_TOPIC_TEMPLATE.format(node=node)


def status_topic(node):
    """Topic voor online/offline-status van een node (MQTT last-will)."""
    return _STATUS_TOPIC_TEMPLATE.format(node=node)


def config_scare_topic(zone):
    return _CONFIG_SCARE_TEMPLATE.format(zone=zone)


def control_scare_test_topic(zone):
    return _CONTROL_SCARE_TEST_TEMPLATE.format(zone=zone)
