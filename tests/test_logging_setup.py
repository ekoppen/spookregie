import json
import logging
from shared.logging_setup import setup_logging, MqttLogHandler


class FakeMqttClient:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload):
        self.published.append((topic, payload))


def test_setup_logging_writes_to_file(tmp_path):
    logger = setup_logging("test-node-file", str(tmp_path))
    logger.info("hello")
    for handler in logger.handlers:
        handler.flush()

    log_file = tmp_path / "test-node-file.log"
    assert log_file.exists()
    assert "hello" in log_file.read_text()


def test_setup_logging_publishes_to_mqtt_when_client_given(tmp_path):
    fake_client = FakeMqttClient()
    logger = setup_logging(
        "test-node-mqtt", str(tmp_path), mqtt_client=fake_client, mqtt_log_topic="log/test-node-mqtt"
    )
    logger.info("hello")

    assert len(fake_client.published) == 1
    topic, payload = fake_client.published[0]
    assert topic == "log/test-node-mqtt"
    data = json.loads(payload)
    assert data["msg"] == "hello"
    assert data["level"] == "INFO"


def test_setup_logging_skips_mqtt_handler_without_topic(tmp_path):
    fake_client = FakeMqttClient()
    logger = setup_logging("test-node-no-topic", str(tmp_path), mqtt_client=fake_client)
    logger.info("hello")

    assert fake_client.published == []


def test_mqtt_log_handler_emit_publishes_json():
    fake_client = FakeMqttClient()
    handler = MqttLogHandler(fake_client, "log/x")
    logger = logging.getLogger("mqtt-handler-test")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.warning("careful")

    topic, payload = fake_client.published[0]
    assert topic == "log/x"
    data = json.loads(payload)
    assert data["level"] == "WARNING"
    assert data["msg"] == "careful"


def test_setup_logging_does_not_duplicate_handlers_on_repeated_calls(tmp_path):
    """Verify that calling setup_logging() twice with the same node_name
    doesn't accumulate duplicate handlers (relies on handlers.clear())."""
    logger = setup_logging("test-node-dedup", str(tmp_path))
    handlers_after_first = len(logger.handlers)

    # Call setup_logging again with same node_name
    logger = setup_logging("test-node-dedup", str(tmp_path))
    handlers_after_second = len(logger.handlers)

    assert handlers_after_second == handlers_after_first, (
        f"Expected {handlers_after_first} handlers after second call, "
        f"but got {handlers_after_second} (handlers were duplicated)"
    )
