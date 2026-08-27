import admin.app.mqtt_bridge as mqtt_bridge_module
from admin.app.mqtt_bridge import MqttBridge
from admin.app.runtime_settings import RuntimeSettings


class FakeMqttClient:
    instances = []

    def __init__(self, client_id=None):
        self.client_id = client_id
        self.username = None
        self.password = None
        self.connected_to = None
        self.loop_started = False
        self.loop_stopped = False
        self.disconnected = False
        self.subscribed = []
        self.published = []
        FakeMqttClient.instances.append(self)

    def username_pw_set(self, username, password):
        self.username = username
        self.password = password

    def reconnect_delay_set(self, min_delay=1, max_delay=30):
        pass

    def connect_async(self, host, port):
        self.connected_to = (host, port)

    def loop_start(self):
        self.loop_started = True

    def loop_stop(self):
        self.loop_stopped = True

    def disconnect(self):
        self.disconnected = True

    def subscribe(self, topic):
        self.subscribed.append(topic)

    def publish(self, topic, payload=None, retain=False):
        self.published.append((topic, payload, retain))


def _settings(**overrides):
    base = dict(
        mqtt_host="broker-a", mqtt_port=1883, mqtt_user="", mqtt_pass="",
        ha_url="http://localhost:8123", ha_token="", mirror_stream_url="",
    )
    base.update(overrides)
    return RuntimeSettings(**base)


def test_start_connects_with_configured_host_and_port(monkeypatch):
    monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)

    bridge = MqttBridge(_settings(mqtt_host="broker-a", mqtt_port=1883), tracker=object())
    bridge.start()

    assert bridge._client.connected_to == ("broker-a", 1883)


def test_reconfigure_disconnects_old_client_and_connects_new_one(monkeypatch):
    monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)

    bridge = MqttBridge(_settings(), tracker=object())
    bridge.start()
    old_client = bridge._client

    bridge.reconfigure(_settings(mqtt_host="broker-b", mqtt_port=1884, mqtt_user="op", mqtt_pass="geheim"))

    assert old_client.loop_stopped is True
    assert old_client.disconnected is True
    new_client = bridge._client
    assert new_client is not old_client
    assert new_client.connected_to == ("broker-b", 1884)
    assert new_client.username == "op"
    assert new_client.password == "geheim"


def test_start_subscribes_with_configured_prefix(monkeypatch):
    monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)

    bridge = MqttBridge(_settings(mqtt_topic_prefix="test"), tracker=object())
    bridge.start()
    bridge._on_connect(bridge._client, None, None, 0)

    assert bridge._client.subscribed == [
        "test/status/+", "test/log/+", "test/mirror/triggered", "test/scare/+/triggered"
    ]


def test_publish_mirror_config_uses_configured_prefix(monkeypatch):
    monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)

    bridge = MqttBridge(_settings(mqtt_topic_prefix="test"), tracker=object())

    bridge.publish_mirror_config({"effect": "xray"})

    assert bridge._client.published[-1][0] == "test/config/mirror"


def test_on_message_strips_prefix_before_tracker_and_broadcast(monkeypatch):
    monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)

    class FakeTracker:
        def __init__(self):
            self.calls = []

        def handle_message(self, topic, payload):
            self.calls.append((topic, payload))

    tracker = FakeTracker()
    bridge = MqttBridge(_settings(mqtt_topic_prefix="test"), tracker=tracker)

    class FakeMsg:
        topic = "test/status/mirror"
        payload = b"online"

    bridge._on_message(bridge._client, None, FakeMsg())

    assert tracker.calls == [("status/mirror", "online")]
