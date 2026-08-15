import json
import time

TOPIC_MIRROR_TRIGGERED = "mirror/triggered"
TOPIC_SYSTEM_SLEEP = "system/sleep"

_SCARE_TOPIC_TEMPLATE = "scare/{zone}/triggered"
_LOG_TOPIC_TEMPLATE = "log/{node}"


def trigger_payload():
    """JSON payload voor een 'iets is getriggerd'-bericht."""
    return json.dumps({"ts": time.time()})


def scare_topic(zone):
    return _SCARE_TOPIC_TEMPLATE.format(zone=zone)


def log_topic(node):
    return _LOG_TOPIC_TEMPLATE.format(node=node)
