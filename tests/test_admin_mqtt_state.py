import json
from admin.app.mqtt_state import NodeStatusTracker


def test_status_message_updates_node_state():
    tracker = NodeStatusTracker()

    tracker.handle_message("status/mirror", "online")

    nodes = tracker.get_nodes()
    assert nodes["mirror"]["status"] == "online"


def test_status_offline_updates_state():
    tracker = NodeStatusTracker()
    tracker.handle_message("status/mirror", "online")

    tracker.handle_message("status/mirror", "offline")

    assert tracker.get_nodes()["mirror"]["status"] == "offline"


def test_log_message_is_recorded():
    tracker = NodeStatusTracker()
    payload = json.dumps({"ts": 123.0, "level": "INFO", "msg": "mirror-node gestart"})

    tracker.handle_message("log/mirror", payload)

    logs = tracker.get_recent_logs()
    assert len(logs) == 1
    assert logs[0]["msg"] == "mirror-node gestart"
    assert logs[0]["node"] == "mirror"


def test_get_recent_logs_filters_by_node():
    tracker = NodeStatusTracker()
    tracker.handle_message("log/mirror", json.dumps({"ts": 1.0, "level": "INFO", "msg": "a"}))
    tracker.handle_message("log/scare-zone-a", json.dumps({"ts": 2.0, "level": "INFO", "msg": "b"}))

    mirror_logs = tracker.get_recent_logs(node="mirror")

    assert len(mirror_logs) == 1
    assert mirror_logs[0]["msg"] == "a"


def test_get_recent_logs_respects_limit():
    tracker = NodeStatusTracker()
    for i in range(10):
        tracker.handle_message("log/mirror", json.dumps({"ts": float(i), "level": "INFO", "msg": str(i)}))

    logs = tracker.get_recent_logs(limit=3)

    assert len(logs) == 3


def test_unrelated_topic_is_ignored_without_crashing():
    tracker = NodeStatusTracker()

    tracker.handle_message("mirror/triggered", '{"ts": 1.0}')  # geen crash

    assert tracker.get_nodes() == {}


def test_malformed_log_payload_does_not_crash():
    tracker = NodeStatusTracker()

    tracker.handle_message("log/mirror", "dit is geen JSON")

    assert tracker.get_recent_logs() == []
